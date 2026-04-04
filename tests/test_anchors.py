"""Tests for anchor manager."""

from __future__ import annotations

import uuid

import pytest

from max.db.postgres import Database
from max.memory.anchors import AnchorManager
from max.memory.models import (
    AnchorLifecycleState,
    AnchorPermanenceClass,
)


@pytest.fixture
async def anchor_mgr(db: Database) -> AnchorManager:
    return AnchorManager(db)


class TestAnchorCRUD:
    async def test_create_anchor(self, anchor_mgr: AnchorManager):
        anchor = await anchor_mgr.create(
            content="User prefers terse updates",
            anchor_type="system_rule",
            permanence_class=AnchorPermanenceClass.ADAPTIVE,
            decay_rate=0.0005,
        )
        assert isinstance(anchor.id, uuid.UUID)
        assert anchor.lifecycle_state == AnchorLifecycleState.ACTIVE

    async def test_get_anchor(self, anchor_mgr: AnchorManager):
        created = await anchor_mgr.create(
            content="Always write tests",
            anchor_type="quality_standard",
        )
        fetched = await anchor_mgr.get(created.id)
        assert fetched is not None
        assert fetched.content == "Always write tests"

    async def test_get_missing_anchor(self, anchor_mgr: AnchorManager):
        result = await anchor_mgr.get(uuid.uuid4())
        assert result is None

    async def test_list_active_anchors(self, anchor_mgr: AnchorManager):
        await anchor_mgr.create(content="Anchor 1", anchor_type="user_goal")
        await anchor_mgr.create(content="Anchor 2", anchor_type="correction")
        active = await anchor_mgr.list_active()
        assert len(active) >= 2

    async def test_record_access(self, anchor_mgr: AnchorManager):
        anchor = await anchor_mgr.create(content="Test", anchor_type="system_rule")
        await anchor_mgr.record_access(anchor.id)
        updated = await anchor_mgr.get(anchor.id)
        assert updated.access_count == 1


class TestLifecycle:
    async def test_transition_to_stale(self, anchor_mgr: AnchorManager):
        anchor = await anchor_mgr.create(content="Old rule", anchor_type="system_rule")
        await anchor_mgr.transition(anchor.id, AnchorLifecycleState.STALE)
        updated = await anchor_mgr.get(anchor.id)
        assert updated.lifecycle_state == AnchorLifecycleState.STALE

    async def test_transition_to_archived(self, anchor_mgr: AnchorManager):
        anchor = await anchor_mgr.create(content="Outdated", anchor_type="decision")
        await anchor_mgr.transition(anchor.id, AnchorLifecycleState.STALE)
        await anchor_mgr.transition(anchor.id, AnchorLifecycleState.ARCHIVED)
        updated = await anchor_mgr.get(anchor.id)
        assert updated.lifecycle_state == AnchorLifecycleState.ARCHIVED

    async def test_permanent_anchor_cannot_be_archived(self, anchor_mgr: AnchorManager):
        anchor = await anchor_mgr.create(
            content="Security rule",
            anchor_type="security",
            permanence_class=AnchorPermanenceClass.PERMANENT,
            decay_rate=0.0,
        )
        with pytest.raises(ValueError, match="permanent"):
            await anchor_mgr.transition(anchor.id, AnchorLifecycleState.ARCHIVED)


class TestSupersession:
    async def test_supersede_anchor(self, anchor_mgr: AnchorManager):
        v1 = await anchor_mgr.create(
            content="Use MySQL",
            anchor_type="decision",
        )
        v2 = await anchor_mgr.supersede(
            old_anchor_id=v1.id,
            new_content="Use PostgreSQL",
        )
        assert v2.version == 2
        assert v2.parent_anchor_id == v1.id

        old = await anchor_mgr.get(v1.id)
        assert old.lifecycle_state == AnchorLifecycleState.SUPERSEDED
        assert old.superseded_by == v2.id

    async def test_supersession_chain(self, anchor_mgr: AnchorManager):
        v1 = await anchor_mgr.create(content="v1", anchor_type="decision")
        v2 = await anchor_mgr.supersede(v1.id, "v2")
        v3 = await anchor_mgr.supersede(v2.id, "v3")
        assert v3.version == 3
        assert v3.parent_anchor_id == v2.id
        v2_fetched = await anchor_mgr.get(v2.id)
        assert v2_fetched.superseded_by == v3.id


class TestRelevanceScore:
    async def test_update_relevance(self, anchor_mgr: AnchorManager):
        anchor = await anchor_mgr.create(content="Test", anchor_type="system_rule")
        await anchor_mgr.update_relevance(anchor.id, 0.5)
        updated = await anchor_mgr.get(anchor.id)
        assert updated.relevance_score == pytest.approx(0.5, abs=0.01)

    async def test_find_stale_candidates(self, anchor_mgr: AnchorManager):
        a1 = await anchor_mgr.create(content="Low", anchor_type="system_rule")
        await anchor_mgr.update_relevance(a1.id, 0.2)
        a2 = await anchor_mgr.create(content="High", anchor_type="user_goal")

        stale = await anchor_mgr.find_stale_candidates(threshold=0.3)
        stale_ids = {s.id for s in stale}
        assert a1.id in stale_ids
        assert a2.id not in stale_ids
