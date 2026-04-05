"""Tests for MCPToolProvider."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from max.tools.providers.mcp import MCPToolProvider


class TestMCPToolProvider:
    @pytest.mark.asyncio
    async def test_provider_id(self):
        provider = MCPToolProvider(server_command=["echo", "test"], server_id="test-mcp")
        assert provider.provider_id == "test-mcp"

    @pytest.mark.asyncio
    async def test_list_tools_maps_to_tool_definitions(self):
        provider = MCPToolProvider(server_command=["echo"], server_id="test-mcp")

        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = "A test tool"
        mock_tool.inputSchema = {"type": "object", "properties": {"arg": {"type": "string"}}}

        provider._session = AsyncMock()
        provider._session.list_tools = AsyncMock(
            return_value=MagicMock(tools=[mock_tool])
        )
        provider._connected = True

        tools = await provider.list_tools()
        assert len(tools) == 1
        assert tools[0].tool_id == "test_tool"
        assert tools[0].provider_id == "test-mcp"

    @pytest.mark.asyncio
    async def test_execute_success(self):
        provider = MCPToolProvider(server_command=["echo"], server_id="test-mcp")

        mock_result = MagicMock()
        mock_result.isError = False
        mock_content = MagicMock()
        mock_content.text = '{"result": "ok"}'
        mock_result.content = [mock_content]

        provider._session = AsyncMock()
        provider._session.call_tool = AsyncMock(return_value=mock_result)
        provider._connected = True

        result = await provider.execute("test_tool", {"arg": "value"})
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_error(self):
        provider = MCPToolProvider(server_command=["echo"], server_id="test-mcp")

        mock_result = MagicMock()
        mock_result.isError = True
        mock_content = MagicMock()
        mock_content.text = "Something went wrong"
        mock_result.content = [mock_content]

        provider._session = AsyncMock()
        provider._session.call_tool = AsyncMock(return_value=mock_result)
        provider._connected = True

        result = await provider.execute("test_tool", {"arg": "value"})
        assert result.success is False
        assert "Something went wrong" in result.error

    @pytest.mark.asyncio
    async def test_health_check_when_not_connected(self):
        provider = MCPToolProvider(server_command=["echo"], server_id="test-mcp")
        assert await provider.health_check() is False

    @pytest.mark.asyncio
    async def test_health_check_when_connected(self):
        provider = MCPToolProvider(server_command=["echo"], server_id="test-mcp")
        provider._connected = True
        provider._session = AsyncMock()
        provider._session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))
        assert await provider.health_check() is True
