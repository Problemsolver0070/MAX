"""End-to-end integration test for the tool system.

Tests: Registry -> Provider -> Executor -> Agent tool loop.
All LLM calls mocked. Tools execute for real (file ops on tmp_path).
"""

from unittest.mock import AsyncMock

import pytest

from max.agents.base import AgentConfig, BaseAgent
from max.llm.models import LLMResponse, ToolCall
from max.tools.executor import ToolExecutor
from max.tools.models import AgentToolPolicy
from max.tools.native import register_all_native_tools
from max.tools.providers.native import NativeToolProvider
from max.tools.registry import ToolRegistry


class _StubAgent(BaseAgent):
    async def run(self, input_data):
        return {}


class TestToolIntegration:
    @pytest.mark.asyncio
    async def test_agent_reads_file_via_tool_loop(self, tmp_path):
        """Agent uses file.read tool to read a file, then answers."""
        # Setup real file
        test_file = tmp_path / "hello.txt"
        test_file.write_text("Hello from Max!")

        # Setup provider + registry
        provider = NativeToolProvider()
        register_all_native_tools(provider)
        registry = ToolRegistry()
        await registry.register_provider(provider)

        policy = AgentToolPolicy(agent_name="test_agent", allowed_categories=["code"])
        registry.set_agent_policy(policy)

        store = AsyncMock()
        store.record = AsyncMock()
        executor = ToolExecutor(registry=registry, store=store, audit_enabled=True)

        # Setup agent with mocked LLM
        llm = AsyncMock()
        config = AgentConfig(name="test_agent", system_prompt="You are a test agent")
        agent = _StubAgent(config=config, llm=llm)

        # LLM call 1: request file.read tool
        tool_response = LLMResponse(
            text="",
            input_tokens=10,
            output_tokens=5,
            model="claude-opus-4-6",
            stop_reason="tool_use",
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="file.read",
                    input={"path": str(test_file)},
                )
            ],
        )
        # LLM call 2: final answer using tool result
        final_response = LLMResponse(
            text="The file contains: Hello from Max!",
            input_tokens=20,
            output_tokens=10,
            model="claude-opus-4-6",
            stop_reason="end_turn",
            tool_calls=None,
        )
        llm.complete = AsyncMock(side_effect=[tool_response, final_response])

        tools = registry.to_anthropic_tools(
            [t.tool_id for t in registry.get_agent_tools("test_agent")]
        )
        response = await agent.think_with_tools(
            messages=[{"role": "user", "content": f"Read {test_file}"}],
            tools=tools,
            tool_executor=executor,
        )

        assert "Hello from Max!" in response.text
        assert llm.complete.call_count == 2
        # Audit should have recorded one tool invocation
        store.record.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_all_native_tools(self):
        """All 15 native tools register correctly."""
        provider = NativeToolProvider()
        register_all_native_tools(provider)
        tools = await provider.list_tools()
        assert len(tools) == 15
        tool_ids = {t.tool_id for t in tools}
        expected = {
            "file.read",
            "file.write",
            "file.edit",
            "directory.list",
            "file.glob",
            "file.delete",
            "shell.execute",
            "git.status",
            "git.diff",
            "git.log",
            "git.commit",
            "http.fetch",
            "http.request",
            "process.list",
            "grep.search",
        }
        assert expected == tool_ids
