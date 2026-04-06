"""Tests for orphaned task recovery on startup."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

from max.api.dependencies import AppState


def _make_state(**overrides) -> AppState:
    defaults = {
        "settings": MagicMock(task_recovery_enabled=True),
        "db": MagicMock(),
        "redis_client": MagicMock(),
        "bus": AsyncMock(),
        "transport": None,
        "warm_memory": MagicMock(),
        "llm": MagicMock(),
        "circuit_breaker": MagicMock(),
        "task_store": AsyncMock(),
        "quality_store": MagicMock(),
        "evolution_store": MagicMock(),
        "sentinel_store": MagicMock(),
        "state_manager": MagicMock(),
        "scheduler": MagicMock(),
        "tool_registry": MagicMock(),
        "tool_executor": MagicMock(),
        "agents": {},
        "start_time": 0.0,
    }
    defaults.update(overrides)
    return AppState(**defaults)


class TestRecoverOrphanedTasks:
    async def test_republishes_planned_tasks(self):
        from max.recovery import recover_orphaned_tasks

        task_id = uuid.uuid4()
        state = _make_state()
        state.task_store.get_active_tasks = AsyncMock(
            return_value=[{"id": str(task_id), "status": "planned", "goal_anchor": "do thing"}]
        )
        count = await recover_orphaned_tasks(state)
        assert count == 1
        state.bus.publish.assert_called_once_with(
            "tasks.execute", {"task_id": str(task_id), "recovery": True}
        )

    async def test_republishes_executing_tasks(self):
        from max.recovery import recover_orphaned_tasks

        task_id = uuid.uuid4()
        state = _make_state()
        state.task_store.get_active_tasks = AsyncMock(
            return_value=[{"id": str(task_id), "status": "executing", "goal_anchor": "run"}]
        )
        count = await recover_orphaned_tasks(state)
        assert count == 1
        state.bus.publish.assert_called_once_with(
            "tasks.execute", {"task_id": str(task_id), "recovery": True}
        )

    async def test_republishes_auditing_tasks(self):
        from max.recovery import recover_orphaned_tasks

        task_id = uuid.uuid4()
        state = _make_state()
        state.task_store.get_active_tasks = AsyncMock(
            return_value=[{"id": str(task_id), "status": "auditing", "goal_anchor": "check"}]
        )
        count = await recover_orphaned_tasks(state)
        assert count == 1
        state.bus.publish.assert_called_once_with(
            "audit.request", {"task_id": str(task_id), "recovery": True}
        )

    async def test_skips_pending_tasks(self):
        from max.recovery import recover_orphaned_tasks

        state = _make_state()
        state.task_store.get_active_tasks = AsyncMock(
            return_value=[{"id": str(uuid.uuid4()), "status": "pending", "goal_anchor": "wait"}]
        )
        count = await recover_orphaned_tasks(state)
        assert count == 0
        state.bus.publish.assert_not_called()

    async def test_handles_empty_task_list(self):
        from max.recovery import recover_orphaned_tasks

        state = _make_state()
        state.task_store.get_active_tasks = AsyncMock(return_value=[])
        count = await recover_orphaned_tasks(state)
        assert count == 0
