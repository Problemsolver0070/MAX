"""Redis warm memory store for Max.

Provides fast key-value and list operations for coordinator state,
active task context, and session data with optional TTL support.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

PREFIX = "max:"


class WarmMemory:
    """Warm-tier memory backed by Redis.

    Stores structured data as JSON with automatic key prefixing.
    Supports key-value operations with optional TTL and list operations.
    """

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    def _key(self, key: str) -> str:
        return f"{PREFIX}{key}"

    async def set(self, key: str, value: dict[str, Any], ttl_seconds: int | None = None) -> None:
        """Set a key to a JSON-serialised value, with optional TTL."""
        payload = json.dumps(value)
        if ttl_seconds:
            await self._redis.setex(self._key(key), ttl_seconds, payload)
        else:
            await self._redis.set(self._key(key), payload)

    async def get(self, key: str) -> dict[str, Any] | None:
        """Get and deserialise a value by key. Returns None if missing."""
        raw = await self._redis.get(self._key(key))
        if raw is None:
            return None
        return json.loads(raw)

    async def delete(self, key: str) -> None:
        """Delete a key."""
        await self._redis.delete(self._key(key))

    async def list_push(self, key: str, value: dict[str, Any]) -> None:
        """Append a JSON-serialised value to the right end of a list."""
        payload = json.dumps(value)
        await self._redis.rpush(self._key(key), payload)

    async def list_range(self, key: str, start: int, stop: int) -> list[dict[str, Any]]:
        """Return a slice of the list, deserialised from JSON."""
        raw_items = await self._redis.lrange(self._key(key), start, stop)
        return [json.loads(item) for item in raw_items]
