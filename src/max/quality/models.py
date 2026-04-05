"""Phase 5 Quality Gate models — audit requests, responses, patterns, verdicts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from max.models.tasks import AuditVerdict


class QualityPattern(BaseModel):
    """A quality pattern learned from high-scoring audits — reinforced over time."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    pattern: str
    source_task_id: uuid.UUID
    category: str
    reinforcement_count: int = 1
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SubtaskAuditItem(BaseModel):
    """One subtask's output for the auditor to evaluate.

    Deliberately excludes reasoning, confidence, and error fields
    from SubtaskResult to enforce the blind audit protocol.
    """

    subtask_id: uuid.UUID
    description: str
    content: str
    quality_criteria: dict[str, Any] = Field(default_factory=dict)


class AuditRequest(BaseModel):
    """Published on audit.request by the Orchestrator."""

    task_id: uuid.UUID
    goal_anchor: str
    subtask_results: list[SubtaskAuditItem]
    quality_criteria: dict[str, Any] = Field(default_factory=dict)


class SubtaskVerdict(BaseModel):
    """Audit verdict for a single subtask."""

    subtask_id: uuid.UUID
    verdict: AuditVerdict
    score: float = Field(ge=0.0, le=1.0)
    goal_alignment: float = Field(ge=0.0, le=1.0)
    issues: list[dict[str, str]] = Field(default_factory=list)


class FixInstruction(BaseModel):
    """Instructions for fixing a failed subtask."""

    subtask_id: uuid.UUID
    instructions: str
    original_content: str
    issues: list[dict[str, str]] = Field(default_factory=list)


class AuditResponse(BaseModel):
    """Published on audit.complete by the Quality Director."""

    task_id: uuid.UUID
    success: bool
    verdicts: list[SubtaskVerdict]
    overall_score: float = Field(ge=0.0, le=1.0)
    fix_required: list[FixInstruction] = Field(default_factory=list)
