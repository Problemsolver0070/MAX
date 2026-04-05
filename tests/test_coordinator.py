"""Tests for CoordinatorAgent — intent classification, routing, lifecycle."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from max.agents.base import AgentConfig
from max.command.coordinator import ROUTING_SYSTEM_PROMPT, CoordinatorAgent
from max.command.models import CoordinatorActionType
from max.config import Settings
from max.llm.models import LLMResponse, ModelType
from max.models.tasks import TaskStatus


def _make_settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    return Settings()


def _make_llm_response(action_dict: dict) -> LLMResponse:
    return LLMResponse(
        text=json.dumps(action_dict),
        input_tokens=100,
        output_tokens=50,
        model="claude-opus-4-6",
        stop_reason="end_turn",
    )


def _make_coordinator(llm, bus, db, warm, settings):
    config = AgentConfig(
        name="coordinator",
        system_prompt="",
        model=ModelType.OPUS,
    )
    state_mgr = AsyncMock()
    state_mgr.load = AsyncMock(
        return_value=MagicMock(
            active_tasks=[],
            task_queue=[],
            model_dump=MagicMock(return_value={}),
        )
    )
    state_mgr.save = AsyncMock()
    task_store = AsyncMock()
    return CoordinatorAgent(
        config=config,
        llm=llm,
        bus=bus,
        db=db,
        warm_memory=warm,
        settings=settings,
        state_manager=state_mgr,
        task_store=task_store,
    )


class TestCoordinatorClassification:
    @pytest.mark.asyncio
    async def test_create_task_action(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        llm.complete = AsyncMock(
            return_value=_make_llm_response(
                {
                    "action": "create_task",
                    "goal_anchor": "Deploy the app",
                    "priority": "high",
                    "quality_criteria": {},
                    "reasoning": "New deployment request",
                }
            )
        )

        coord = _make_coordinator(llm, bus, db, warm, settings)
        coord._task_store.create_task = AsyncMock(
            return_value={
                "id": uuid.uuid4(),
                "goal_anchor": "Deploy the app",
                "status": "pending",
                "priority": "high",
            }
        )

        intent_data = {
            "id": str(uuid.uuid4()),
            "user_message": "Deploy the app to staging",
            "source_platform": "telegram",
            "goal_anchor": "Deploy the app",
            "priority": "high",
        }
        await coord.on_intent("intents.new", intent_data)

        # Should publish status update and tasks.plan
        calls = bus.publish.call_args_list
        channels = [c[0][0] for c in calls]
        assert "status_updates.new" in channels
        assert "tasks.plan" in channels

    @pytest.mark.asyncio
    async def test_query_status_action(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        llm.complete = AsyncMock(
            return_value=_make_llm_response(
                {
                    "action": "query_status",
                    "reasoning": "User asking about progress",
                }
            )
        )

        coord = _make_coordinator(llm, bus, db, warm, settings)
        intent_data = {
            "id": str(uuid.uuid4()),
            "user_message": "What are you working on?",
            "source_platform": "telegram",
            "goal_anchor": "What are you working on?",
            "priority": "normal",
        }
        await coord.on_intent("intents.new", intent_data)

        calls = bus.publish.call_args_list
        channels = [c[0][0] for c in calls]
        assert "status_updates.new" in channels
        # Should NOT publish tasks.plan
        assert "tasks.plan" not in channels

    @pytest.mark.asyncio
    async def test_cancel_task_action(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        task_id = uuid.uuid4()
        llm.complete = AsyncMock(
            return_value=_make_llm_response(
                {
                    "action": "cancel_task",
                    "task_id": str(task_id),
                    "reasoning": "User wants to cancel",
                }
            )
        )

        coord = _make_coordinator(llm, bus, db, warm, settings)
        coord._state_manager.load = AsyncMock(
            return_value=MagicMock(
                active_tasks=[MagicMock(task_id=task_id, goal_anchor="Deploy")],
                task_queue=[],
                model_dump=MagicMock(return_value={}),
            )
        )
        coord._task_store.update_task_status = AsyncMock()

        intent_data = {
            "id": str(uuid.uuid4()),
            "user_message": "Cancel that",
            "source_platform": "telegram",
            "goal_anchor": "Cancel that",
            "priority": "normal",
        }
        await coord.on_intent("intents.new", intent_data)

        calls = bus.publish.call_args_list
        channels = [c[0][0] for c in calls]
        assert "tasks.cancel" in channels
        coord._task_store.update_task_status.assert_called_once()


class TestCoordinatorTaskComplete:
    @pytest.mark.asyncio
    async def test_on_task_complete_success(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        coord = _make_coordinator(llm, bus, db, warm, settings)
        task_id = uuid.uuid4()
        coord._task_store.update_task_status = AsyncMock()
        coord._task_store.get_task = AsyncMock(
            return_value={
                "id": task_id,
                "goal_anchor": "Deploy the app",
            }
        )

        await coord.on_task_complete(
            "tasks.complete",
            {
                "task_id": str(task_id),
                "success": True,
                "result_content": "Deployed successfully",
                "confidence": 0.95,
            },
        )

        coord._task_store.update_task_status.assert_called_once_with(task_id, TaskStatus.COMPLETED)
        calls = bus.publish.call_args_list
        channels = [c[0][0] for c in calls]
        assert "results.new" in channels

    @pytest.mark.asyncio
    async def test_on_task_complete_failure(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        coord = _make_coordinator(llm, bus, db, warm, settings)
        task_id = uuid.uuid4()
        coord._task_store.update_task_status = AsyncMock()
        coord._task_store.get_task = AsyncMock(
            return_value={
                "id": task_id,
                "goal_anchor": "Deploy the app",
            }
        )

        await coord.on_task_complete(
            "tasks.complete",
            {
                "task_id": str(task_id),
                "success": False,
                "error": "All subtasks failed",
            },
        )

        coord._task_store.update_task_status.assert_called_once_with(task_id, TaskStatus.FAILED)
        calls = bus.publish.call_args_list
        channels = [c[0][0] for c in calls]
        assert "results.new" in channels


class TestCoordinatorLifecycle:
    @pytest.mark.asyncio
    async def test_start_subscribes_to_channels(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        coord = _make_coordinator(llm, bus, db, warm, settings)
        await coord.start()

        subscribe_calls = bus.subscribe.call_args_list
        channels = [c[0][0] for c in subscribe_calls]
        assert "intents.new" in channels
        assert "tasks.complete" in channels

    @pytest.mark.asyncio
    async def test_stop_unsubscribes(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.unsubscribe = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        coord = _make_coordinator(llm, bus, db, warm, settings)
        await coord.start()
        await coord.stop()

        unsub_calls = bus.unsubscribe.call_args_list
        channels = [c[0][0] for c in unsub_calls]
        assert "intents.new" in channels
        assert "tasks.complete" in channels


class TestCoordinatorParsing:
    @pytest.mark.asyncio
    async def test_parse_llm_response_json(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()
        coord = _make_coordinator(llm, bus, db, warm, settings)

        result = coord._parse_action_response('{"action": "query_status", "reasoning": "test"}')
        assert result.action == CoordinatorActionType.QUERY_STATUS

    @pytest.mark.asyncio
    async def test_parse_llm_response_markdown(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()
        coord = _make_coordinator(llm, bus, db, warm, settings)

        result = coord._parse_action_response(
            '```json\n{"action": "create_task", "goal_anchor": "Test", "reasoning": "ok"}\n```'
        )
        assert result.action == CoordinatorActionType.CREATE_TASK
        assert result.goal_anchor == "Test"


class TestRoutingSystemPrompt:
    def test_prompt_contains_action_types(self):
        assert "create_task" in ROUTING_SYSTEM_PROMPT
        assert "query_status" in ROUTING_SYSTEM_PROMPT
        assert "cancel_task" in ROUTING_SYSTEM_PROMPT
        assert "provide_context" in ROUTING_SYSTEM_PROMPT
        assert "clarification_response" in ROUTING_SYSTEM_PROMPT
