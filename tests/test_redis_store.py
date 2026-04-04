# tests/test_redis_store.py
import pytest
import redis.asyncio as aioredis

from max.db.redis_store import WarmMemory


@pytest.fixture
async def redis_client():
    client = aioredis.from_url("redis://localhost:6379/14")  # test DB
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def warm(redis_client):
    return WarmMemory(redis_client)


@pytest.mark.asyncio
async def test_set_and_get(warm):
    await warm.set("user:prefs", {"tone": "direct", "detail": "high"})
    result = await warm.get("user:prefs")
    assert result["tone"] == "direct"
    assert result["detail"] == "high"


@pytest.mark.asyncio
async def test_get_missing_key(warm):
    result = await warm.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_set_with_ttl(warm):
    await warm.set("temp:data", {"value": 42}, ttl_seconds=1)
    result = await warm.get("temp:data")
    assert result["value"] == 42


@pytest.mark.asyncio
async def test_delete(warm):
    await warm.set("to:delete", {"data": True})
    await warm.delete("to:delete")
    result = await warm.get("to:delete")
    assert result is None


@pytest.mark.asyncio
async def test_set_state_document(warm):
    state = {
        "active_tasks": [],
        "pending_decisions": [],
        "system_health": "ok",
    }
    await warm.set("coordinator:state", state)
    result = await warm.get("coordinator:state")
    assert result["system_health"] == "ok"


@pytest.mark.asyncio
async def test_set_with_ttl_expires(warm):
    """Verify TTL actually expires keys."""
    import asyncio
    await warm.set("short_lived", {"data": "brief"}, ttl_seconds=1)
    result = await warm.get("short_lived")
    assert result is not None
    await asyncio.sleep(1.5)
    result = await warm.get("short_lived")
    assert result is None


@pytest.mark.asyncio
async def test_list_push_and_range(warm):
    await warm.list_push("events", {"type": "task_started", "id": "1"})
    await warm.list_push("events", {"type": "task_completed", "id": "2"})
    items = await warm.list_range("events", 0, -1)
    assert len(items) == 2
    assert items[0]["type"] == "task_started"
    assert items[1]["type"] == "task_completed"
