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

    async def test_delegates_to_message_router_when_available(self):
        """When message_router is in agents, should call _on_inbound instead of bus.publish."""
        mock_router = AsyncMock()
        mock_router._on_inbound = AsyncMock()
        state = _make_state(agents={"message_router": mock_router})
        app = _make_app(state)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/webhook/telegram",
                json=TELEGRAM_UPDATE,
                headers={"X-Telegram-Bot-Api-Secret-Token": "my-secret"},
            )

        assert r.status_code == 200
        # MessageRouter._on_inbound should have been called
        mock_router._on_inbound.assert_called_once()
        inbound = mock_router._on_inbound.call_args[0][0]
        from max.comm.models import InboundMessage, MessageType

        assert isinstance(inbound, InboundMessage)
        assert inbound.platform == "telegram"
        assert inbound.text == "Hello from Telegram"
        assert inbound.platform_user_id == 999
        assert inbound.platform_chat_id == 999
        assert inbound.platform_message_id == 1
        assert inbound.message_type == MessageType.TEXT

        # bus.publish should NOT have been called (router handles it)
        state.bus.publish.assert_not_called()

    async def test_delegates_command_to_message_router(self):
        """Commands (starting with /) should be parsed and delegated to MessageRouter."""
        mock_router = AsyncMock()
        mock_router._on_inbound = AsyncMock()
        state = _make_state(agents={"message_router": mock_router})
        app = _make_app(state)

        command_update = {
            "update_id": 123456,
            "message": {
                "message_id": 2,
                "from": {"id": 999, "is_bot": False, "first_name": "Test"},
                "chat": {"id": 999, "type": "private"},
                "date": 1700000000,
                "text": "/status check everything",
            },
        }

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/webhook/telegram",
                json=command_update,
                headers={"X-Telegram-Bot-Api-Secret-Token": "my-secret"},
            )

        assert r.status_code == 200
        mock_router._on_inbound.assert_called_once()
        inbound = mock_router._on_inbound.call_args[0][0]
        from max.comm.models import MessageType

        assert inbound.message_type == MessageType.COMMAND
        assert inbound.command == "status"
        assert inbound.command_args == "check everything"

    async def test_falls_back_to_bus_publish_without_router(self):
        """Without message_router in agents, should fall back to bus.publish."""
        state = _make_state(agents={})  # explicitly empty agents
        app = _make_app(state)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/webhook/telegram",
                json=TELEGRAM_UPDATE,
                headers={"X-Telegram-Bot-Api-Secret-Token": "my-secret"},
            )

        assert r.status_code == 200
        state.bus.publish.assert_called_once()
        call_data = state.bus.publish.call_args[0][1]
        assert call_data["user_message"] == "Hello from Telegram"
        assert call_data["source_platform"] == "telegram"
