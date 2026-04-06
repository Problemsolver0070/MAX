"""EvolutionDirectorAgent -- main orchestrator for the self-evolution pipeline.

Subscribes to bus triggers and proposals, evaluates priority, runs the
full experiment pipeline (snapshot -> implement -> canary -> promote/rollback),
and enforces anti-degradation freezes.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from max.evolution.models import (
    CanaryRequest,
    EvolutionJournalEntry,
    EvolutionProposal,
    PromotionEvent,
    RollbackEvent,
)

if TYPE_CHECKING:
    from max.bus.message_bus import MessageBus
    from max.command.task_store import TaskStore
    from max.config import Settings
    from max.evolution.canary import CanaryRunner
    from max.evolution.improver import ImprovementAgent
    from max.evolution.self_model import SelfModel
    from max.evolution.snapshot import SnapshotManager
    from max.evolution.store import EvolutionStore
    from max.llm.client import LLMClient
    from max.memory.coordinator_state import CoordinatorStateManager
    from max.quality.store import QualityStore
    from max.sentinel.scorer import SentinelScorer

logger = logging.getLogger(__name__)


class EvolutionDirectorAgent:
    """Orchestrates the full evolution pipeline: evaluate, snapshot, implement,
    canary, promote/rollback.

    Manages anti-degradation monitoring and freeze/unfreeze lifecycle.
    """

    def __init__(
        self,
        llm: LLMClient,
        bus: MessageBus,
        evo_store: EvolutionStore,
        quality_store: QualityStore,
        snapshot_manager: SnapshotManager,
        improver: ImprovementAgent,
        canary_runner: CanaryRunner,
        self_model: SelfModel,
        settings: Settings,
        state_manager: CoordinatorStateManager,
        task_store: TaskStore,
        sentinel_scorer: SentinelScorer | None = None,
    ) -> None:
        self._llm = llm
        self._bus = bus
        self._evo_store = evo_store
        self._quality_store = quality_store
        self._snapshot_manager = snapshot_manager
        self._improver = improver
        self._canary_runner = canary_runner
        self._self_model = self_model
        self._settings = settings
        self._state_manager = state_manager
        self._task_store = task_store
        self._sentinel_scorer = sentinel_scorer

        # Instance state
        self._consecutive_drops: int = 0
        self._frozen: bool = False

    # ── Bus Integration ───────────────────────────────────────────────────

    async def start(self) -> None:
        """Subscribe to evolution bus channels."""
        await self._bus.subscribe("evolution.trigger", self._on_trigger)
        await self._bus.subscribe("evolution.proposal", self._on_proposal)
        logger.info("EvolutionDirectorAgent started and subscribed to bus channels")

    async def stop(self) -> None:
        """Unsubscribe from evolution bus channels."""
        await self._bus.unsubscribe("evolution.trigger", self._on_trigger)
        await self._bus.unsubscribe("evolution.proposal", self._on_proposal)
        logger.info("EvolutionDirectorAgent stopped")

    async def load_persisted_state(self) -> None:
        """Load persisted state from journal on startup."""
        entries = await self._evo_store.get_journal(limit=1)
        if entries:
            last = entries[0]
            if last.get("action") == "freeze":
                self._frozen = True
                self._consecutive_drops = last.get("details", {}).get(
                    "consecutive_drops", self._settings.evolution_freeze_consecutive_drops
                )
                logger.info(
                    "Loaded persisted freeze state (consecutive_drops=%d)",
                    self._consecutive_drops,
                )

    async def _on_trigger(self, channel: str, data: dict[str, Any]) -> None:
        """Handle scheduled or manual evolution triggers.

        Checks anti-degradation and runs pipeline for pending proposals.
        """
        try:
            logger.info("Evolution trigger received: %s", data)
            should_freeze = await self.check_anti_degradation()
            if should_freeze:
                await self.freeze("Anti-degradation: consecutive quality drops detected")
                return

            proposals = await self._evo_store.get_proposals(status="proposed")
            for row in proposals:
                proposal = EvolutionProposal.model_validate(row)
                if self.evaluate_proposal(proposal):
                    await self.run_pipeline(proposal)
        except Exception:
            logger.exception("Error handling evolution trigger")

    async def _on_proposal(self, channel: str, data: dict[str, Any]) -> None:
        """Handle an incoming evolution proposal from a scout.

        Evaluates priority and runs the pipeline if accepted.
        """
        try:
            proposal = EvolutionProposal.model_validate(data)
            logger.info(
                "Received proposal %s (priority=%.2f): %s",
                proposal.id,
                proposal.computed_priority,
                proposal.description,
            )

            if not self.evaluate_proposal(proposal):
                logger.info("Proposal %s rejected (priority too low)", proposal.id)
                await self._evo_store.update_proposal_status(proposal.id, "rejected")
                return

            await self.run_pipeline(proposal)
        except Exception:
            logger.exception("Error handling evolution proposal")

    # ── Evaluate (Step 2) ─────────────────────────────────────────────────

    def evaluate_proposal(self, proposal: EvolutionProposal) -> bool:
        """Return True if the proposal's computed priority meets the threshold."""
        priority = proposal.computed_priority
        return priority >= self._settings.evolution_min_priority

    # ── Anti-Degradation ──────────────────────────────────────────────────

    async def check_anti_degradation(self) -> bool:
        """Check for consecutive quality drops. Returns True if freeze should trigger."""
        pulse_24h = await self._quality_store.get_quality_pulse(hours=24)
        pulse_48h = await self._quality_store.get_quality_pulse(hours=48)

        current_rate = pulse_24h.get("pass_rate", 0.0)
        previous_rate = pulse_48h.get("pass_rate", 0.0)

        if current_rate < previous_rate:
            self._consecutive_drops += 1
            logger.warning(
                "Quality drop detected: %.2f -> %.2f (consecutive: %d)",
                previous_rate,
                current_rate,
                self._consecutive_drops,
            )
        else:
            self._consecutive_drops = 0

        return self._consecutive_drops >= self._settings.evolution_freeze_consecutive_drops

    # ── Freeze / Unfreeze ─────────────────────────────────────────────────

    async def freeze(self, reason: str) -> None:
        """Freeze the evolution pipeline. No experiments will run until unfrozen."""
        self._frozen = True
        logger.warning("Evolution FROZEN: %s", reason)

        await self._evo_store.record_to_ledger(
            "evolution_freeze", {"reason": reason}
        )
        await self._self_model.record_evolution(
            EvolutionJournalEntry(
                experiment_id=None,
                action="freeze",
                details={
                    "reason": reason,
                    "consecutive_drops": self._consecutive_drops,
                },
            )
        )
        await self._bus.publish(
            "evolution.freeze", {"frozen": True, "reason": reason}
        )
        await self._state_manager.update_evolution_state({
            "evolution_frozen": True,
            "freeze_reason": reason,
        })

    async def unfreeze(self) -> None:
        """Unfreeze the evolution pipeline, allowing experiments to resume."""
        self._frozen = False
        self._consecutive_drops = 0
        logger.info("Evolution UNFROZEN")

        await self._evo_store.record_to_ledger(
            "evolution_unfreeze", {"unfrozen": True}
        )
        await self._self_model.record_evolution(
            EvolutionJournalEntry(
                experiment_id=None,
                action="unfreeze",
                details={"unfrozen": True},
            )
        )
        await self._bus.publish("evolution.unfreeze", {"frozen": False})
        await self._state_manager.update_evolution_state({
            "evolution_frozen": False,
            "freeze_reason": None,
        })

    # ── Full Pipeline ─────────────────────────────────────────────────────

    async def run_pipeline(self, proposal: EvolutionProposal) -> None:
        """Run the complete evolution pipeline for a proposal.

        Steps:
        1. Skip if frozen
        2. Create experiment, set status to approved
        3. Snapshot current state
        4. Implement changes
        5. (empty changeset -> discard and return)
        6. Canary test
        7. Promote or rollback
        """
        # Step 1: Skip if frozen
        if self._frozen:
            logger.info("Pipeline skipped: system is frozen")
            return

        # Step 2: Create experiment
        experiment_id = uuid.uuid4()
        proposal.experiment_id = experiment_id
        await self._evo_store.update_proposal_status(
            proposal.id, "approved", experiment_id=experiment_id
        )
        logger.info(
            "Pipeline started for proposal %s (experiment %s)",
            proposal.id,
            experiment_id,
        )

        snapshot_id: uuid.UUID | None = None

        try:
            # Step 3: Snapshot
            snapshot_id = await self._snapshot_manager.capture(experiment_id)

            # Step 3a: Sentinel baseline (before any changes)
            if self._sentinel_scorer is not None:
                await self._sentinel_scorer.run_baseline(experiment_id)

            # Step 4: Implement
            changeset = await self._improver.implement(proposal)

            # Step 5: Empty changeset -> discard
            if not changeset.entries:
                logger.info(
                    "Empty changeset for proposal %s, discarding", proposal.id
                )
                await self._evo_store.update_proposal_status(
                    proposal.id, "discarded"
                )
                await self._evo_store.discard_candidates(experiment_id)
                return

            # Step 5a: Sentinel candidate run (after implementation)
            if self._sentinel_scorer is not None:
                await self._sentinel_scorer.run_candidate(experiment_id)

            # Step 6: Sentinel evaluation (replaces canary)
            if self._sentinel_scorer is not None:
                sentinel_verdict = await self._sentinel_scorer.compare_and_verdict(
                    experiment_id
                )
                if sentinel_verdict.passed:
                    await self._promote(experiment_id, proposal, sentinel_verdict)
                else:
                    await self._rollback(
                        experiment_id,
                        proposal,
                        snapshot_id,
                        reason=f"Sentinel verdict failed: {sentinel_verdict.summary}",
                    )
            else:
                # Fallback to canary if sentinel not configured
                recent_tasks = await self._task_store.get_active_tasks()
                task_ids = [
                    t["id"] for t in recent_tasks
                    if isinstance(t.get("id"), uuid.UUID)
                ]
                for t in recent_tasks:
                    tid = t.get("id")
                    if isinstance(tid, str):
                        try:
                            task_ids.append(uuid.UUID(tid))
                        except ValueError:
                            pass

                canary_request = CanaryRequest(
                    experiment_id=experiment_id,
                    task_ids=task_ids[:self._settings.evolution_canary_replay_count],
                    candidate_config={},
                    timeout_seconds=self._settings.evolution_canary_timeout_seconds,
                )
                canary_result = await self._canary_runner.run(canary_request)

                if canary_result.overall_passed:
                    await self._promote(experiment_id, proposal, canary_result)
                else:
                    await self._rollback(
                        experiment_id,
                        proposal,
                        snapshot_id,
                        reason="Canary test failed",
                    )

        except Exception:
            logger.error(
                "Pipeline error for proposal %s, attempting rollback",
                proposal.id,
                exc_info=True,
            )
            try:
                if snapshot_id is not None:
                    await self._snapshot_manager.restore(experiment_id)
                await self._evo_store.discard_candidates(experiment_id)
            except Exception:
                logger.error(
                    "Rollback failed for experiment %s",
                    experiment_id,
                    exc_info=True,
                )

    # ── Private Helpers ───────────────────────────────────────────────────

    async def _promote(
        self,
        experiment_id: uuid.UUID,
        proposal: EvolutionProposal,
        canary_or_verdict: Any,
    ) -> None:
        """Promote candidate changes to production."""
        await self._evo_store.promote_candidates(experiment_id)
        await self._evo_store.update_proposal_status(proposal.id, "promoted")

        event = PromotionEvent(
            experiment_id=experiment_id,
            proposal_description=proposal.description,
        )
        await self._evo_store.record_to_ledger(
            "evolution_promotion", event.model_dump(mode="json")
        )
        await self._self_model.record_evolution(
            EvolutionJournalEntry(
                experiment_id=experiment_id,
                action="promote",
                details={
                    "proposal_id": str(proposal.id),
                    "description": proposal.description,
                    "verdict_summary": getattr(canary_or_verdict, "summary", ""),
                    "duration": getattr(canary_or_verdict, "duration_seconds", 0.0),
                },
            )
        )
        await self._bus.publish(
            "evolution.promoted",
            event.model_dump(mode="json"),
        )
        # Sync CoordinatorState (Task 10 gap fix)
        await self._state_manager.update_evolution_state({
            "last_promotion": event.model_dump(mode="json"),
        })
        logger.info(
            "Experiment %s PROMOTED for proposal %s",
            experiment_id,
            proposal.id,
        )

    async def _rollback(
        self,
        experiment_id: uuid.UUID,
        proposal: EvolutionProposal,
        snapshot_id: uuid.UUID | None,
        *,
        reason: str = "Unknown",
    ) -> None:
        """Rollback: restore snapshot, discard candidates, shelve proposal."""
        if snapshot_id is not None:
            await self._snapshot_manager.restore(experiment_id)

        await self._evo_store.discard_candidates(experiment_id)
        await self._evo_store.update_proposal_status(proposal.id, "shelved")

        event = RollbackEvent(
            experiment_id=experiment_id,
            reason=reason,
            snapshot_id=snapshot_id,
        )
        await self._evo_store.record_to_ledger(
            "evolution_rollback", event.model_dump(mode="json")
        )
        await self._self_model.record_evolution(
            EvolutionJournalEntry(
                experiment_id=experiment_id,
                action="rollback",
                details={
                    "proposal_id": str(proposal.id),
                    "reason": reason,
                },
            )
        )
        await self._bus.publish(
            "evolution.rolled_back",
            event.model_dump(mode="json"),
        )
        await self._state_manager.update_evolution_state({
            "last_rollback": event.model_dump(mode="json"),
        })
        logger.info(
            "Experiment %s ROLLED BACK for proposal %s: %s",
            experiment_id,
            proposal.id,
            reason,
        )
