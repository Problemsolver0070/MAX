from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from max.llm.client import LLMClient
from max.llm.models import ModelType


def test_model_type_ids():
    assert ModelType.OPUS.model_id == "claude-opus-4-6"
    assert ModelType.SONNET.model_id == "claude-sonnet-4-6"


@pytest.fixture
def llm_client():
    return LLMClient(api_key="sk-ant-test-key")


def test_client_creation(llm_client):
    assert llm_client is not None
    assert llm_client.default_model == ModelType.OPUS


@pytest.mark.asyncio
async def test_client_complete(llm_client):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text="Hello back!")]
    mock_response.usage = MagicMock(input_tokens=10, output_tokens=5)
    mock_response.model = "claude-opus-4-6"
    mock_response.stop_reason = "end_turn"

    with patch.object(
        llm_client._client.messages, "create", new_callable=AsyncMock, return_value=mock_response
    ):
        response = await llm_client.complete(
            messages=[{"role": "user", "content": "Hello"}],
            system_prompt="You are Max.",
        )
        assert response.text == "Hello back!"
        assert response.input_tokens == 10
        assert response.output_tokens == 5


@pytest.mark.asyncio
async def test_client_complete_with_model_override(llm_client):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text="Routed.")]
    mock_response.usage = MagicMock(input_tokens=8, output_tokens=3)
    mock_response.model = "claude-sonnet-4-6"
    mock_response.stop_reason = "end_turn"

    with patch.object(
        llm_client._client.messages, "create", new_callable=AsyncMock, return_value=mock_response
    ) as mock_create:
        response = await llm_client.complete(
            messages=[{"role": "user", "content": "Route this"}],
            model=ModelType.SONNET,
        )
        assert response.text == "Routed."
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["model"] == "claude-sonnet-4-6"


def test_usage_tracking(llm_client):
    assert llm_client.total_input_tokens == 0
    assert llm_client.total_output_tokens == 0
