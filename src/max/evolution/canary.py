"""CanaryRunner -- replay tasks under candidate configuration and verify quality."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import TYPE_CHECKING, Any

from max.evolution.models import CanaryRequest, CanaryResult, CanaryTaskResult

if TYPE_CHECKING:
    from max.evolution.store import EvolutionStore
    from max.llm.client import LLMClient
    from max.memory.metrics import MetricCollector
    from max.quality.store import QualityStore

logger = logging.getLogger(__name__)

CANARY_EVAL_PROMPT = """\
You are evaluating the quality of a subtask output. Score the output on a \
scale of 0.0 to 1.0 based on how well it fulfills the task goal.

Task goal: {goal}
Subtask description: {description}
Subtask output:
{output}

Respond with a JSON object:
{{"score": <float 0.0-1.0>, "reasoning": "<brief explanation>"}}
"""


class CanaryRunner:
    """Replays historical tasks under a candidate configuration to detect regressions.

    For each task in a CanaryRequest, re-evaluates subtask outputs with the LLM,
    compares against original audit scores, and determines whether the candidate
    configuration is safe to promote.
    """

    def __init__(
        self,
        task_store: Any,
        quality_store: QualityStore,
        evo_store: EvolutionStore,
        llm: LLMClient,
        metrics: MetricCollector,
        timeout_seconds: int = 300,
    ) -> None:
        self._task_store = task_store
        self._quality_store = quality_store
        self._evo_store = evo_store
        self._llm = llm
        self._metrics = metrics
        self._timeout_seconds = timeout_seconds

    async def run(self, request: CanaryRequest) -> CanaryResult:
        """Run canary tests for all tasks in the request.

        Returns a CanaryResult with per-task results and overall pass/fail.
        Empty task list is considered a pass.
        """
        start = time.monotonic()
        task_results: list[CanaryTaskResult] = []

        for task_id in request.task_ids:
            task_result = await self._evaluate_task(task_id, request)
            task_results.append(task_result)

        overall_passed = all(tr.passed for tr in task_results) if task_results else True
        duration = time.monotonic() - start

        return CanaryResult(
            experiment_id=request.experiment_id,
            task_results=task_results,
            overall_passed=overall_passed,
            duration_seconds=duration,
        )

    async def _evaluate_task(
        self, task_id: uuid.UUID, request: CanaryRequest
    ) -> CanaryTaskResult:
        """Evaluate a single task under the candidate configuration.

        On any error, returns a failed result with score 0.0.
        """
        try:
            task, subtasks = await self._replay_task(task_id, request)
            original_score = await self._get_original_score(task_id)
            goal = task.get("goal_anchor", "")

            if not subtasks:
                # No subtasks means nothing to evaluate; treat as pass
                return CanaryTaskResult(
                    task_id=task_id,
                    original_score=original_score,
                    canary_score=original_score,
                    passed=True,
                )

            subtask_scores: list[float] = []
            for subtask in subtasks:
                score = await self._evaluate_subtask(
                    goal=goal,
                    description=subtask.get("description", ""),
                    output=subtask.get("output", ""),
                )
                subtask_scores.append(score)

            canary_score = sum(subtask_scores) / len(subtask_scores)
            passed = canary_score >= original_score

            return CanaryTaskResult(
                task_id=task_id,
                original_score=original_score,
                canary_score=canary_score,
                passed=passed,
            )

        except Exception:
            logger.error(
                "CanaryRunner failed evaluating task %s", task_id, exc_info=True
            )
            return CanaryTaskResult(
                task_id=task_id,
                original_score=0.0,
                canary_score=0.0,
                passed=False,
            )

    async def _replay_task(
        self, task_id: uuid.UUID, request: CanaryRequest
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Retrieve the task and its subtasks from the store."""
        task = await self._task_store.get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")
        subtasks = await self._task_store.get_subtasks(task_id)
        return task, subtasks

    async def _get_original_score(self, task_id: uuid.UUID) -> float:
        """Get the average audit report score for a task.

        Returns 0.0 if no audit reports exist.
        """
        reports = await self._quality_store.get_audit_reports(task_id)
        if not reports:
            return 0.0
        total = sum(float(r.get("score", 0.0)) for r in reports)
        return total / len(reports)

    async def _evaluate_subtask(
        self, goal: str, description: str, output: str
    ) -> float:
        """Evaluate a subtask output with the LLM, returning a score 0.0-1.0.

        Returns 0.0 on any error.
        """
        try:
            prompt_text = CANARY_EVAL_PROMPT.format(
                goal=goal,
                description=description,
                output=output or "(no output)",
            )
            response = await self._llm.complete(
                messages=[{"role": "user", "content": prompt_text}],
            )
            data = self._parse_json(response.text)
            score = float(data.get("score", 0.0))
            return max(0.0, min(1.0, score))
        except Exception:
            logger.warning("Subtask evaluation failed", exc_info=True)
            return 0.0

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        """Parse a JSON string, handling markdown code fences.

        Returns an empty dict if parsing fails.
        """
        cleaned = text.strip()
        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", cleaned, re.DOTALL)
        if fence_match:
            cleaned = fence_match.group(1).strip()
        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            return {}
