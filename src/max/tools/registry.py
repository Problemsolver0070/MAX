"""Tool registry for managing Max's tool catalog.

Handles registration, permission checking, category filtering,
provider management, per-agent access policies, and conversion
to Anthropic API format for LLM tool_use calls.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from max.tools.models import AgentToolPolicy

if TYPE_CHECKING:
    from max.tools.providers.base import ToolProvider

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
    provider_id: str = "native"
    timeout_seconds: int | None = None


class ToolRegistry:
    """Registry that manages the tool catalog for Max.

    The Orchestrator uses this to assign tools to sub-agents
    based on task requirements and permissions.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._providers: dict[str, ToolProvider] = {}
        self._policies: dict[str, AgentToolPolicy] = {}

    # ── Tool registration ──────────────────────────────────────────────

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

    # ── Permission checking ────────────────────────────────────────────

    def check_permission(self, tool_id: str, allowed: list[str]) -> bool:
        """Check if a tool's required permissions are all in the allowed set."""
        tool = self._tools.get(tool_id)
        if tool is None:
            return False
        return all(perm in allowed for perm in tool.permissions)

    # ── Provider management ────────────────────────────────────────────

    async def register_provider(self, provider: ToolProvider) -> None:
        """Register a provider and discover its tools."""
        self._providers[provider.provider_id] = provider
        tools = await provider.list_tools()
        for tool in tools:
            self.register(tool)
        logger.info(
            "Registered provider %s with %d tools",
            provider.provider_id,
            len(tools),
        )

    def get_provider(self, provider_id: str) -> ToolProvider | None:
        """Get a provider by its ID."""
        return self._providers.get(provider_id)

    # ── Agent access policies ──────────────────────────────────────────

    def set_agent_policy(self, policy: AgentToolPolicy) -> None:
        """Set the tool access policy for an agent."""
        self._policies[policy.agent_name] = policy

    def check_agent_access(self, agent_name: str, tool_id: str) -> bool:
        """Check if an agent is allowed to use a tool."""
        policy = self._policies.get(agent_name)
        if policy is None:
            return False

        # Denied tools always override
        if tool_id in policy.denied_tools:
            return False

        # Check explicit tool allowlist
        if tool_id in policy.allowed_tools:
            return True

        # Check category allowlist
        tool = self._tools.get(tool_id)
        if tool and tool.category in policy.allowed_categories:
            return True

        return False

    def get_agent_tools(self, agent_name: str) -> list[ToolDefinition]:
        """Get all tools an agent is allowed to use."""
        return [t for t in self._tools.values() if self.check_agent_access(agent_name, t.tool_id)]

    # ── Anthropic API format ───────────────────────────────────────────

    def to_anthropic_tools(self, tool_ids: list[str]) -> list[dict[str, Any]]:
        """Convert selected tools to Anthropic API tool_use format."""
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
