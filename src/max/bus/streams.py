"""Redis Streams transport for the MessageBus.

Provides durable message delivery with consumer groups, acknowledgment,
and dead letter handling. Replaces fire-and-forget pub/sub for cases
where at-least-once delivery is required.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class StreamsTransport:
    """Redis Streams transport with consumer groups and dead letter support.

    Args:
        redis_client: An async Redis client instance.
        consumer_group: Name of the consumer group (shared across replicas).
        consumer_name: Unique name for this consumer (unique per replica).
        max_retries: Max delivery attempts before dead-lettering.
        stream_max_len: Approximate max length for each stream (XTRIM MAXLEN ~).
    """

    def __init__(
        self,
        redis_client: aioredis.Redis,
        consumer_group: str = "max_workers",
        consumer_name: str = "worker-1",
        max_retries: int = 3,
        stream_max_len: int = 10000,
    ) -> None:
        self._redis = redis_client
        self._consumer_group = consumer_group
        self._consumer_name = consumer_name
        self._max_retries = max_retries
        self._stream_max_len = stream_max_len
        self._ensured_groups: set[str] = set()

    def _stream_key(self, channel: str) -> str:
        """Map a logical channel name to a Redis stream key."""
        return f"stream:{channel}"

    def _dead_letter_key(self, channel: str) -> str:
        """Map a logical channel name to its dead letter stream key."""
        return f"dead_letter:{channel}"

    async def ensure_group(self, channel: str) -> None:
        """Create a consumer group for the channel if it doesn't exist.

        Uses an in-memory cache to avoid redundant XGROUP CREATE calls.
        The BUSYGROUP error (group already exists) is silently ignored;
        all other Redis errors are propagated.
        """
        stream_key = self._stream_key(channel)
        if stream_key in self._ensured_groups:
            return
        try:
            await self._redis.xgroup_create(
                stream_key,
                self._consumer_group,
                id="0",
                mkstream=True,
            )
        except Exception as exc:
            if "BUSYGROUP" in str(exc):
                pass  # Group already exists — this is fine
            else:
                raise
        self._ensured_groups.add(stream_key)

    async def publish(self, channel: str, data: dict[str, Any]) -> str:
        """Publish a message to a stream.

        The message is added with an auto-generated ``message_id`` field
        for correlation, and the stream is trimmed to ``stream_max_len``
        (approximate) to bound memory usage.

        Returns:
            The Redis stream entry ID (e.g. ``"1234567890-0"``).
        """
        stream_key = self._stream_key(channel)
        message_id = str(uuid.uuid4())
        fields = {
            "data": json.dumps(data, default=str),
            "message_id": message_id,
        }
        entry_id = await self._redis.xadd(
            stream_key,
            fields,
            maxlen=self._stream_max_len,
        )
        return entry_id if isinstance(entry_id, str) else entry_id.decode()

    async def read_messages(
        self,
        channels: list[str],
        timeout_ms: int = 1000,
    ) -> list[dict[str, Any]]:
        """Read new messages from streams using the consumer group.

        Calls ``XREADGROUP`` with ``>`` to fetch only new (undelivered)
        messages. Each returned dict contains:

        - ``channel``: the logical channel name (without ``stream:`` prefix)
        - ``data``: the deserialised JSON payload
        - ``stream_id``: the Redis stream entry ID (for ack / dead-letter)
        - ``message_id``: the application-level correlation ID
        """
        if not channels:
            return []

        streams = {self._stream_key(ch): ">" for ch in channels}

        raw = await self._redis.xreadgroup(
            self._consumer_group,
            self._consumer_name,
            streams,
            count=10,
            block=timeout_ms,
        )
        if not raw:
            return []

        messages: list[dict[str, Any]] = []
        for stream_ref, entries in raw:
            stream_name = stream_ref.decode() if isinstance(stream_ref, bytes) else stream_ref
            channel = stream_name.removeprefix("stream:")

            for entry_id_ref, fields in entries:
                entry_id = (
                    entry_id_ref.decode() if isinstance(entry_id_ref, bytes) else entry_id_ref
                )
                # Handle both bytes-keyed and string-keyed field dicts
                data_raw = fields.get(b"data") or fields.get("data", "{}")
                if isinstance(data_raw, bytes):
                    data_raw = data_raw.decode()
                message_id_raw = fields.get(b"message_id") or fields.get("message_id", "")
                if isinstance(message_id_raw, bytes):
                    message_id_raw = message_id_raw.decode()

                try:
                    data = json.loads(data_raw)
                except (json.JSONDecodeError, TypeError):
                    data = {}

                messages.append(
                    {
                        "channel": channel,
                        "data": data,
                        "stream_id": entry_id,
                        "message_id": message_id_raw,
                    }
                )

        return messages

    async def ack(self, channel: str, stream_id: str) -> None:
        """Acknowledge a processed message, removing it from the PEL."""
        await self._redis.xack(
            self._stream_key(channel),
            self._consumer_group,
            stream_id,
        )

    async def dead_letter(
        self,
        channel: str,
        stream_id: str,
        data: dict[str, Any],
        error: str,
        attempt: int,
    ) -> None:
        """Move a failed message to the dead letter stream.

        The original message data, error details, and attempt count are
        preserved in the dead letter entry for later inspection or replay.
        The original message is acknowledged so it is not re-delivered.
        """
        dl_key = self._dead_letter_key(channel)
        dl_data = {
            "original_data": data,
            "error": error,
            "attempt": attempt,
            "channel": channel,
            "original_stream_id": stream_id,
        }
        await self._redis.xadd(
            dl_key,
            {"data": json.dumps(dl_data, default=str)},
        )
        # Acknowledge the original message so it's not re-delivered
        await self.ack(channel, stream_id)
        logger.warning(
            "Message dead-lettered on %s (attempt %d): %s",
            channel,
            attempt,
            error,
        )

    async def get_dead_letters(self, channel: str, count: int = 50) -> list[dict[str, Any]]:
        """Retrieve dead letter entries for a channel.

        Returns a list of dicts, each containing ``original_data``,
        ``error``, ``attempt``, ``channel``, and ``original_stream_id``.
        """
        dl_key = self._dead_letter_key(channel)
        raw = await self._redis.xrange(dl_key, count=count)
        entries: list[dict[str, Any]] = []
        for _entry_id, fields in raw:
            data_raw = fields.get(b"data") or fields.get("data", "{}")
            if isinstance(data_raw, bytes):
                data_raw = data_raw.decode()
            try:
                entries.append(json.loads(data_raw))
            except (json.JSONDecodeError, TypeError):
                pass
        return entries

    @property
    def max_retries(self) -> int:
        """Maximum delivery attempts before dead-lettering."""
        return self._max_retries
