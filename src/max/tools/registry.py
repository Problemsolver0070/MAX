"""Tool registry for managing Max's tool catalog.

Handles registration, permission checking, category filtering,
and conversion to Anthropic API format for LLM tool_use calls.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ToolDefinition(BaseModel):
    """Definition of a tool available to Max agents."""

    tool_id: str
    category: str
    description: str
    permissions: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )
    cost_tier: str = "low"
    reliability: float = 1.0
    avg_latency_ms: int = 0


class ToolRegistry:
    """Registry that manages the tool catalog for Max.

    The Orchestrator uses this to assign tools to sub-agents
    based on task requirements and permissions.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool definition in the registry."""
        self._tools[tool.tool_id] = tool
        logger.debug("Registered tool: %s", tool.tool_id)

    def get(self, tool_id: str) -> ToolDefinition | None:
        """Get a tool by its ID, or None if not found."""
        return self._tools.get(tool_id)

    def list_all(self) -> list[ToolDefinition]:
        """Return all registered tools."""
        return list(self._tools.values())

    def list_by_category(self, category: str) -> list[ToolDefinition]:
        """Return all tools in a given category."""
        return [t for t in self._tools.values() if t.category == category]

    def check_permission(self, tool_id: str, allowed: list[str]) -> bool:
        """Check if a tool's required permissions are all in the allowed set.

        Returns False if the tool is not found or if any required
        permission is missing from the allowed list.
        """
        tool = self._tools.get(tool_id)
        if tool is None:
            return False
        return all(perm in allowed for perm in tool.permissions)

    def to_anthropic_tools(self, tool_ids: list[str]) -> list[dict[str, Any]]:
        """Convert selected tools to Anthropic API tool_use format.

        Args:
            tool_ids: List of tool IDs to include.

        Returns:
            List of dicts in Anthropic tool format with name,
            description, and input_schema keys.
        """
        result = []
        for tool_id in tool_ids:
            tool = self._tools.get(tool_id)
            if tool is None:
                continue
            result.append(
                {
                    "name": tool.tool_id,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
            )
        return result
