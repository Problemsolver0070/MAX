"""Tests for CanaryRunner -- replay tasks under candidate config and verify quality."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest

from max.evolution.canary import CanaryRunner
from max.evolution.models import CanaryRequest

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_subtask(
    subtask_id: uuid.UUID | None = None,
    description: str = "Write a unit test",
    output: str = "def test_example(): assert True",
) -> dict:
    return {
        "id": subtask_id or uuid.uuid4(),
        "description": description,
        "output": output,
        "status": "completed",
    }


def _make_audit_report(score: float = 0.85) -> dict:
    return {
        "id": uuid.uuid4(),
        "score": score,
        "verdict": "pass",
    }


def _make_canary_request(
    task_ids: list[uuid.UUID] | None = None,
    timeout: int = 300,
) -> CanaryRequest:
    return CanaryRequest(
        experiment_id=uuid.uuid4(),
        task_ids=task_ids if task_ids is not None else [uuid.uuid4()],
        candidate_config={"worker": "improved prompt"},
        timeout_seconds=timeout,
    )


def _scoring_llm(score: float = 0.9) -> AsyncMock:
    """Create a mock LLM that returns a canary evaluation score."""
    resp = AsyncMock()
    resp.text = json.dumps({"score": score, "reasoning": "Looks good."})
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=resp)
    return llm


def _failing_llm() -> AsyncMock:
    llm = AsyncMock()
    llm.complete = AsyncMock(side_effect=Exception("LLM down"))
    return llm


@pytest.fixture
def mock_task_store():
    task_id = uuid.uuid4()
    store = AsyncMock()
    store.get_task = AsyncMock(return_value={
        "id": task_id,
        "goal_anchor": "Build a test suite",
        "status": "completed",
    })
    store.get_subtasks = AsyncMock(return_value=[_make_subtask()])
    return store


@pytest.fixture
def mock_quality_store():
    store = AsyncMock()
    store.get_audit_reports = AsyncMock(return_value=[
        _make_audit_report(0.85),
        _make_audit_report(0.90),
    ])
    return store


@pytest.fixture
def mock_evo_store():
    return AsyncMock()


@pytest.fixture
def mock_metrics():
    return AsyncMock()


# ── All Tasks Pass ───────────────────────────────────────────────────────────


class TestAllPass:
    async def test_single_task_passes(
        self, mock_task_store, mock_quality_store, mock_evo_store, mock_metrics,
    ):
        llm = _scoring_llm(0.9)  # canary score > original 0.875
        runner = CanaryRunner(
            mock_task_store, mock_quality_store, mock_evo_store, llm, mock_metrics,
        )
        request = _make_canary_request()

        result = await runner.run(request)

        assert result.overall_passed is True
        assert len(result.task_results) == 1
        assert result.task_results[0].passed is True
        assert result.task_results[0].canary_score == pytest.approx(0.9)
        assert result.experiment_id == request.experiment_id

    async def test_multiple_tasks_all_pass(
        self, mock_task_store, mock_quality_store, mock_evo_store, mock_metrics,
    ):
        llm = _scoring_llm(0.95)
        runner = CanaryRunner(
            mock_task_store, mock_quality_store, mock_evo_store, llm, mock_metrics,
        )
        task_ids = [uuid.uuid4(), uuid.uuid4()]
        request = _make_canary_request(task_ids=task_ids)

        result = await runner.run(request)

        assert result.overall_passed is True
        assert len(result.task_results) == 2

    async def test_result_has_timing(
        self, mock_task_store, mock_quality_store, mock_evo_store, mock_metrics,
    ):
        llm = _scoring_llm(0.9)
        runner = CanaryRunner(
            mock_task_store, mock_quality_store, mock_evo_store, llm, mock_metrics,
        )
        request = _make_canary_request()

        result = await runner.run(request)

        assert result.duration_seconds >= 0.0


# ── Regression Fails ─────────────────────────────────────────────────────────


class TestRegressionFails:
    async def test_canary_score_below_original_fails(
        self, mock_task_store, mock_quality_store, mock_evo_store, mock_metrics,
    ):
        # original avg is 0.875, canary gives 0.5
        llm = _scoring_llm(0.5)
        runner = CanaryRunner(
            mock_task_store, mock_quality_store, mock_evo_store, llm, mock_metrics,
        )
        request = _make_canary_request()

        result = await runner.run(request)

        assert result.overall_passed is False
        assert result.task_results[0].passed is False
        assert result.task_results[0].canary_score == pytest.approx(0.5)

    async def test_one_task_fails_overall_fails(
        self, mock_task_store, mock_quality_store, mock_evo_store, mock_metrics,
    ):
        """If any single task regresses, overall should fail."""
        # First call returns high score, second returns low
        resp_high = AsyncMock()
        resp_high.text = json.dumps({"score": 0.95})
        resp_low = AsyncMock()
        resp_low.text = json.dumps({"score": 0.3})
        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=[resp_high, resp_low])

        runner = CanaryRunner(
            mock_task_store, mock_quality_store, mock_evo_store, llm, mock_metrics,
        )
        task_ids = [uuid.uuid4(), uuid.uuid4()]
        # Each task has one subtask, so two LLM calls
        request = _make_canary_request(task_ids=task_ids)

        result = await runner.run(request)

        assert result.overall_passed is False


# ── Empty Tasks ──────────────────────────────────────────────────────────────


class TestEmptyTasks:
    async def test_empty_task_list_passes(
        self, mock_task_store, mock_quality_store, mock_evo_store, mock_metrics,
    ):
        llm = _scoring_llm(0.9)
        runner = CanaryRunner(
            mock_task_store, mock_quality_store, mock_evo_store, llm, mock_metrics,
        )
        request = _make_canary_request(task_ids=[])

        result = await runner.run(request)

        assert result.overall_passed is True
        assert len(result.task_results) == 0


# ── Error During Replay ─────────────────────────────────────────────────────


class TestErrorHandling:
    async def test_llm_failure_during_eval_fails_task(
        self, mock_task_store, mock_quality_store, mock_evo_store, mock_metrics,
    ):
        llm = _failing_llm()
        runner = CanaryRunner(
            mock_task_store, mock_quality_store, mock_evo_store, llm, mock_metrics,
        )
        request = _make_canary_request()

        result = await runner.run(request)

        assert result.overall_passed is False
        assert result.task_results[0].passed is False
        assert result.task_results[0].canary_score == pytest.approx(0.0)

    async def test_task_store_failure_fails_task(
        self, mock_quality_store, mock_evo_store, mock_metrics,
    ):
        task_store = AsyncMock()
        task_store.get_task = AsyncMock(side_effect=Exception("DB down"))
        llm = _scoring_llm(0.9)
        runner = CanaryRunner(
            task_store, mock_quality_store, mock_evo_store, llm, mock_metrics,
        )
        request = _make_canary_request()

        result = await runner.run(request)

        assert result.overall_passed is False
        assert result.task_results[0].canary_score == pytest.approx(0.0)

    async def test_missing_audit_reports_uses_zero_original(
        self, mock_task_store, mock_evo_store, mock_metrics,
    ):
        """When no audit reports exist, original score is 0.0 so any canary score passes."""
        quality_store = AsyncMock()
        quality_store.get_audit_reports = AsyncMock(return_value=[])
        llm = _scoring_llm(0.5)
        runner = CanaryRunner(
            mock_task_store, quality_store, mock_evo_store, llm, mock_metrics,
        )
        request = _make_canary_request()

        result = await runner.run(request)

        # canary 0.5 >= original 0.0 -> pass
        assert result.overall_passed is True
        assert result.task_results[0].original_score == pytest.approx(0.0)


# ── Markdown Fencing ─────────────────────────────────────────────────────────


class TestMarkdownFencing:
    async def test_handles_fenced_json(
        self, mock_task_store, mock_quality_store, mock_evo_store, mock_metrics,
    ):
        resp = AsyncMock()
        resp.text = '```json\n{"score": 0.92}\n```'
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=resp)
        runner = CanaryRunner(
            mock_task_store, mock_quality_store, mock_evo_store, llm, mock_metrics,
        )
        request = _make_canary_request()

        result = await runner.run(request)

        assert result.task_results[0].canary_score == pytest.approx(0.92)


# ── Multiple Subtasks ────────────────────────────────────────────────────────


class TestMultipleSubtasks:
    async def test_averages_subtask_scores(
        self, mock_task_store, mock_quality_store, mock_evo_store, mock_metrics,
    ):
        """Canary score should be the average of all subtask eval scores."""
        mock_task_store.get_subtasks = AsyncMock(return_value=[
            _make_subtask(description="Subtask A"),
            _make_subtask(description="Subtask B"),
        ])

        # Two subtask evaluations: 0.8 and 1.0 -> avg 0.9
        resp_a = AsyncMock()
        resp_a.text = json.dumps({"score": 0.8})
        resp_b = AsyncMock()
        resp_b.text = json.dumps({"score": 1.0})
        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=[resp_a, resp_b])

        runner = CanaryRunner(
            mock_task_store, mock_quality_store, mock_evo_store, llm, mock_metrics,
        )
        request = _make_canary_request()

        result = await runner.run(request)

        assert result.task_results[0].canary_score == pytest.approx(0.9)
