"""TaskStore -- async CRUD for tasks and subtasks over PostgreSQL."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from max.db.postgres import Database
from max.models.tasks import TaskStatus

logger = logging.getLogger(__name__)

# JSONB columns that asyncpg may return as strings (no auto-decode without codec init).
_TASK_JSON_FIELDS = ("quality_criteria",)
_SUBTASK_JSON_FIELDS = (
    "result",
    "tool_categories",
    "quality_criteria",
    "assigned_tools",
    "context_package",
)


def _parse_jsonb(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """Ensure JSONB columns are Python objects, not raw JSON strings."""
    out = dict(row)
    for field in fields:
        val = out.get(field)
        if isinstance(val, str):
            try:
                out[field] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
    return out


class TaskStore:
    """Thin persistence layer for Task and SubTask operations."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create_task(
        self,
        intent_id: uuid.UUID,
        goal_anchor: str,
        priority: str = "normal",
        quality_criteria: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new task and return its row as a dict."""
        task_id = uuid.uuid4()
        criteria = json.dumps(quality_criteria or {})
        await self._db.execute(
            "INSERT INTO tasks "
            "(id, goal_anchor, source_intent_id, status, priority, quality_criteria) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
            task_id,
            goal_anchor,
            intent_id,
            "pending",
            priority,
            criteria,
        )
        return await self.get_task(task_id)  # type: ignore[return-value]

    async def get_task(self, task_id: uuid.UUID) -> dict[str, Any] | None:
        """Get a task by ID."""
        row = await self._db.fetchone("SELECT * FROM tasks WHERE id = $1", task_id)
        return _parse_jsonb(row, _TASK_JSON_FIELDS) if row else None

    async def get_active_tasks(self) -> list[dict[str, Any]]:
        """Get all non-terminal tasks."""
        rows = await self._db.fetchall(
            "SELECT * FROM tasks WHERE status NOT IN ('completed', 'failed') "
            "ORDER BY created_at DESC"
        )
        return [_parse_jsonb(r, _TASK_JSON_FIELDS) for r in rows]

    async def update_task_status(
        self,
        task_id: uuid.UUID,
        status: TaskStatus,
    ) -> None:
        """Update a task's status. Sets completed_at for terminal states."""
        if status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            await self._db.execute(
                "UPDATE tasks SET status = $1, completed_at = $2 WHERE id = $3",
                status.value,
                datetime.now(UTC),
                task_id,
            )
        else:
            await self._db.execute(
                "UPDATE tasks SET status = $1 WHERE id = $2",
                status.value,
                task_id,
            )

    async def create_subtask(
        self,
        task_id: uuid.UUID,
        description: str,
        phase_number: int = 0,
        tool_categories: list[str] | None = None,
        quality_criteria: dict[str, Any] | None = None,
        estimated_complexity: str = "moderate",
    ) -> dict[str, Any]:
        """Create a subtask and return its row."""
        subtask_id = uuid.uuid4()
        cats = json.dumps(tool_categories or [])
        criteria = json.dumps(quality_criteria or {})
        await self._db.execute(
            "INSERT INTO subtasks "
            "(id, parent_task_id, description, phase_number, tool_categories, "
            "quality_criteria, estimated_complexity) "
            "VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7)",
            subtask_id,
            task_id,
            description,
            phase_number,
            cats,
            criteria,
            estimated_complexity,
        )
        row = await self._db.fetchone("SELECT * FROM subtasks WHERE id = $1", subtask_id)
        return _parse_jsonb(row, _SUBTASK_JSON_FIELDS) if row else row  # type: ignore[return-value]

    async def get_subtasks(self, task_id: uuid.UUID) -> list[dict[str, Any]]:
        """Get all subtasks for a task, ordered by phase then creation time."""
        rows = await self._db.fetchall(
            "SELECT * FROM subtasks WHERE parent_task_id = $1 ORDER BY phase_number, created_at",
            task_id,
        )
        return [_parse_jsonb(r, _SUBTASK_JSON_FIELDS) for r in rows]

    async def update_subtask_status(
        self,
        subtask_id: uuid.UUID,
        status: TaskStatus,
    ) -> None:
        """Update a subtask's status."""
        if status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            await self._db.execute(
                "UPDATE subtasks SET status = $1, completed_at = $2 WHERE id = $3",
                status.value,
                datetime.now(UTC),
                subtask_id,
            )
        else:
            await self._db.execute(
                "UPDATE subtasks SET status = $1 WHERE id = $2",
                status.value,
                subtask_id,
            )

    async def update_subtask_result(
        self,
        subtask_id: uuid.UUID,
        result_data: dict[str, Any],
    ) -> None:
        """Write the result to a subtask and mark it completed."""
        await self._db.execute(
            "UPDATE subtasks SET result = $1::jsonb, status = 'completed', "
            "completed_at = $2 WHERE id = $3",
            json.dumps(result_data),
            datetime.now(UTC),
            subtask_id,
        )

    async def create_result(
        self,
        task_id: uuid.UUID,
        content: str,
        confidence: float,
        artifacts: list[str] | None = None,
    ) -> uuid.UUID:
        """Create a Result record and return its ID."""
        result_id = uuid.uuid4()
        arts = json.dumps(artifacts or [])
        await self._db.execute(
            "INSERT INTO results (id, task_id, content, confidence, artifacts) "
            "VALUES ($1, $2, $3, $4, $5::jsonb)",
            result_id,
            task_id,
            content,
            confidence,
            arts,
        )
        return result_id

    async def get_completed_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recently completed tasks, ordered by completion time descending."""
        rows = await self._db.fetchall(
            "SELECT * FROM tasks WHERE status = 'completed' "
            "ORDER BY completed_at DESC LIMIT $1",
            limit,
        )
        return [_parse_jsonb(r, _TASK_JSON_FIELDS) for r in rows]
