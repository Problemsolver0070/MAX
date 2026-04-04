# tests/test_formatter.py
"""Tests for outbound message formatter."""

from __future__ import annotations

import uuid

from max.comm.formatter import OutboundFormatter
from max.comm.models import OutboundMessage, UrgencyLevel


class TestResultFormatting:
    def test_format_result(self):
        msg = OutboundFormatter.format_result(
            chat_id=100,
            goal_anchor="Build REST API",
            content="API endpoints implemented with full CRUD operations.",
            confidence=0.92,
            task_id=uuid.uuid4(),
        )
        assert isinstance(msg, OutboundMessage)
        assert msg.chat_id == 100
        assert "<b>Task Complete</b>" in msg.text
        assert "Build REST API" in msg.text
        assert "92%" in msg.text
        assert msg.urgency == UrgencyLevel.IMPORTANT
        assert msg.source_type == "result"

    def test_format_result_with_artifacts(self):
        msg = OutboundFormatter.format_result(
            chat_id=100,
            goal_anchor="Generate report",
            content="Report generated.",
            confidence=0.85,
            task_id=uuid.uuid4(),
            artifacts=["report.pdf", "summary.csv"],
        )
        assert "report.pdf" in msg.text
        assert "summary.csv" in msg.text


class TestStatusUpdateFormatting:
    def test_format_status_update(self):
        msg = OutboundFormatter.format_status_update(
            chat_id=100,
            goal_anchor="Build REST API",
            message="Schema design completed",
            progress=0.45,
            task_id=uuid.uuid4(),
        )
        assert "<b>Progress Update</b>" in msg.text
        assert "45%" in msg.text
        assert msg.source_type == "status_update"

    def test_progress_bar(self):
        msg = OutboundFormatter.format_status_update(
            chat_id=100,
            goal_anchor="Test",
            message="Running tests",
            progress=0.60,
            task_id=uuid.uuid4(),
        )
        assert "\u2588" in msg.text  # filled block
        assert "\u2591" in msg.text  # light block


class TestClarificationFormatting:
    def test_format_clarification_no_options(self):
        req_id = uuid.uuid4()
        msg = OutboundFormatter.format_clarification(
            chat_id=100,
            goal_anchor="Deploy app",
            question="Which environment?",
            request_id=req_id,
        )
        assert "<b>Clarification Needed</b>" in msg.text
        assert "Which environment?" in msg.text
        assert msg.inline_keyboard is None
        assert msg.source_type == "clarification"

    def test_format_clarification_with_options(self):
        req_id = uuid.uuid4()
        msg = OutboundFormatter.format_clarification(
            chat_id=100,
            goal_anchor="Deploy app",
            question="Which environment?",
            request_id=req_id,
            options=["staging", "production"],
        )
        assert msg.inline_keyboard is not None
        assert len(msg.inline_keyboard) == 1
        assert len(msg.inline_keyboard[0]) == 2
        assert msg.inline_keyboard[0][0].text == "staging"
        assert msg.inline_keyboard[0][0].callback_data == f"clarify:{req_id}:0"
        assert msg.inline_keyboard[0][1].callback_data == f"clarify:{req_id}:1"


class TestBatchFormatting:
    def test_format_batch_summary(self):
        items = [
            {"goal": "Build API", "message": "Progress: 45% → 60%"},
            {"goal": "Fix auth", "message": "Started planning phase"},
        ]
        msg = OutboundFormatter.format_batch_summary(chat_id=100, items=items)
        assert "<b>Updates</b> (2)" in msg.text
        assert "Build API" in msg.text
        assert "Fix auth" in msg.text
        assert msg.urgency == UrgencyLevel.SILENT

    def test_format_batch_empty(self):
        msg = OutboundFormatter.format_batch_summary(chat_id=100, items=[])
        assert msg is None


class TestErrorFormatting:
    def test_format_error(self):
        msg = OutboundFormatter.format_error(
            chat_id=100,
            description="Task failed: timeout exceeded",
        )
        assert "<b>System Alert</b>" in msg.text
        assert "timeout exceeded" in msg.text
        assert msg.urgency == UrgencyLevel.CRITICAL
