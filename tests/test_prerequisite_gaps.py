"""Tests for prerequisite gap fixes needed by Plan B composition root."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestCoordinatorStateManagerUpdateEvolution:
    """CoordinatorStateManager.update_evolution_state()."""

    async def test_updates_evolution_fields_in_state(self):
        from max.memory.coordinator_state import CoordinatorStateManager
        from max.memory.models import CoordinatorState

        db = AsyncMock()
        warm = AsyncMock()
        mgr = CoordinatorStateManager(db, warm)

        # Pre-seed a state in warm memory
        initial = CoordinatorState(version=1)
        warm.get = AsyncMock(return_value=initial.model_dump(mode="json"))

        await mgr.update_evolution_state(
            {"evolution_frozen": True, "freeze_reason": "test freeze"}
        )

        # Should have called save (which calls warm.set)
        warm.set.assert_called_once()
        saved_data = warm.set.call_args[0][1]
        assert saved_data["evolution"]["evolution_frozen"] is True
        assert saved_data["evolution"]["freeze_reason"] == "test freeze"

    async def test_preserves_existing_evolution_fields(self):
        from max.memory.coordinator_state import CoordinatorStateManager
        from max.memory.models import CoordinatorState

        db = AsyncMock()
        warm = AsyncMock()
        mgr = CoordinatorStateManager(db, warm)

        initial = CoordinatorState(version=1)
        initial_dump = initial.model_dump(mode="json")
        # Set an initial value on the evolution sub-doc
        initial_dump["evolution"]["canary_status"] = "running"
        warm.get = AsyncMock(return_value=initial_dump)

        await mgr.update_evolution_state({"evolution_frozen": True})

        saved_data = warm.set.call_args[0][1]
        assert saved_data["evolution"]["evolution_frozen"] is True
        assert saved_data["evolution"]["canary_status"] == "running"


class TestTaskStoreGetCompletedTasks:
    """TaskStore.get_completed_tasks()."""

    async def test_returns_completed_tasks(self):
        from max.command.task_store import TaskStore

        db = AsyncMock()
        db.fetchall = AsyncMock(
            return_value=[
                {"id": uuid.uuid4(), "goal_anchor": "task 1", "status": "completed", "quality_criteria": "{}"},
                {"id": uuid.uuid4(), "goal_anchor": "task 2", "status": "completed", "quality_criteria": "{}"},
            ]
        )
        store = TaskStore(db)
        tasks = await store.get_completed_tasks(limit=10)
        assert len(tasks) == 2
        db.fetchall.assert_called_once()

    async def test_respects_limit(self):
        from max.command.task_store import TaskStore

        db = AsyncMock()
        db.fetchall = AsyncMock(return_value=[])
        store = TaskStore(db)
        await store.get_completed_tasks(limit=5)
        query = db.fetchall.call_args[0][0]
        assert "LIMIT" in query


class TestEvolutionDirectorStop:
    """EvolutionDirectorAgent.stop() unsubscribes from bus."""

    async def test_stop_unsubscribes_channels(self):
        from max.evolution.director import EvolutionDirectorAgent

        bus = AsyncMock()
        agent = EvolutionDirectorAgent.__new__(EvolutionDirectorAgent)
        agent._bus = bus

        await agent.stop()

        assert bus.unsubscribe.call_count == 2
        channels = [call.args[0] for call in bus.unsubscribe.call_args_list]
        assert "evolution.trigger" in channels
        assert "evolution.proposal" in channels
