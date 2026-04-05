"""NativeToolProvider — wraps Python async functions as tools."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

from max.tools.models import ToolResult
from max.tools.providers.base import ToolProvider
from max.tools.registry import ToolDefinition

logger = logging.getLogger(__name__)

ToolHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, Any]]


class NativeToolProvider(ToolProvider):
    """Provides tools implemented as Python async functions."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, ToolHandler] = {}

    @property
    def provider_id(self) -> str:
        return "native"

    def register_tool(self, definition: ToolDefinition, handler: ToolHandler) -> None:
        """Register a native tool with its handler function."""
        self._tools[definition.tool_id] = definition
        self._handlers[definition.tool_id] = handler
        logger.debug("Registered native tool: %s", definition.tool_id)

    async def list_tools(self) -> list[ToolDefinition]:
        """Return all registered native tools."""
        return list(self._tools.values())

    async def execute(self, tool_id: str, inputs: dict[str, Any]) -> ToolResult:
        """Execute a native tool handler."""
        handler = self._handlers.get(tool_id)
        if handler is None:
            return ToolResult(
                tool_id=tool_id,
                success=False,
                error=f"Tool not found: {tool_id}",
            )

        start = time.monotonic()
        try:
            output = await handler(inputs)
            duration_ms = int((time.monotonic() - start) * 1000)
            return ToolResult(
                tool_id=tool_id,
                success=True,
                output=output,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.exception("Native tool %s failed", tool_id)
            return ToolResult(
                tool_id=tool_id,
                success=False,
                error=str(exc),
                duration_ms=duration_ms,
            )

    async def health_check(self) -> bool:
        """Native provider is always healthy."""
        return True
