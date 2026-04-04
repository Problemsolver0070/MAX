"""Phase 3 communication models — all Pydantic models and enums."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ── Enums ────────────────────────────────────────────────────────────────────


class MessageType(StrEnum):
    TEXT = "text"
    PHOTO = "photo"
    DOCUMENT = "document"
    COMMAND = "command"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class UrgencyLevel(StrEnum):
    SILENT = "silent"
    NORMAL = "normal"
    IMPORTANT = "important"
    CRITICAL = "critical"


# ── Attachment ───────────────────────────────────────────────────────────────


class Attachment(BaseModel):
    file_id: str
    file_type: MessageType
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    local_path: str | None = None


# ── Inline Button ────────────────────────────────────────────────────────────


class InlineButton(BaseModel):
    text: str
    callback_data: str


# ── Inbound Message ──────────────────────────────────────────────────────────


class InboundMessage(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    platform: str
    platform_message_id: int
    platform_chat_id: int
    platform_user_id: int
    message_type: MessageType
    text: str | None = None
    command: str | None = None
    command_args: str | None = None
    attachments: list[Attachment] = Field(default_factory=list)
    reply_to_message_id: int | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ── Outbound Message ─────────────────────────────────────────────────────────


class OutboundMessage(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    platform: str = "telegram"
    chat_id: int
    text: str
    urgency: UrgencyLevel = UrgencyLevel.NORMAL
    reply_to_message_id: int | None = None
    attachments: list[Attachment] = Field(default_factory=list)
    inline_keyboard: list[list[InlineButton]] | None = None
    source_type: str = ""
    source_id: uuid.UUID | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ── Conversation Entry ───────────────────────────────────────────────────────


class ConversationEntry(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    direction: str
    platform: str
    platform_message_id: int | None = None
    message_type: MessageType
    content: str
    attachments_meta: list[dict[str, Any]] = Field(default_factory=list)
    intent_id: uuid.UUID | None = None
    source_type: str | None = None
    source_id: uuid.UUID | None = None
    urgency: UrgencyLevel | None = None
    delivery_status: DeliveryStatus = DeliveryStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ── Injection Scan Result ────────────────────────────────────────────────────


class InjectionScanResult(BaseModel):
    trust_score: float = Field(default=1.0, ge=0.0, le=1.0)
    patterns_found: list[str] = Field(default_factory=list)
    is_suspicious: bool = False
