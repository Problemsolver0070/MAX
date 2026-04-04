# tests/test_telegram_adapter.py
"""Tests for Telegram adapter — normalization, auth middleware, sending."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from max.comm.models import (
    InboundMessage,
    InlineButton,
    MessageType,
    OutboundMessage,
)
from max.comm.telegram_adapter import OwnerOnlyMiddleware, TelegramAdapter


def _make_tg_message(
    text: str | None = None,
    message_id: int = 1,
    chat_id: int = 100,
    user_id: int = 200,
    photo: list | None = None,
    document: MagicMock | None = None,
    caption: str | None = None,
    reply_to_message: MagicMock | None = None,
) -> MagicMock:
    """Create a mock aiogram Message."""
    msg = MagicMock()
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.text = text
    msg.caption = caption
    msg.photo = photo
    msg.document = document
    msg.reply_to_message = reply_to_message
    return msg


class TestMessageNormalization:
    def test_normalize_text_message(self):
        tg_msg = _make_tg_message(text="Deploy the app")
        result = TelegramAdapter.normalize_message(tg_msg)
        assert isinstance(result, InboundMessage)
        assert result.platform == "telegram"
        assert result.platform_message_id == 1
        assert result.platform_chat_id == 100
        assert result.platform_user_id == 200
        assert result.message_type == MessageType.TEXT
        assert result.text == "Deploy the app"
        assert result.attachments == []

    def test_normalize_photo_message(self):
        photo_small = MagicMock()
        photo_small.file_id = "small_id"
        photo_large = MagicMock()
        photo_large.file_id = "large_id"
        photo_large.file_size = 50000
        tg_msg = _make_tg_message(photo=[photo_small, photo_large], caption="A screenshot")
        tg_msg.text = None
        result = TelegramAdapter.normalize_message(tg_msg)
        assert result.message_type == MessageType.PHOTO
        assert result.text == "A screenshot"
        assert len(result.attachments) == 1
        assert result.attachments[0].file_id == "large_id"
        assert result.attachments[0].file_type == MessageType.PHOTO

    def test_normalize_document_message(self):
        doc = MagicMock()
        doc.file_id = "doc_id"
        doc.file_name = "report.pdf"
        doc.mime_type = "application/pdf"
        doc.file_size = 12345
        tg_msg = _make_tg_message(document=doc, caption="Quarterly report")
        tg_msg.text = None
        tg_msg.photo = None
        result = TelegramAdapter.normalize_message(tg_msg)
        assert result.message_type == MessageType.DOCUMENT
        assert result.text == "Quarterly report"
        assert result.attachments[0].file_name == "report.pdf"
        assert result.attachments[0].mime_type == "application/pdf"

    def test_normalize_command(self):
        tg_msg = _make_tg_message(text="/status task-123")
        result = TelegramAdapter.normalize_message(tg_msg)
        assert result.message_type == MessageType.COMMAND
        assert result.command == "status"
        assert result.command_args == "task-123"

    def test_normalize_command_no_args(self):
        tg_msg = _make_tg_message(text="/help")
        result = TelegramAdapter.normalize_message(tg_msg)
        assert result.command == "help"
        assert result.command_args is None

    def test_normalize_reply(self):
        reply_msg = MagicMock()
        reply_msg.message_id = 99
        tg_msg = _make_tg_message(text="Yes", reply_to_message=reply_msg)
        result = TelegramAdapter.normalize_message(tg_msg)
        assert result.reply_to_message_id == 99


class TestOwnerOnlyMiddleware:
    @pytest.mark.asyncio
    async def test_allows_owner(self):
        middleware = OwnerOnlyMiddleware(owner_telegram_id=200)
        handler = AsyncMock(return_value="ok")
        event = MagicMock()
        user = MagicMock()
        user.id = 200
        data = {"event_from_user": user}
        result = await middleware(handler, event, data)
        handler.assert_awaited_once()
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_blocks_non_owner(self):
        middleware = OwnerOnlyMiddleware(owner_telegram_id=200)
        handler = AsyncMock()
        event = MagicMock()
        user = MagicMock()
        user.id = 999
        data = {"event_from_user": user}
        result = await middleware(handler, event, data)
        handler.assert_not_awaited()
        assert result is None

    @pytest.mark.asyncio
    async def test_blocks_no_user(self):
        middleware = OwnerOnlyMiddleware(owner_telegram_id=200)
        handler = AsyncMock()
        event = MagicMock()
        data = {}
        await middleware(handler, event, data)
        handler.assert_not_awaited()


class TestSending:
    @pytest.mark.asyncio
    async def test_send_text_message(self):
        on_msg = AsyncMock()
        on_cb = AsyncMock()
        adapter = TelegramAdapter(
            bot_token="123456789:AAFakeTokenForTestingPurposes",
            owner_telegram_id=200,
            on_message=on_msg,
            on_callback_query=on_cb,
        )
        adapter._bot = AsyncMock()
        sent_msg = MagicMock()
        sent_msg.message_id = 55
        adapter._bot.send_message = AsyncMock(return_value=sent_msg)

        out_msg = OutboundMessage(chat_id=100, text="Hello <b>world</b>")
        result = await adapter.send(out_msg)
        assert result == 55
        adapter._bot.send_message.assert_awaited_once()
        call_kwargs = adapter._bot.send_message.call_args
        assert call_kwargs[1]["chat_id"] == 100

    @pytest.mark.asyncio
    async def test_send_with_keyboard(self):
        on_msg = AsyncMock()
        on_cb = AsyncMock()
        adapter = TelegramAdapter(
            bot_token="123456789:AAFakeTokenForTestingPurposes",
            owner_telegram_id=200,
            on_message=on_msg,
            on_callback_query=on_cb,
        )
        adapter._bot = AsyncMock()
        sent_msg = MagicMock()
        sent_msg.message_id = 56
        adapter._bot.send_message = AsyncMock(return_value=sent_msg)

        buttons = [[InlineButton(text="Yes", callback_data="y")]]
        out_msg = OutboundMessage(chat_id=100, text="Confirm?", inline_keyboard=buttons)
        await adapter.send(out_msg)
        call_kwargs = adapter._bot.send_message.call_args
        assert call_kwargs[1].get("reply_markup") is not None
