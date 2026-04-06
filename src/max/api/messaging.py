"""Messaging endpoints — send messages to Max and poll for responses."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from max.api.auth import verify_api_key
from max.api.dependencies import AppState, get_app_state

router = APIRouter(prefix="/api/v1", tags=["messaging"])


class MessageRequest(BaseModel):
    """Inbound message from an API client."""

    text: str
    user_id: str


class WebhookRegistration(BaseModel):
    """Webhook URL registration for push delivery."""

    url: str
    user_id: str


@router.post("/messages")
async def send_message(
    body: MessageRequest,
    app_state: AppState = Depends(get_app_state),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """Accept a message and publish it to the agent pipeline."""
    message_id = str(uuid.uuid4())

    await app_state.bus.publish(
        "intents.new",
        {
            "id": message_id,
            "user_message": body.text,
            "source_platform": "api",
            "goal_anchor": body.text,
            "priority": "normal",
            "attachments": [],
            "user_id": body.user_id,
        },
    )

    return {"message_id": message_id, "status": "accepted"}


@router.get("/messages")
async def get_messages(
    user_id: str,
    app_state: AppState = Depends(get_app_state),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """Poll for pending responses for a user."""
    key = f"api_responses:{user_id}"
    responses = await app_state.warm_memory.list_range(key, 0, -1)

    if responses:
        await app_state.warm_memory.delete(key)

    return {"messages": responses}


@router.post("/messages/webhook")
async def register_webhook(
    body: WebhookRegistration,
    app_state: AppState = Depends(get_app_state),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """Register a webhook URL for push delivery of responses."""
    await app_state.warm_memory.set(
        f"api_webhook:{body.user_id}",
        {"url": body.url, "user_id": body.user_id},
    )
    return {"status": "registered", "user_id": body.user_id}
