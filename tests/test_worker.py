"""Tests for WorkerAgent — ephemeral subtask executor."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from max.command.worker import WORKER_SYSTEM_PROMPT_TEMPLATE, WorkerAgent
from max.llm.models import LLMResponse, ModelType


def _make_llm_response(text: str) -> LLMResponse:
    return LLMResponse(
        text=text,
        input_tokens=100,
        output_tokens=50,
        model="claude-opus-4-6",
        stop_reason="end_turn",
    )


class TestWorkerAgent:
    @pytest.mark.asyncio
    async def test_run_success(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(
            return_value=_make_llm_response(
                '{"content": "The answer is 42", "confidence": 0.9, "reasoning": "Calculated"}'
            )
        )
        worker = WorkerAgent(
            llm=llm,
            system_prompt="You are a worker.",
            model=ModelType.OPUS,
            max_turns=10,
        )
        result = await worker.run(
            {
                "subtask_id": str(uuid.uuid4()),
                "task_id": str(uuid.uuid4()),
                "description": "Calculate the answer",
                "context_package": {},
                "quality_criteria": {},
            }
        )
        assert result["success"] is True
        assert result["content"] == "The answer is 42"
        assert result["confidence"] == 0.9

    @pytest.mark.asyncio
    async def test_run_json_in_markdown_block(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(
            return_value=_make_llm_response(
                '```json\n{"content": "Result", "confidence": 0.8, "reasoning": "Done"}\n```'
            )
        )
        worker = WorkerAgent(
            llm=llm,
            system_prompt="You are a worker.",
            model=ModelType.OPUS,
        )
        result = await worker.run(
            {
                "subtask_id": str(uuid.uuid4()),
                "task_id": str(uuid.uuid4()),
                "description": "Do something",
            }
        )
        assert result["success"] is True
        assert result["content"] == "Result"

    @pytest.mark.asyncio
    async def test_run_llm_returns_plain_text(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(
            return_value=_make_llm_response(
                "Here is the answer to your question about Python features."
            )
        )
        worker = WorkerAgent(
            llm=llm,
            system_prompt="You are a worker.",
            model=ModelType.OPUS,
        )
        result = await worker.run(
            {
                "subtask_id": str(uuid.uuid4()),
                "task_id": str(uuid.uuid4()),
                "description": "Research Python",
            }
        )
        assert result["success"] is True
        assert "Python features" in result["content"]
        assert result["confidence"] == 0.5  # fallback confidence

    @pytest.mark.asyncio
    async def test_run_llm_exception(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=RuntimeError("API down"))
        worker = WorkerAgent(
            llm=llm,
            system_prompt="You are a worker.",
            model=ModelType.OPUS,
        )
        result = await worker.run(
            {
                "subtask_id": str(uuid.uuid4()),
                "task_id": str(uuid.uuid4()),
                "description": "Do work",
            }
        )
        assert result["success"] is False
        assert "API down" in result["error"]


class TestWorkerSystemPromptTemplate:
    def test_template_contains_placeholders(self):
        assert "{description}" in WORKER_SYSTEM_PROMPT_TEMPLATE
        assert "{context_summary}" in WORKER_SYSTEM_PROMPT_TEMPLATE
        assert "{quality_criteria}" in WORKER_SYSTEM_PROMPT_TEMPLATE
