"""Tests for BaseAgent.think_with_tools() — agent tool loop."""

import json
from unittest.mock import AsyncMock

import pytest

from max.agents.base import AgentConfig, BaseAgent
from max.llm.models import LLMResponse, ModelType, ToolCall
from max.tools.executor import ToolExecutor
from max.tools.models import AgentToolPolicy, ToolResult
from max.tools.providers.native import NativeToolProvider
from max.tools.registry import ToolDefinition, ToolRegistry


class ConcreteAgent(BaseAgent):
    async def run(self, input_data):
        return {}


def _make_agent_with_tools():
    llm = AsyncMock()
    config = AgentConfig(name="test_agent", system_prompt="You are a test agent")
    agent = ConcreteAgent(config=config, llm=llm)

    registry = ToolRegistry()
    provider = NativeToolProvider()

    async def read_file(inputs):
        return {"content": f"File contents of {inputs['path']}"}

    tool_def = ToolDefinition(
        tool_id="file.read",
        category="code",
        description="Read a file",
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    )
    provider.register_tool(tool_def, read_file)
    registry.register(tool_def)
    registry._providers["native"] = provider

    policy = AgentToolPolicy(agent_name="test_agent", allowed_categories=["code"])
    registry.set_agent_policy(policy)

    store = AsyncMock()
    store.record = AsyncMock()
    executor = ToolExecutor(registry=registry, store=store, audit_enabled=False)

    tools_anthropic = registry.to_anthropic_tools(["file.read"])
    return agent, llm, executor, tools_anthropic


class TestThinkWithToolsNoToolUse:
    @pytest.mark.asyncio
    async def test_returns_response_when_no_tool_calls(self):
        agent, llm, executor, tools = _make_agent_with_tools()
        llm.complete = AsyncMock(
            return_value=LLMResponse(
                text="The answer is 42",
                input_tokens=10,
                output_tokens=5,
                model="claude-opus-4-6",
                stop_reason="end_turn",
                tool_calls=None,
            )
        )
        response = await agent.think_with_tools(
            messages=[{"role": "user", "content": "What is the answer?"}],
            tools=tools,
            tool_executor=executor,
        )
        assert response.text == "The answer is 42"
        assert llm.complete.call_count == 1


class TestThinkWithToolsSingleToolCall:
    @pytest.mark.asyncio
    async def test_executes_tool_and_continues(self):
        agent, llm, executor, tools = _make_agent_with_tools()

        # First call: LLM requests tool use
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
                    input={"path": "/tmp/test.txt"},
                )
            ],
        )
        # Second call: LLM gives final answer
        final_response = LLMResponse(
            text="The file contains: File contents of /tmp/test.txt",
            input_tokens=20,
            output_tokens=10,
            model="claude-opus-4-6",
            stop_reason="end_turn",
            tool_calls=None,
        )
        llm.complete = AsyncMock(side_effect=[tool_response, final_response])

        response = await agent.think_with_tools(
            messages=[{"role": "user", "content": "Read /tmp/test.txt"}],
            tools=tools,
            tool_executor=executor,
        )
        assert "File contents of /tmp/test.txt" in response.text
        assert llm.complete.call_count == 2


class TestThinkWithToolsMaxTurns:
    @pytest.mark.asyncio
    async def test_stops_at_max_turns(self):
        agent, llm, executor, tools = _make_agent_with_tools()
        agent.config.max_turns = 2

        # LLM always requests tool use (infinite loop)
        tool_response = LLMResponse(
            text="",
            input_tokens=10,
            output_tokens=5,
            model="claude-opus-4-6",
            stop_reason="tool_use",
            tool_calls=[
                ToolCall(id="call_1", name="file.read", input={"path": "/tmp/test"})
            ],
        )
        llm.complete = AsyncMock(return_value=tool_response)

        with pytest.raises(RuntimeError, match="exceeded max_turns"):
            await agent.think_with_tools(
                messages=[{"role": "user", "content": "Read it"}],
                tools=tools,
                tool_executor=executor,
            )
