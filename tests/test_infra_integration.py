"""Integration tests for infrastructure hardening components.

Verifies that the infrastructure modules (circuit breaker, message bus,
observability, scheduler) work together through their full lifecycles.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from max.bus.message_bus import MessageBus
from max.bus.streams import StreamsTransport
from max.llm.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpen,
    CircuitState,
)
from max.observability import (
    CorrelationContext,
    JsonFormatter,
    configure_metrics,
    set_correlation_id,
)
from max.scheduler import SchedulerJob


class TestCircuitBreakerFullCycle:
    """Test the full circuit breaker lifecycle: closed -> open -> half-open -> closed."""

    def test_full_lifecycle(self):
        cb = CircuitBreaker(threshold=2, cooldown_seconds=0.1)

        # Start closed
        assert cb.state == CircuitState.CLOSED
        cb.check()  # no error

        # Two failures open it
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Can't call while open
        with pytest.raises(CircuitBreakerOpen):
            cb.check()

        # Wait for cooldown
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

        # One test call allowed
        cb.check()

        # Success closes it
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0


class TestStreamsBusIntegration:
    """Test MessageBus with mocked StreamsTransport end-to-end."""

    async def test_publish_subscribe_ack_cycle(self):
        mock_redis = AsyncMock()
        transport = AsyncMock(spec=StreamsTransport)
        transport.ensure_group = AsyncMock()
        transport.publish = AsyncMock(return_value="1-0")
        transport.ack = AsyncMock()
        transport.dead_letter = AsyncMock()
        transport.max_retries = 3

        bus = MessageBus(redis_client=mock_redis, transport=transport)
        received: list[tuple[str, dict]] = []

        async def handler(channel: str, data: dict) -> None:
            received.append((channel, data))

        await bus.subscribe("test.channel", handler)
        transport.ensure_group.assert_called_with("test.channel")

        # Simulate incoming messages: first call returns one message,
        # subsequent calls return empty (the loop runs until cancelled).
        transport.read_messages = AsyncMock(
            side_effect=[
                [
                    {
                        "channel": "test.channel",
                        "data": {"msg": "hello"},
                        "stream_id": "1-0",
                        "message_id": "abc",
                    }
                ],
                [],  # empty on second read
                asyncio.CancelledError(),  # stop the loop
            ]
        )

        await bus.start_listening()
        # Give the listener loop time to process the message
        await asyncio.sleep(0.15)
        await bus.stop_listening()

        assert len(received) == 1
        assert received[0] == ("test.channel", {"msg": "hello"})
        transport.ack.assert_called_with("test.channel", "1-0")


class TestObservabilityIntegration:
    """Test logging + correlation ID + metrics together."""

    def test_correlation_flows_through_json_log(self):
        import io
        import logging

        # Set up a JSON handler on a test logger
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())
        test_logger = logging.getLogger("test.integration.obs")
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.DEBUG)

        token = set_correlation_id("req-abc-123")
        try:
            test_logger.info("Processing request")
            output = stream.getvalue()
            parsed = json.loads(output.strip())
            assert parsed["correlation_id"] == "req-abc-123"
            assert parsed["message"] == "Processing request"
        finally:
            CorrelationContext.reset(token)
            test_logger.removeHandler(handler)

    def test_metrics_registry_instruments_work(self):
        registry = configure_metrics(service_name="test-integration", enabled=False)
        counter = registry.counter("max.test.messages", "Test counter")
        histogram = registry.histogram("max.test.latency", "Test histogram")

        counter.add(1, {"channel": "telegram"})
        histogram.record(0.5, {"agent": "coordinator"})
        # No assertions on values (OpenTelemetry doesn't expose sync reads),
        # just verify no exceptions


class TestSchedulerJobModel:
    """Test SchedulerJob due/advance logic."""

    def test_job_due_and_advance(self):
        job = SchedulerJob("test", 3600, AsyncMock())
        job.next_run_at = datetime.now(UTC) - timedelta(seconds=1)
        assert job.is_due() is True

        job.advance()
        assert job.is_due() is False
        assert job.last_run_at is not None
        # next_run should be ~3600s from now
        delta = (job.next_run_at - datetime.now(UTC)).total_seconds()
        assert 3590 < delta < 3610


class TestPubSubFallback:
    """Test that MessageBus works in pub/sub mode when transport is None."""

    async def test_publish_uses_redis_directly(self):
        mock_redis = AsyncMock()
        mock_redis.pubsub = MagicMock(return_value=AsyncMock())
        bus = MessageBus(redis_client=mock_redis, transport=None)

        await bus.publish("ch", {"key": "value"})
        mock_redis.publish.assert_called_once()
        call_args = mock_redis.publish.call_args
        assert call_args[0][0] == "ch"
        payload = json.loads(call_args[0][1])
        assert payload["key"] == "value"
