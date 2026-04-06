from __future__ import annotations

import logging
from typing import Any

import anthropic
from anthropic import AsyncAnthropic

from max.llm.circuit_breaker import CircuitBreaker, CircuitBreakerOpen
from max.llm.errors import LLMAuthError, LLMConnectionError, LLMError, LLMRateLimitError
from max.llm.models import LLMResponse, ModelType, ToolCall

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(
        self,
        api_key: str,
        default_model: ModelType = ModelType.OPUS,
        max_retries: int = 3,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self._client = AsyncAnthropic(api_key=api_key, max_retries=max_retries)
        self.default_model = default_model
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self._circuit_breaker = circuit_breaker

    async def complete(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        model: ModelType | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        # Circuit breaker gate
        if self._circuit_breaker is not None:
            self._circuit_breaker.check()

        model_type = model or self.default_model
        kwargs: dict[str, Any] = {
            "model": model_type.model_id,
            "messages": messages,
            "max_tokens": max_tokens or model_type.max_tokens,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if tools:
            kwargs["tools"] = tools

        try:
            response = await self._client.messages.create(**kwargs)
        except anthropic.RateLimitError as exc:
            logger.warning("Rate limited by Anthropic API: %s", exc)
            if self._circuit_breaker is not None:
                self._circuit_breaker.record_failure()
            raise LLMRateLimitError(str(exc), cause=exc) from exc
        except anthropic.APIConnectionError as exc:
            logger.error("Failed to connect to Anthropic API: %s", exc)
            if self._circuit_breaker is not None:
                self._circuit_breaker.record_failure()
            raise LLMConnectionError(str(exc), cause=exc) from exc
        except anthropic.AuthenticationError as exc:
            logger.error("Anthropic API authentication failed: %s", exc)
            if self._circuit_breaker is not None:
                self._circuit_breaker.record_failure()
            raise LLMAuthError(str(exc), cause=exc) from exc
        except anthropic.APIStatusError as exc:
            logger.error("Anthropic API error (status %s): %s", exc.status_code, exc)
            if self._circuit_breaker is not None:
                self._circuit_breaker.record_failure()
            raise LLMError(str(exc), cause=exc) from exc

        text_parts = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=block.input))

        self.total_input_tokens += response.usage.input_tokens
        self.total_output_tokens += response.usage.output_tokens

        if self._circuit_breaker is not None:
            self._circuit_breaker.record_success()

        return LLMResponse(
            text="\n".join(text_parts),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
            stop_reason=response.stop_reason,
            tool_calls=tool_calls if tool_calls else None,
        )

    async def close(self):
        await self._client.close()
