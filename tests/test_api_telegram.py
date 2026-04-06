"""Tests for Telegram webhook endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from max.api.dependencies import AppState
from max.api.telegram import router


def _make_state(**overrides) -> AppState:
    defaults = {
        "settings": MagicMock(comm_webhook_secret="my-secret"),
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


TELEGRAM_UPDATE = {
    "update_id": 123456,
    "message": {
        "message_id": 1,
        "from": {"id": 999, "is_bot": False, "first_name": "Test"},
        "chat": {"id": 999, "type": "private"},
        "date": 1700000000,
        "text": "Hello from Telegram",
    },
}


class TestTelegramWebhook:
    async def test_valid_secret_returns_200(self):
        state = _make_state()
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/webhook/telegram",
                json=TELEGRAM_UPDATE,
                headers={"X-Telegram-Bot-Api-Secret-Token": "my-secret"},
            )
        assert r.status_code == 200

    async def test_invalid_secret_returns_401(self):
        state = _make_state()
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/webhook/telegram",
                json=TELEGRAM_UPDATE,
                headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
            )
        assert r.status_code == 401

    async def test_missing_secret_returns_401(self):
        state = _make_state()
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/webhook/telegram", json=TELEGRAM_UPDATE)
        assert r.status_code == 401

    async def test_publishes_intent_for_text_message(self):
        state = _make_state()
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.post(
                "/webhook/telegram",
                json=TELEGRAM_UPDATE,
                headers={"X-Telegram-Bot-Api-Secret-Token": "my-secret"},
            )
        state.bus.publish.assert_called_once()
        call_data = state.bus.publish.call_args[0][1]
        assert call_data["user_message"] == "Hello from Telegram"
        assert call_data["source_platform"] == "telegram"

    async def test_ignores_non_message_updates(self):
        state = _make_state()
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/webhook/telegram",
                json={"update_id": 999},  # no message field
                headers={"X-Telegram-Bot-Api-Secret-Token": "my-secret"},
            )
        assert r.status_code == 200
        state.bus.publish.assert_not_called()
