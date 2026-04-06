"""Tests for Redis Streams transport layer."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from max.bus.streams import StreamsTransport


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.xadd = AsyncMock(return_value=b"1234567890-0")
    redis.xreadgroup = AsyncMock(return_value=[])
    redis.xack = AsyncMock(return_value=1)
    redis.xgroup_create = AsyncMock()
    redis.xlen = AsyncMock(return_value=0)
    redis.xtrim = AsyncMock()
    redis.xinfo_groups = AsyncMock(return_value=[])
    redis.xrange = AsyncMock(return_value=[])
    redis.xpending_range = AsyncMock(return_value=[])
    return redis


@pytest.fixture
def transport(mock_redis):
    return StreamsTransport(
        redis_client=mock_redis,
        consumer_group="test_group",
        consumer_name="test_worker",
        max_retries=3,
        stream_max_len=1000,
    )


class TestPublish:
    async def test_publishes_to_stream(self, transport, mock_redis):
        await transport.publish("test_channel", {"key": "value"})
        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "stream:test_channel"
        fields = call_args[0][1]
        assert "data" in fields
        parsed = json.loads(fields["data"])
        assert parsed["key"] == "value"

    async def test_publish_includes_message_id(self, transport, mock_redis):
        await transport.publish("ch", {"x": 1})
        call_args = mock_redis.xadd.call_args
        fields = call_args[0][1]
        assert "message_id" in fields

    async def test_publish_trims_stream(self, transport, mock_redis):
        await transport.publish("ch", {"x": 1})
        call_args = mock_redis.xadd.call_args
        assert call_args[1].get("maxlen") == 1000 or "maxlen" in str(call_args)

    async def test_publish_returns_entry_id(self, transport, mock_redis):
        result = await transport.publish("ch", {"x": 1})
        assert result == "1234567890-0"

    async def test_publish_serialises_non_string_values(self, transport, mock_redis):
        """Non-JSON-serialisable values are converted via default=str."""
        from datetime import datetime

        dt = datetime(2026, 1, 1, 12, 0, 0)
        await transport.publish("ch", {"ts": dt})
        call_args = mock_redis.xadd.call_args
        fields = call_args[0][1]
        parsed = json.loads(fields["data"])
        assert "2026" in parsed["ts"]


class TestConsumerGroupSetup:
    async def test_creates_consumer_group(self, transport, mock_redis):
        await transport.ensure_group("test_channel")
        mock_redis.xgroup_create.assert_called_once_with(
            "stream:test_channel",
            "test_group",
            id="0",
            mkstream=True,
        )

    async def test_ignores_existing_group(self, transport, mock_redis):
        from redis.exceptions import ResponseError

        mock_redis.xgroup_create.side_effect = ResponseError("BUSYGROUP")
        await transport.ensure_group("test_channel")  # should not raise

    async def test_caches_ensured_groups(self, transport, mock_redis):
        """Second call for same channel should not hit Redis again."""
        await transport.ensure_group("test_channel")
        await transport.ensure_group("test_channel")
        mock_redis.xgroup_create.assert_called_once()

    async def test_propagates_non_busygroup_errors(self, transport, mock_redis):
        from redis.exceptions import ResponseError

        mock_redis.xgroup_create.side_effect = ResponseError("SOME OTHER ERROR")
        with pytest.raises(ResponseError, match="SOME OTHER ERROR"):
            await transport.ensure_group("test_channel")


class TestConsume:
    async def test_calls_xreadgroup(self, transport, mock_redis):
        mock_redis.xreadgroup.return_value = []
        messages = await transport.read_messages(["test_channel"], timeout_ms=100)
        mock_redis.xreadgroup.assert_called_once()
        assert messages == []

    async def test_parses_stream_messages(self, transport, mock_redis):
        mock_redis.xreadgroup.return_value = [
            (
                b"stream:test_channel",
                [
                    (
                        b"1234-0",
                        {
                            b"data": json.dumps({"key": "value"}).encode(),
                            b"message_id": b"abc-123",
                        },
                    )
                ],
            )
        ]
        messages = await transport.read_messages(["test_channel"], timeout_ms=100)
        assert len(messages) == 1
        assert messages[0]["channel"] == "test_channel"
        assert messages[0]["data"]["key"] == "value"
        assert messages[0]["stream_id"] == "1234-0"
        assert messages[0]["message_id"] == "abc-123"

    async def test_handles_string_keyed_fields(self, transport, mock_redis):
        """Some redis clients return string keys rather than bytes."""
        mock_redis.xreadgroup.return_value = [
            (
                "stream:test_channel",
                [
                    (
                        "9999-0",
                        {
                            "data": json.dumps({"a": 1}),
                            "message_id": "xyz",
                        },
                    )
                ],
            )
        ]
        messages = await transport.read_messages(["test_channel"], timeout_ms=50)
        assert len(messages) == 1
        assert messages[0]["data"]["a"] == 1
        assert messages[0]["stream_id"] == "9999-0"

    async def test_handles_empty_channels_list(self, transport, mock_redis):
        messages = await transport.read_messages([], timeout_ms=50)
        assert messages == []
        mock_redis.xreadgroup.assert_not_called()

    async def test_handles_malformed_json_data(self, transport, mock_redis):
        mock_redis.xreadgroup.return_value = [
            (
                b"stream:ch",
                [
                    (
                        b"1-0",
                        {
                            b"data": b"not-valid-json",
                            b"message_id": b"m1",
                        },
                    )
                ],
            )
        ]
        messages = await transport.read_messages(["ch"], timeout_ms=50)
        assert len(messages) == 1
        assert messages[0]["data"] == {}

    async def test_parses_multiple_streams(self, transport, mock_redis):
        mock_redis.xreadgroup.return_value = [
            (
                b"stream:alpha",
                [(b"1-0", {b"data": json.dumps({"x": 1}).encode(), b"message_id": b"m1"})],
            ),
            (
                b"stream:beta",
                [(b"2-0", {b"data": json.dumps({"y": 2}).encode(), b"message_id": b"m2"})],
            ),
        ]
        messages = await transport.read_messages(["alpha", "beta"], timeout_ms=50)
        assert len(messages) == 2
        channels = {m["channel"] for m in messages}
        assert channels == {"alpha", "beta"}


class TestAcknowledge:
    async def test_acknowledges_message(self, transport, mock_redis):
        await transport.ack("test_channel", "1234-0")
        mock_redis.xack.assert_called_once_with(
            "stream:test_channel", "test_group", "1234-0"
        )


class TestDeadLetter:
    async def test_sends_to_dead_letter_stream(self, transport, mock_redis):
        await transport.dead_letter(
            channel="test_channel",
            stream_id="1234-0",
            data={"key": "value"},
            error="Handler failed",
            attempt=3,
        )
        # Two xadd calls: one for dead letter, one implicit ack doesn't use xadd
        # Actually dead_letter calls xadd for dead letter stream + xack for original
        assert mock_redis.xadd.call_count == 1
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "dead_letter:test_channel"

    async def test_dead_letter_includes_error_info(self, transport, mock_redis):
        await transport.dead_letter(
            channel="ch",
            stream_id="1-0",
            data={"x": 1},
            error="boom",
            attempt=3,
        )
        call_args = mock_redis.xadd.call_args
        fields = call_args[0][1]
        parsed = json.loads(fields["data"])
        assert parsed["original_data"]["x"] == 1
        assert parsed["error"] == "boom"
        assert parsed["attempt"] == 3

    async def test_dead_letter_acks_original(self, transport, mock_redis):
        """Dead-lettering should acknowledge the original message."""
        await transport.dead_letter(
            channel="ch",
            stream_id="5-0",
            data={},
            error="err",
            attempt=1,
        )
        mock_redis.xack.assert_called_once_with("stream:ch", "test_group", "5-0")

    async def test_dead_letter_preserves_channel(self, transport, mock_redis):
        await transport.dead_letter(
            channel="events.task",
            stream_id="1-0",
            data={"a": 1},
            error="err",
            attempt=2,
        )
        call_args = mock_redis.xadd.call_args
        fields = call_args[0][1]
        parsed = json.loads(fields["data"])
        assert parsed["channel"] == "events.task"
        assert parsed["original_stream_id"] == "1-0"


class TestGetDeadLetters:
    async def test_returns_dead_letter_entries(self, transport, mock_redis):
        mock_redis.xrange.return_value = [
            (
                b"1-0",
                {
                    b"data": json.dumps({
                        "original_data": {"x": 1},
                        "error": "boom",
                        "attempt": 3,
                        "channel": "ch",
                    }).encode()
                },
            )
        ]
        entries = await transport.get_dead_letters("ch", count=10)
        assert len(entries) == 1
        assert entries[0]["original_data"]["x"] == 1
        assert entries[0]["error"] == "boom"

    async def test_empty_dead_letter_stream(self, transport, mock_redis):
        mock_redis.xrange.return_value = []
        entries = await transport.get_dead_letters("ch", count=10)
        assert entries == []

    async def test_calls_correct_stream_key(self, transport, mock_redis):
        mock_redis.xrange.return_value = []
        await transport.get_dead_letters("my_channel", count=25)
        mock_redis.xrange.assert_called_once_with("dead_letter:my_channel", count=25)


class TestProperties:
    def test_max_retries_property(self, transport):
        assert transport.max_retries == 3

    def test_stream_key_mapping(self, transport):
        assert transport._stream_key("events.task") == "stream:events.task"

    def test_dead_letter_key_mapping(self, transport):
        assert transport._dead_letter_key("events.task") == "dead_letter:events.task"
