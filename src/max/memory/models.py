"""Phase 2 memory system models — all Pydantic models and enums."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from max.models.messages import Priority
from max.models.tasks import TaskStatus

# ── Enums ────────────────────────────────────────────────────────────────────


class AnchorLifecycleState(StrEnum):
    ACTIVE = "active"
    STALE = "stale"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class AnchorPermanenceClass(StrEnum):
    PERMANENT = "permanent"
    DURABLE = "durable"
    ADAPTIVE = "adaptive"
    TASK_SCOPED = "task_scoped"


class EdgeRelation(StrEnum):
    DERIVED_FROM = "derived_from"
    DEPENDS_ON = "depends_on"
    SUPERSEDES = "supersedes"
    RELATED_TO = "related_to"
    PRODUCED_BY = "produced_by"
    CONSTRAINS = "constrains"
    PARENT_OF = "parent_of"
    TRIGGERED_BY = "triggered_by"
    REFERENCES = "references"


class CompactionTier(StrEnum):
    FULL = "full"
    SUMMARIZED = "summarized"
    POINTER = "pointer"
    COLD_ONLY = "cold_only"


# ── Context Anchors ──────────────────────────────────────────────────────────


class ContextAnchor(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    content: str
    anchor_type: str
    source_task_id: uuid.UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    lifecycle_state: AnchorLifecycleState = AnchorLifecycleState.ACTIVE
    relevance_score: float = Field(default=1.0, ge=0.0, le=1.0)
    last_accessed: datetime = Field(default_factory=lambda: datetime.now(UTC))
    access_count: int = 0
    decay_rate: float = 0.001
    permanence_class: AnchorPermanenceClass = AnchorPermanenceClass.ADAPTIVE
    superseded_by: uuid.UUID | None = None
    version: int = 1
    parent_anchor_id: uuid.UUID | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ── Graph ────────────────────────────────────────────────────────────────────


class GraphNode(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    node_type: str
    content_id: uuid.UUID
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GraphEdge(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    source_id: uuid.UUID
    target_id: uuid.UUID
    relation: EdgeRelation
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_traversed: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TraversalPath(BaseModel):
    edges: list[GraphEdge]
    terminal_node: GraphNode
    score: float


class SubGraph(BaseModel):
    center_id: uuid.UUID
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    depth: int


class GraphStats(BaseModel):
    total_nodes: int
    total_edges: int
    orphan_nodes: int
    avg_edge_weight: float


# Spec-compliant alias — the spec names this GraphHealthStatus
GraphHealthStatus = GraphStats


# ── Retrieval ────────────────────────────────────────────────────────────────


class HybridRetrievalQuery(BaseModel):
    query_text: str
    seed_node_ids: list[uuid.UUID] = Field(default_factory=list)
    max_graph_depth: int = 3
    min_edge_weight: float = 0.1
    relation_filter: set[EdgeRelation] | None = None
    semantic_top_k: int = 20
    keyword_top_k: int = 20
    final_top_k: int = 30
    graph_weight: float = 1.0
    semantic_weight: float = 0.8
    keyword_weight: float = 0.6


class RetrievalResult(BaseModel):
    content_id: uuid.UUID
    content_type: str
    content: str
    rrf_score: float
    strategies: list[str]
    graph_path: list[uuid.UUID] | None = None
    similarity_score: float | None = None
    tier: str = "full"
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Context Package ──────────────────────────────────────────────────────────


class ContextPackage(BaseModel):
    task_summary: str
    anchors: list[ContextAnchor]
    graph_context: list[dict[str, Any]]
    semantic_matches: list[dict[str, Any]]
    agent_state: dict[str, Any] = Field(default_factory=dict)
    navigation_hints: str = ""
    token_count: int = 0
    budget_remaining: int = 0
    packaging_reasoning: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ── Coordinator State ────────────────────────────────────────────────────────


class ActiveTaskSummary(BaseModel):
    task_id: uuid.UUID
    goal_anchor: str
    status: TaskStatus
    assigned_agent_ids: list[str] = Field(default_factory=list)
    subtask_count: int = 0
    subtasks_completed: int = 0
    priority: Priority = Priority.NORMAL
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    estimated_completion: datetime | None = None


class QueuedTask(BaseModel):
    task_id: uuid.UUID
    goal_anchor: str
    priority: Priority = Priority.NORMAL
    estimated_complexity: str = "moderate"
    dependencies: list[uuid.UUID] = Field(default_factory=list)
    queued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentEntry(BaseModel):
    agent_id: str
    agent_type: str
    status: str = "idle"
    current_task_id: uuid.UUID | None = None
    turn_count: int = 0
    max_turns: int = 10
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_heartbeat: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ContextBudgetStatus(BaseModel):
    total_warm_tokens: int = 0
    warm_capacity_percent: float = 0.0
    compaction_pressure: float = 1.0
    items_per_tier: dict[str, int] = Field(default_factory=dict)
    last_compaction_run: datetime = Field(default_factory=lambda: datetime.now(UTC))
    items_compacted_last_hour: int = 0


class CommunicationState(BaseModel):
    pending_user_messages: int = 0
    active_channels: list[str] = Field(default_factory=list)
    last_user_interaction: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_outbound_message: datetime = Field(default_factory=lambda: datetime.now(UTC))
    pending_clarifications: int = 0
    queued_status_updates: int = 0


class AnchorInventory(BaseModel):
    total_active: int = 0
    total_stale: int = 0
    total_superseded: int = 0
    anchors_by_type: dict[str, int] = Field(default_factory=dict)
    anchors_by_permanence: dict[str, int] = Field(default_factory=dict)
    last_re_evaluation: datetime = Field(default_factory=lambda: datetime.now(UTC))
    pending_re_evaluations: int = 0


class ActiveAudit(BaseModel):
    audit_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    task_id: uuid.UUID
    subtask_id: uuid.UUID
    auditor_agent_id: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RecentVerdict(BaseModel):
    task_id: uuid.UUID
    verdict: str
    score: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class QualityPulse(BaseModel):
    avg_score_last_24h: float = 0.0
    pass_rate_last_24h: float = 0.0
    trend: str = "stable"
    consecutive_failures: int = 0


class AuditPipelineState(BaseModel):
    active_audits: list[ActiveAudit] = Field(default_factory=list)
    audit_queue_depth: int = 0
    recent_verdicts: list[RecentVerdict] = Field(default_factory=list)
    quality_pulse: QualityPulse = Field(default_factory=QualityPulse)


class ActiveExperiment(BaseModel):
    experiment_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    description: str
    status: str = "sandbox"
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metrics_before: dict[str, float] = Field(default_factory=dict)
    metrics_current: dict[str, float] | None = None


class EvolutionState(BaseModel):
    active_experiments: list[ActiveExperiment] = Field(default_factory=list)
    canary_status: str = "idle"
    last_promotion: datetime | None = None
    last_rollback: datetime | None = None
    shelved_improvements: int = 0
    evolution_frozen: bool = False
    freeze_reason: str | None = None


class CoordinatorState(BaseModel):
    active_tasks: list[ActiveTaskSummary] = Field(default_factory=list)
    task_queue: list[QueuedTask] = Field(default_factory=list)
    agent_registry: list[AgentEntry] = Field(default_factory=list)
    context_budget: ContextBudgetStatus = Field(default_factory=ContextBudgetStatus)
    communication: CommunicationState = Field(default_factory=CommunicationState)
    active_anchors: AnchorInventory = Field(default_factory=AnchorInventory)
    graph_health: GraphStats = Field(
        default_factory=lambda: GraphStats(
            total_nodes=0, total_edges=0, orphan_nodes=0, avg_edge_weight=0.0
        )
    )
    audit_pipeline: AuditPipelineState = Field(default_factory=AuditPipelineState)
    evolution: EvolutionState = Field(default_factory=EvolutionState)
    last_updated: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: int = 1


# ── Metrics ──────────────────────────────────────────────────────────────────


class MetricBaseline(BaseModel):
    metric_name: str
    mean: float
    median: float
    p95: float
    p99: float
    stddev: float
    sample_count: int
    window_start: datetime
    window_end: datetime


class ComparisonResult(BaseModel):
    metric_name: str
    system_a_mean: float
    system_b_mean: float
    difference_percent: float
    is_significant: bool
    verdict: str


class ShelvedImprovement(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    description: str
    proposed_by: str
    failure_reason: str
    metrics_before: dict[str, float]
    metrics_after: dict[str, float]
    regressed_metrics: list[str]
    shelved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    retry_allowed: bool = False
    retry_approach: str | None = None
