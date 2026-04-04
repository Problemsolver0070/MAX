from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest

from max.llm.client import LLMClient
from max.llm.errors import LLMAuthError, LLMConnectionError, LLMError, LLMRateLimitError
from max.llm.models import ModelType, ToolCall


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


# --- Error handling tests ---


@pytest.mark.asyncio
async def test_client_wraps_rate_limit_error(llm_client):
    with patch.object(
        llm_client._client.messages,
        "create",
        new_callable=AsyncMock,
        side_effect=anthropic.RateLimitError(
            message="Rate limit exceeded",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        ),
    ):
        with pytest.raises(LLMRateLimitError, match="Rate limit exceeded"):
            await llm_client.complete(
                messages=[{"role": "user", "content": "Hello"}],
            )


@pytest.mark.asyncio
async def test_client_wraps_connection_error(llm_client):
    with patch.object(
        llm_client._client.messages,
        "create",
        new_callable=AsyncMock,
        side_effect=anthropic.APIConnectionError(request=MagicMock()),
    ):
        with pytest.raises(LLMConnectionError):
            await llm_client.complete(
                messages=[{"role": "user", "content": "Hello"}],
            )


@pytest.mark.asyncio
async def test_client_wraps_auth_error(llm_client):
    with patch.object(
        llm_client._client.messages,
        "create",
        new_callable=AsyncMock,
        side_effect=anthropic.AuthenticationError(
            message="Invalid API key",
            response=MagicMock(status_code=401, headers={}),
            body=None,
        ),
    ):
        with pytest.raises(LLMAuthError, match="Invalid API key"):
            await llm_client.complete(
                messages=[{"role": "user", "content": "Hello"}],
            )


@pytest.mark.asyncio
async def test_client_wraps_generic_api_error(llm_client):
    with patch.object(
        llm_client._client.messages,
        "create",
        new_callable=AsyncMock,
        side_effect=anthropic.APIStatusError(
            message="Internal server error",
            response=MagicMock(status_code=500, headers={}),
            body=None,
        ),
    ):
        with pytest.raises(LLMError, match="Internal server error"):
            await llm_client.complete(
                messages=[{"role": "user", "content": "Hello"}],
            )


def test_llm_error_hierarchy():
    assert issubclass(LLMRateLimitError, LLMError)
    assert issubclass(LLMConnectionError, LLMError)
    assert issubclass(LLMAuthError, LLMError)


# --- Tool use test ---


@pytest.mark.asyncio
async def test_client_complete_with_tool_use(llm_client):
    mock_response = MagicMock()
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.id = "toolu_01"
    tool_block.name = "file.write"
    tool_block.input = {"path": "/tmp/a.txt"}
    mock_response.content = [tool_block]
    mock_response.usage = MagicMock(input_tokens=10, output_tokens=5)
    mock_response.model = "claude-opus-4-6"
    mock_response.stop_reason = "tool_use"

    with patch.object(
        llm_client._client.messages, "create", new_callable=AsyncMock, return_value=mock_response
    ):
        response = await llm_client.complete(
            messages=[{"role": "user", "content": "Write a file"}],
        )
        assert response.tool_calls is not None
        assert len(response.tool_calls) == 1
        assert isinstance(response.tool_calls[0], ToolCall)
        assert response.tool_calls[0].name == "file.write"
