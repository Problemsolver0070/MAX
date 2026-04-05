"""Phase 6A Tool System models — results, policies, health."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Result of a tool invocation."""

    tool_id: str
    success: bool
    output: Any = None
    error: str | None = None
    duration_ms: int = 0


class AgentToolPolicy(BaseModel):
    """Per-agent tool access whitelist."""

    agent_name: str
    allowed_tools: list[str] = Field(default_factory=list)
    allowed_categories: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)


class ProviderHealth(BaseModel):
    """Health status for a tool provider."""

    provider_id: str
    is_healthy: bool = True
    last_checked: datetime | None = None
    error_count: int = 0
    consecutive_failures: int = 0
