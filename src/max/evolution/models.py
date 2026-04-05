"""Phase 7 evolution domain models — all Pydantic models for the self-evolution system."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

# ── Preference Profile Models ───────────────────────────────────────────────


class CommunicationPrefs(BaseModel):
    """User communication style preferences."""

    tone: str = "professional"
    detail_level: str = "moderate"
    update_frequency: str = "on_completion"
    languages: list[str] = Field(default_factory=lambda: ["en"])
    timezone: str = "UTC"


class CodePrefs(BaseModel):
    """Code style and quality preferences per language."""

    style: dict[str, str] = Field(default_factory=dict)
    review_depth: str = "thorough"
    test_coverage: str = "high"
    commit_style: str = "conventional"


class WorkflowPrefs(BaseModel):
    """Workflow and autonomy preferences."""

    clarification_threshold: float = 0.3
    autonomy_level: str = "high"
    reporting_style: str = "concise"


class DomainPrefs(BaseModel):
    """Domain expertise and project conventions."""

    expertise_areas: list[str] = Field(default_factory=list)
    client_contexts: dict[str, dict[str, Any]] = Field(default_factory=dict)
    project_conventions: dict[str, dict[str, Any]] = Field(default_factory=dict)


class Observation(BaseModel):
    """A single observed signal about user preferences."""

    signal_type: str
    data: dict[str, Any]
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PreferenceProfile(BaseModel):
    """Complete preference profile for a user."""

    user_id: str
    communication: CommunicationPrefs = Field(default_factory=CommunicationPrefs)
    code: CodePrefs = Field(default_factory=CodePrefs)
    workflow: WorkflowPrefs = Field(default_factory=WorkflowPrefs)
    domain_knowledge: DomainPrefs = Field(default_factory=DomainPrefs)
    observation_log: list[Observation] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: int = 1


# ── Evolution Pipeline Models ───────────────────────────────────────────────


class EvolutionProposal(BaseModel):
    """A proposed evolution change discovered by a scout agent."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    scout_type: str
    description: str
    target_type: str
    target_id: str | None = None
    impact_score: float = Field(default=0.0, ge=0.0, le=1.0)
    effort_score: float = Field(default=0.0, ge=0.0, le=1.0)
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    priority: float = 0.0
    status: str = "proposed"
    experiment_id: uuid.UUID | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def computed_priority(self) -> float:
        """Calculate priority: impact * (1 - risk) / max(effort, 0.1)."""
        return self.impact_score * (1 - self.risk_score) / max(self.effort_score, 0.1)


class ChangeSetEntry(BaseModel):
    """A single change within a change set."""

    target_type: str
    target_id: str
    old_value: Any = None
    new_value: Any = None


class ChangeSet(BaseModel):
    """A set of changes to apply for an evolution proposal."""

    proposal_id: uuid.UUID
    entries: list[ChangeSetEntry]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SnapshotData(BaseModel):
    """Snapshot of system configuration before an experiment."""

    prompts: dict[str, str]
    tool_configs: dict[str, dict[str, Any]]
    context_rules: list[dict[str, Any]]
    metrics_baseline: dict[str, float]


# ── Canary Models ───────────────────────────────────────────────────────────


class CanaryRequest(BaseModel):
    """Request to run a canary test for an experiment."""

    experiment_id: uuid.UUID
    task_ids: list[uuid.UUID]
    candidate_config: dict[str, Any]
    timeout_seconds: int = 300


class CanaryTaskResult(BaseModel):
    """Result of a canary test for a single task."""

    task_id: uuid.UUID
    original_score: float
    canary_score: float
    passed: bool


class CanaryResult(BaseModel):
    """Aggregate result of all canary tests for an experiment."""

    experiment_id: uuid.UUID
    task_results: list[CanaryTaskResult]
    overall_passed: bool = False
    duration_seconds: float = 0.0


# ── Event Models ────────────────────────────────────────────────────────────


class PromotionEvent(BaseModel):
    """Event recorded when an experiment is promoted to production."""

    experiment_id: uuid.UUID
    proposal_description: str
    score_improvement: float = 0.0
    promoted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RollbackEvent(BaseModel):
    """Event recorded when an experiment is rolled back."""

    experiment_id: uuid.UUID
    reason: str
    snapshot_id: uuid.UUID | None = None
    rolled_back_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ── Self-Model ──────────────────────────────────────────────────────────────


class EvolutionJournalEntry(BaseModel):
    """A journal entry recording an evolution action for self-reflection."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    experiment_id: uuid.UUID | None
    action: str
    details: dict[str, Any]
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
