"""PlannerAgent -- task decomposition, clarification, execution plan creation."""

from __future__ import annotations

import json
import logging
import uuid as uuid_mod
from typing import Any

from max.agents.base import AgentConfig, AgentContext, BaseAgent
from max.command.models import ExecutionPlan, PlannedSubtask
from max.command.task_store import TaskStore
from max.config import Settings
from max.llm.client import LLMClient

logger = logging.getLogger(__name__)

PLANNING_SYSTEM_PROMPT = """You are the Planner for Max, an autonomous AI agent system.
Your job is to decompose a task into executable subtasks organized by phase.

Subtasks within the same phase can run in parallel. Phases execute sequentially.

Goal: {goal_anchor}
Priority: {priority}
Quality criteria: {quality_criteria}

Return ONLY valid JSON:
{{
  "subtasks": [
    {{
      "description": "Clear description of what this subtask does",
      "phase_number": 1,
      "tool_categories": [],
      "quality_criteria": {{}},
      "estimated_complexity": "low | moderate | high"
    }}
  ],
  "needs_clarification": false,
  "clarification_question": null,
  "clarification_options": [],
  "reasoning": "Explanation of your decomposition"
}}

Rules:
- Phase numbers start at 1
- Subtasks in the same phase have no dependencies on each other
- Each phase depends on all previous phases completing
- Be specific -- each subtask should be independently executable
- If the goal is ambiguous, set needs_clarification=true and provide a question"""


