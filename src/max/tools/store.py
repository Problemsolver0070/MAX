"""ToolInvocationStore — audit trail for tool invocations."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from max.db.postgres import Database

logger = logging.getLogger(__name__)


class ToolInvocationStore:
    """Persistence layer for tool invocation audit trail."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self,
        agent_id: str,
        tool_id: str,
        inputs: dict[str, Any],
        output: Any,
        success: bool,
        error: str | None,
        duration_ms: int,
    ) -> None:
        """Record a tool invocation."""
        await self._db.execute(
            "INSERT INTO tool_invocations "
            "(id, agent_id, tool_id, inputs, output, success, error, duration_ms) "
            "VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7, $8)",
            uuid.uuid4(),
            agent_id,
            tool_id,
            json.dumps(inputs),
            json.dumps(output) if output is not None else None,
            success,
            error,
            duration_ms,
        )

    async def get_invocations(self, tool_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent invocations for a tool."""
        return await self._db.fetchall(
            "SELECT * FROM tool_invocations WHERE tool_id = $1 "
            "ORDER BY created_at DESC LIMIT $2",
            tool_id,
            limit,
        )

    async def get_agent_invocations(self, agent_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent invocations by an agent."""
        return await self._db.fetchall(
            "SELECT * FROM tool_invocations WHERE agent_id = $1 "
            "ORDER BY created_at DESC LIMIT $2",
            agent_id,
            limit,
        )

    async def get_stats(self, tool_id: str, hours: int = 24) -> dict[str, Any]:
        """Get aggregated stats for a tool."""
        row = await self._db.fetchone(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN success THEN 1 ELSE 0 END) AS success_count, "
            "AVG(duration_ms) AS avg_duration "
            "FROM tool_invocations WHERE tool_id = $1 "
            "AND created_at > NOW() - INTERVAL '1 hour' * $2",
            tool_id,
            hours,
        )
        if row is None:
            return {"total": 0, "success_count": 0, "avg_duration": 0.0}
        return {
            "total": row["total"] or 0,
            "success_count": row["success_count"] or 0,
            "avg_duration": float(row["avg_duration"]) if row["avg_duration"] else 0.0,
        }
