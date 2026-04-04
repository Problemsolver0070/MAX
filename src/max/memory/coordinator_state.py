"""Coordinator state document manager — load/save/backup."""

from __future__ import annotations

import json
import logging
import uuid as uuid_mod
from datetime import UTC, datetime

from max.db.postgres import Database
from max.db.redis_store import WarmMemory
from max.memory.models import CoordinatorState

logger = logging.getLogger(__name__)

STATE_KEY = "coordinator:state"
VERSION_KEY = "coordinator:version"


class CoordinatorStateManager:
    """Manages the Coordinator's persistent state document.

    The state document lives in Redis (warm memory) for fast access.
    Periodic backups are written to PostgreSQL's quality_ledger table
    for durability and audit trail.
    """

    def __init__(self, db: Database, warm_memory: WarmMemory) -> None:
        self._db = db
        self._warm = warm_memory
        self._version = 0

    async def load(self) -> CoordinatorState:
        """Load the state document from warm memory.

        Returns a default CoordinatorState with version=0 if nothing
        has been saved yet.
        """
        raw = await self._warm.get(STATE_KEY)
        if raw is None:
            return CoordinatorState(version=0)
        state = CoordinatorState.model_validate(raw)
        self._version = state.version
        return state

    async def save(self, state: CoordinatorState) -> None:
        """Save the state document to warm memory, incrementing version."""
        self._version += 1
        state.version = self._version
        state.last_updated = datetime.now(UTC)
        await self._warm.set(STATE_KEY, state.model_dump(mode="json"))
        logger.debug("Coordinator state saved (version %d)", self._version)

    async def backup_to_cold(self) -> None:
        """Backup current state to PostgreSQL quality_ledger."""
        raw = await self._warm.get(STATE_KEY)
        if raw is None:
            return
        await self._db.execute(
            "INSERT INTO quality_ledger (id, entry_type, content) VALUES ($1, $2, $3::jsonb)",
            uuid_mod.uuid4(),
            "coordinator_state_backup",
            json.dumps(raw),
        )
        logger.info("Coordinator state backed up to cold storage")
