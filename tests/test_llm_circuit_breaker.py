"""Tests for LLMClient with circuit breaker integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from max.llm.circuit_breaker import CircuitBreaker, CircuitBreakerOpen, CircuitState
from max.llm.client import LLMClient
from max.llm.errors import LLMConnectionError


@pytest.fixture
def circuit_breaker():
    return CircuitBreaker(threshold=3, cooldown_seconds=60)


@pytest.fixture
def client_with_cb(circuit_breaker):
    return LLMClient(
        api_key="test-key",
        circuit_breaker=circuit_breaker,
    )


@pytest.fixture
def client_without_cb():
    return LLMClient(api_key="test-key")


class TestClientAcceptsCircuitBreaker:
    def test_constructor_accepts_circuit_breaker(self, client_with_cb, circuit_breaker):
        assert client_with_cb._circuit_breaker is circuit_breaker

    def test_constructor_works_without_circuit_breaker(self, client_without_cb):
        assert client_without_cb._circuit_breaker is None


class TestCircuitBreakerBlocking:
    async def test_raises_when_circuit_open(self, client_with_cb, circuit_breaker):
        # Force circuit open
        for _ in range(3):
            circuit_breaker.record_failure()
        assert circuit_breaker.state == CircuitState.OPEN

        with pytest.raises(CircuitBreakerOpen):
            await client_with_cb.complete(messages=[{"role": "user", "content": "hello"}])

    async def test_no_api_call_when_circuit_open(self, client_with_cb, circuit_breaker):
        for _ in range(3):
            circuit_breaker.record_failure()

        with patch.object(client_with_cb._client.messages, "create") as mock_create:
            with pytest.raises(CircuitBreakerOpen):
                await client_with_cb.complete(messages=[{"role": "user", "content": "hello"}])
            mock_create.assert_not_called()


class TestCircuitBreakerRecording:
    async def test_records_success_on_successful_call(self, client_with_cb, circuit_breaker):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="hi")]
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5
        mock_response.model = "claude-opus-4-6"
        mock_response.stop_reason = "end_turn"

        with patch.object(
            client_with_cb._client.messages,
            "create",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            await client_with_cb.complete(messages=[{"role": "user", "content": "hello"}])
        assert circuit_breaker.failure_count == 0

    async def test_records_failure_on_connection_error(self, client_with_cb, circuit_breaker):
        import anthropic

        with patch.object(
            client_with_cb._client.messages,
            "create",
            new_callable=AsyncMock,
            side_effect=anthropic.APIConnectionError(request=MagicMock()),
        ):
            with pytest.raises(LLMConnectionError):
                await client_with_cb.complete(messages=[{"role": "user", "content": "hello"}])
        assert circuit_breaker.failure_count == 1


class TestWithoutCircuitBreaker:
    async def test_works_normally_without_cb(self, client_without_cb):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="hi")]
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5
        mock_response.model = "claude-opus-4-6"
        mock_response.stop_reason = "end_turn"

        with patch.object(
            client_without_cb._client.messages,
            "create",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await client_without_cb.complete(
                messages=[{"role": "user", "content": "hello"}]
            )
        assert result.text == "hi"
