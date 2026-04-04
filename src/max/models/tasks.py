from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
    PENDING = "pending"
    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    AUDITING = "auditing"
    FIXING = "fixing"
    COMPLETED = "completed"
    FAILED = "failed"


class AuditVerdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    CONDITIONAL = "conditional"


class SubTask(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    parent_task_id: uuid.UUID
    description: str
    status: TaskStatus = TaskStatus.PENDING
    assigned_tools: list[str] = Field(default_factory=list)
    context_package: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    audit_report: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


class Task(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    goal_anchor: str
    source_intent_id: uuid.UUID
    status: TaskStatus = TaskStatus.PENDING
    subtasks: list[SubTask] = Field(default_factory=list)
    quality_criteria: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


class AuditReport(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    task_id: uuid.UUID
    subtask_id: uuid.UUID
    verdict: AuditVerdict
    score: float = Field(ge=0.0, le=1.0)
    goal_alignment: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    issues: list[dict[str, str]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
