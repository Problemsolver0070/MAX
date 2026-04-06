"""MessageBus -- async message broker with pluggable transport.

Supports two transports:
- Redis Streams (default when transport provided): durable, with consumer
  groups, acknowledgment, retry, and dead letter handling.
- Redis pub/sub (fallback when transport is None): fire-and-forget, for
  backward compatibility with existing callers.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import redis.asyncio as aioredis

    from max.bus.streams import StreamsTransport

logger = logging.getLogger(__name__)

Handler = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


class MessageBus:
    """Async message bus with pluggable Redis transport.

    Args:
        redis_client: An async Redis client instance.
        transport: Optional StreamsTransport. When provided, the bus uses
            Redis Streams with consumer groups for durable delivery.
            When ``None`` (the default), falls back to Redis pub/sub
            for backward compatibility.
    """

    def __init__(
        self,
        redis_client: aioredis.Redis,
        transport: StreamsTransport | None = None,
    ) -> None:
        self._redis = redis_client
        self._transport = transport
        self._handlers: dict[str, list[Handler]] = {}
        self._listen_task: asyncio.Task | None = None
        self._running = False

        # Pub/sub fallback -- only created when no streams transport
        if self._transport is None:
            self._pubsub = redis_client.pubsub()
        else:
            self._pubsub = None

    # ── Subscribe / Unsubscribe ──────────────────────────────────────────

    async def subscribe(self, channel: str, handler: Handler) -> None:
        """Register a handler for a channel.

        First subscription to a channel will either create a consumer group
        (streams mode) or subscribe to the Redis pub/sub channel (fallback).
        """
        if channel not in self._handlers:
            self._handlers[channel] = []
            if self._transport is not None:
                await self._transport.ensure_group(channel)
            elif self._pubsub is not None:
                await self._pubsub.subscribe(channel)

        self._handlers[channel].append(handler)
        logger.debug(
            "Subscribed handler to %s (total: %d)",
            channel,
            len(self._handlers[channel]),
        )

    async def unsubscribe(
        self, channel: str, handler: Handler | None = None
    ) -> None:
        """Remove a handler (or all handlers) for a channel.

        When the last handler for a channel is removed, the pub/sub
        subscription (if any) is also cleaned up.
        """
        if channel not in self._handlers:
            return

        if handler is None:
            del self._handlers[channel]
        else:
            self._handlers[channel] = [
                h for h in self._handlers[channel] if h is not handler
            ]
            if not self._handlers[channel]:
                del self._handlers[channel]

        if channel not in self._handlers and self._pubsub is not None:
            await self._pubsub.unsubscribe(channel)

        logger.debug("Unsubscribed from %s", channel)

    # ── Publish ──────────────────────────────────────────────────────────

    async def publish(self, channel: str, data: dict[str, Any]) -> None:
        """Publish a message to a channel.

        Uses the streams transport when available, otherwise falls back
        to Redis pub/sub.
        """
        if self._transport is not None:
            await self._transport.publish(channel, data)
        else:
            payload = json.dumps(data, default=str)
            await self._redis.publish(channel, payload)
        logger.debug("Published to %s", channel)

    # ── Listener lifecycle ───────────────────────────────────────────────

    async def start_listening(self) -> None:
        """Start the background listener loop.

        Idempotent -- calling while already listening is a no-op.
        """
        if self._listen_task is not None and not self._listen_task.done():
            return
        self._running = True
        if self._transport is not None:
            self._listen_task = asyncio.create_task(self._streams_listen_loop())
        else:
            self._listen_task = asyncio.create_task(self._pubsub_listen_loop())

    async def stop_listening(self) -> None:
        """Stop the background listener loop."""
        self._running = False
        if self._listen_task is not None:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

    async def close(self) -> None:
        """Stop listening and release resources."""
        await self.stop_listening()
        if self._pubsub is not None:
            await self._pubsub.aclose()

    # ── Streams listener ────────────────────────────────────────────────

    async def _streams_listen_loop(self) -> None:
        """Listen loop using Redis Streams with consumer groups.

        For each message:
        - All registered handlers are invoked.
        - On success the message is acknowledged.
        - On failure with retry budget remaining, the message is re-published
          with an incremented ``_retry_count``.
        - On failure at max retries, the message is dead-lettered.
        """
        logger.info("Streams listen loop started")
        while self._running:
            try:
                channels = list(self._handlers.keys())
                if not channels:
                    await asyncio.sleep(0.05)
                    continue

                messages = await self._transport.read_messages(
                    channels, timeout_ms=1000
                )

                for msg in messages:
                    channel = msg["channel"]
                    data = msg["data"]
                    stream_id = msg["stream_id"]
                    retry_count = msg.get("_retry_count", 0)

                    handlers = self._handlers.get(channel, [])
                    success = True

                    for handler in handlers:
                        try:
                            await handler(channel, data)
                        except Exception:
                            success = False
                            logger.exception(
                                "Handler error on %s (stream_id=%s)",
                                channel,
                                stream_id,
                            )

                    if success:
                        await self._transport.ack(channel, stream_id)
                    elif retry_count >= self._transport.max_retries:
                        await self._transport.dead_letter(
                            channel=channel,
                            stream_id=stream_id,
                            data=data,
                            error="Handler failed after max retries",
                            attempt=retry_count,
                        )
                    else:
                        # NACK: ack original, re-publish with incremented retry
                        await self._transport.ack(channel, stream_id)
                        data["_retry_count"] = retry_count + 1
                        await self._transport.publish(channel, data)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in streams listen loop")
                await asyncio.sleep(1)

        logger.info("Streams listen loop stopped")

    # ── Pub/sub listener (fallback) ──────────────────────────────────────

    async def _pubsub_listen_loop(self) -> None:
        """Listen loop using Redis pub/sub (legacy fallback)."""
        logger.info("Pub/sub listen loop started")
        try:
            async for message in self._pubsub.listen():
                if not self._running:
                    break
                if message["type"] != "message":
                    continue

                channel = message["channel"]
                if isinstance(channel, bytes):
                    channel = channel.decode("utf-8")

                handlers = self._handlers.get(channel, [])
                if not handlers:
                    continue

                try:
                    data = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    logger.exception(
                        "Failed to decode message on %s", channel
                    )
                    continue

                for handler in handlers:
                    try:
                        await handler(channel, data)
                    except Exception:
                        logger.exception(
                            "Error in handler for %s", channel
                        )
        except asyncio.CancelledError:
            raise

        logger.info("Pub/sub listen loop stopped")
