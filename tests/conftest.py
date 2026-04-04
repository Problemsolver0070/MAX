import pytest
import redis.asyncio as aioredis

from max.bus.message_bus import MessageBus
from max.config import Settings
from max.db.postgres import Database
from max.db.redis_store import WarmMemory


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("POSTGRES_PASSWORD", "max_dev_password")
    return Settings()


@pytest.fixture
async def db(settings):
    database = Database(dsn=settings.postgres_dsn)
    await database.connect()
    await database.init_schema()
    yield database
    await database.close()


@pytest.fixture
async def redis_client():
    client = aioredis.from_url("redis://localhost:6379/15")
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def warm_memory(redis_client):
    return WarmMemory(redis_client)


@pytest.fixture
async def bus(redis_client):
    b = MessageBus(redis_client)
    yield b
    await b.close()
