from unittest.mock import AsyncMock, MagicMock

import pytest

from max.agents.base import AgentConfig, AgentContext, BaseAgent
from max.llm.models import LLMResponse, ModelType


class SampleAgent(BaseAgent):
    async def run(self, input_data: dict) -> dict:
        response = await self.think(
            messages=[{"role": "user", "content": input_data["message"]}],
        )
        return {"response": response.text}


@pytest.fixture
def mock_llm():
    client = MagicMock()
    client.complete = AsyncMock(
        return_value=LLMResponse(
            text="I'm a test agent.",
            input_tokens=10,
            output_tokens=5,
            model="claude-opus-4-6",
            stop_reason="end_turn",
        )
    )
    return client


@pytest.fixture
def agent(mock_llm):
    config = AgentConfig(
        name="test-agent",
        model=ModelType.OPUS,
        system_prompt="You are a test agent.",
    )
    return SampleAgent(config=config, llm=mock_llm)


def test_agent_creation(agent):
    assert agent.config.name == "test-agent"
    assert agent.config.model == ModelType.OPUS


@pytest.mark.asyncio
async def test_agent_think(agent, mock_llm):
    response = await agent.think(
        messages=[{"role": "user", "content": "hello"}],
    )
    assert response.text == "I'm a test agent."
    mock_llm.complete.assert_called_once()
    call_kwargs = mock_llm.complete.call_args[1]
    assert call_kwargs["system_prompt"] == "You are a test agent."
    assert call_kwargs["model"] == ModelType.OPUS


@pytest.mark.asyncio
async def test_agent_run(agent):
    result = await agent.run({"message": "hello"})
    assert result["response"] == "I'm a test agent."


def test_agent_config_defaults():
    config = AgentConfig(name="minimal", system_prompt="Be helpful.")
    assert config.model == ModelType.OPUS
    assert config.max_turns == 10
    assert config.tools == []


class LifecycleAgent(BaseAgent):
    def __init__(self, config, llm, context=None):
        super().__init__(config, llm, context)
        self.started = False
        self.stopped = False

    async def on_start(self) -> None:
        self.started = True

    async def on_stop(self) -> None:
        self.stopped = True

    async def run(self, input_data: dict) -> dict:
        return {"done": True}


@pytest.mark.asyncio
async def test_agent_context_creation():
    ctx = AgentContext(bus=None, db=None, warm_memory=None)
    assert ctx.bus is None
    assert ctx.db is None
    assert ctx.warm_memory is None


@pytest.mark.asyncio
async def test_agent_lifecycle_hooks(mock_llm):
    config = AgentConfig(name="lifecycle", system_prompt="Test.")
    agent = LifecycleAgent(config=config, llm=mock_llm)
    assert agent.started is False
    await agent.on_start()
    assert agent.started is True
    await agent.on_stop()
    assert agent.stopped is True


@pytest.mark.asyncio
async def test_agent_context_accessible(mock_llm):
    ctx = AgentContext(bus="mock_bus", db="mock_db", warm_memory="mock_wm")
    config = AgentConfig(name="ctx-test", system_prompt="Test.")
    agent = LifecycleAgent(config=config, llm=mock_llm, context=ctx)
    assert agent.context.bus == "mock_bus"
    assert agent.context.db == "mock_db"
    assert agent.context.warm_memory == "mock_wm"


@pytest.mark.asyncio
async def test_max_turns_enforced(mock_llm):
    config = AgentConfig(name="limited", system_prompt="Test.", max_turns=2)
    agent = SampleAgent(config=config, llm=mock_llm)
    await agent.think(messages=[{"role": "user", "content": "1"}])
    await agent.think(messages=[{"role": "user", "content": "2"}])
    with pytest.raises(RuntimeError, match="exceeded max_turns"):
        await agent.think(messages=[{"role": "user", "content": "3"}])


def test_agent_reset(mock_llm):
    config = AgentConfig(name="reset-test", system_prompt="Test.")
    agent = SampleAgent(config=config, llm=mock_llm)
    agent._turn_count = 5
    agent.reset()
    assert agent._turn_count == 0


@pytest.mark.asyncio
async def test_turn_count_increments(mock_llm):
    config = AgentConfig(name="counter", system_prompt="Test.")
    agent = SampleAgent(config=config, llm=mock_llm)
    assert agent._turn_count == 0
    await agent.think(messages=[{"role": "user", "content": "1"}])
    assert agent._turn_count == 1
    await agent.think(messages=[{"role": "user", "content": "2"}])
    assert agent._turn_count == 2
