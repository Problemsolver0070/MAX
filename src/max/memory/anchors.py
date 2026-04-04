"""Anchor manager — lifecycle, supersession, usage tracking for context anchors."""

from __future__ import annotations

import json
import logging
import uuid as uuid_mod
from typing import Any

from max.db.postgres import Database
from max.memory.models import (
    AnchorLifecycleState,
    AnchorPermanenceClass,
    ContextAnchor,
)

logger = logging.getLogger(__name__)


class AnchorManager:
    """Manages context anchor CRUD, lifecycle, and supersession chains."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        content: str,
        anchor_type: str,
        source_task_id: uuid_mod.UUID | None = None,
        metadata: dict[str, Any] | None = None,
        permanence_class: AnchorPermanenceClass = AnchorPermanenceClass.ADAPTIVE,
        decay_rate: float = 0.001,
    ) -> ContextAnchor:
        anchor_id = uuid_mod.uuid4()
        meta_json = json.dumps(metadata or {})
        await self._db.execute(
            "INSERT INTO context_anchors "
            "(id, content, anchor_type, source_task_id, metadata, "
            "lifecycle_state, relevance_score, decay_rate, permanence_class, version) "
            "VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10)",
            anchor_id,
            content,
            anchor_type,
            source_task_id,
            meta_json,
            AnchorLifecycleState.ACTIVE.value,
            1.0,
            decay_rate,
            permanence_class.value,
            1,
        )
        return ContextAnchor(
            id=anchor_id,
            content=content,
            anchor_type=anchor_type,
            source_task_id=source_task_id,
            metadata=metadata or {},
            permanence_class=permanence_class,
            decay_rate=decay_rate,
        )

    async def get(self, anchor_id: uuid_mod.UUID) -> ContextAnchor | None:
        row = await self._db.fetchone(
            "SELECT id, content, anchor_type, source_task_id, metadata, "
            "lifecycle_state, relevance_score, last_accessed, access_count, "
            "decay_rate, permanence_class, superseded_by, version, "
            "parent_anchor_id, created_at "
            "FROM context_anchors WHERE id = $1",
            anchor_id,
        )
        if row is None:
            return None
        return self._row_to_anchor(row)

    async def list_active(self) -> list[ContextAnchor]:
        rows = await self._db.fetchall(
            "SELECT id, content, anchor_type, source_task_id, metadata, "
            "lifecycle_state, relevance_score, last_accessed, access_count, "
            "decay_rate, permanence_class, superseded_by, version, "
            "parent_anchor_id, created_at "
            "FROM context_anchors WHERE lifecycle_state = $1 "
            "ORDER BY relevance_score DESC",
            AnchorLifecycleState.ACTIVE.value,
        )
        return [self._row_to_anchor(r) for r in rows]

    async def record_access(self, anchor_id: uuid_mod.UUID) -> None:
        await self._db.execute(
            "UPDATE context_anchors "
            "SET access_count = access_count + 1, last_accessed = NOW() "
            "WHERE id = $1",
            anchor_id,
        )

    async def transition(
        self, anchor_id: uuid_mod.UUID, new_state: AnchorLifecycleState
    ) -> None:
        anchor = await self.get(anchor_id)
        if anchor is None:
            raise ValueError(f"Anchor {anchor_id} not found")
        if (
            anchor.permanence_class == AnchorPermanenceClass.PERMANENT
            and new_state == AnchorLifecycleState.ARCHIVED
        ):
            raise ValueError(f"Cannot archive permanent anchor {anchor_id}")
        await self._db.execute(
            "UPDATE context_anchors SET lifecycle_state = $1 WHERE id = $2",
            new_state.value,
            anchor_id,
        )

    async def supersede(
        self,
        old_anchor_id: uuid_mod.UUID,
        new_content: str,
        metadata: dict[str, Any] | None = None,
    ) -> ContextAnchor:
        old = await self.get(old_anchor_id)
        if old is None:
            raise ValueError(f"Anchor {old_anchor_id} not found")

        new_anchor = await self.create(
            content=new_content,
            anchor_type=old.anchor_type,
            source_task_id=old.source_task_id,
            metadata=metadata or old.metadata,
            permanence_class=old.permanence_class,
            decay_rate=old.decay_rate,
        )
        # Update new anchor's version and parent
        await self._db.execute(
            "UPDATE context_anchors SET version = $1, parent_anchor_id = $2 "
            "WHERE id = $3",
            old.version + 1,
            old.id,
            new_anchor.id,
        )
        # Mark old as superseded
        await self._db.execute(
            "UPDATE context_anchors SET lifecycle_state = $1, superseded_by = $2 "
            "WHERE id = $3",
            AnchorLifecycleState.SUPERSEDED.value,
            new_anchor.id,
            old.id,
        )
        # Return fresh copy
        return await self.get(new_anchor.id)

    async def update_relevance(
        self, anchor_id: uuid_mod.UUID, score: float
    ) -> None:
        await self._db.execute(
            "UPDATE context_anchors SET relevance_score = $1 WHERE id = $2",
            score,
            anchor_id,
        )

    async def find_stale_candidates(
        self, threshold: float = 0.3
    ) -> list[ContextAnchor]:
        rows = await self._db.fetchall(
            "SELECT id, content, anchor_type, source_task_id, metadata, "
            "lifecycle_state, relevance_score, last_accessed, access_count, "
            "decay_rate, permanence_class, superseded_by, version, "
            "parent_anchor_id, created_at "
            "FROM context_anchors "
            "WHERE lifecycle_state = $1 AND relevance_score < $2 "
            "AND permanence_class != $3",
            AnchorLifecycleState.ACTIVE.value,
            threshold,
            AnchorPermanenceClass.PERMANENT.value,
        )
        return [self._row_to_anchor(r) for r in rows]

    @staticmethod
    def _row_to_anchor(row: dict[str, Any]) -> ContextAnchor:
        return ContextAnchor(
            id=row["id"],
            content=row["content"],
            anchor_type=row["anchor_type"],
            source_task_id=row["source_task_id"],
            metadata=row["metadata"] if isinstance(row["metadata"], dict) else {},
            lifecycle_state=AnchorLifecycleState(row["lifecycle_state"]),
            relevance_score=float(row["relevance_score"]),
            last_accessed=row["last_accessed"],
            access_count=row["access_count"],
            decay_rate=float(row["decay_rate"]),
            permanence_class=AnchorPermanenceClass(row["permanence_class"]),
            superseded_by=row["superseded_by"],
            version=row["version"],
            parent_anchor_id=row["parent_anchor_id"],
            created_at=row["created_at"],
        )
