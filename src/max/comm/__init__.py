# src/max/comm/__init__.py
"""Communication layer — Telegram adapter, Communicator agent, message routing."""

from max.comm.communicator import CommunicatorAgent
from max.comm.formatter import OutboundFormatter
from max.comm.injection_scanner import PromptInjectionScanner
from max.comm.models import (
    Attachment,
    ConversationEntry,
    DeliveryStatus,
    InboundMessage,
    InlineButton,
    InjectionScanResult,
    MessageType,
    OutboundMessage,
    UrgencyLevel,
)
from max.comm.router import MessageRouter
from max.comm.telegram_adapter import TelegramAdapter

__all__ = [
    "Attachment",
    "CommunicatorAgent",
    "ConversationEntry",
    "DeliveryStatus",
    "InboundMessage",
    "InjectionScanResult",
    "InlineButton",
    "MessageRouter",
    "MessageType",
    "OutboundFormatter",
    "OutboundMessage",
    "PromptInjectionScanner",
    "TelegramAdapter",
    "UrgencyLevel",
]
