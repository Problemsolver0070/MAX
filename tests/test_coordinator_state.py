"""Tests for coordinator state manager."""

from __future__ import annotations

import uuid

import pytest

from max.db.postgres import Database
from max.db.redis_store import WarmMemory
from max.memory.coordinator_state import CoordinatorStateManager
from max.memory.models import (
    ActiveTaskSummary,
    ContextBudgetStatus,
    CoordinatorState,
)
from max.models.messages import Priority
from max.models.tasks import TaskStatus


@pytest.fixture
async def state_mgr(db: Database, warm_memory: WarmMemory) -> CoordinatorStateManager:
    return CoordinatorStateManager(db=db, warm_memory=warm_memory)


class TestStateLoadSave:
    async def test_save_and_load(self, state_mgr: CoordinatorStateManager):
        state = CoordinatorState()
        await state_mgr.save(state)
        loaded = await state_mgr.load()
        assert loaded is not None
        assert loaded.version == 1

    async def test_version_increments(self, state_mgr: CoordinatorStateManager):
        state = CoordinatorState()
        await state_mgr.save(state)
        await state_mgr.save(state)
        loaded = await state_mgr.load()
        assert loaded.version == 2

    async def test_load_empty_returns_default(self, state_mgr: CoordinatorStateManager):
        loaded = await state_mgr.load()
        assert loaded is not None
        assert loaded.version == 0

    async def test_save_with_active_tasks(self, state_mgr: CoordinatorStateManager):
        state = CoordinatorState()
        state.active_tasks.append(
            ActiveTaskSummary(
                task_id=uuid.uuid4(),
                goal_anchor="Build API",
                status=TaskStatus.IN_PROGRESS,
                priority=Priority.HIGH,
            )
        )
        await state_mgr.save(state)
        loaded = await state_mgr.load()
        assert len(loaded.active_tasks) == 1
        assert loaded.active_tasks[0].goal_anchor == "Build API"


class TestColdBackup:
    async def test_backup_to_cold(self, state_mgr: CoordinatorStateManager):
        state = CoordinatorState()
        state.context_budget = ContextBudgetStatus(
            total_warm_tokens=50000,
            warm_capacity_percent=0.5,
            compaction_pressure=1.0,
            items_per_tier={"full": 10},
            items_compacted_last_hour=0,
        )
        await state_mgr.save(state)
        await state_mgr.backup_to_cold()

        row = await state_mgr._db.fetchone(
            "SELECT content FROM quality_ledger "
            "WHERE entry_type = 'coordinator_state_backup' "
            "ORDER BY created_at DESC LIMIT 1"
        )
        assert row is not None
