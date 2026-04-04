# src/max/comm/telegram_adapter.py
"""Telegram adapter — aiogram bot, auth middleware, message normalization, sending."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import (
    CallbackQuery,
    Document,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from max.comm.models import (
    Attachment,
    InboundMessage,
    InlineButton,
    MessageType,
    OutboundMessage,
)

logger = logging.getLogger(__name__)


class OwnerOnlyMiddleware(BaseMiddleware):
    """Drops all updates from non-owner users. Silent — no response."""

    def __init__(self, owner_telegram_id: int) -> None:
        self._owner_id = owner_telegram_id

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or user.id != self._owner_id:
            user_id = user.id if user else "unknown"
            logger.warning("Blocked message from unauthorized user: %s", user_id)
            return None
        return await handler(event, data)


class TelegramAdapter:
    """Pure I/O layer — receives Telegram updates, sends outbound messages."""

    def __init__(
        self,
        bot_token: str,
        owner_telegram_id: int,
        on_message: Callable[[InboundMessage], Awaitable[None]],
        on_callback_query: Callable[[str, int], Awaitable[None]],
    ) -> None:
        self._on_message = on_message
        self._on_callback_query = on_callback_query
        self._bot = Bot(
            token=bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self._dp = Dispatcher()
        self._router = Router(name="comm")

        # Auth middleware
        auth = OwnerOnlyMiddleware(owner_telegram_id)
        self._router.message.middleware(auth)
        self._router.callback_query.middleware(auth)

        # Register handlers
        self._router.message.register(self._handle_message)
        self._router.callback_query.register(self._handle_callback)

        self._dp.include_router(self._router)

    async def start_polling(self) -> None:
        """Start receiving updates via long polling."""
        logger.info("Starting Telegram polling...")
        await self._dp.start_polling(self._bot)

    async def start_webhook(self, host: str, port: int, path: str, secret: str) -> None:
        """Start receiving updates via webhook."""
        await self._bot.set_webhook(
            url=f"https://{host}{path}",
            secret_token=secret,
        )
        logger.info("Webhook set: %s%s", host, path)

    async def stop(self) -> None:
        """Stop the adapter and close the bot session."""
        await self._dp.stop_polling()
        await self._bot.session.close()
        logger.info("Telegram adapter stopped")

    async def send(self, message: OutboundMessage) -> int | None:
        """Send an outbound message. Returns the platform message_id."""
        try:
            reply_markup = self._build_keyboard(message.inline_keyboard)

            if message.attachments:
                att = message.attachments[0]
                if att.file_type == MessageType.PHOTO:
                    source = att.local_path or att.file_id
                    sent = await self._bot.send_photo(
                        chat_id=message.chat_id,
                        photo=source,
                        caption=message.text,
                        reply_to_message_id=message.reply_to_message_id,
                        reply_markup=reply_markup,
                    )
                elif att.file_type == MessageType.DOCUMENT:
                    source = att.local_path or att.file_id
                    sent = await self._bot.send_document(
                        chat_id=message.chat_id,
                        document=source,
                        caption=message.text,
                        reply_to_message_id=message.reply_to_message_id,
                        reply_markup=reply_markup,
                    )
                else:
                    sent = await self._bot.send_message(
                        chat_id=message.chat_id,
                        text=message.text,
                        reply_to_message_id=message.reply_to_message_id,
                        reply_markup=reply_markup,
                    )
            else:
                sent = await self._bot.send_message(
                    chat_id=message.chat_id,
                    text=message.text,
                    reply_to_message_id=message.reply_to_message_id,
                    reply_markup=reply_markup,
                )
            return sent.message_id
        except TelegramRetryAfter as exc:
            logger.warning("Rate limited, retrying in %ds", exc.retry_after)
            await asyncio.sleep(exc.retry_after)
            return await self.send(message)
        except TelegramForbiddenError:
            logger.warning("Bot blocked by user (chat_id=%d)", message.chat_id)
            return None

    async def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        keyboard: list[list[InlineButton]] | None = None,
    ) -> None:
        """Edit an existing message."""
        reply_markup = self._build_keyboard(keyboard)
        try:
            await self._bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
            )
        except Exception:
            logger.exception("Failed to edit message %d in chat %d", message_id, chat_id)

    async def download_file(self, file_id: str, destination: Path) -> Path:
        """Download a file from Telegram servers."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        await self._bot.download(file_id, destination=destination)
        return destination

    # -- Internal handlers ---------------------------------------------------------

    async def _handle_message(self, message: Message) -> None:
        normalized = self.normalize_message(message)
        await self._on_message(normalized)

    async def _handle_callback(self, query: CallbackQuery) -> None:
        await query.answer()
        if query.data and query.message:
            await self._on_callback_query(query.data, query.message.message_id)

    # -- Normalization -------------------------------------------------------------

    @staticmethod
    def normalize_message(message: Message) -> InboundMessage:
        """Convert an aiogram Message to an InboundMessage."""
        msg_type = MessageType.TEXT
        text = message.text
        command = None
        command_args = None
        attachments: list[Attachment] = []

        # Commands
        if text and text.startswith("/"):
            msg_type = MessageType.COMMAND
            parts = text[1:].split(None, 1)
            command = parts[0].lower() if parts else ""
            command_args = parts[1] if len(parts) > 1 else None

        # Photos
        elif message.photo:
            msg_type = MessageType.PHOTO
            text = message.caption
            best = message.photo[-1]
            attachments.append(
                Attachment(
                    file_id=best.file_id,
                    file_type=MessageType.PHOTO,
                    file_size=best.file_size,
                )
            )

        # Documents
        elif message.document:
            msg_type = MessageType.DOCUMENT
            text = message.caption
            doc: Document = message.document
            attachments.append(
                Attachment(
                    file_id=doc.file_id,
                    file_type=MessageType.DOCUMENT,
                    file_name=doc.file_name,
                    mime_type=doc.mime_type,
                    file_size=doc.file_size,
                )
            )

        return InboundMessage(
            platform="telegram",
            platform_message_id=message.message_id,
            platform_chat_id=message.chat.id,
            platform_user_id=message.from_user.id if message.from_user else 0,
            message_type=msg_type,
            text=text,
            command=command,
            command_args=command_args,
            attachments=attachments,
            reply_to_message_id=(
                message.reply_to_message.message_id if message.reply_to_message else None
            ),
        )

    @staticmethod
    def _build_keyboard(
        buttons: list[list[InlineButton]] | None,
    ) -> InlineKeyboardMarkup | None:
        if not buttons:
            return None
        rows = [
            [InlineKeyboardButton(text=b.text, callback_data=b.callback_data) for b in row]
            for row in buttons
        ]
        return InlineKeyboardMarkup(inline_keyboard=rows)
