"""Tests for SentinelScorer -- orchestrator for baseline -> candidate -> verdict."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from max.sentinel.scorer import SentinelScorer


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.create_test_run = AsyncMock(return_value=uuid.uuid4())
    store.complete_test_run = AsyncMock()
    store.get_benchmarks = AsyncMock(return_value=[])
    store.record_score = AsyncMock()
    store.record_capability_score = AsyncMock()
    store.record_verdict = AsyncMock()
    store.record_revert = AsyncMock()
    store.record_to_ledger = AsyncMock()
    store.get_scores = AsyncMock(return_value=[])
    store.get_capability_scores = AsyncMock(return_value=[])
    store.get_test_runs = AsyncMock(return_value=[])
    return store


@pytest.fixture
def mock_runner():
    runner = AsyncMock()
    runner.run_benchmark = AsyncMock(return_value={
        "score": 0.9, "criteria_scores": [], "reasoning": "Good",
    })
    runner.get_replay_tasks = AsyncMock(return_value=[])
    runner.run_replay = AsyncMock(return_value={
        "score": 0.88, "criteria_scores": [], "reasoning": "Ok",
    })
    return runner


@pytest.fixture
def mock_comparator():
    from max.sentinel.models import SentinelVerdict
    comparator = MagicMock()
    comparator.compare = MagicMock(return_value=SentinelVerdict(
        experiment_id=uuid.uuid4(),
        baseline_run_id=uuid.uuid4(),
        candidate_run_id=uuid.uuid4(),
        passed=True,
        summary="All passed",
    ))
    return comparator


@pytest.fixture
def scorer(mock_store, mock_runner, mock_comparator):
    return SentinelScorer(
        store=mock_store,
        runner=mock_runner,
        comparator=mock_comparator,
        task_store=AsyncMock(),
        replay_count=10,
    )


class TestRunBaseline:
    @pytest.mark.asyncio
    async def test_creates_run_and_returns_id(self, scorer, mock_store):
        run_id = await scorer.run_baseline(uuid.uuid4())
        assert isinstance(run_id, uuid.UUID)
        mock_store.create_test_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_runs_all_benchmarks(self, scorer, mock_store, mock_runner):
        mock_store.get_benchmarks.return_value = [
            {"id": uuid.uuid4(), "name": "b1", "category": "planning",
             "scenario": {}, "evaluation_criteria": []},
            {"id": uuid.uuid4(), "name": "b2", "category": "security",
             "scenario": {}, "evaluation_criteria": []},
        ]
        await scorer.run_baseline(uuid.uuid4())
        assert mock_runner.run_benchmark.call_count == 2

    @pytest.mark.asyncio
    async def test_records_scores(self, scorer, mock_store, mock_runner):
        bid = uuid.uuid4()
        mock_store.get_benchmarks.return_value = [
            {"id": bid, "name": "b1", "category": "planning",
             "scenario": {}, "evaluation_criteria": []},
        ]
        await scorer.run_baseline(uuid.uuid4())
        mock_store.record_score.assert_called()

    @pytest.mark.asyncio
    async def test_records_capability_scores(self, scorer, mock_store):
        bid = uuid.uuid4()
        mock_store.get_benchmarks.return_value = [
            {"id": bid, "name": "b1", "category": "planning",
             "scenario": {}, "evaluation_criteria": [], "weight": 1.0},
        ]
        await scorer.run_baseline(uuid.uuid4())
        mock_store.record_capability_score.assert_called()

    @pytest.mark.asyncio
    async def test_marks_run_completed(self, scorer, mock_store):
        await scorer.run_baseline(uuid.uuid4())
        mock_store.complete_test_run.assert_called_once()
        args = mock_store.complete_test_run.call_args[0]
        assert args[1] == "completed"


class TestRunCandidate:
    @pytest.mark.asyncio
    async def test_creates_candidate_run(self, scorer, mock_store):
        run_id = await scorer.run_candidate(uuid.uuid4())
        assert isinstance(run_id, uuid.UUID)
        call_kwargs = mock_store.create_test_run.call_args
        assert call_kwargs[1]["run_type"] == "candidate" or call_kwargs[0][1] == "candidate"


class TestCompareAndVerdict:
    @pytest.mark.asyncio
    async def test_returns_verdict(self, scorer, mock_store, mock_comparator):
        mock_store.get_scores.return_value = [
            {"benchmark_id": uuid.uuid4(), "score": 0.9, "benchmark_name": "t1", "category": "planning"}
        ]
        mock_store.get_capability_scores.return_value = [
            {"capability": "planning", "aggregate_score": 0.9, "test_count": 1}
        ]
        exp_id = uuid.uuid4()
        mock_store.get_test_runs.return_value = [
            {"id": uuid.uuid4(), "run_type": "baseline"},
            {"id": uuid.uuid4(), "run_type": "candidate"},
        ]
        verdict = await scorer.compare_and_verdict(exp_id)
        assert verdict.passed is True
        mock_store.record_verdict.assert_called_once()

    @pytest.mark.asyncio
    async def test_records_reverts_on_failure(self, scorer, mock_store, mock_comparator):
        from max.sentinel.models import SentinelVerdict, TestRegression
        failing_verdict = SentinelVerdict(
            experiment_id=uuid.uuid4(),
            baseline_run_id=uuid.uuid4(),
            candidate_run_id=uuid.uuid4(),
            passed=False,
            test_regressions=[
                TestRegression(
                    benchmark_id=uuid.uuid4(),
                    benchmark_name="t1",
                    capability="planning",
                    before_score=0.9,
                    after_score=0.7,
                    delta=-0.2,
                    judge_reasoning="Dropped",
                ),
            ],
            summary="Regression",
        )
        mock_comparator.compare.return_value = failing_verdict
        mock_store.get_test_runs.return_value = [
            {"id": uuid.uuid4(), "run_type": "baseline"},
            {"id": uuid.uuid4(), "run_type": "candidate"},
        ]
        mock_store.get_scores.return_value = []
        mock_store.get_capability_scores.return_value = []
        verdict = await scorer.compare_and_verdict(uuid.uuid4())
        assert verdict.passed is False
        assert mock_store.record_revert.call_count >= 1
        mock_store.record_to_ledger.assert_called()


class TestRunScheduled:
    @pytest.mark.asyncio
    async def test_creates_scheduled_run(self, scorer, mock_store):
        run_id = await scorer.run_scheduled()
        assert isinstance(run_id, uuid.UUID)
