"""MCPToolProvider — proxies tool calls to MCP servers."""

from __future__ import annotations

import logging
import time
from typing import Any

from max.tools.models import ToolResult
from max.tools.providers.base import ToolProvider
from max.tools.registry import ToolDefinition

logger = logging.getLogger(__name__)


class MCPToolProvider(ToolProvider):
    """Connects to an MCP server and proxies tool calls.

    Uses stdio transport to communicate with an MCP server subprocess.
    """

    def __init__(
        self,
        server_command: list[str],
        server_id: str,
        env: dict[str, str] | None = None,
    ) -> None:
        self._server_command = server_command
        self._server_id = server_id
        self._env = env
        self._session: Any = None
        self._connected = False

    @property
    def provider_id(self) -> str:
        return self._server_id

    async def connect(self) -> None:
        """Connect to the MCP server via stdio transport."""
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            params = StdioServerParameters(
                command=self._server_command[0],
                args=self._server_command[1:] if len(self._server_command) > 1 else [],
                env=self._env,
            )
            self._transport_ctx = stdio_client(params)
            transport = await self._transport_ctx.__aenter__()
            self._session = ClientSession(*transport)
            await self._session.__aenter__()
            await self._session.initialize()
            self._connected = True
            logger.info("Connected to MCP server: %s", self._server_id)
        except ImportError:
            logger.warning("mcp package not installed — MCPToolProvider unavailable")
            self._connected = False
        except Exception:
            logger.exception("Failed to connect to MCP server: %s", self._server_id)
            self._connected = False

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
                await self._transport_ctx.__aexit__(None, None, None)
            except Exception:
                logger.warning("Error disconnecting from MCP server: %s", self._server_id)
            self._session = None
            self._connected = False

    async def list_tools(self) -> list[ToolDefinition]:
        """List tools available from the MCP server."""
        if not self._connected or not self._session:
            return []

        result = await self._session.list_tools()
        definitions = []
        for tool in result.tools:
            definitions.append(
                ToolDefinition(
                    tool_id=tool.name,
                    category="mcp",
                    description=tool.description or "",
                    provider_id=self._server_id,
                    input_schema=tool.inputSchema if hasattr(tool, "inputSchema") else {},
                )
            )
        return definitions

    async def execute(self, tool_id: str, inputs: dict[str, Any]) -> ToolResult:
        """Execute a tool on the MCP server."""
        if not self._connected or not self._session:
            return ToolResult(
                tool_id=tool_id,
                success=False,
                error=f"MCP server {self._server_id} not connected",
            )

        start = time.monotonic()
        try:
            result = await self._session.call_tool(tool_id, arguments=inputs)
            duration_ms = int((time.monotonic() - start) * 1000)

            if result.isError:
                error_text = " ".join(c.text for c in result.content if hasattr(c, "text"))
                return ToolResult(
                    tool_id=tool_id,
                    success=False,
                    error=error_text or "MCP tool returned error",
                    duration_ms=duration_ms,
                )

            output_parts = []
            for content in result.content:
                if hasattr(content, "text"):
                    output_parts.append(content.text)
            output = "\n".join(output_parts)

            return ToolResult(
                tool_id=tool_id,
                success=True,
                output=output,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.exception("MCP tool %s execution failed", tool_id)
            return ToolResult(
                tool_id=tool_id,
                success=False,
                error=str(exc),
                duration_ms=duration_ms,
            )

    async def health_check(self) -> bool:
        """Check if the MCP server is responsive."""
        if not self._connected or not self._session:
            return False
        try:
            await self._session.list_tools()
            return True
        except Exception:
            return False
