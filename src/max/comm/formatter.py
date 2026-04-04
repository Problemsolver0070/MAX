# src/max/comm/formatter.py
"""Outbound message formatter — domain objects to rich HTML messages."""

from __future__ import annotations

import uuid

from max.comm.models import InlineButton, OutboundMessage, UrgencyLevel


class OutboundFormatter:
    """Converts domain objects into rich OutboundMessage instances."""

    @staticmethod
    def format_result(
        chat_id: int,
        goal_anchor: str,
        content: str,
        confidence: float,
        task_id: uuid.UUID,
        artifacts: list[str] | None = None,
    ) -> OutboundMessage:
        lines = [
            "\u2705 <b>Task Complete</b>",
            f"<b>Goal:</b> {goal_anchor}",
            f"<b>Confidence:</b> {confidence:.0%}",
            "",
            content,
        ]
        if artifacts:
            lines.append("")
            lines.append("<b>Artifacts:</b>")
            for artifact in artifacts:
                lines.append(f"\u2022 {artifact}")

        return OutboundMessage(
            chat_id=chat_id,
            text="\n".join(lines),
            urgency=UrgencyLevel.IMPORTANT,
            source_type="result",
            source_id=task_id,
        )

    @staticmethod
    def format_status_update(
        chat_id: int,
        goal_anchor: str,
        message: str,
        progress: float,
        task_id: uuid.UUID,
    ) -> OutboundMessage:
        filled = int(progress * 10)
        empty = 10 - filled
        bar = "\u2588" * filled + "\u2591" * empty

        lines = [
            "\U0001f4ca <b>Progress Update</b>",
            f"<b>Task:</b> {goal_anchor}",
            f"<b>Progress:</b> {bar} {progress:.0%}",
            "",
            message,
        ]
        return OutboundMessage(
            chat_id=chat_id,
            text="\n".join(lines),
            urgency=UrgencyLevel.SILENT,
            source_type="status_update",
            source_id=task_id,
        )

    @staticmethod
    def format_clarification(
        chat_id: int,
        goal_anchor: str,
        question: str,
        request_id: uuid.UUID,
        options: list[str] | None = None,
    ) -> OutboundMessage:
        lines = [
            "\u2753 <b>Clarification Needed</b>",
            f"<b>Task:</b> {goal_anchor}",
            "",
            question,
        ]
        keyboard = None
        if options:
            row = [
                InlineButton(text=opt, callback_data=f"clarify:{request_id}:{i}")
                for i, opt in enumerate(options)
            ]
            keyboard = [row]

        return OutboundMessage(
            chat_id=chat_id,
            text="\n".join(lines),
            urgency=UrgencyLevel.IMPORTANT,
            source_type="clarification",
            source_id=request_id,
            inline_keyboard=keyboard,
        )

    @staticmethod
    def format_batch_summary(
        chat_id: int,
        items: list[dict[str, str]],
    ) -> OutboundMessage | None:
        if not items:
            return None
        lines = [f"\U0001f4cb <b>Updates</b> ({len(items)}):"]
        for item in items:
            lines.append(f"\u2022 [Task: {item['goal']}] {item['message']}")

        return OutboundMessage(
            chat_id=chat_id,
            text="\n".join(lines),
            urgency=UrgencyLevel.SILENT,
            source_type="system",
        )

    @staticmethod
    def format_error(
        chat_id: int,
        description: str,
    ) -> OutboundMessage:
        lines = [
            "\u26a0\ufe0f <b>System Alert</b>",
            "",
            description,
        ]
        return OutboundMessage(
            chat_id=chat_id,
            text="\n".join(lines),
            urgency=UrgencyLevel.CRITICAL,
            source_type="system",
        )
