"""Tests for SelfModel -- capability tracking, baselines, failures, calibration, journal."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from max.evolution.models import EvolutionJournalEntry
from max.evolution.self_model import SelfModel


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.get_capability_map = AsyncMock(return_value={})
    store.upsert_capability = AsyncMock()
    store.record_failure = AsyncMock()
    store.get_failure_counts = AsyncMock(return_value={})
    store.record_prediction = AsyncMock()
    store.get_calibration_error = AsyncMock(return_value=0.0)
    store.record_journal = AsyncMock()
    store.get_journal = AsyncMock(return_value=[])
    return store


@pytest.fixture
def mock_metrics():
    metrics = AsyncMock()
    metrics.get_baseline = AsyncMock(return_value=None)
    return metrics


@pytest.fixture
def model(mock_store, mock_metrics):
    return SelfModel(mock_store, mock_metrics)


# ── Capability Map ────────────────────────────────────────────────────────


class TestRecordCapability:
    async def test_new_capability_uses_raw_score(self, model, mock_store):
        """First recording for a domain/task_type should use the raw score."""
        mock_store.get_capability_map.return_value = {}

        await model.record_capability("python", "refactoring", 0.85)

        mock_store.upsert_capability.assert_called_once()
        call_args = mock_store.upsert_capability.call_args[0]
        assert call_args[0] == "python"
        assert call_args[1] == "refactoring"
        assert call_args[2] == pytest.approx(0.85)

    async def test_existing_capability_uses_ema(self, model, mock_store):
        """Subsequent recordings should use exponential moving average."""
        mock_store.get_capability_map.return_value = {
            "python": {"refactoring": 0.80},
        }

        await model.record_capability("python", "refactoring", 0.90)

        mock_store.upsert_capability.assert_called_once()
        call_args = mock_store.upsert_capability.call_args[0]
        # EMA: 0.80 * 0.9 + 0.90 * 0.1 = 0.72 + 0.09 = 0.81
        expected = 0.80 * 0.9 + 0.90 * 0.1
        assert call_args[2] == pytest.approx(expected)

    async def test_new_domain_with_existing_map(self, model, mock_store):
        """Adding a new domain when other domains already exist."""
        mock_store.get_capability_map.return_value = {
            "python": {"refactoring": 0.80},
        }

        await model.record_capability("javascript", "debugging", 0.70)

        call_args = mock_store.upsert_capability.call_args[0]
        assert call_args[0] == "javascript"
        assert call_args[1] == "debugging"
        assert call_args[2] == pytest.approx(0.70)  # New, so raw score

    async def test_new_task_type_in_existing_domain(self, model, mock_store):
        """Adding a new task_type to an existing domain."""
        mock_store.get_capability_map.return_value = {
            "python": {"refactoring": 0.80},
        }

        await model.record_capability("python", "testing", 0.90)

        call_args = mock_store.upsert_capability.call_args[0]
        assert call_args[2] == pytest.approx(0.90)  # New task_type, raw score


class TestGetCapabilityMap:
    async def test_delegates_to_store(self, model, mock_store):
        mock_store.get_capability_map.return_value = {
            "python": {"testing": 0.9},
            "rust": {"debugging": 0.7},
        }

        result = await model.get_capability_map()
        assert result == {"python": {"testing": 0.9}, "rust": {"debugging": 0.7}}
        mock_store.get_capability_map.assert_called_once()


# ── Performance Baselines ─────────────────────────────────────────────────


class TestUpdateBaselines:
    async def test_returns_baselines_for_tracked_metrics(self, model, mock_metrics):
        baseline_obj = AsyncMock()
        baseline_obj.metric_name = "audit_score"
        baseline_obj.mean = 0.85
        baseline_obj.median = 0.84
        baseline_obj.p95 = 0.95
        baseline_obj.p99 = 0.98
        baseline_obj.stddev = 0.05
        baseline_obj.sample_count = 100
        baseline_obj.window_start = datetime.now(UTC)
        baseline_obj.window_end = datetime.now(UTC)

        mock_metrics.get_baseline.side_effect = [baseline_obj, None]

        result = await model.update_baselines()

        assert "audit_score" in result
        assert result["audit_score"] == baseline_obj
        # audit_duration_seconds had None, should not be in result
        assert "audit_duration_seconds" not in result

    async def test_returns_empty_when_no_data(self, model, mock_metrics):
        mock_metrics.get_baseline.return_value = None
        result = await model.update_baselines()
        assert result == {}

    async def test_queries_all_tracked_metrics(self, model, mock_metrics):
        mock_metrics.get_baseline.return_value = None
        await model.update_baselines()
        # Should query for both tracked metrics
        assert mock_metrics.get_baseline.call_count == 2


class TestGetBaseline:
    async def test_returns_baseline_when_exists(self, model, mock_metrics):
        baseline_obj = AsyncMock()
        baseline_obj.mean = 0.85
        mock_metrics.get_baseline.return_value = baseline_obj

        result = await model.get_baseline("audit_score")
        assert result is not None
        assert result.mean == 0.85

    async def test_returns_none_when_missing(self, model, mock_metrics):
        mock_metrics.get_baseline.return_value = None
        result = await model.get_baseline("nonexistent_metric")
        assert result is None


# ── Failure Taxonomy ──────────────────────────────────────────────────────


class TestRecordFailure:
    async def test_delegates_to_store(self, model, mock_store):
        await model.record_failure(
            category="timeout",
            details={"endpoint": "/v1/messages"},
            subcategory="api_call",
        )

        mock_store.record_failure.assert_called_once_with(
            category="timeout",
            subcategory="api_call",
            details={"endpoint": "/v1/messages"},
        )

    async def test_default_subcategory(self, model, mock_store):
        await model.record_failure(
            category="validation",
            details={"field": "name"},
        )

        mock_store.record_failure.assert_called_once_with(
            category="validation",
            subcategory="general",
            details={"field": "name"},
        )


class TestGetFailureTaxonomy:
    async def test_delegates_to_store(self, model, mock_store):
        mock_store.get_failure_counts.return_value = {
            "timeout": 5,
            "validation": 3,
        }

        result = await model.get_failure_taxonomy()
        assert result == {"timeout": 5, "validation": 3}
        mock_store.get_failure_counts.assert_called_once()


# ── Confidence Calibration ────────────────────────────────────────────────


class TestRecordPrediction:
    async def test_delegates_to_store(self, model, mock_store):
        await model.record_prediction(0.85, 0.78, task_type="refactoring")

        mock_store.record_prediction.assert_called_once_with(
            predicted=0.85,
            actual=0.78,
            task_type="refactoring",
        )

    async def test_without_task_type(self, model, mock_store):
        await model.record_prediction(0.9, 0.88)

        mock_store.record_prediction.assert_called_once_with(
            predicted=0.9,
            actual=0.88,
            task_type=None,
        )


class TestGetCalibrationError:
    async def test_delegates_to_store(self, model, mock_store):
        mock_store.get_calibration_error.return_value = 0.15

        result = await model.get_calibration_error()
        assert result == 0.15
        mock_store.get_calibration_error.assert_called_once()


# ── Evolution Journal ─────────────────────────────────────────────────────


class TestRecordEvolution:
    async def test_delegates_to_store(self, model, mock_store):
        entry = EvolutionJournalEntry(
            experiment_id=uuid.uuid4(),
            action="promoted",
            details={"score_delta": 0.12},
        )

        await model.record_evolution(entry)

        mock_store.record_journal.assert_called_once()
        call_args = mock_store.record_journal.call_args[0][0]
        assert call_args["action"] == "promoted"
        assert call_args["experiment_id"] == entry.experiment_id
        assert call_args["details"]["score_delta"] == 0.12

    async def test_with_none_experiment(self, model, mock_store):
        entry = EvolutionJournalEntry(
            experiment_id=None,
            action="observation",
            details={"note": "test"},
        )

        await model.record_evolution(entry)

        call_args = mock_store.record_journal.call_args[0][0]
        assert call_args["experiment_id"] is None


class TestGetJournal:
    async def test_delegates_to_store(self, model, mock_store):
        mock_store.get_journal.return_value = [
            {"action": "promoted", "details": {}},
            {"action": "rollback", "details": {}},
        ]

        result = await model.get_journal(limit=10)
        assert len(result) == 2
        mock_store.get_journal.assert_called_once_with(limit=10)

    async def test_default_limit(self, model, mock_store):
        await model.get_journal()
        mock_store.get_journal.assert_called_once_with(limit=50)
