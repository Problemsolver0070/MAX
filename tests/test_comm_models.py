# tests/test_comm_models.py
"""Tests for Phase 3 communication models."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from max.comm.models import (
    Attachment,
    ConversationEntry,
    DeliveryStatus,
    InboundMessage,
    InjectionScanResult,
    InlineButton,
    MessageType,
    OutboundMessage,
    UrgencyLevel,
)


class TestEnums:
    def test_message_types(self):
        assert MessageType.TEXT == "text"
        assert MessageType.PHOTO == "photo"
        assert MessageType.DOCUMENT == "document"
        assert MessageType.COMMAND == "command"

    def test_delivery_status(self):
        assert DeliveryStatus.PENDING == "pending"
        assert DeliveryStatus.SENT == "sent"
        assert DeliveryStatus.FAILED == "failed"

    def test_urgency_levels(self):
        assert UrgencyLevel.SILENT == "silent"
        assert UrgencyLevel.NORMAL == "normal"
        assert UrgencyLevel.IMPORTANT == "important"
        assert UrgencyLevel.CRITICAL == "critical"


class TestAttachment:
    def test_create_photo(self):
        att = Attachment(file_id="abc123", file_type=MessageType.PHOTO)
        assert att.file_id == "abc123"
        assert att.file_type == MessageType.PHOTO
        assert att.file_name is None
        assert att.local_path is None

    def test_create_document(self):
        att = Attachment(
            file_id="doc456",
            file_type=MessageType.DOCUMENT,
            file_name="report.pdf",
            mime_type="application/pdf",
            file_size=1024,
        )
        assert att.file_name == "report.pdf"
        assert att.mime_type == "application/pdf"


class TestInboundMessage:
    def test_create_text_message(self):
        msg = InboundMessage(
            platform="telegram",
            platform_message_id=42,
            platform_chat_id=100,
            platform_user_id=200,
            message_type=MessageType.TEXT,
            text="Deploy the app",
        )
        assert msg.platform == "telegram"
        assert msg.text == "Deploy the app"
        assert msg.command is None
        assert msg.attachments == []
        assert isinstance(msg.id, uuid.UUID)

    def test_create_command_message(self):
        msg = InboundMessage(
            platform="telegram",
            platform_message_id=43,
            platform_chat_id=100,
            platform_user_id=200,
            message_type=MessageType.COMMAND,
            command="status",
            command_args="task-123",
        )
        assert msg.command == "status"
        assert msg.command_args == "task-123"

    def test_create_photo_message_with_attachment(self):
        att = Attachment(file_id="photo123", file_type=MessageType.PHOTO)
        msg = InboundMessage(
            platform="telegram",
            platform_message_id=44,
            platform_chat_id=100,
            platform_user_id=200,
            message_type=MessageType.PHOTO,
            text="Check this image",
            attachments=[att],
        )
        assert len(msg.attachments) == 1
        assert msg.attachments[0].file_id == "photo123"


class TestOutboundMessage:
    def test_create_text(self):
        msg = OutboundMessage(
            chat_id=100,
            text="<b>Hello</b>",
        )
        assert msg.chat_id == 100
        assert msg.text == "<b>Hello</b>"
        assert msg.urgency == UrgencyLevel.NORMAL
        assert msg.inline_keyboard is None
        assert msg.source_type == ""

    def test_create_with_keyboard(self):
        buttons = [
            [InlineButton(text="Yes", callback_data="confirm_yes")],
            [InlineButton(text="No", callback_data="confirm_no")],
        ]
        msg = OutboundMessage(
            chat_id=100,
            text="Confirm?",
            inline_keyboard=buttons,
        )
        assert len(msg.inline_keyboard) == 2
        assert msg.inline_keyboard[0][0].callback_data == "confirm_yes"


class TestInlineButton:
    def test_create(self):
        btn = InlineButton(text="Option A", callback_data="select_a")
        assert btn.text == "Option A"
        assert btn.callback_data == "select_a"


class TestConversationEntry:
    def test_create_inbound(self):
        entry = ConversationEntry(
            direction="inbound",
            platform="telegram",
            platform_message_id=42,
            message_type=MessageType.TEXT,
            content="Deploy the app",
        )
        assert entry.direction == "inbound"
        assert entry.delivery_status == DeliveryStatus.PENDING
        assert entry.intent_id is None

    def test_create_outbound(self):
        entry = ConversationEntry(
            direction="outbound",
            platform="telegram",
            platform_message_id=99,
            message_type=MessageType.TEXT,
            content="Task completed",
            source_type="result",
            source_id=uuid.uuid4(),
            urgency=UrgencyLevel.IMPORTANT,
            delivery_status=DeliveryStatus.SENT,
        )
        assert entry.source_type == "result"
        assert entry.urgency == UrgencyLevel.IMPORTANT


class TestInjectionScanResult:
    def test_default_trust_score(self):
        result = InjectionScanResult()
        assert result.trust_score == 1.0

    def test_patterns_found_defaults_empty(self):
        result = InjectionScanResult()
        assert result.patterns_found == []

    def test_is_suspicious_defaults_false(self):
        result = InjectionScanResult()
        assert result.is_suspicious is False

    def test_trust_score_zero(self):
        result = InjectionScanResult(trust_score=0.0)
        assert result.trust_score == 0.0

    def test_trust_score_mid(self):
        result = InjectionScanResult(trust_score=0.5)
        assert result.trust_score == 0.5

    def test_trust_score_rejects_above_one(self):
        with pytest.raises(ValidationError):
            InjectionScanResult(trust_score=1.1)

    def test_trust_score_rejects_below_zero(self):
        with pytest.raises(ValidationError):
            InjectionScanResult(trust_score=-0.1)
