# tests/test_router.py
"""Tests for MessageRouter — lifecycle, wiring, conversation persistence."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from max.comm.models import (
    InboundMessage,
    MessageType,
    OutboundMessage,
)
from max.comm.router import MessageRouter
from max.config import Settings
from max.db.postgres import Database


def _make_settings(monkeypatch) -> Settings:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:AAFakeTokenForTesting")
    monkeypatch.setenv("MAX_OWNER_TELEGRAM_ID", "200")
    return Settings()


class TestConversationPersistence:
    @pytest.mark.asyncio
    async def test_persist_inbound_message(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        db = AsyncMock(spec=Database)
        db.execute = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        llm = AsyncMock()
        warm = AsyncMock()

        router = MessageRouter(
            settings=settings,
            llm=llm,
            bus=bus,
            db=db,
            warm_memory=warm,
        )

        msg = InboundMessage(
            platform="telegram",
            platform_message_id=42,
            platform_chat_id=100,
            platform_user_id=200,
            message_type=MessageType.TEXT,
            content="Hello",
            text="Hello",
        )
        await router._persist_inbound(msg)
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_persist_outbound_message(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        db = AsyncMock(spec=Database)
        db.execute = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        llm = AsyncMock()
        warm = AsyncMock()

        router = MessageRouter(
            settings=settings,
            llm=llm,
            bus=bus,
            db=db,
            warm_memory=warm,
        )

        msg = OutboundMessage(
            chat_id=100,
            text="Task complete",
            source_type="result",
        )
        await router._persist_outbound(msg, platform_message_id=55)
        db.execute.assert_awaited_once()


class TestCallbackRouting:
    @pytest.mark.asyncio
    async def test_callback_query_published_to_bus(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        db = AsyncMock(spec=Database)
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        llm = AsyncMock()
        warm = AsyncMock()

        router = MessageRouter(
            settings=settings,
            llm=llm,
            bus=bus,
            db=db,
            warm_memory=warm,
        )

        req_id = uuid.uuid4()
        await router._handle_callback_query(f"clarify:{req_id}:1", 99)
        bus.publish.assert_awaited_once_with(
            "clarifications.response",
            {"request_id": str(req_id), "selected_option_index": 1, "message_id": 99},
        )
