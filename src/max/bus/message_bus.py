from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

Handler = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


class MessageBus:
    def __init__(self, redis_client: aioredis.Redis):
        self._redis = redis_client
        self._pubsub = redis_client.pubsub()
        self._handlers: dict[str, Handler] = {}
        self._listen_task: asyncio.Task | None = None

    async def subscribe(self, channel: str, handler: Handler) -> None:
        self._handlers[channel] = handler
        await self._pubsub.subscribe(channel)
        logger.debug("Subscribed to %s", channel)

    async def unsubscribe(self, channel: str) -> None:
        self._handlers.pop(channel, None)
        await self._pubsub.unsubscribe(channel)
        logger.debug("Unsubscribed from %s", channel)

    async def publish(self, channel: str, data: dict[str, Any]) -> None:
        payload = json.dumps(data)
        await self._redis.publish(channel, payload)
        logger.debug("Published to %s: %s", channel, payload[:200])

    async def start_listening(self) -> None:
        if self._listen_task is not None:
            return
        self._listen_task = asyncio.create_task(self._listen_loop())

    async def stop_listening(self) -> None:
        if self._listen_task is not None:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

    async def _listen_loop(self) -> None:
        try:
            async for message in self._pubsub.listen():
                if message["type"] != "message":
                    continue
                channel = message["channel"]
                if isinstance(channel, bytes):
                    channel = channel.decode("utf-8")
                handler = self._handlers.get(channel)
                if handler is None:
                    continue
                try:
                    data = json.loads(message["data"])
                    await handler(channel, data)
                except Exception:
                    logger.exception("Error in handler for %s", channel)
        except asyncio.CancelledError:
            raise

    async def close(self) -> None:
        await self.stop_listening()
        await self._pubsub.aclose()
