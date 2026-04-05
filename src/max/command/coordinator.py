"""CoordinatorAgent — intent classification, routing, state management."""

from __future__ import annotations

import json
import logging
import uuid as uuid_mod
from typing import Any

from max.agents.base import AgentConfig, AgentContext, BaseAgent
from max.command.models import CoordinatorAction, CoordinatorActionType
from max.command.task_store import TaskStore
from max.config import Settings
from max.llm.client import LLMClient
from max.memory.coordinator_state import CoordinatorStateManager
from max.memory.models import ActiveTaskSummary
from max.models.messages import Priority
from max.models.tasks import TaskStatus

logger = logging.getLogger(__name__)

ROUTING_SYSTEM_PROMPT = """You are the Coordinator for Max, an autonomous AI agent system.
Your job is to classify user intents and decide what action to take.

Current state:
{state_summary}

Classify the intent into exactly ONE action. Return ONLY valid JSON:
{{
  "action": "create_task | query_status | cancel_task | provide_context | clarification_response",
  "goal_anchor": "one-sentence summary of what user wants (for create_task)",
  "priority": "low | normal | high | urgent (for create_task)",
  "task_id": "UUID of relevant task (for cancel_task, provide_context, clarification_response)",
  "quality_criteria": {{}} ,
  "context_text": "additional context (for provide_context)",
  "clarification_answer": "user's answer (for clarification_response)",
  "reasoning": "brief explanation of your classification"
}}

Action guidelines:
- create_task: User wants something done. New work request.
- query_status: User asking about progress or current tasks.
- cancel_task: User wants to stop/cancel a task. Use most recent active task if not specified.
- provide_context: User is adding info to an existing in-progress task.
- clarification_response: User is answering a question Max asked them."""


