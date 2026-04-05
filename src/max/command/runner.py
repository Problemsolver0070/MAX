"""AgentRunner -- abstraction for agent execution (in-process or subprocess)."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from max.agents.base import AgentContext
from max.command.models import SubtaskResult, WorkerConfig
from max.command.worker import WorkerAgent
from max.llm.client import LLMClient
from max.llm.models import ModelType

logger = logging.getLogger(__name__)


class AgentRunner(ABC):
    """Abstract interface for running worker agents."""

    @abstractmethod
    async def run(
        self,
        worker_config: WorkerConfig,
        context: AgentContext,
    ) -> SubtaskResult:
        """Run a worker agent with the given config and return its result."""


class InProcessRunner(AgentRunner):
    """Runs worker agents in the current process as asyncio tasks."""

    def __init__(
        self,
        llm: LLMClient,
        default_model: ModelType = ModelType.OPUS,
    ) -> None:
        self._llm = llm
        self._default_model = default_model

    async def run(
        self,
        worker_config: WorkerConfig,
        context: AgentContext,
    ) -> SubtaskResult:
        """Create a WorkerAgent, execute, and wrap the result."""
        worker = WorkerAgent(
            llm=self._llm,
            system_prompt=worker_config.system_prompt,
            model=self._default_model,
            max_turns=worker_config.max_turns,
        )
        raw = await worker.run(
            {
                "subtask_id": str(worker_config.subtask_id),
                "task_id": str(worker_config.task_id),
                "description": worker_config.system_prompt,
                "context_package": worker_config.context_package,
                "quality_criteria": worker_config.quality_criteria,
            }
        )
        return SubtaskResult(
            subtask_id=worker_config.subtask_id,
            task_id=worker_config.task_id,
            success=raw.get("success", False),
            content=raw.get("content", ""),
            confidence=raw.get("confidence", 0.0),
            reasoning=raw.get("reasoning", ""),
            error=raw.get("error"),
        )
