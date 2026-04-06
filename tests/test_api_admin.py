"""Tests for admin endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from max.api.admin import router
from max.api.dependencies import AppState

AUTH = {"Authorization": "Bearer test-key"}


def _make_state(**overrides) -> AppState:
    defaults = {
        "settings": MagicMock(max_api_keys="test-key"),
        "db": MagicMock(),
        "redis_client": MagicMock(),
        "bus": AsyncMock(),
        "transport": None,
        "warm_memory": MagicMock(),
        "llm": MagicMock(),
        "circuit_breaker": MagicMock(),
        "task_store": MagicMock(),
        "quality_store": MagicMock(),
        "evolution_store": MagicMock(),
        "sentinel_store": MagicMock(),
        "state_manager": MagicMock(),
        "scheduler": MagicMock(),
        "tool_registry": MagicMock(),
        "tool_executor": MagicMock(),
        "agents": {},
        "start_time": 0.0,
    }
    defaults.update(overrides)
    return AppState(**defaults)


def _make_app(state: AppState) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.app_state = state
    return app


class TestEvolutionFreeze:
    async def test_freeze_publishes_to_bus(self):
        state = _make_state()
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/v1/admin/evolution/freeze", headers=AUTH)
        assert r.status_code == 200
        state.bus.publish.assert_called_once_with("evolution.freeze", {"source": "admin_api"})

    async def test_unfreeze_publishes_to_bus(self):
        state = _make_state()
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/v1/admin/evolution/unfreeze", headers=AUTH)
        assert r.status_code == 200
        state.bus.publish.assert_called_once_with("evolution.unfreeze", {"source": "admin_api"})


class TestSentinelRun:
    async def test_trigger_publishes_to_bus(self):
        state = _make_state()
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/v1/admin/sentinel/run", headers=AUTH)
        assert r.status_code == 200
        state.bus.publish.assert_called_once_with(
            "sentinel.run_request", {"source": "admin_api", "scheduled": False}
        )


class TestAdminAuth:
    async def test_freeze_requires_auth(self):
        app = _make_app(_make_state())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/v1/admin/evolution/freeze")
        assert r.status_code == 401

    async def test_sentinel_run_requires_auth(self):
        app = _make_app(_make_state())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/v1/admin/sentinel/run")
        assert r.status_code == 401

    async def test_invalid_key_returns_401(self):
        app = _make_app(_make_state())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/v1/admin/evolution/freeze",
                headers={"Authorization": "Bearer invalid"},
            )
        assert r.status_code == 401
