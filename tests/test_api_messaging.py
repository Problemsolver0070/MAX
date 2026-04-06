"""Tests for messaging endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from max.api.dependencies import AppState
from max.api.messaging import router

AUTH = {"Authorization": "Bearer test-key"}


def _make_state(**overrides) -> AppState:
    defaults = {
        "settings": MagicMock(max_api_keys="test-key"),
        "db": MagicMock(),
        "redis_client": MagicMock(),
        "bus": AsyncMock(),
        "transport": None,
        "warm_memory": AsyncMock(),
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


class TestSendMessage:
    async def test_publishes_intent_to_bus(self):
        state = _make_state()
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/v1/messages",
                json={"text": "Hello Max", "user_id": "user-1"},
                headers=AUTH,
            )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "accepted"
        assert "message_id" in body
        state.bus.publish.assert_called_once()
        call_args = state.bus.publish.call_args
        assert call_args[0][0] == "intents.new"
        assert call_args[0][1]["user_message"] == "Hello Max"
        assert call_args[0][1]["source_platform"] == "api"

    async def test_returns_401_without_auth(self):
        app = _make_app(_make_state())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/v1/messages", json={"text": "hi", "user_id": "u1"})
        assert r.status_code == 401

    async def test_returns_422_missing_text(self):
        app = _make_app(_make_state())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/v1/messages", json={"user_id": "u1"}, headers=AUTH)
        assert r.status_code == 422


class TestGetMessages:
    async def test_returns_pending_responses(self):
        state = _make_state()
        state.warm_memory.list_range = AsyncMock(
            return_value=[{"text": "Hello!", "timestamp": "2026-01-01T00:00:00"}]
        )
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/messages?user_id=user-1", headers=AUTH)
        assert r.status_code == 200
        assert len(r.json()["messages"]) == 1

    async def test_returns_empty_when_no_responses(self):
        state = _make_state()
        state.warm_memory.list_range = AsyncMock(return_value=[])
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/messages?user_id=user-1", headers=AUTH)
        assert r.json()["messages"] == []

    async def test_clears_after_read(self):
        state = _make_state()
        state.warm_memory.list_range = AsyncMock(return_value=[{"text": "hi"}])
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.get("/api/v1/messages?user_id=user-1", headers=AUTH)
        state.warm_memory.delete.assert_called_once()


class TestRegisterWebhook:
    async def test_stores_webhook_url(self):
        state = _make_state()
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/v1/messages/webhook",
                json={"url": "https://example.com/hook", "user_id": "u1"},
                headers=AUTH,
            )
        assert r.status_code == 200
        state.warm_memory.set.assert_called_once()
