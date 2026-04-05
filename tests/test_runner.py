"""Tests for AgentRunner abstraction and InProcessRunner."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from max.agents.base import AgentContext
from max.command.models import SubtaskResult, WorkerConfig
from max.command.runner import AgentRunner, InProcessRunner
from max.llm.models import LLMResponse, ModelType


def _make_llm_response(text: str) -> LLMResponse:
    return LLMResponse(
        text=text,
        input_tokens=100,
        output_tokens=50,
        model="claude-opus-4-6",
        stop_reason="end_turn",
    )


class TestInProcessRunner:
    @pytest.mark.asyncio
    async def test_run_success(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(
            return_value=_make_llm_response(
                '{"content": "Done", "confidence": 0.85, "reasoning": "Simple task"}'
            )
        )
        runner = InProcessRunner(llm=llm)
        config = WorkerConfig(
            subtask_id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            system_prompt="You are a worker.",
        )
        context = AgentContext()
        result = await runner.run(config, context)
        assert isinstance(result, SubtaskResult)
        assert result.success is True
        assert result.content == "Done"
        assert result.confidence == 0.85

    @pytest.mark.asyncio
    async def test_run_failure(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=RuntimeError("LLM error"))
        runner = InProcessRunner(llm=llm)
        config = WorkerConfig(
            subtask_id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            system_prompt="You are a worker.",
        )
        context = AgentContext()
        result = await runner.run(config, context)
        assert isinstance(result, SubtaskResult)
        assert result.success is False
        assert "LLM error" in result.error

    @pytest.mark.asyncio
    async def test_run_with_custom_model(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(
            return_value=_make_llm_response(
                '{"content": "OK", "confidence": 0.7, "reasoning": "Worked"}'
            )
        )
        runner = InProcessRunner(llm=llm, default_model=ModelType.SONNET)
        config = WorkerConfig(
            subtask_id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            system_prompt="You are a worker.",
        )
        result = await runner.run(config, AgentContext())
        assert result.success is True


class TestAgentRunnerIsAbstract:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            AgentRunner()  # type: ignore[abstract]