class PlannerAgent(BaseAgent):
    """Decomposes tasks into phased execution plans."""

    def __init__(
        self,
        config: AgentConfig,
        llm: LLMClient,
        bus: Any,
        db: Any,
        warm_memory: Any,
        settings: Settings,
        task_store: TaskStore,
    ) -> None:
        context = AgentContext(bus=bus, db=db, warm_memory=warm_memory)
        super().__init__(config=config, llm=llm, context=context)
        self._bus = bus
        self._db = db
        self._warm = warm_memory
        self._settings = settings
        self._task_store = task_store
        self._pending_clarifications: dict[uuid_mod.UUID, dict[str, Any]] = {}

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """BaseAgent requires this. PlannerAgent uses event-driven methods instead."""
        return {}

    async def start(self) -> None:
        """Subscribe to planning-related channels and start the agent."""
        await self._bus.subscribe("tasks.plan", self.on_task_plan)
        await self._bus.subscribe("clarifications.response", self.on_clarification_response)
        await self._bus.subscribe("tasks.context_update", self.on_context_update)
        await self.on_start()
        logger.info("PlannerAgent started")

    async def stop(self) -> None:
        """Unsubscribe from channels and stop the agent."""
        await self._bus.unsubscribe("tasks.plan", self.on_task_plan)
        await self._bus.unsubscribe("clarifications.response", self.on_clarification_response)
        await self._bus.unsubscribe("tasks.context_update", self.on_context_update)
        await self.on_stop()
        logger.info("PlannerAgent stopped")

    async def on_task_plan(self, channel: str, data: dict[str, Any]) -> None:
        """Handle a task planning request from the bus."""
        task_id = uuid_mod.UUID(data["task_id"])
        goal_anchor = data.get("goal_anchor", "")
        priority = data.get("priority", "normal")
        quality_criteria = data.get("quality_criteria", {})
        await self._decompose_and_publish(task_id, goal_anchor, priority, quality_criteria)

    async def on_clarification_response(self, channel: str, data: dict[str, Any]) -> None:
        """Resume planning after the user provides clarification."""
        task_id = uuid_mod.UUID(data["task_id"])
        answer = data.get("answer", "")
        pending = self._pending_clarifications.pop(task_id, None)
        if pending is None:
            logger.warning("Clarification response for unknown task %s", task_id)
            return
        original_goal = pending.get("goal_anchor", "")
        enriched_goal = f"{original_goal}\nUser clarification: {answer}"
        await self._decompose_and_publish(
            task_id,
            enriched_goal,
            pending.get("priority", "normal"),
            pending.get("quality_criteria", {}),
        )

    async def on_context_update(self, channel: str, data: dict[str, Any]) -> None:
        """Store extra context for a task awaiting clarification."""
        task_id = uuid_mod.UUID(data["task_id"])
        context_text = data.get("context_text", "")
        if task_id in self._pending_clarifications:
            self._pending_clarifications[task_id]["extra_context"] = context_text

    async def _decompose_and_publish(
        self,
        task_id: uuid_mod.UUID,
        goal_anchor: str,
        priority: str,
        quality_criteria: dict[str, Any],
    ) -> None:
        """Call the LLM to decompose the goal, then publish the plan or request clarification."""
        prompt = PLANNING_SYSTEM_PROMPT.format(
            goal_anchor=goal_anchor,
            priority=priority,
            quality_criteria=json.dumps(quality_criteria) if quality_criteria else "None",
        )
        self.reset()
        try:
            response = await self.think(
                messages=[{"role": "user", "content": f"Decompose this task: {goal_anchor}"}],
                system_prompt=prompt,
            )
            parsed = self._parse_plan_response(response.text)
        except Exception:
            logger.exception("Planner decomposition failed for task %s", task_id)
            parsed = {
                "subtasks": [
                    {
                        "description": goal_anchor,
                        "phase_number": 1,
                        "tool_categories": [],
                        "quality_criteria": {},
                        "estimated_complexity": "moderate",
                    }
                ],
                "needs_clarification": False,
                "reasoning": "Fallback: single-step execution",
            }

        if parsed.get("needs_clarification"):
            self._pending_clarifications[task_id] = {
                "goal_anchor": goal_anchor,
                "priority": priority,
                "quality_criteria": quality_criteria,
            }
            await self._bus.publish(
                "clarifications.new",
                {
                    "id": str(uuid_mod.uuid4()),
                    "task_id": str(task_id),
                    "question": parsed.get("clarification_question", "Could you clarify?"),
                    "options": parsed.get("clarification_options", []),
                },
            )
            return

        raw_subtasks = parsed.get("subtasks", [])
        max_subtasks = self._settings.planner_max_subtasks
        capped_subtasks = raw_subtasks[:max_subtasks]

        planned: list[PlannedSubtask] = []
        for st_data in capped_subtasks:
            ps = PlannedSubtask(
                description=st_data.get("description", ""),
                phase_number=st_data.get("phase_number", 1),
                tool_categories=st_data.get("tool_categories", []),
                quality_criteria=st_data.get("quality_criteria", {}),
                estimated_complexity=st_data.get("estimated_complexity", "moderate"),
            )
            await self._task_store.create_subtask(
                task_id=task_id,
                description=ps.description,
                phase_number=ps.phase_number,
                tool_categories=ps.tool_categories,
                quality_criteria=ps.quality_criteria,
                estimated_complexity=ps.estimated_complexity,
            )
            planned.append(ps)

        total_phases = max((p.phase_number for p in planned), default=1)
        plan = ExecutionPlan(
            task_id=task_id,
            goal_anchor=goal_anchor,
            subtasks=planned,
            total_phases=total_phases,
            reasoning=parsed.get("reasoning", ""),
        )
        await self._bus.publish("tasks.execute", plan.model_dump(mode="json"))

    @staticmethod
    def _parse_plan_response(text: str) -> dict[str, Any]:
        """Extract JSON from the LLM response, handling markdown fences."""
        text = text.strip()
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                try:
                    return json.loads(part)
                except (json.JSONDecodeError, ValueError):
                    continue
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return {
                "subtasks": [],
                "needs_clarification": True,
                "clarification_question": "I couldn't understand the task. Could you rephrase?",
                "reasoning": "Failed to parse plan",
            }
