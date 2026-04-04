import asyncio

import pytest
import redis.asyncio as aioredis

from max.bus.message_bus import MessageBus


@pytest.fixture
async def redis_client():
    client = aioredis.from_url("redis://localhost:6379/15")  # test DB
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def bus(redis_client):
    bus = MessageBus(redis_client)
    yield bus
    await bus.close()


@pytest.mark.asyncio
async def test_publish_and_subscribe(bus):
    received = []

    async def handler(channel: str, data: dict):
        received.append((channel, data))

    await bus.subscribe("test.channel", handler)
    await bus.start_listening()
    await asyncio.sleep(0.1)

    await bus.publish("test.channel", {"type": "greeting", "text": "hello"})
    await asyncio.sleep(0.3)

    await bus.stop_listening()
    assert len(received) == 1
    assert received[0][0] == "test.channel"
    assert received[0][1]["text"] == "hello"


@pytest.mark.asyncio
async def test_multiple_channels(bus):
    received_a = []
    received_b = []

    async def handler_a(channel: str, data: dict):
        received_a.append(data)

    async def handler_b(channel: str, data: dict):
        received_b.append(data)

    await bus.subscribe("channel.a", handler_a)
    await bus.subscribe("channel.b", handler_b)
    await bus.start_listening()
    await asyncio.sleep(0.1)

    await bus.publish("channel.a", {"msg": "for_a"})
    await bus.publish("channel.b", {"msg": "for_b"})
    await asyncio.sleep(0.3)

    await bus.stop_listening()
    assert len(received_a) == 1
    assert received_a[0]["msg"] == "for_a"
    assert len(received_b) == 1
    assert received_b[0]["msg"] == "for_b"


@pytest.mark.asyncio
async def test_unsubscribe(bus):
    received = []

    async def handler(channel: str, data: dict):
        received.append(data)

    await bus.subscribe("test.unsub", handler)
    await bus.start_listening()
    await asyncio.sleep(0.1)

    await bus.publish("test.unsub", {"n": 1})
    await asyncio.sleep(0.2)

    await bus.unsubscribe("test.unsub")
    await bus.publish("test.unsub", {"n": 2})
    await asyncio.sleep(0.2)

    await bus.stop_listening()
    assert len(received) == 1
