from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class ModelType(Enum):
    OPUS = "opus"
    SONNET = "sonnet"

    @property
    def model_id(self) -> str:
        return {
            ModelType.OPUS: "claude-opus-4-6",
            ModelType.SONNET: "claude-sonnet-4-6",
        }[self]

    @property
    def max_tokens(self) -> int:
        return {
            ModelType.OPUS: 32768,
            ModelType.SONNET: 16384,
        }[self]


class ToolCall(BaseModel):
    """A structured tool call returned by the LLM."""

    id: str
    name: str
    input: dict[str, Any]


class LLMResponse(BaseModel):
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    stop_reason: str
    tool_calls: list[ToolCall] | None = None
