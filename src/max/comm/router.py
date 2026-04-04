# src/max/comm/router.py
"""MessageRouter — glue layer connecting TelegramAdapter and CommunicatorAgent."""

from __future__ import annotations

import json
import logging

from max.agents.base import AgentConfig
from max.bus.message_bus import MessageBus
from max.comm.communicator import CommunicatorAgent
from max.comm.models import (
    DeliveryStatus,
    InboundMessage,
    MessageType,
    OutboundMessage,
)
from max.comm.telegram_adapter import TelegramAdapter
from max.config import Settings
from max.db.postgres import Database
from max.db.redis_store import WarmMemory
from max.llm.client import LLMClient
from max.llm.models import ModelType

logger = logging.getLogger(__name__)


class MessageRouter:
    """Connects TelegramAdapter <-> CommunicatorAgent, manages lifecycle and persistence."""

    def __init__(
        self,
        settings: Settings,
        llm: LLMClient,
        bus: MessageBus,
        db: Database,
        warm_memory: WarmMemory,
    ) -> None:
        self._settings = settings
        self._db = db
        self._bus = bus

        owner_id = int(settings.max_owner_telegram_id) if settings.max_owner_telegram_id else 0

        # Create adapter
        self._adapter = TelegramAdapter(
            bot_token=settings.telegram_bot_token,
            owner_telegram_id=owner_id,
            on_message=self._on_inbound,
            on_callback_query=self._handle_callback_query,
        )

        # Create communicator
        config = AgentConfig(
            name="communicator",
            system_prompt="You are the Communicator for Max.",
            model=ModelType.OPUS,
            max_turns=10000,
        )
        self._communicator = CommunicatorAgent(
            config=config,
            llm=llm,
            bus=bus,
            db=db,
            warm_memory=warm_memory,
            settings=settings,
        )
        self._communicator.set_send_callback(self._on_outbound)

    async def start(self) -> None:
        """Start the communicator and adapter."""
        await self._communicator.start()
        if self._settings.comm_webhook_enabled:
            await self._adapter.start_webhook(
                webhook_url=self._settings.comm_webhook_url,
                host=self._settings.comm_webhook_host,
                port=self._settings.comm_webhook_port,
                path=self._settings.comm_webhook_path,
                secret=self._settings.comm_webhook_secret,
            )
        else:
            await self._adapter.start_polling()

    async def stop(self) -> None:
        """Stop adapter and communicator."""
        await self._adapter.stop()
        await self._communicator.stop()

    # ── Internal wiring ──────────────────────────────────────────────

    async def _on_inbound(self, message: InboundMessage) -> None:
        """Route inbound message from adapter to communicator."""
        await self._persist_inbound(message)

        if message.message_type == MessageType.COMMAND:
            result = await self._communicator.handle_command(message)
            if result is not None:
                await self._on_outbound(result)
            else:
                await self._communicator.handle_inbound(message)
        else:
            await self._communicator.handle_inbound(message)

    async def _on_outbound(self, message: OutboundMessage) -> None:
        """Route outbound message from communicator to adapter."""
        platform_msg_id = await self._adapter.send(message)
        await self._persist_outbound(message, platform_msg_id)

    async def _handle_callback_query(self, callback_data: str, message_id: int) -> None:
        """Route inline keyboard callbacks."""
        if callback_data.startswith("clarify:"):
            parts = callback_data.split(":")
            if len(parts) == 3:
                request_id = parts[1]
                option_index = int(parts[2])
                await self._bus.publish(
                    "clarifications.response",
                    {
                        "request_id": request_id,
                        "selected_option_index": option_index,
                        "message_id": message_id,
                    },
                )
            return
        logger.warning("Unknown callback data: %s", callback_data)

    # ── Persistence ──────────────────────────────────────────────────

    async def _persist_inbound(self, message: InboundMessage) -> None:
        try:
            attachments_meta = [a.model_dump(mode="json") for a in message.attachments]
            await self._db.execute(
                "INSERT INTO conversation_messages "
                "(id, direction, platform, platform_message_id, message_type, content, "
                "attachments_meta, delivery_status) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)",
                message.id,
                "inbound",
                message.platform,
                message.platform_message_id,
                message.message_type.value,
                message.text or "",
                json.dumps(attachments_meta),
                "sent",
            )
        except Exception:
            logger.exception("Failed to persist inbound message")

    async def _persist_outbound(
        self, message: OutboundMessage, platform_message_id: int | None
    ) -> None:
        status = DeliveryStatus.SENT if platform_message_id else DeliveryStatus.FAILED
        try:
            await self._db.execute(
                "INSERT INTO conversation_messages "
                "(id, direction, platform, platform_message_id, message_type, content, "
                "source_type, source_id, urgency, delivery_status) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
                message.id,
                "outbound",
                message.platform,
                platform_message_id,
                MessageType.TEXT.value,
                message.text,
                message.source_type or None,
                message.source_id,
                message.urgency.value if message.urgency else None,
                status.value,
            )
        except Exception:
            logger.exception("Failed to persist outbound message")
