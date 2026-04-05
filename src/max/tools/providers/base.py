"""ToolProvider ABC — base class for all tool sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from max.tools.models import ToolResult
from max.tools.registry import ToolDefinition


class ToolProvider(ABC):
    """Base class for all tool sources."""

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Unique identifier for this provider."""

    @abstractmethod
    async def list_tools(self) -> list[ToolDefinition]:
        """List all tools available from this provider."""

    @abstractmethod
    async def execute(self, tool_id: str, inputs: dict[str, Any]) -> ToolResult:
        """Execute a tool and return the result."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is healthy and responsive."""
