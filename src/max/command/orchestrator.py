"""OrchestratorAgent -- phase execution, worker lifecycle, result assembly."""

from __future__ import annotations

import asyncio
import logging
import uuid as uuid_mod
from collections import defaultdict
from typing import Any

from max.agents.base import AgentConfig, AgentContext, BaseAgent
from max.command.models import ExecutionPlan, SubtaskResult, WorkerConfig
from max.command.runner import AgentRunner
from max.command.task_store import TaskStore
from max.config import Settings
from max.llm.client import LLMClient
from max.models.tasks import TaskStatus

logger = logging.getLogger(__name__)

WORKER_BASE_PROMPT = """You are a worker agent for Max.

Your subtask: {description}

Context from previous phases:
{prior_results}

Produce the best possible result for this subtask.

Return ONLY valid JSON:
{{
  "content": "Your complete work product",
  "confidence": 0.0 to 1.0,
  "reasoning": "How you approached this"
}}"""


class OrchestratorAgent(BaseAgent):
    """Manages worker agent lifecycle and phase-by-phase execution.

    The orchestrator receives an ExecutionPlan (published on ``tasks.execute``),
    groups subtasks by phase number, and runs each phase sequentially.  Within a
    phase, subtasks execute concurrently via ``asyncio.gather``.  If a subtask
    fails, it is retried up to ``settings.worker_max_retries`` times.  If all
    retries are exhausted the entire task is marked as failed and later phases
    are skipped.

    Cancellation is cooperative: ``on_cancel`` adds the task_id to a set that
    ``_execute_subtask`` checks before each attempt.
    """

    def __init__(
        self,
        config: AgentConfig,
        llm: LLMClient,
        bus: Any,
        db: Any,
        warm_memory: Any,
        settings: Settings,
        task_store: TaskStore,
        runner: AgentRunner,
    ) -> None:
        context = AgentContext(bus=bus, db=db, warm_memory=warm_memory)
        super().__init__(config=config, llm=llm, context=context)
        self._bus = bus
        self._db = db
        self._warm = warm_memory
        self._settings = settings
        self._task_store = task_store
        self._runner = runner
        self._cancelled_tasks: set[uuid_mod.UUID] = set()

    # -- BaseAgent abstract method -------------------------------------------

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Not used directly; orchestration is driven via bus events."""
        return {}

    # -- Lifecycle ------------------------------------------------------------

    async def start(self) -> None:
        """Subscribe to execution, cancellation, and context-update channels."""
        await self._bus.subscribe("tasks.execute", self.on_execute)
        await self._bus.subscribe("tasks.cancel", self.on_cancel)
        await self._bus.subscribe("tasks.context_update", self.on_context_update)
        await self.on_start()
        logger.info("OrchestratorAgent started")

    async def stop(self) -> None:
        """Unsubscribe from all channels."""
        await self._bus.unsubscribe("tasks.execute", self.on_execute)
        await self._bus.unsubscribe("tasks.cancel", self.on_cancel)
        await self._bus.unsubscribe("tasks.context_update", self.on_context_update)
        await self.on_stop()
        logger.info("OrchestratorAgent stopped")

    # -- Event handlers -------------------------------------------------------

    async def on_execute(self, channel: str, data: dict[str, Any]) -> None:
        """Handle an execution plan: run subtasks phase-by-phase."""
        plan = ExecutionPlan.model_validate(data)
        task_id = plan.task_id

        db_subtasks = await self._task_store.get_subtasks(task_id)

        # Group subtasks by phase number.
        phases: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for st in db_subtasks:
            phases[st["phase_number"]].append(st)

        prior_results: list[SubtaskResult] = []
        all_succeeded = True
        total_subtasks = len(db_subtasks)
        completed_count = 0

        for phase_num in sorted(phases.keys()):
            if task_id in self._cancelled_tasks:
                all_succeeded = False
                break

            phase_subtasks = phases[phase_num]
            results = await asyncio.gather(
                *(self._execute_subtask(st, task_id, prior_results) for st in phase_subtasks),
                return_exceptions=True,
            )

            for result in results:
                if isinstance(result, BaseException):
                    logger.error("Subtask raised exception: %s", result)
                    all_succeeded = False
                    continue

                if result.success:
                    prior_results.append(result)
                    completed_count += 1
                    await self._task_store.update_subtask_result(
                        result.subtask_id,
                        {
                            "content": result.content,
                            "confidence": result.confidence,
                            "reasoning": result.reasoning,
                        },
                    )
                else:
                    all_succeeded = False
                    await self._task_store.update_subtask_status(
                        result.subtask_id,
                        TaskStatus.FAILED,
                    )

            # Publish progress after each phase.
            progress = completed_count / total_subtasks if total_subtasks > 0 else 0.0
            await self._bus.publish(
                "status_updates.new",
                {
                    "id": str(uuid_mod.uuid4()),
                    "task_id": str(task_id),
                    "message": (
                        f"Phase {phase_num} complete ({completed_count}/{total_subtasks} subtasks)"
                    ),
                    "progress": progress,
                },
            )

            if not all_succeeded:
                break

        # Assemble final result.
        if all_succeeded and prior_results:
            combined_content = "\n\n".join(r.content for r in prior_results if r.content)
            avg_confidence = sum(r.confidence for r in prior_results) / len(prior_results)

            await self._task_store.create_result(
                task_id=task_id,
                content=combined_content,
                confidence=avg_confidence,
            )
            await self._bus.publish(
                "tasks.complete",
                {
                    "task_id": str(task_id),
                    "success": True,
                    "result_content": combined_content,
                    "confidence": avg_confidence,
                },
            )
        else:
            error_msgs: list[str] = []
            if prior_results:
                error_msgs = [r.error for r in prior_results if not r.success and r.error]
            if not error_msgs:
                error_msgs = ["All subtasks failed"]

            await self._bus.publish(
                "tasks.complete",
                {
                    "task_id": str(task_id),
                    "success": False,
                    "error": "; ".join(error_msgs),
                },
            )

    async def on_cancel(self, channel: str, data: dict[str, Any]) -> None:
        """Mark a task for cancellation and fail its in-progress subtasks."""
        task_id = uuid_mod.UUID(data["task_id"])
        self._cancelled_tasks.add(task_id)
        logger.info("Task %s marked for cancellation", task_id)

        subtasks = await self._task_store.get_subtasks(task_id)
        for st in subtasks:
            if st["status"] in ("pending", "in_progress"):
                await self._task_store.update_subtask_status(
                    st["id"],
                    TaskStatus.FAILED,
                )

    async def on_context_update(self, channel: str, data: dict[str, Any]) -> None:
        """Handle a context update for a running task (informational)."""
        logger.info("Context update for task %s", data.get("task_id"))

    # -- Internal helpers -----------------------------------------------------

    async def _execute_subtask(
        self,
        subtask: dict[str, Any],
        task_id: uuid_mod.UUID,
        prior_results: list[SubtaskResult],
    ) -> SubtaskResult:
        """Execute a single subtask with retry logic.

        Returns a ``SubtaskResult``.  On success the result has
        ``success=True``; on exhausted retries it has the last error.
        """
        subtask_id = subtask["id"]
        description = subtask["description"]
        quality_criteria = subtask.get("quality_criteria", {})
        max_retries = self._settings.worker_max_retries

        await self._task_store.update_subtask_status(subtask_id, TaskStatus.IN_PROGRESS)

        prior_summary = (
            "\n".join(f"- {r.content[:200]}" for r in prior_results if r.content)
            or "None (first phase)"
        )

        system_prompt = WORKER_BASE_PROMPT.format(
            description=description,
            prior_results=prior_summary,
        )

        config = WorkerConfig(
            subtask_id=subtask_id,
            task_id=task_id,
            system_prompt=system_prompt,
            quality_criteria=quality_criteria if isinstance(quality_criteria, dict) else {},
        )

        context = AgentContext(bus=self._bus, db=self._db, warm_memory=self._warm)

        last_result: SubtaskResult | None = None
        for attempt in range(1 + max_retries):
            if task_id in self._cancelled_tasks:
                return SubtaskResult(
                    subtask_id=subtask_id,
                    task_id=task_id,
                    success=False,
                    error="Task cancelled",
                )

            try:
                result = await asyncio.wait_for(
                    self._runner.run(config, context),
                    timeout=self._settings.worker_timeout_seconds,
                )
            except TimeoutError:
                result = SubtaskResult(
                    subtask_id=subtask_id,
                    task_id=task_id,
                    success=False,
                    error=(f"Worker timed out after {self._settings.worker_timeout_seconds}s"),
                )

            if result.success:
                return result

            last_result = result
            if attempt < max_retries:
                logger.warning(
                    "Subtask %s failed (attempt %d/%d): %s",
                    subtask_id,
                    attempt + 1,
                    1 + max_retries,
                    result.error,
                )

        return last_result or SubtaskResult(
            subtask_id=subtask_id,
            task_id=task_id,
            success=False,
            error="All retries exhausted",
        )
