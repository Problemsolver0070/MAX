from __future__ import annotations

from typing import Any

from anthropic import AsyncAnthropic

from max.llm.models import LLMResponse, ModelType


class LLMClient:
    def __init__(self, api_key: str, default_model: ModelType = ModelType.OPUS):
        self._client = AsyncAnthropic(api_key=api_key)
        self.default_model = default_model
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    async def complete(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        model: ModelType | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
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

        response = await self._client.messages.create(**kwargs)

        text_parts = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append({"id": block.id, "name": block.name, "input": block.input})

        self.total_input_tokens += response.usage.input_tokens
        self.total_output_tokens += response.usage.output_tokens

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
