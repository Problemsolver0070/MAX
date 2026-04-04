"""Tests for metric collector."""

from __future__ import annotations

import pytest

from max.db.postgres import Database
from max.memory.metrics import MetricCollector


@pytest.fixture
async def metrics(db: Database) -> MetricCollector:
    await db.execute("DELETE FROM performance_metrics")
    return MetricCollector(db)


class TestRecording:
    async def test_record_metric(self, metrics: MetricCollector):
        await metrics.record("graph_latency_p50", 12.5)

    async def test_record_with_metadata(self, metrics: MetricCollector):
        await metrics.record(
            "retrieval_precision",
            0.85,
            metadata={"task_type": "code_review"},
        )


class TestBaseline:
    async def test_get_baseline(self, metrics: MetricCollector):
        for i in range(10):
            await metrics.record("test_metric", 10.0 + i)

        baseline = await metrics.get_baseline("test_metric", window_hours=1)
        assert baseline is not None
        assert baseline.sample_count == 10
        assert baseline.mean == pytest.approx(14.5, abs=0.1)

    async def test_baseline_empty(self, metrics: MetricCollector):
        baseline = await metrics.get_baseline("nonexistent_metric")
        assert baseline is None


class TestComparison:
    async def test_compare_a_better(self, metrics: MetricCollector):
        result = await metrics.compare(
            "latency",
            system_a=[10.0, 11.0, 12.0],
            system_b=[15.0, 16.0, 17.0],
            lower_is_better=True,
        )
        assert result.verdict == "a_better"
        assert result.is_significant is True

    async def test_compare_b_better(self, metrics: MetricCollector):
        result = await metrics.compare(
            "accuracy",
            system_a=[0.80, 0.82, 0.81],
            system_b=[0.90, 0.91, 0.92],
            lower_is_better=False,
        )
        assert result.verdict == "b_better"

    async def test_compare_no_difference(self, metrics: MetricCollector):
        result = await metrics.compare(
            "metric",
            system_a=[10.0, 10.1, 10.0],
            system_b=[10.0, 10.1, 10.0],
            lower_is_better=True,
        )
        assert result.verdict == "no_difference"

    async def test_compare_empty_lists(self, metrics: MetricCollector):
        result = await metrics.compare("metric", [], [], lower_is_better=True)
        assert result.verdict == "no_difference"
        assert result.is_significant is False
