"""Tests for NativeToolProvider."""

import pytest

from max.tools.models import ToolResult
from max.tools.providers.native import NativeToolProvider
from max.tools.registry import ToolDefinition


class TestNativeToolProvider:
    @pytest.mark.asyncio
    async def test_register_and_list_tools(self):
        provider = NativeToolProvider()

        async def my_handler(inputs: dict) -> str:
            return "hello"

        tool_def = ToolDefinition(
            tool_id="test.hello",
            category="test",
            description="Say hello",
            provider_id="native",
        )
        provider.register_tool(tool_def, my_handler)
        tools = await provider.list_tools()
        assert len(tools) == 1
        assert tools[0].tool_id == "test.hello"

    @pytest.mark.asyncio
    async def test_execute_success(self):
        provider = NativeToolProvider()

        async def read_file(inputs: dict) -> dict:
            return {"content": f"Contents of {inputs['path']}"}

        provider.register_tool(
            ToolDefinition(
                tool_id="file.read",
                category="code",
                description="Read a file",
                provider_id="native",
            ),
            read_file,
        )
        result = await provider.execute("file.read", {"path": "/tmp/test.txt"})
        assert result.success is True
        assert result.output["content"] == "Contents of /tmp/test.txt"

    @pytest.mark.asyncio
    async def test_execute_not_found(self):
        provider = NativeToolProvider()
        result = await provider.execute("nonexistent", {})
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_handler_exception(self):
        provider = NativeToolProvider()

        async def bad_handler(inputs: dict) -> str:
            raise ValueError("Oops")

        provider.register_tool(
            ToolDefinition(
                tool_id="test.bad",
                category="test",
                description="A bad tool",
                provider_id="native",
            ),
            bad_handler,
        )
        result = await provider.execute("test.bad", {})
        assert result.success is False
        assert "Oops" in result.error

    @pytest.mark.asyncio
    async def test_health_check(self):
        provider = NativeToolProvider()
        assert await provider.health_check() is True

    def test_provider_id(self):
        provider = NativeToolProvider()
        assert provider.provider_id == "native"
