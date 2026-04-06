"""Tests for health and readiness endpoints."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from max.api.dependencies import AppState
from max.api.health import router


def _make_state(**overrides) -> AppState:
    defaults = {
        "settings": MagicMock(),
        "db": AsyncMock(),
        "redis_client": AsyncMock(),
        "bus": MagicMock(_running=True),
        "transport": None,
        "warm_memory": MagicMock(),
        "llm": MagicMock(),
        "circuit_breaker": MagicMock(state=MagicMock(value="closed")),
        "task_store": MagicMock(),
        "quality_store": MagicMock(),
        "evolution_store": MagicMock(),
        "sentinel_store": MagicMock(),
        "state_manager": MagicMock(),
        "scheduler": MagicMock(),
        "tool_registry": MagicMock(),
        "tool_executor": MagicMock(),
        "agents": {"coordinator": MagicMock(), "planner": MagicMock()},
        "start_time": time.time() - 100,
    }
    defaults.update(overrides)
    return AppState(**defaults)


def _make_app(state: AppState) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.app_state = state
    return app


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_returns_200_when_healthy(self):
        state = _make_state()
        state.db.fetchone = AsyncMock(return_value={"?column?": 1})
        state.redis_client.ping = AsyncMock(return_value=True)
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["uptime_seconds"] >= 100

    @pytest.mark.asyncio
    async def test_includes_agent_statuses(self):
        state = _make_state()
        state.db.fetchone = AsyncMock(return_value={"?column?": 1})
        state.redis_client.ping = AsyncMock(return_value=True)
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/health")
        agents = r.json()["agents"]
        assert "coordinator" in agents
        assert "planner" in agents

    @pytest.mark.asyncio
    async def test_shows_db_disconnected(self):
        state = _make_state()
        state.db.fetchone = AsyncMock(side_effect=Exception("down"))
        state.redis_client.ping = AsyncMock(return_value=True)
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/health")
        assert r.json()["infrastructure"]["database"] == "disconnected"

    @pytest.mark.asyncio
    async def test_shows_circuit_breaker_state(self):
        state = _make_state(circuit_breaker=MagicMock(state=MagicMock(value="open")))
        state.db.fetchone = AsyncMock(return_value={"?column?": 1})
        state.redis_client.ping = AsyncMock(return_value=True)
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/health")
        assert r.json()["infrastructure"]["circuit_breaker"] == "open"


class TestReadyEndpoint:
    @pytest.mark.asyncio
    async def test_ready_when_all_ok(self):
        state = _make_state()
        state.db.fetchone = AsyncMock(return_value={"?column?": 1})
        state.redis_client.ping = AsyncMock(return_value=True)
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/ready")
        assert r.status_code == 200
        assert r.json()["ready"] is True

    @pytest.mark.asyncio
    async def test_not_ready_when_db_down(self):
        state = _make_state()
        state.db.fetchone = AsyncMock(side_effect=Exception("down"))
        state.redis_client.ping = AsyncMock(return_value=True)
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/ready")
        assert r.status_code == 503
        assert r.json()["ready"] is False

    @pytest.mark.asyncio
    async def test_not_ready_when_redis_down(self):
        state = _make_state()
        state.db.fetchone = AsyncMock(return_value={"?column?": 1})
        state.redis_client.ping = AsyncMock(side_effect=Exception("down"))
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/ready")
        assert r.status_code == 503
        assert r.json()["checks"]["redis"] == "failed"

    @pytest.mark.asyncio
    async def test_no_auth_required(self):
        state = _make_state()
        state.db.fetchone = AsyncMock(return_value={"?column?": 1})
        state.redis_client.ping = AsyncMock(return_value=True)
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/health")
        # No auth header, should still work
        assert r.status_code == 200
