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

    # Extract message text (if present)
    message = body.get("message")
    if message is None:
        return {"ok": True}

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
