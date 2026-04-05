import json
import uuid
from unittest.mock import AsyncMock

import pytest

from max.agents.base import AgentConfig
from max.command.planner import PLANNING_SYSTEM_PROMPT, PlannerAgent
from max.config import Settings
from max.llm.models import LLMResponse, ModelType


def _make_settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    return Settings()


def _make_llm_response(data: dict) -> LLMResponse:
    return LLMResponse(
        text=json.dumps(data),
        input_tokens=200,
        output_tokens=100,
        model="claude-opus-4-6",
        stop_reason="end_turn",
    )


def _make_planner(llm, bus, db, warm, settings):
    config = AgentConfig(name="planner", system_prompt="", model=ModelType.OPUS)
    task_store = AsyncMock()
    return PlannerAgent(
        config=config,
        llm=llm,
        bus=bus,
        db=db,
        warm_memory=warm,
        settings=settings,
        task_store=task_store,
    )


class TestPlannerDecomposition:
    @pytest.mark.asyncio
    async def test_successful_decomposition(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        task_id = uuid.uuid4()
        llm.complete = AsyncMock(return_value=_make_llm_response({
            "subtasks": [
                {"description": "Research topic", "phase_number": 1,
                 "tool_categories": [], "quality_criteria": {}, "estimated_complexity": "low"},
                {"description": "Write summary", "phase_number": 2,
                 "tool_categories": [], "quality_criteria": {}, "estimated_complexity": "moderate"},
            ],
            "needs_clarification": False,
            "reasoning": "Two-phase approach: research then summarize",
        }))

        planner = _make_planner(llm, bus, db, warm, settings)
        planner._task_store.create_subtask = AsyncMock(side_effect=[
            {"id": uuid.uuid4(), "description": "Research topic",
             "phase_number": 1, "status": "pending"},
            {"id": uuid.uuid4(), "description": "Write summary",
             "phase_number": 2, "status": "pending"},
        ])

        await planner.on_task_plan("tasks.plan", {
            "task_id": str(task_id),
            "goal_anchor": "Research Python 3.13",
            "priority": "normal",
            "quality_criteria": {},
        })

        calls = bus.publish.call_args_list
        channels = [c[0][0] for c in calls]
        assert "tasks.execute" in channels

        plan_call = next(c for c in calls if c[0][0] == "tasks.execute")
        plan_data = plan_call[0][1]
        assert plan_data["task_id"] == str(task_id)
        assert len(plan_data["subtasks"]) == 2
        assert plan_data["total_phases"] == 2

    @pytest.mark.asyncio
    async def test_clarification_needed(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        llm.complete = AsyncMock(return_value=_make_llm_response({
            "subtasks": [],
            "needs_clarification": True,
            "clarification_question": "Which app do you want deployed?",
            "clarification_options": ["App A", "App B"],
            "reasoning": "Ambiguous target",
        }))

        planner = _make_planner(llm, bus, db, warm, settings)
        task_id = uuid.uuid4()

        await planner.on_task_plan("tasks.plan", {
            "task_id": str(task_id),
            "goal_anchor": "Deploy the thing",
            "priority": "normal",
            "quality_criteria": {},
        })

        calls = bus.publish.call_args_list
        channels = [c[0][0] for c in calls]
        assert "clarifications.new" in channels
        assert "tasks.execute" not in channels
        assert task_id in planner._pending_clarifications


class TestPlannerClarificationResume:
    @pytest.mark.asyncio
    async def test_resume_after_clarification(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        task_id = uuid.uuid4()
        llm.complete = AsyncMock(return_value=_make_llm_response({
            "subtasks": [
                {"description": "Deploy App A", "phase_number": 1,
                 "tool_categories": [], "quality_criteria": {},
                 "estimated_complexity": "moderate"},
            ],
            "needs_clarification": False,
            "reasoning": "Clear after clarification",
        }))

        planner = _make_planner(llm, bus, db, warm, settings)
        planner._task_store.create_subtask = AsyncMock(return_value={
            "id": uuid.uuid4(), "description": "Deploy App A",
            "phase_number": 1, "status": "pending",
        })

        planner._pending_clarifications[task_id] = {
            "goal_anchor": "Deploy the thing",
            "priority": "normal",
            "quality_criteria": {},
        }

        await planner.on_clarification_response("clarifications.response", {
            "task_id": str(task_id),
            "answer": "App A to staging",
        })

        calls = bus.publish.call_args_list
        channels = [c[0][0] for c in calls]
        assert "tasks.execute" in channels
        assert task_id not in planner._pending_clarifications


class TestPlannerLifecycle:
    @pytest.mark.asyncio
    async def test_start_subscribes(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        planner = _make_planner(llm, bus, db, warm, settings)
        await planner.start()

        channels = [c[0][0] for c in bus.subscribe.call_args_list]
        assert "tasks.plan" in channels
        assert "clarifications.response" in channels
        assert "tasks.context_update" in channels

    @pytest.mark.asyncio
    async def test_stop_unsubscribes(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.unsubscribe = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        planner = _make_planner(llm, bus, db, warm, settings)
        await planner.start()
        await planner.stop()

        channels = [c[0][0] for c in bus.unsubscribe.call_args_list]
        assert "tasks.plan" in channels
        assert "clarifications.response" in channels


class TestPlannerMaxSubtasks:
    @pytest.mark.asyncio
    async def test_subtasks_capped_at_max(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("POSTGRES_PASSWORD", "test")
        monkeypatch.setenv("PLANNER_MAX_SUBTASKS", "3")
        settings = Settings()
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        llm.complete = AsyncMock(return_value=_make_llm_response({
            "subtasks": [
                {"description": f"Step {i}", "phase_number": 1,
                 "tool_categories": [], "quality_criteria": {},
                 "estimated_complexity": "low"}
                for i in range(5)
            ],
            "needs_clarification": False,
            "reasoning": "Many steps",
        }))

        planner = _make_planner(llm, bus, db, warm, settings)
        planner._task_store.create_subtask = AsyncMock(return_value={
            "id": uuid.uuid4(), "description": "Step",
            "phase_number": 1, "status": "pending",
        })

        await planner.on_task_plan("tasks.plan", {
            "task_id": str(uuid.uuid4()),
            "goal_anchor": "Big task",
            "priority": "normal",
            "quality_criteria": {},
        })

        assert planner._task_store.create_subtask.call_count == 3


class TestPlanningSystemPrompt:
    def test_prompt_has_required_fields(self):
        assert "subtasks" in PLANNING_SYSTEM_PROMPT
        assert "phase_number" in PLANNING_SYSTEM_PROMPT
        assert "needs_clarification" in PLANNING_SYSTEM_PROMPT
