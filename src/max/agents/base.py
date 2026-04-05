from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from max.llm.client import LLMClient
from max.llm.models import LLMResponse, ModelType

logger = logging.getLogger(__name__)


class AgentConfig(BaseModel):
    name: str
    system_prompt: str
    model: ModelType = ModelType.OPUS
    max_turns: int = 10
    tools: list[str] = Field(default_factory=list)


class AgentContext:
    """Bundles shared infrastructure dependencies for an agent."""

    __slots__ = ("bus", "db", "warm_memory")

    def __init__(self, bus: Any = None, db: Any = None, warm_memory: Any = None) -> None:
        self.bus = bus
        self.db = db
        self.warm_memory = warm_memory


class BaseAgent(ABC):
    def __init__(
        self,
        config: AgentConfig,
        llm: LLMClient,
        context: AgentContext | None = None,
    ):
        self.config = config
        self.llm = llm
        self.context = context or AgentContext()
        self.agent_id = str(uuid.uuid4())
        self._turn_count = 0

    async def on_start(self) -> None:
        """Called when the agent starts. Override in subclasses."""

    async def on_stop(self) -> None:
        """Called when the agent stops. Override in subclasses."""

    async def think(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        model: ModelType | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        if self._turn_count >= self.config.max_turns:
            raise RuntimeError(
                f"Agent '{self.config.name}' exceeded max_turns ({self.config.max_turns})"
            )
        self._turn_count += 1
        logger.debug(
            "[%s] Turn %d/%d: sending %d messages",
            self.config.name,
            self._turn_count,
            self.config.max_turns,
            len(messages),
        )
        response = await self.llm.complete(
            messages=messages,
            system_prompt=system_prompt or self.config.system_prompt,
            model=model or self.config.model,
            tools=tools,
        )
        logger.debug(
            "[%s] Turn %d: received %d tokens",
            self.config.name,
            self._turn_count,
            response.output_tokens,
        )
        return response

    async def think_with_tools(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        model: ModelType | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_executor: Any = None,
    ) -> LLMResponse:
        """Think with tool-use loop: call LLM, execute tools, feed results back.

        Loops until the LLM responds without tool calls or max_turns is hit.
        """
        import json as _json

        conversation = list(messages)

        while True:
            response = await self.think(
                messages=conversation,
                system_prompt=system_prompt,
                model=model,
                tools=tools,
            )

            if not response.tool_calls or tool_executor is None:
                return response

            # Build assistant message with tool_use blocks
            assistant_content: list[dict[str, Any]] = []
            if response.text:
                assistant_content.append({"type": "text", "text": response.text})
            for tc in response.tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.input,
                })
            conversation.append({"role": "assistant", "content": assistant_content})

            # Execute each tool and build tool_result messages
            tool_results_content: list[dict[str, Any]] = []
            for tc in response.tool_calls:
                result = await tool_executor.execute(
                    self.config.name,
                    tc.name,
                    tc.input,
                )
                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": _json.dumps(result.output) if result.success else result.error,
                    "is_error": not result.success,
                })
            conversation.append({"role": "user", "content": tool_results_content})

    @abstractmethod
    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]: ...

    def reset(self) -> None:
        self._turn_count = 0
