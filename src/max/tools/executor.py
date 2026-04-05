"""ToolExecutor — central pipeline for all tool invocations."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from max.tools.models import ToolResult
from max.tools.registry import ToolRegistry
from max.tools.store import ToolInvocationStore

logger = logging.getLogger(__name__)


class ToolExecutor:
    """Executes tools through the permission → execute → audit pipeline."""

    def __init__(
        self,
        registry: ToolRegistry,
        store: ToolInvocationStore | None = None,
        default_timeout: int = 60,
        audit_enabled: bool = True,
    ) -> None:
        self._registry = registry
        self._store = store
        self._default_timeout = default_timeout
        self._audit_enabled = audit_enabled

    async def execute(
        self,
        agent_name: str,
        tool_id: str,
        inputs: dict[str, Any],
    ) -> ToolResult:
        """Execute a tool through the full pipeline."""
        start = time.monotonic()

        # 1. Resolve tool
        tool_def = self._registry.get(tool_id)
        if tool_def is None:
            result = ToolResult(
                tool_id=tool_id,
                success=False,
                error=f"Tool not found: {tool_id}",
            )
            await self._audit(agent_name, result, inputs)
            return result

        # 2. Permission check
        if not self._registry.check_agent_access(agent_name, tool_id):
            result = ToolResult(
                tool_id=tool_id,
                success=False,
                error=f"Permission denied: {agent_name} cannot use {tool_id}",
            )
            await self._audit(agent_name, result, inputs)
            return result

        # 3. Get provider
        provider = self._registry.get_provider(tool_def.provider_id)
        if provider is None:
            result = ToolResult(
                tool_id=tool_id,
                success=False,
                error=f"Provider not found: {tool_def.provider_id}",
            )
            await self._audit(agent_name, result, inputs)
            return result

        # 4. Health check
        if not await provider.health_check():
            result = ToolResult(
                tool_id=tool_id,
                success=False,
                error=f"Provider {tool_def.provider_id} is unhealthy",
            )
            await self._audit(agent_name, result, inputs)
            return result

        # 5. Execute with timeout
        timeout = tool_def.timeout_seconds or self._default_timeout
        try:
            result = await asyncio.wait_for(
                provider.execute(tool_id, inputs),
                timeout=timeout,
            )
        except TimeoutError:
            duration_ms = int((time.monotonic() - start) * 1000)
            result = ToolResult(
                tool_id=tool_id,
                success=False,
                error=f"Tool execution timed out after {timeout}s",
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.exception("Tool %s execution failed", tool_id)
            result = ToolResult(
                tool_id=tool_id,
                success=False,
                error=str(exc),
                duration_ms=duration_ms,
            )

        # 6. Audit log
        await self._audit(agent_name, result, inputs)
        return result

    async def _audit(
        self,
        agent_name: str,
        result: ToolResult,
        inputs: dict[str, Any],
    ) -> None:
        """Record invocation to audit store if enabled."""
        if not self._audit_enabled or self._store is None:
            return
        try:
            await self._store.record(
                agent_id=agent_name,
                tool_id=result.tool_id,
                inputs=inputs,
                output=result.output,
                success=result.success,
                error=result.error,
                duration_ms=result.duration_ms,
            )
        except Exception:
            logger.warning("Failed to record tool audit for %s", result.tool_id)
