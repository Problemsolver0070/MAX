"""Integration test — end-to-end memory pipeline."""

from __future__ import annotations

import uuid

from max.db.postgres import Database
from max.db.redis_store import WarmMemory
from max.memory.anchors import AnchorManager
from max.memory.compaction import CompactionEngine
from max.memory.coordinator_state import CoordinatorStateManager
from max.memory.graph import MemoryGraph
from max.memory.metrics import MetricCollector
from max.memory.models import (
    AnchorLifecycleState,
    AnchorPermanenceClass,
    CompactionTier,
    CoordinatorState,
    EdgeRelation,
)
from max.memory.retrieval import RetrievalResult, RRFMerger


async def test_full_pipeline(db: Database, warm_memory: WarmMemory):
    """End-to-end: create anchors -> build graph -> check compaction -> verify state."""

    # 1. Create anchors
    anchor_mgr = AnchorManager(db)
    anchor = await anchor_mgr.create(
        content="User wants tests first",
        anchor_type="quality_standard",
        permanence_class=AnchorPermanenceClass.DURABLE,
        decay_rate=0.0002,
    )
    assert anchor.lifecycle_state == AnchorLifecycleState.ACTIVE

    # 2. Supersede anchor
    v2 = await anchor_mgr.supersede(anchor.id, "User wants TDD — red/green/refactor")
    old = await anchor_mgr.get(anchor.id)
    assert old.lifecycle_state == AnchorLifecycleState.SUPERSEDED
    assert v2.version == 2

    # 3. Build graph connections
    graph = MemoryGraph(db)
    task_cid = uuid.uuid4()
    anchor_cid = v2.id
    task_node = await graph.add_node("task", task_cid, {"goal": "Build API"})
    anchor_node = await graph.add_node("anchor", anchor_cid)
    await graph.add_edge(task_node, anchor_node, EdgeRelation.CONSTRAINS, weight=0.95)

    # 4. Traverse graph
    paths = await graph.traverse(task_node, max_depth=1)
    assert len(paths) == 1
    assert paths[0].terminal_node.content_id == anchor_cid

    # 5. Test compaction scoring
    relevance = CompactionEngine.calculate_relevance(
        base_relevance=0.8,
        hours_since_last_access=2.0,
        access_count=5,
        max_access_count=10,
        decay_rate=0.01,
        is_anchored=True,
    )
    assert relevance == 1.0  # capped at 1.0 (anchor_boost would push higher without cap)
    tier = CompactionEngine.determine_tier(relevance)
    assert tier == CompactionTier.FULL

    # 6. Test soft budget pressure
    pressure_normal = CompactionEngine.pressure_multiplier(0.5)
    pressure_high = CompactionEngine.pressure_multiplier(0.95)
    assert pressure_high > pressure_normal

    # 7. Test coordinator state
    state_mgr = CoordinatorStateManager(db=db, warm_memory=warm_memory)
    state = CoordinatorState()
    await state_mgr.save(state)
    loaded = await state_mgr.load()
    assert loaded.version == 1

    # 8. Record metrics
    metrics = MetricCollector(db)
    await metrics.record("integration_test_latency", 42.0)
    baseline = await metrics.get_baseline("integration_test_latency", window_hours=1)
    assert baseline is not None
    assert baseline.sample_count == 1

    # 9. Test RRF merge
    r1 = RetrievalResult(
        content_id=uuid.uuid4(),
        content_type="memory",
        content="Result A",
        rrf_score=0.0,
        strategies=["graph"],
    )
    r2 = RetrievalResult(
        content_id=uuid.uuid4(),
        content_type="anchor",
        content="Result B",
        rrf_score=0.0,
        strategies=["semantic"],
    )
    merged = RRFMerger.merge(
        {"graph": [r1], "semantic": [r2]},
        weights={"graph": 1.0, "semantic": 0.8},
        k=60,
    )
    assert len(merged) == 2
    assert all(r.rrf_score > 0 for r in merged)

    # 10. Graph stats
    stats = await graph.get_stats()
    assert stats.total_nodes >= 2
    assert stats.total_edges >= 1
