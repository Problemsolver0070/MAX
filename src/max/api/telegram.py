"""Telegram webhook endpoint — verified by secret token header."""

from __future__ import annotations

import hmac
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from max.api.dependencies import AppState, get_app_state

router = APIRouter(tags=["telegram"])


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request) -> dict:
    """Receive a Telegram update via webhook.

    Validates the X-Telegram-Bot-Api-Secret-Token header, extracts
    the message text, and publishes an intent to the bus.
    """
    state: AppState = get_app_state(request)

    # Verify secret token
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    expected = state.settings.comm_webhook_secret
    if not expected or not hmac.compare_digest(secret, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    body: dict[str, Any] = await request.json()

    message = body.get("message")
    if message is None:
        return {"ok": True}

    # Delegate to MessageRouter when available (full pipeline)
    message_router = state.agents.get("message_router")
    if message_router is not None:
        from max.comm.models import InboundMessage, MessageType

        text = message.get("text", "")
        from_user = message.get("from", {})
        user_id = from_user.get("id", 0)
        chat_id = message.get("chat", {}).get("id", 0)

        msg_type = MessageType.COMMAND if text and text.startswith("/") else MessageType.TEXT
        command = None
        command_args = None
        if msg_type == MessageType.COMMAND:
            parts = text[1:].split(None, 1)
            command = parts[0].lower() if parts else ""
            command_args = parts[1] if len(parts) > 1 else None

        inbound = InboundMessage(
            platform="telegram",
            platform_message_id=message.get("message_id", 0),
            platform_chat_id=chat_id,
            platform_user_id=user_id,
            message_type=msg_type,
            text=text,
            command=command,
            command_args=command_args,
        )
        await message_router._on_inbound(inbound)
        return {"ok": True}

    # Fallback: raw intent publishing (no MessageRouter)
    text = message.get("text", "")
    from_user = message.get("from", {})
    user_id = str(from_user.get("id", "unknown"))

    await state.bus.publish(
        "intents.new",
        {
            "id": str(uuid.uuid4()),
            "user_message": text,
            "source_platform": "telegram",
            "goal_anchor": text,
            "priority": "normal",
            "attachments": [],
            "user_id": user_id,
        },
    )

    return {"ok": True}
