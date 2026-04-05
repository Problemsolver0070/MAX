"""Phase 4 Command Chain models — actions, plans, configs, results."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from max.models.messages import Priority


class CoordinatorActionType(StrEnum):
    CREATE_TASK = "create_task"
    QUERY_STATUS = "query_status"
    CANCEL_TASK = "cancel_task"
    PROVIDE_CONTEXT = "provide_context"
    CLARIFICATION_RESPONSE = "clarification_response"


class CoordinatorAction(BaseModel):
    action: CoordinatorActionType
    task_id: uuid.UUID | None = None
    goal_anchor: str = ""
    priority: Priority = Priority.NORMAL
    quality_criteria: dict[str, Any] = Field(default_factory=dict)
    context_text: str = ""
    clarification_answer: str = ""
    reasoning: str = ""


class PlannedSubtask(BaseModel):
    description: str
    phase_number: int
    tool_categories: list[str] = Field(default_factory=list)
    quality_criteria: dict[str, Any] = Field(default_factory=dict)
    estimated_complexity: str = "moderate"


class ExecutionPlan(BaseModel):
    task_id: uuid.UUID
    goal_anchor: str
    subtasks: list[PlannedSubtask]
    total_phases: int
    reasoning: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkerConfig(BaseModel):
    subtask_id: uuid.UUID
    task_id: uuid.UUID
    system_prompt: str
    tool_ids: list[str] = Field(default_factory=list)
    context_package: dict[str, Any] = Field(default_factory=dict)
    quality_criteria: dict[str, Any] = Field(default_factory=dict)
    max_turns: int = 10


class SubtaskResult(BaseModel):
    subtask_id: uuid.UUID
    task_id: uuid.UUID
    success: bool
    content: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = ""
    error: str | None = None
