import pytest
from unittest.mock import AsyncMock, MagicMock

from max.agents.base import BaseAgent, AgentConfig
from max.llm.models import ModelType, LLMResponse


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
