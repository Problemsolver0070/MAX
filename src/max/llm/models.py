from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class ModelType(Enum):
    OPUS = ("opus", "claude-opus-4-6", 32768)
    SONNET = ("sonnet", "claude-sonnet-4-6", 16384)

    def __init__(self, label: str, model_id: str, max_tokens: int) -> None:
        self.label = label
        self._model_id = model_id
        self._max_tokens = max_tokens

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def max_tokens(self) -> int:
        return self._max_tokens


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
