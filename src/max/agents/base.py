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

    @abstractmethod
    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]: ...

    def reset(self) -> None:
        self._turn_count = 0
