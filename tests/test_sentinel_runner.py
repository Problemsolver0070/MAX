"""Tests for TestRunner -- LLM-based benchmark and replay execution."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from max.sentinel.runner import TestRunner


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.complete = AsyncMock()
    return llm


@pytest.fixture
def mock_task_store():
    store = AsyncMock()
    store.get_completed_tasks = AsyncMock(return_value=[])
    store.get_subtasks = AsyncMock(return_value=[])
    return store


@pytest.fixture
def mock_quality_store():
    store = AsyncMock()
    store.get_audit_reports = AsyncMock(return_value=[])
    return store


@pytest.fixture
def mock_evo_store():
    store = AsyncMock()
    store.get_all_prompts = AsyncMock(return_value={})
    store.get_all_tool_configs = AsyncMock(return_value={})
    return store


@pytest.fixture
def runner(mock_llm, mock_task_store, mock_quality_store, mock_evo_store):
    return TestRunner(
        llm=mock_llm,
        task_store=mock_task_store,
        quality_store=mock_quality_store,
        evo_store=mock_evo_store,
    )


class TestRunBenchmark:
    @pytest.mark.asyncio
    async def test_returns_score(self, runner, mock_llm):
        # LLM returns agent response, then judge response
        mock_llm.complete.side_effect = [
            MagicMock(text="PostgreSQL 15 is our database."),
            MagicMock(text=json.dumps({
                "criteria_scores": [
                    {"criterion": "c1", "score": 0.9, "reasoning": "Good"},
                ],
                "overall_score": 0.9,
                "overall_reasoning": "Accurate",
            })),
        ]
        benchmark = {
            "id": uuid.uuid4(),
            "name": "test_bench",
            "category": "memory_retrieval",
            "scenario": {
                "system_prompt": "You are an assistant.",
                "user_message": "What database?",
            },
            "evaluation_criteria": ["Correct answer"],
        }
        score = await runner.run_benchmark(benchmark)
        assert 0.0 <= score["score"] <= 1.0
        assert len(score["criteria_scores"]) >= 1

    @pytest.mark.asyncio
    async def test_benchmark_error_returns_zero(self, runner, mock_llm):
        mock_llm.complete.side_effect = Exception("LLM error")
        benchmark = {
            "id": uuid.uuid4(),
            "name": "failing",
            "category": "planning",
            "scenario": {"system_prompt": "x", "user_message": "y"},
            "evaluation_criteria": ["z"],
        }
        score = await runner.run_benchmark(benchmark)
        assert score["score"] == 0.0


class TestRunReplay:
    @pytest.mark.asyncio
    async def test_returns_score_for_task(self, runner, mock_llm, mock_quality_store):
        mock_quality_store.get_audit_reports.return_value = [
            {"score": 0.85, "subtask_id": uuid.uuid4()}
        ]
        mock_llm.complete.return_value = MagicMock(text=json.dumps({
            "criteria_scores": [{"criterion": "quality", "score": 0.88, "reasoning": "ok"}],
            "overall_score": 0.88,
            "overall_reasoning": "Good work",
        }))
        task = {"id": uuid.uuid4(), "goal_anchor": "Test task"}
        subtasks = [{"id": uuid.uuid4(), "description": "Do thing", "result": {"output": "Done"}}]
        score = await runner.run_replay(task, subtasks)
        assert 0.0 <= score["score"] <= 1.0

    @pytest.mark.asyncio
    async def test_replay_no_subtasks_returns_original(self, runner, mock_quality_store):
        mock_quality_store.get_audit_reports.return_value = [{"score": 0.9}]
        task = {"id": uuid.uuid4(), "goal_anchor": "Test"}
        score = await runner.run_replay(task, [])
        assert score["score"] == 0.9

    @pytest.mark.asyncio
    async def test_replay_error_returns_zero(self, runner, mock_llm):
        mock_llm.complete.side_effect = Exception("Error")
        task = {"id": uuid.uuid4(), "goal_anchor": "Test"}
        subtasks = [{"id": uuid.uuid4(), "description": "x", "result": {"output": "y"}}]
        score = await runner.run_replay(task, subtasks)
        assert score["score"] == 0.0


class TestGetReplayTasks:
    @pytest.mark.asyncio
    async def test_returns_recent_completed(self, runner, mock_task_store):
        mock_task_store.get_completed_tasks.return_value = [
            {"id": uuid.uuid4(), "goal_anchor": "Task 1"},
            {"id": uuid.uuid4(), "goal_anchor": "Task 2"},
        ]
        tasks = await runner.get_replay_tasks(limit=10)
        assert len(tasks) == 2

    @pytest.mark.asyncio
    async def test_respects_limit(self, runner, mock_task_store):
        await runner.get_replay_tasks(limit=5)
        mock_task_store.get_completed_tasks.assert_called_once_with(limit=5)


class TestParseJudgeResponse:
    def test_parses_valid_json(self, runner):
        text = json.dumps({
            "criteria_scores": [{"criterion": "a", "score": 0.9}],
            "overall_score": 0.9,
            "overall_reasoning": "Good",
        })
        result = runner._parse_judge_response(text)
        assert result["overall_score"] == 0.9

    def test_parses_fenced_json(self, runner):
        text = '```json\n{"criteria_scores": [], "overall_score": 0.8, "overall_reasoning": "ok"}\n```'
        result = runner._parse_judge_response(text)
        assert result["overall_score"] == 0.8

    def test_returns_zero_on_invalid(self, runner):
        result = runner._parse_judge_response("not json at all")
        assert result["overall_score"] == 0.0
        assert result["criteria_scores"] == []