class CoordinatorAgent(BaseAgent):
    """Central routing agent — classifies intents and manages task lifecycle."""

    def __init__(
        self,
        config: AgentConfig,
        llm: LLMClient,
        bus: Any,
        db: Any,
        warm_memory: Any,
        settings: Settings,
        state_manager: CoordinatorStateManager,
        task_store: TaskStore,
    ) -> None:
        context = AgentContext(bus=bus, db=db, warm_memory=warm_memory)
        super().__init__(config=config, llm=llm, context=context)
        self._bus = bus
        self._db = db
        self._warm = warm_memory
        self._settings = settings
        self._state_manager = state_manager
        self._task_store = task_store

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """BaseAgent abstract method — not used directly."""
        return {}

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Subscribe to bus channels."""
        await self._bus.subscribe("intents.new", self.on_intent)
        await self._bus.subscribe("tasks.complete", self.on_task_complete)
        await self.on_start()
        logger.info("CoordinatorAgent started")

    async def stop(self) -> None:
        """Unsubscribe from bus channels."""
        await self._bus.unsubscribe("intents.new", self.on_intent)
        await self._bus.unsubscribe("tasks.complete", self.on_task_complete)
        await self.on_stop()
        logger.info("CoordinatorAgent stopped")

    # ── Bus handlers ────────────────────────────────────────────────────

    async def on_intent(self, channel: str, data: dict[str, Any]) -> None:
        """Handle a new intent from the Communicator."""
        state = await self._state_manager.load()
        state_summary = self._build_state_summary(state)
        prompt = ROUTING_SYSTEM_PROMPT.format(state_summary=state_summary)
        user_message = data.get("user_message", "")

        self.reset()
        try:
            response = await self.think(
                messages=[{"role": "user", "content": user_message}],
                system_prompt=prompt,
            )
            action = self._parse_action_response(response.text)
        except Exception:
            logger.exception("Coordinator classification failed")
            action = CoordinatorAction(
                action=CoordinatorActionType.CREATE_TASK,
                goal_anchor=data.get("goal_anchor", user_message),
                priority=Priority(data.get("priority", "normal")),
                reasoning="Fallback: classification failed",
            )

        if action.action == CoordinatorActionType.CREATE_TASK:
            await self._handle_create_task(action, data, state)
        elif action.action == CoordinatorActionType.QUERY_STATUS:
            await self._handle_query_status(state)
        elif action.action == CoordinatorActionType.CANCEL_TASK:
            await self._handle_cancel_task(action, state)
        elif action.action == CoordinatorActionType.PROVIDE_CONTEXT:
            await self._handle_provide_context(action)
        elif action.action == CoordinatorActionType.CLARIFICATION_RESPONSE:
            await self._handle_clarification_response(action)

        await self._state_manager.save(state)

    async def on_task_complete(self, channel: str, data: dict[str, Any]) -> None:
        """Handle task completion from the Orchestrator."""
        task_id = uuid_mod.UUID(data["task_id"])
        success = data.get("success", False)

        if success:
            await self._task_store.update_task_status(task_id, TaskStatus.COMPLETED)
        else:
            await self._task_store.update_task_status(task_id, TaskStatus.FAILED)

        task = await self._task_store.get_task(task_id)
        goal = task["goal_anchor"] if task else "Unknown task"

        result_data = {
            "id": str(uuid_mod.uuid4()),
            "task_id": str(task_id),
            "goal_anchor": goal,
            "content": data.get("result_content", data.get("error", "Task completed")),
            "confidence": data.get("confidence", 1.0 if success else 0.0),
            "artifacts": [],
        }
        await self._bus.publish("results.new", result_data)

        state = await self._state_manager.load()
        state.active_tasks = [t for t in state.active_tasks if t.task_id != task_id]
        await self._state_manager.save(state)

    # ── Action handlers ─────────────────────────────────────────────────

    async def _handle_create_task(
        self,
        action: CoordinatorAction,
        intent_data: dict[str, Any],
        state: Any,
    ) -> None:
        intent_id = uuid_mod.UUID(intent_data["id"])
        task = await self._task_store.create_task(
            intent_id=intent_id,
            goal_anchor=action.goal_anchor or intent_data.get("goal_anchor", ""),
            priority=action.priority.value,
            quality_criteria=action.quality_criteria,
        )
        task_id = task["id"]
        await self._task_store.update_task_status(task_id, TaskStatus.PLANNING)

        state.active_tasks.append(
            ActiveTaskSummary(
                task_id=task_id,
                goal_anchor=task["goal_anchor"],
                status=TaskStatus.PLANNING,
                priority=Priority(action.priority),
            )
        )

        await self._bus.publish(
            "status_updates.new",
            {
                "id": str(uuid_mod.uuid4()),
                "task_id": str(task_id),
                "message": f"Planning: {task['goal_anchor']}",
                "progress": 0.0,
            },
        )
        await self._bus.publish(
            "tasks.plan",
            {
                "task_id": str(task_id),
                "goal_anchor": task["goal_anchor"],
                "priority": action.priority.value,
                "quality_criteria": action.quality_criteria,
            },
        )

    async def _handle_query_status(self, state: Any) -> None:
        if not state.active_tasks:
            message = "No active tasks. I'm idle and ready for work."
        else:
            lines = ["Current tasks:"]
            for t in state.active_tasks:
                lines.append(f"- [{t.status}] {t.goal_anchor}")
            message = "\n".join(lines)

        await self._bus.publish(
            "status_updates.new",
            {
                "id": str(uuid_mod.uuid4()),
                "task_id": str(uuid_mod.uuid4()),
                "message": message,
                "progress": 0.0,
            },
        )

    async def _handle_cancel_task(self, action: CoordinatorAction, state: Any) -> None:
        task_id = action.task_id
        if task_id is None and state.active_tasks:
            task_id = state.active_tasks[-1].task_id

        if task_id is None:
            await self._bus.publish(
                "status_updates.new",
                {
                    "id": str(uuid_mod.uuid4()),
                    "task_id": str(uuid_mod.uuid4()),
                    "message": "No active task to cancel.",
                    "progress": 0.0,
                },
            )
            return

        await self._task_store.update_task_status(task_id, TaskStatus.FAILED)
        await self._bus.publish("tasks.cancel", {"task_id": str(task_id)})

        goal = "Unknown"
        for t in state.active_tasks:
            if t.task_id == task_id:
                goal = t.goal_anchor
                break
        state.active_tasks = [t for t in state.active_tasks if t.task_id != task_id]

        await self._bus.publish(
            "status_updates.new",
            {
                "id": str(uuid_mod.uuid4()),
                "task_id": str(task_id),
                "message": f"Cancelled: {goal}",
                "progress": 0.0,
            },
        )

    async def _handle_provide_context(self, action: CoordinatorAction) -> None:
        if action.task_id:
            await self._bus.publish(
                "tasks.context_update",
                {
                    "task_id": str(action.task_id),
                    "context_text": action.context_text,
                },
            )

    async def _handle_clarification_response(self, action: CoordinatorAction) -> None:
        if action.task_id:
            await self._bus.publish(
                "clarifications.response",
                {
                    "task_id": str(action.task_id),
                    "answer": action.clarification_answer,
                },
            )

    # ── Helpers ──────────────────────────────────────────────────────────

    def _build_state_summary(self, state: Any) -> str:
        if not state.active_tasks:
            return "No active tasks. System is idle."
        lines = [f"Active tasks ({len(state.active_tasks)}):"]
        for t in state.active_tasks:
            lines.append(f"- [{t.status}] {t.goal_anchor} (priority={t.priority})")
        if state.task_queue:
            lines.append(f"\nQueued tasks: {len(state.task_queue)}")
        return "\n".join(lines)

    @staticmethod
    def _parse_action_response(text: str) -> CoordinatorAction:
        """Parse the LLM's JSON response into a CoordinatorAction.

        Handles both raw JSON and markdown-fenced JSON blocks.
        Falls back to a create_task action if parsing fails entirely.
        """
        text = text.strip()
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                try:
                    data = json.loads(part)
                    return CoordinatorAction.model_validate(data)
                except (json.JSONDecodeError, ValueError):
                    continue
        try:
            data = json.loads(text)
            return CoordinatorAction.model_validate(data)
        except (json.JSONDecodeError, ValueError):
            return CoordinatorAction(
                action=CoordinatorActionType.CREATE_TASK,
                goal_anchor=text[:200] if text else "Unknown",
                reasoning="Fallback: could not parse LLM response",
            )
