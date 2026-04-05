"""QualityDirectorAgent — audit lifecycle management.

Receives audit requests, spawns AuditorAgent per subtask, aggregates
verdicts, manages rule/pattern extraction, updates coordinator state,
and publishes audit completion events.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from statistics import mean
from typing import Any

from max.agents.base import AgentConfig, AgentContext, BaseAgent
from max.config import Settings
from max.models.tasks import AuditVerdict
from max.quality.auditor import AuditorAgent
from max.quality.models import (
    AuditRequest,
    AuditResponse,
    FixInstruction,
    SubtaskAuditItem,
    SubtaskVerdict,
)

logger = logging.getLogger(__name__)


class QualityDirectorAgent(BaseAgent):
    """Orchestrates the full audit lifecycle for a task.

    Responsibilities:
      - Subscribes to ``audit.request`` on the message bus.
      - For each subtask, spawns an ephemeral :class:`AuditorAgent`.
      - Aggregates subtask verdicts into an overall result.
      - On failure: extracts quality rules via the rule engine.
      - On high-score pass: extracts quality patterns.
      - Records all verdicts to the quality ledger and audit report store.
      - Updates the coordinator state document with audit pipeline status.
      - Publishes :class:`AuditResponse` on ``audit.complete``.
    """

    def __init__(
        self,
        config: AgentConfig,
        llm: Any,
        bus: Any,
        db: Any,
        warm_memory: Any,
        settings: Settings,
        task_store: Any,
        quality_store: Any,
        rule_engine: Any,
        state_manager: Any,
    ) -> None:
        context = AgentContext(bus=bus, db=db, warm_memory=warm_memory)
        super().__init__(config=config, llm=llm, context=context)

        self._bus = bus
        self._db = db
        self._warm_memory = warm_memory
        self._settings = settings
        self._task_store = task_store
        self._quality_store = quality_store
        self._rule_engine = rule_engine
        self._state_manager = state_manager

    # ── Abstract method (not used directly — director is event-driven) ──

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Not used directly; the director is event-driven via on_audit_request."""
        return {}

    # ── Lifecycle ───────────────────────────────────────────────────────

    async def start(self) -> None:
        """Subscribe to audit.request on the message bus."""
        await self._bus.subscribe("audit.request", self.on_audit_request)
        logger.info("QualityDirectorAgent started — listening on audit.request")

    async def stop(self) -> None:
        """Unsubscribe from audit.request on the message bus."""
        await self._bus.unsubscribe("audit.request", self.on_audit_request)
        logger.info("QualityDirectorAgent stopped")

    # ── Main handler ────────────────────────────────────────────────────

    async def on_audit_request(self, channel: str, data: dict[str, Any]) -> None:
        """Handle an incoming audit request.

        Validates the request, spawns auditors per subtask, aggregates
        results, records verdicts, extracts rules/patterns, and publishes
        the final AuditResponse.
        """
        request = AuditRequest.model_validate(data)
        task_id = request.task_id
        goal_anchor = request.goal_anchor

        logger.info(
            "Audit request received for task %s (%d subtasks)",
            task_id,
            len(request.subtask_results),
        )

        # Get active quality rules for auditor context
        active_rules = await self._rule_engine.get_rules_for_audit()

        # Spawn one AuditorAgent per subtask, run concurrently
        audit_coros = [
            self._audit_subtask(item, goal_anchor, active_rules) for item in request.subtask_results
        ]
        audit_results: list[dict[str, Any]] = await asyncio.gather(*audit_coros)

        # Process results: build verdicts, fix instructions, trigger extraction
        subtask_verdicts: list[SubtaskVerdict] = []
        fix_required: list[FixInstruction] = []
        has_failure = False

        for item, result in zip(request.subtask_results, audit_results, strict=True):
            verdict_str = result.get("verdict", "conditional")
            score = result.get("score", 0.5)
            goal_alignment = result.get("goal_alignment", 0.5)
            confidence = result.get("confidence", 0.5)
            issues = result.get("issues", [])
            fix_instructions_text = result.get("fix_instructions")
            strengths = result.get("strengths", [])

            # Map verdict string to enum
            try:
                verdict_enum = AuditVerdict(verdict_str)
            except ValueError:
                verdict_enum = AuditVerdict.CONDITIONAL

            # Build SubtaskVerdict
            subtask_verdicts.append(
                SubtaskVerdict(
                    subtask_id=item.subtask_id,
                    verdict=verdict_enum,
                    score=score,
                    goal_alignment=goal_alignment,
                    issues=issues,
                )
            )

            # Record audit report to store
            report_id = uuid.uuid4()
            await self._quality_store.create_audit_report(
                report_id=report_id,
                task_id=task_id,
                subtask_id=item.subtask_id,
                verdict=verdict_enum,
                score=score,
                goal_alignment=goal_alignment,
                confidence=confidence,
                issues=issues,
                fix_instructions=fix_instructions_text,
                strengths=strengths,
            )

            # Record verdict to quality ledger
            await self._quality_store.record_verdict(
                task_id=task_id,
                subtask_id=item.subtask_id,
                verdict=verdict_enum,
                score=score,
            )

            # Handle FAIL: build fix instruction, extract rules
            if verdict_enum == AuditVerdict.FAIL:
                has_failure = True
                fix_required.append(
                    FixInstruction(
                        subtask_id=item.subtask_id,
                        instructions=fix_instructions_text or "Review and improve output",
                        original_content=item.content,
                        issues=issues,
                    )
                )
                # Extract quality rules from failure
                await self._rule_engine.extract_rules(
                    audit_id=report_id,
                    issues=issues,
                    subtask_description=item.description,
                    output_content=item.content,
                )

            # Handle high-score PASS: extract patterns
            if (
                verdict_enum in (AuditVerdict.PASS, AuditVerdict.CONDITIONAL)
                and score >= self._settings.quality_high_score_threshold
                and strengths
            ):
                await self._rule_engine.extract_patterns(
                    task_id=task_id,
                    strengths=strengths,
                    subtask_description=item.description,
                    output_content=item.content,
                )

        # Aggregate overall score
        scores = [v.score for v in subtask_verdicts]
        overall_score = mean(scores) if scores else 0.0

        # success = no failures (CONDITIONAL is treated as pass)
        success = not has_failure

        # Build and publish AuditResponse
        response = AuditResponse(
            task_id=task_id,
            success=success,
            verdicts=subtask_verdicts,
            overall_score=overall_score,
            fix_required=fix_required,
        )

        await self._bus.publish("audit.complete", response.model_dump(mode="json"))

        logger.info(
            "Audit complete for task %s: success=%s overall_score=%.2f",
            task_id,
            success,
            overall_score,
        )

        # Update coordinator state with audit pipeline info
        await self._update_audit_state(task_id, subtask_verdicts, overall_score)

    # ── Private helpers ─────────────────────────────────────────────────

    async def _audit_subtask(
        self,
        item: SubtaskAuditItem,
        goal_anchor: str,
        active_rules: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Spawn an ephemeral AuditorAgent to audit a single subtask."""
        auditor = AuditorAgent(llm=self.llm)
        result = await auditor.run(
            {
                "goal_anchor": goal_anchor,
                "subtask_description": item.description,
                "content": item.content,
                "quality_criteria": item.quality_criteria,
                "quality_rules": active_rules,
            }
        )
        return result

    async def _update_audit_state(
        self,
        task_id: uuid.UUID,
        verdicts: list[SubtaskVerdict],
        overall_score: float,
    ) -> None:
        """Update the AuditPipelineState in the coordinator state document."""
        from max.memory.models import QualityPulse, RecentVerdict

        state = await self._state_manager.load()

        # Add recent verdicts (capped to configured max)
        max_recent = self._settings.quality_max_recent_verdicts
        for v in verdicts:
            state.audit_pipeline.recent_verdicts.insert(
                0,
                RecentVerdict(
                    task_id=task_id,
                    verdict=v.verdict.value,
                    score=v.score,
                    timestamp=datetime.now(UTC),
                ),
            )
        state.audit_pipeline.recent_verdicts = state.audit_pipeline.recent_verdicts[:max_recent]

        # Update quality pulse
        try:
            pass_rate = await self._quality_store.get_pass_rate()
            avg_score = await self._quality_store.get_avg_score()
        except Exception:
            logger.warning("Failed to fetch quality metrics for pulse update")
            pass_rate = 0.0
            avg_score = 0.0

        # Determine trend from recent verdicts
        recent_scores = [rv.score for rv in state.audit_pipeline.recent_verdicts[:10]]
        if len(recent_scores) >= 2:
            first_half = mean(recent_scores[: len(recent_scores) // 2])
            second_half = mean(recent_scores[len(recent_scores) // 2 :])
            if first_half - second_half > 0.05:
                trend = "improving"
            elif second_half - first_half > 0.05:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "stable"

        # Count consecutive failures
        consecutive_failures = 0
        for rv in state.audit_pipeline.recent_verdicts:
            if rv.verdict == AuditVerdict.FAIL.value:
                consecutive_failures += 1
            else:
                break

        state.audit_pipeline.quality_pulse = QualityPulse(
            avg_score_last_24h=avg_score,
            pass_rate_last_24h=pass_rate,
            trend=trend,
            consecutive_failures=consecutive_failures,
        )

        await self._state_manager.save(state)
        logger.debug("Coordinator audit pipeline state updated for task %s", task_id)
