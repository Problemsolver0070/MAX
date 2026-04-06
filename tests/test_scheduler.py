"""Tests for the database-backed job scheduler."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from max.scheduler import Scheduler, SchedulerJob


class TestSchedulerJob:
    def test_creates_job(self):
        callback = AsyncMock()
        job = SchedulerJob(
            name="test_job",
            interval_seconds=3600,
            callback=callback,
        )
        assert job.name == "test_job"
        assert job.interval_seconds == 3600

    def test_is_due_when_next_run_in_past(self):
        job = SchedulerJob(
            name="test",
            interval_seconds=60,
            callback=AsyncMock(),
        )
        job.next_run_at = datetime.now(UTC) - timedelta(seconds=10)
        assert job.is_due() is True

    def test_not_due_when_next_run_in_future(self):
        job = SchedulerJob(
            name="test",
            interval_seconds=60,
            callback=AsyncMock(),
        )
        job.next_run_at = datetime.now(UTC) + timedelta(seconds=60)
        assert job.is_due() is False


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.fetchone = AsyncMock(return_value=None)
    db.fetchall = AsyncMock(return_value=[])
    db.execute = AsyncMock()
    return db


@pytest.fixture
def scheduler(mock_db):
    return Scheduler(db=mock_db)


class TestRegisterJob:
    async def test_registers_job(self, scheduler):
        callback = AsyncMock()
        scheduler.register("my_job", 3600, callback)
        assert "my_job" in scheduler._jobs

    async def test_register_duplicate_raises(self, scheduler):
        scheduler.register("dup", 60, AsyncMock())
        with pytest.raises(ValueError, match="already registered"):
            scheduler.register("dup", 60, AsyncMock())


class TestLoadState:
    async def test_loads_next_run_from_db(self, scheduler, mock_db):
        callback = AsyncMock()
        scheduler.register("persisted_job", 3600, callback)

        next_run = datetime.now(UTC) + timedelta(hours=1)
        mock_db.fetchone.return_value = {
            "job_name": "persisted_job",
            "last_run_at": datetime.now(UTC) - timedelta(hours=1),
            "next_run_at": next_run,
            "interval_seconds": 3600,
        }

        await scheduler.load_state()
        assert scheduler._jobs["persisted_job"].next_run_at == next_run

    async def test_catch_up_when_next_run_in_past(self, scheduler, mock_db):
        callback = AsyncMock()
        scheduler.register("late_job", 3600, callback)

        past = datetime.now(UTC) - timedelta(hours=2)
        mock_db.fetchone.return_value = {
            "job_name": "late_job",
            "last_run_at": past - timedelta(hours=1),
            "next_run_at": past,
            "interval_seconds": 3600,
        }

        await scheduler.load_state()
        assert scheduler._jobs["late_job"].is_due() is True


class TestTick:
    async def test_executes_due_job(self, scheduler, mock_db):
        callback = AsyncMock()
        scheduler.register("due_job", 60, callback)
        scheduler._jobs["due_job"].next_run_at = datetime.now(UTC) - timedelta(
            seconds=10
        )

        await scheduler.tick()
        callback.assert_called_once()

    async def test_skips_not_due_job(self, scheduler, mock_db):
        callback = AsyncMock()
        scheduler.register("future_job", 60, callback)
        scheduler._jobs["future_job"].next_run_at = datetime.now(UTC) + timedelta(
            hours=1
        )

        await scheduler.tick()
        callback.assert_not_called()

    async def test_updates_next_run_after_execution(self, scheduler, mock_db):
        callback = AsyncMock()
        scheduler.register("update_job", 60, callback)
        scheduler._jobs["update_job"].next_run_at = datetime.now(UTC) - timedelta(
            seconds=10
        )

        await scheduler.tick()
        # Next run should be ~60 seconds from now
        job = scheduler._jobs["update_job"]
        assert job.next_run_at > datetime.now(UTC)

    async def test_persists_state_after_execution(self, scheduler, mock_db):
        callback = AsyncMock()
        scheduler.register("persist_job", 60, callback)
        scheduler._jobs["persist_job"].next_run_at = datetime.now(UTC) - timedelta(
            seconds=10
        )

        await scheduler.tick()
        mock_db.execute.assert_called()

    async def test_handles_callback_error_gracefully(self, scheduler, mock_db):
        callback = AsyncMock(side_effect=Exception("boom"))
        scheduler.register("error_job", 60, callback)
        scheduler._jobs["error_job"].next_run_at = datetime.now(UTC) - timedelta(
            seconds=10
        )

        await scheduler.tick()  # should not raise
        # next_run should still advance to prevent infinite retry loops
        assert scheduler._jobs["error_job"].next_run_at > datetime.now(UTC)


class TestStartStop:
    async def test_start_creates_task(self, scheduler):
        await scheduler.start()
        assert scheduler._task is not None
        await scheduler.stop()

    async def test_stop_cancels_task(self, scheduler):
        await scheduler.start()
        await scheduler.stop()
        assert scheduler._task is None or scheduler._task.done()
