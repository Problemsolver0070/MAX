"""Tests for MessageBus with Redis Streams backend.

Verifies the upgraded MessageBus works with:
- StreamsTransport (primary): consumer groups, ack, dead letter
- Pub/sub fallback (legacy): fire-and-forget, backward compatible
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from max.bus.message_bus import MessageBus
from max.bus.streams import StreamsTransport


@pytest.fixture
def mock_redis():
    """Mock async Redis client with pubsub support.

    redis.pubsub() is a synchronous method that returns an object with
    async methods (subscribe, unsubscribe, listen, aclose), so we use
    MagicMock for pubsub() and AsyncMock for the returned object.
    """
    redis = AsyncMock()
    pubsub = AsyncMock()
    redis.pubsub = MagicMock(return_value=pubsub)
    return redis


@pytest.fixture
def mock_transport():
    """Mock StreamsTransport with all required methods."""
    transport = AsyncMock(spec=StreamsTransport)
    transport.read_messages = AsyncMock(return_value=[])
    transport.publish = AsyncMock(return_value="1-0")
    transport.ack = AsyncMock()
    transport.dead_letter = AsyncMock()
    transport.ensure_group = AsyncMock()
    transport.max_retries = 3
    return transport


@pytest.fixture
def bus_with_streams(mock_redis, mock_transport):
    """MessageBus instance configured with StreamsTransport."""
    return MessageBus(
        redis_client=mock_redis,
        transport=mock_transport,
    )


@pytest.fixture
def bus_with_pubsub(mock_redis):
    """MessageBus instance with no transport (pub/sub fallback)."""
    return MessageBus(redis_client=mock_redis, transport=None)


# ── Backward Compatibility ──────────────────────────────────────────────


class TestBackwardCompatibility:
    """Ensure existing callers that pass only redis_client still work."""

    async def test_positional_redis_client_creates_pubsub_bus(self, mock_redis):
        bus = MessageBus(mock_redis)
        assert bus._transport is None
        assert bus._pubsub is not None

    async def test_keyword_redis_client_creates_pubsub_bus(self, mock_redis):
        bus = MessageBus(redis_client=mock_redis)
        assert bus._transport is None
        assert bus._pubsub is not None


# ── Subscribe ────────────────────────────────────────────────────────────


class TestSubscribeWithStreams:
    """Subscribe behavior when StreamsTransport is active."""

    async def test_subscribe_registers_handler(self, bus_with_streams):
        handler = AsyncMock()
        await bus_with_streams.subscribe("test_channel", handler)
        assert "test_channel" in bus_with_streams._handlers
        assert handler in bus_with_streams._handlers["test_channel"]

    async def test_subscribe_ensures_consumer_group(self, bus_with_streams, mock_transport):
        handler = AsyncMock()
        await bus_with_streams.subscribe("test_channel", handler)
        mock_transport.ensure_group.assert_called_with("test_channel")

    async def test_subscribe_does_not_use_pubsub(self, bus_with_streams, mock_redis):
        handler = AsyncMock()
        await bus_with_streams.subscribe("test_channel", handler)
        # Should NOT have created a pubsub subscription
        mock_redis.pubsub.return_value.subscribe.assert_not_called()

    async def test_subscribe_multiple_handlers_same_channel(self, bus_with_streams, mock_transport):
        h1 = AsyncMock()
        h2 = AsyncMock()
        await bus_with_streams.subscribe("ch", h1)
        await bus_with_streams.subscribe("ch", h2)
        assert len(bus_with_streams._handlers["ch"]) == 2
        # ensure_group should only be called once for the channel
        assert mock_transport.ensure_group.call_count == 1


class TestSubscribeWithPubSub:
    """Subscribe behavior when no transport (pub/sub fallback)."""

    async def test_subscribe_uses_pubsub(self, bus_with_pubsub, mock_redis):
        handler = AsyncMock()
        await bus_with_pubsub.subscribe("test_channel", handler)
        mock_redis.pubsub.return_value.subscribe.assert_called_with("test_channel")


# ── Publish ──────────────────────────────────────────────────────────────


class TestPublishWithStreams:
    """Publish behavior when StreamsTransport is active."""

    async def test_publish_uses_transport(self, bus_with_streams, mock_transport):
        await bus_with_streams.publish("ch", {"key": "value"})
        mock_transport.publish.assert_called_once_with("ch", {"key": "value"})

    async def test_publish_does_not_use_redis_publish(self, bus_with_streams, mock_redis):
        await bus_with_streams.publish("ch", {"key": "value"})
        mock_redis.publish.assert_not_called()


class TestPublishFallbackPubSub:
    """Publish behavior with pub/sub fallback."""

    async def test_publish_uses_redis_publish(self, bus_with_pubsub, mock_redis):
        await bus_with_pubsub.publish("ch", {"key": "value"})
        mock_redis.publish.assert_called_once()

    async def test_publish_serializes_data_as_json(self, bus_with_pubsub, mock_redis):
        await bus_with_pubsub.publish("ch", {"a": 1, "b": "two"})
        call_args = mock_redis.publish.call_args
        payload = call_args[0][1]
        parsed = json.loads(payload)
        assert parsed == {"a": 1, "b": "two"}


# ── Unsubscribe ──────────────────────────────────────────────────────────


class TestUnsubscribe:
    """Unsubscribe behavior for both transport modes."""

    async def test_unsubscribe_all_handlers(self, bus_with_streams):
        h1 = AsyncMock()
        h2 = AsyncMock()
        await bus_with_streams.subscribe("ch", h1)
        await bus_with_streams.subscribe("ch", h2)
        await bus_with_streams.unsubscribe("ch")
        assert "ch" not in bus_with_streams._handlers

    async def test_unsubscribe_specific_handler(self, bus_with_streams):
        h1 = AsyncMock()
        h2 = AsyncMock()
        await bus_with_streams.subscribe("ch", h1)
        await bus_with_streams.subscribe("ch", h2)
        await bus_with_streams.unsubscribe("ch", h1)
        assert "ch" in bus_with_streams._handlers
        assert h1 not in bus_with_streams._handlers["ch"]
        assert h2 in bus_with_streams._handlers["ch"]

    async def test_unsubscribe_last_handler_removes_channel(self, bus_with_streams):
        handler = AsyncMock()
        await bus_with_streams.subscribe("ch", handler)
        await bus_with_streams.unsubscribe("ch", handler)
        assert "ch" not in bus_with_streams._handlers

    async def test_unsubscribe_nonexistent_channel_is_noop(self, bus_with_streams):
        # Should not raise
        await bus_with_streams.unsubscribe("no_such_channel")

    async def test_unsubscribe_pubsub_calls_pubsub_unsubscribe(self, bus_with_pubsub, mock_redis):
        handler = AsyncMock()
        await bus_with_pubsub.subscribe("ch", handler)
        await bus_with_pubsub.unsubscribe("ch")
        mock_redis.pubsub.return_value.unsubscribe.assert_called_with("ch")


# ── Streams Listen Loop ─────────────────────────────────────────────────


class TestStreamListenLoop:
    """Streams-based listen loop behavior."""

    async def test_dispatches_to_handler(self, bus_with_streams, mock_transport):
        handler = AsyncMock()
        await bus_with_streams.subscribe("ch", handler)

        # Simulate one message then empty reads
        mock_transport.read_messages.side_effect = [
            [
                {
                    "channel": "ch",
                    "data": {"key": "value"},
                    "stream_id": "1-0",
                    "message_id": "abc",
                }
            ],
            [],
            [],
            [],
        ]

        await bus_with_streams.start_listening()
        await asyncio.sleep(0.15)
        await bus_with_streams.stop_listening()

        handler.assert_called_once_with("ch", {"key": "value"})

    async def test_acks_after_successful_handler(self, bus_with_streams, mock_transport):
        handler = AsyncMock()
        await bus_with_streams.subscribe("ch", handler)

        mock_transport.read_messages.side_effect = [
            [
                {
                    "channel": "ch",
                    "data": {"x": 1},
                    "stream_id": "1-0",
                    "message_id": "abc",
                }
            ],
            [],
            [],
            [],
        ]

        await bus_with_streams.start_listening()
        await asyncio.sleep(0.15)
        await bus_with_streams.stop_listening()

        mock_transport.ack.assert_called_once_with("ch", "1-0")

    async def test_dead_letters_after_handler_failure(self, bus_with_streams, mock_transport):
        handler = AsyncMock(side_effect=Exception("boom"))
        await bus_with_streams.subscribe("ch", handler)

        mock_transport.read_messages.side_effect = [
            [
                {
                    "channel": "ch",
                    "data": {"x": 1, "_retry_count": 3},
                    "stream_id": "1-0",
                    "message_id": "abc",
                }
            ],
            [],
            [],
            [],
        ]

        await bus_with_streams.start_listening()
        await asyncio.sleep(0.15)
        await bus_with_streams.stop_listening()

        mock_transport.dead_letter.assert_called_once()

    async def test_nacks_and_republishes_on_retriable_failure(
        self, bus_with_streams, mock_transport
    ):
        """When handler fails but retry_count < max_retries, re-publish."""
        handler = AsyncMock(side_effect=Exception("transient"))
        await bus_with_streams.subscribe("ch", handler)

        mock_transport.read_messages.side_effect = [
            [
                {
                    "channel": "ch",
                    "data": {"x": 1, "_retry_count": 1},
                    "stream_id": "2-0",
                    "message_id": "def",
                }
            ],
            [],
            [],
            [],
        ]

        await bus_with_streams.start_listening()
        await asyncio.sleep(0.15)
        await bus_with_streams.stop_listening()

        # Should ack the original and re-publish with incremented count
        mock_transport.ack.assert_called_once_with("ch", "2-0")
        mock_transport.publish.assert_called_once()
        republished_data = mock_transport.publish.call_args[0][1]
        assert republished_data["_retry_count"] == 2

    async def test_multiple_handlers_all_called(self, bus_with_streams, mock_transport):
        h1 = AsyncMock()
        h2 = AsyncMock()
        await bus_with_streams.subscribe("ch", h1)
        await bus_with_streams.subscribe("ch", h2)

        mock_transport.read_messages.side_effect = [
            [
                {
                    "channel": "ch",
                    "data": {"v": 42},
                    "stream_id": "3-0",
                    "message_id": "ghi",
                }
            ],
            [],
            [],
            [],
        ]

        await bus_with_streams.start_listening()
        await asyncio.sleep(0.15)
        await bus_with_streams.stop_listening()

        h1.assert_called_once_with("ch", {"v": 42})
        h2.assert_called_once_with("ch", {"v": 42})
        mock_transport.ack.assert_called_once_with("ch", "3-0")

    async def test_start_listening_is_idempotent(self, bus_with_streams, mock_transport):
        handler = AsyncMock()
        await bus_with_streams.subscribe("ch", handler)
        mock_transport.read_messages.return_value = []

        await bus_with_streams.start_listening()
        task1 = bus_with_streams._listen_task
        await bus_with_streams.start_listening()  # second call
        task2 = bus_with_streams._listen_task

        assert task1 is task2  # same task, no duplicate
        await bus_with_streams.stop_listening()


# ── Close ────────────────────────────────────────────────────────────────


class TestCloseWithStreams:
    """Close behavior with StreamsTransport."""

    async def test_close_stops_listening(self, bus_with_streams, mock_transport):
        mock_transport.read_messages.return_value = []
        await bus_with_streams.start_listening()
        await asyncio.sleep(0.05)
        await bus_with_streams.close()
        assert bus_with_streams._listen_task is None or bus_with_streams._listen_task.done()

    async def test_close_does_not_close_pubsub_in_streams_mode(self, bus_with_streams, mock_redis):
        """When using streams, there is no pubsub to close."""
        await bus_with_streams.close()
        # _pubsub should be None in streams mode
        assert bus_with_streams._pubsub is None


class TestCloseWithPubSub:
    """Close behavior with pub/sub fallback."""

    async def test_close_closes_pubsub(self, bus_with_pubsub, mock_redis):
        await bus_with_pubsub.close()
        mock_redis.pubsub.return_value.aclose.assert_called_once()
