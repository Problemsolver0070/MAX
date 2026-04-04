"""Tests for Phase 2 memory system models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from max.memory.models import (
    ActiveTaskSummary,
    AnchorInventory,
    AnchorLifecycleState,
    AnchorPermanenceClass,
    AuditPipelineState,
    CommunicationState,
    CompactionTier,
    ComparisonResult,
    ContextAnchor,
    ContextBudgetStatus,
    ContextPackage,
    CoordinatorState,
    EdgeRelation,
    EvolutionState,
    GraphEdge,
    GraphNode,
    GraphStats,
    MetricBaseline,
    QualityPulse,
    QueuedTask,
    RetrievalResult,
    ShelvedImprovement,
    SubGraph,
    TraversalPath,
)
from max.models.messages import Priority
from max.models.tasks import TaskStatus


class TestEnums:
    def test_anchor_lifecycle_states(self):
        assert AnchorLifecycleState.ACTIVE == "active"
        assert AnchorLifecycleState.STALE == "stale"
        assert AnchorLifecycleState.SUPERSEDED == "superseded"
        assert AnchorLifecycleState.ARCHIVED == "archived"

    def test_anchor_permanence_classes(self):
        assert AnchorPermanenceClass.PERMANENT == "permanent"
        assert AnchorPermanenceClass.DURABLE == "durable"
        assert AnchorPermanenceClass.ADAPTIVE == "adaptive"
        assert AnchorPermanenceClass.TASK_SCOPED == "task_scoped"

    def test_edge_relations(self):
        assert EdgeRelation.DERIVED_FROM == "derived_from"
        assert EdgeRelation.DEPENDS_ON == "depends_on"
        assert EdgeRelation.SUPERSEDES == "supersedes"
        assert EdgeRelation.RELATED_TO == "related_to"
        assert EdgeRelation.PRODUCED_BY == "produced_by"
        assert EdgeRelation.CONSTRAINS == "constrains"
        assert EdgeRelation.PARENT_OF == "parent_of"
        assert EdgeRelation.TRIGGERED_BY == "triggered_by"
        assert EdgeRelation.REFERENCES == "references"

    def test_compaction_tiers(self):
        assert CompactionTier.FULL == "full"
        assert CompactionTier.SUMMARIZED == "summarized"
        assert CompactionTier.POINTER == "pointer"
        assert CompactionTier.COLD_ONLY == "cold_only"


class TestContextAnchor:
    def test_create_default(self):
        anchor = ContextAnchor(content="User prefers terse updates", anchor_type="system_rule")
        assert anchor.content == "User prefers terse updates"
        assert anchor.anchor_type == "system_rule"
        assert anchor.lifecycle_state == AnchorLifecycleState.ACTIVE
        assert anchor.relevance_score == 1.0
        assert anchor.access_count == 0
        assert anchor.decay_rate == 0.001
        assert anchor.permanence_class == AnchorPermanenceClass.ADAPTIVE
        assert anchor.superseded_by is None
        assert anchor.version == 1
        assert anchor.parent_anchor_id is None

    def test_create_permanent_security_anchor(self):
        anchor = ContextAnchor(
            content="Only accept user ID 12345",
            anchor_type="security",
            permanence_class=AnchorPermanenceClass.PERMANENT,
            decay_rate=0.0,
        )
        assert anchor.permanence_class == AnchorPermanenceClass.PERMANENT
        assert anchor.decay_rate == 0.0


class TestGraphModels:
    def test_graph_node(self):
        node = GraphNode(node_type="task", content_id=uuid.uuid4())
        assert node.node_type == "task"
        assert node.metadata == {}

    def test_graph_edge(self):
        src = uuid.uuid4()
        tgt = uuid.uuid4()
        edge = GraphEdge(source_id=src, target_id=tgt, relation=EdgeRelation.DEPENDS_ON)
        assert edge.weight == 1.0
        assert edge.source_id == src
        assert edge.target_id == tgt

    def test_traversal_path(self):
        node = GraphNode(node_type="task", content_id=uuid.uuid4())
        edge = GraphEdge(
            source_id=uuid.uuid4(),
            target_id=node.id,
            relation=EdgeRelation.DERIVED_FROM,
        )
        path = TraversalPath(edges=[edge], terminal_node=node, score=0.85)
        assert path.score == 0.85
        assert len(path.edges) == 1

    def test_subgraph(self):
        sg = SubGraph(center_id=uuid.uuid4(), nodes=[], edges=[], depth=2)
        assert sg.depth == 2

    def test_graph_stats(self):
        stats = GraphStats(
            total_nodes=100,
            total_edges=250,
            orphan_nodes=3,
            avg_edge_weight=0.72,
        )
        assert stats.total_nodes == 100


class TestRetrievalResult:
    def test_create(self):
        result = RetrievalResult(
            content_id=uuid.uuid4(),
            content_type="memory",
            content="Some retrieved text",
            rrf_score=0.85,
            strategies=["graph", "semantic"],
            tier="full",
        )
        assert result.rrf_score == 0.85
        assert "graph" in result.strategies
        assert result.graph_path is None
        assert result.similarity_score is None


class TestContextPackage:
    def test_create(self):
        pkg = ContextPackage(
            task_summary="Fix login timeout",
            anchors=[],
            graph_context=[],
            semantic_matches=[],
            agent_state={},
            navigation_hints="Section A covers auth flow",
            token_count=5000,
            budget_remaining=19576,
            packaging_reasoning="Included auth anchors",
        )
        assert pkg.token_count == 5000
        assert pkg.budget_remaining == 19576


class TestCoordinatorStateModels:
    def test_active_task_summary(self):
        task_id = uuid.uuid4()
        summary = ActiveTaskSummary(
            task_id=task_id,
            goal_anchor="Build REST API",
            status=TaskStatus.IN_PROGRESS,
            assigned_agent_ids=["agent-1"],
            subtask_count=3,
            subtasks_completed=1,
            priority=Priority.HIGH,
        )
        assert summary.subtasks_completed == 1
        assert summary.estimated_completion is None

    def test_queued_task(self):
        qt = QueuedTask(
            task_id=uuid.uuid4(),
            goal_anchor="Refactor auth",
            priority=Priority.NORMAL,
            estimated_complexity="moderate",
        )
        assert qt.dependencies == []

    def test_quality_pulse(self):
        pulse = QualityPulse(
            avg_score_last_24h=0.88,
            pass_rate_last_24h=0.95,
            trend="improving",
            consecutive_failures=0,
        )
        assert pulse.trend == "improving"

    def test_coordinator_state(self):
        now = datetime.now(UTC)
        state = CoordinatorState(
            active_tasks=[],
            task_queue=[],
            agent_registry=[],
            context_budget=ContextBudgetStatus(
                total_warm_tokens=50000,
                warm_capacity_percent=0.5,
                compaction_pressure=1.0,
                items_per_tier={"full": 20, "summarized": 5},
                last_compaction_run=now,
                items_compacted_last_hour=3,
            ),
            communication=CommunicationState(
                pending_user_messages=0,
                active_channels=["telegram"],
                last_user_interaction=now,
                last_outbound_message=now,
                pending_clarifications=0,
                queued_status_updates=0,
            ),
            active_anchors=AnchorInventory(
                total_active=10,
                total_stale=2,
                total_superseded=1,
                anchors_by_type={"user_goal": 3},
                anchors_by_permanence={"permanent": 1},
                last_re_evaluation=now,
                pending_re_evaluations=0,
            ),
            graph_health=GraphStats(
                total_nodes=50,
                total_edges=120,
                orphan_nodes=0,
                avg_edge_weight=0.8,
            ),
            audit_pipeline=AuditPipelineState(
                active_audits=[],
                audit_queue_depth=0,
                recent_verdicts=[],
                quality_pulse=QualityPulse(
                    avg_score_last_24h=0.9,
                    pass_rate_last_24h=1.0,
                    trend="stable",
                    consecutive_failures=0,
                ),
            ),
            evolution=EvolutionState(
                active_experiments=[],
                canary_status="idle",
                shelved_improvements=0,
                evolution_frozen=False,
            ),
            last_updated=now,
            version=1,
        )
        assert state.version == 1
        assert state.context_budget.total_warm_tokens == 50000


class TestMetricModels:
    def test_metric_baseline(self):
        now = datetime.now(UTC)
        baseline = MetricBaseline(
            metric_name="graph_traversal_latency_p50",
            mean=12.5,
            median=11.0,
            p95=25.0,
            p99=45.0,
            stddev=5.2,
            sample_count=1000,
            window_start=now,
            window_end=now,
        )
        assert baseline.sample_count == 1000

    def test_comparison_result(self):
        result = ComparisonResult(
            metric_name="retrieval_precision",
            system_a_mean=0.85,
            system_b_mean=0.82,
            difference_percent=-3.5,
            is_significant=True,
            verdict="a_better",
        )
        assert result.verdict == "a_better"

    def test_shelved_improvement(self):
        si = ShelvedImprovement(
            description="Increase graph traversal depth to 4",
            proposed_by="pattern_scout",
            failure_reason="Latency regression",
            metrics_before={"latency_p50": 12.0},
            metrics_after={"latency_p50": 18.0},
            regressed_metrics=["latency_p50"],
        )
        assert si.retry_allowed is False
        assert si.retry_approach is None
