"""Database-backed periodic job scheduler.

Persists job run timestamps to PostgreSQL so schedules survive restarts.
Catches up on missed runs when the application restarts.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from max.db.postgres import Database

logger = logging.getLogger(__name__)

JobCallback = Callable[[], Coroutine[Any, Any, None]]


class SchedulerJob:
    """A registered periodic job."""

    def __init__(
        self,
        name: str,
        interval_seconds: int,
        callback: JobCallback,
    ) -> None:
        self.name = name
        self.interval_seconds = interval_seconds
        self.callback = callback
        self.next_run_at: datetime = datetime.now(UTC)
        self.last_run_at: datetime | None = None

    def is_due(self) -> bool:
        """Return True if the job should run now."""
        return datetime.now(UTC) >= self.next_run_at

    def advance(self) -> None:
        """Advance next_run_at by the interval from now."""
        self.last_run_at = datetime.now(UTC)
        self.next_run_at = self.last_run_at + timedelta(
            seconds=self.interval_seconds
        )


class Scheduler:
    """Database-backed periodic job scheduler.

    Jobs are registered in-memory with callbacks. Run timestamps are
    persisted to the ``scheduler_state`` table so schedules survive restarts.
    On startup, ``load_state()`` restores next_run_at from the database;
    if a job's next_run_at is in the past, it fires immediately (catch-up).
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._jobs: dict[str, SchedulerJob] = {}
        self._task: asyncio.Task | None = None
        self._running = False

    def register(
        self,
        name: str,
        interval_seconds: int,
        callback: JobCallback,
    ) -> None:
        """Register a periodic job. Raises ValueError if duplicate."""
        if name in self._jobs:
            raise ValueError(f"Job '{name}' already registered")
        self._jobs[name] = SchedulerJob(name, interval_seconds, callback)

    async def load_state(self) -> None:
        """Load persisted job state from the database."""
        for job in self._jobs.values():
            row = await self._db.fetchone(
                "SELECT job_name, last_run_at, next_run_at, interval_seconds "
                "FROM scheduler_state WHERE job_name = $1",
                job.name,
            )
            if row:
                job.last_run_at = row["last_run_at"]
                job.next_run_at = row["next_run_at"]
                logger.info(
                    "Loaded scheduler state for %s: next_run=%s",
                    job.name,
                    job.next_run_at,
                )
            else:
                logger.info(
                    "No persisted state for %s, starting due now", job.name
                )

    async def _persist_state(self, job: SchedulerJob) -> None:
        """Save job state to the database (upsert)."""
        await self._db.execute(
            """
            INSERT INTO scheduler_state
                (job_name, last_run_at, next_run_at, interval_seconds, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (job_name) DO UPDATE SET
                last_run_at = EXCLUDED.last_run_at,
                next_run_at = EXCLUDED.next_run_at,
                interval_seconds = EXCLUDED.interval_seconds,
                updated_at = NOW()
            """,
            job.name,
            job.last_run_at,
            job.next_run_at,
            job.interval_seconds,
        )

    async def tick(self) -> None:
        """Check all jobs and execute any that are due."""
        for job in list(self._jobs.values()):
            if not job.is_due():
                continue
            try:
                logger.info("Executing scheduled job: %s", job.name)
                await job.callback()
            except Exception:
                logger.exception("Scheduled job %s failed", job.name)
            finally:
                job.advance()
                try:
                    await self._persist_state(job)
                except Exception:
                    logger.exception(
                        "Failed to persist state for job %s", job.name
                    )

    async def start(self) -> None:
        """Start the scheduler background loop."""
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Scheduler started with %d jobs", len(self._jobs))

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Scheduler stopped")

    async def _run_loop(self) -> None:
        """Background loop that ticks every second."""
        while self._running:
            try:
                await self.tick()
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Scheduler loop error")
                await asyncio.sleep(5)
