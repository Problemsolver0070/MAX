"""Tests for ScoreComparator -- regression detection logic."""

from __future__ import annotations

import uuid

import pytest

from max.sentinel.comparator import ScoreComparator
from max.sentinel.models import SentinelVerdict


@pytest.fixture
def comparator():
    return ScoreComparator()


def _make_score(benchmark_id, name, category, score):
    return {
        "benchmark_id": benchmark_id,
        "benchmark_name": name,
        "category": category,
        "score": score,
        "criteria_scores": [],
        "reasoning": "",
    }


def _make_cap(capability, score, count=4):
    return {
        "capability": capability,
        "aggregate_score": score,
        "test_count": count,
    }


class TestCompareAllPass:
    def test_all_scores_equal(self, comparator):
        bid = uuid.uuid4()
        baseline = [_make_score(bid, "t1", "planning", 0.9)]
        candidate = [_make_score(bid, "t1", "planning", 0.9)]
        b_caps = [_make_cap("planning", 0.9)]
        c_caps = [_make_cap("planning", 0.9)]
        verdict = comparator.compare(
            experiment_id=uuid.uuid4(),
            baseline_run_id=uuid.uuid4(),
            candidate_run_id=uuid.uuid4(),
            baseline_scores=baseline,
            candidate_scores=candidate,
            baseline_capabilities=b_caps,
            candidate_capabilities=c_caps,
        )
        assert verdict.passed is True
        assert len(verdict.test_regressions) == 0
        assert len(verdict.capability_regressions) == 0

    def test_all_scores_improved(self, comparator):
        bid = uuid.uuid4()
        baseline = [_make_score(bid, "t1", "planning", 0.8)]
        candidate = [_make_score(bid, "t1", "planning", 0.95)]
        b_caps = [_make_cap("planning", 0.8)]
        c_caps = [_make_cap("planning", 0.95)]
        verdict = comparator.compare(
            experiment_id=uuid.uuid4(),
            baseline_run_id=uuid.uuid4(),
            candidate_run_id=uuid.uuid4(),
            baseline_scores=baseline,
            candidate_scores=candidate,
            baseline_capabilities=b_caps,
            candidate_capabilities=c_caps,
        )
        assert verdict.passed is True


class TestCompareTestRegression:
    def test_single_test_regression(self, comparator):
        bid = uuid.uuid4()
        baseline = [_make_score(bid, "t1", "planning", 0.9)]
        candidate = [_make_score(bid, "t1", "planning", 0.7)]
        b_caps = [_make_cap("planning", 0.9)]
        c_caps = [_make_cap("planning", 0.7)]
        verdict = comparator.compare(
            experiment_id=uuid.uuid4(),
            baseline_run_id=uuid.uuid4(),
            candidate_run_id=uuid.uuid4(),
            baseline_scores=baseline,
            candidate_scores=candidate,
            baseline_capabilities=b_caps,
            candidate_capabilities=c_caps,
        )
        assert verdict.passed is False
        assert len(verdict.test_regressions) == 1
        reg = verdict.test_regressions[0]
        assert reg.before_score == 0.9
        assert reg.after_score == 0.7
        assert reg.delta == pytest.approx(-0.2, abs=0.001)

    def test_multiple_regressions(self, comparator):
        b1, b2 = uuid.uuid4(), uuid.uuid4()
        baseline = [
            _make_score(b1, "t1", "planning", 0.9),
            _make_score(b2, "t2", "security", 0.85),
        ]
        candidate = [
            _make_score(b1, "t1", "planning", 0.7),
            _make_score(b2, "t2", "security", 0.6),
        ]
        b_caps = [_make_cap("planning", 0.9), _make_cap("security", 0.85)]
        c_caps = [_make_cap("planning", 0.7), _make_cap("security", 0.6)]
        verdict = comparator.compare(
            experiment_id=uuid.uuid4(),
            baseline_run_id=uuid.uuid4(),
            candidate_run_id=uuid.uuid4(),
            baseline_scores=baseline,
            candidate_scores=candidate,
            baseline_capabilities=b_caps,
            candidate_capabilities=c_caps,
        )
        assert verdict.passed is False
        assert len(verdict.test_regressions) == 2


class TestCompareCapabilityRegression:
    def test_capability_drops_but_tests_pass(self, comparator):
        """Tests individually pass but aggregate drops due to weighting."""
        bid = uuid.uuid4()
        baseline = [_make_score(bid, "t1", "planning", 0.9)]
        candidate = [_make_score(bid, "t1", "planning", 0.9)]
        b_caps = [_make_cap("planning", 0.9)]
        c_caps = [_make_cap("planning", 0.85)]  # aggregate dropped
        verdict = comparator.compare(
            experiment_id=uuid.uuid4(),
            baseline_run_id=uuid.uuid4(),
            candidate_run_id=uuid.uuid4(),
            baseline_scores=baseline,
            candidate_scores=candidate,
            baseline_capabilities=b_caps,
            candidate_capabilities=c_caps,
        )
        assert verdict.passed is False
        assert len(verdict.capability_regressions) == 1
        assert verdict.capability_regressions[0].capability == "planning"


class TestCompareEdgeCases:
    def test_empty_scores(self, comparator):
        verdict = comparator.compare(
            experiment_id=uuid.uuid4(),
            baseline_run_id=uuid.uuid4(),
            candidate_run_id=uuid.uuid4(),
            baseline_scores=[],
            candidate_scores=[],
            baseline_capabilities=[],
            candidate_capabilities=[],
        )
        assert verdict.passed is True

    def test_benchmark_missing_in_candidate(self, comparator):
        """If a benchmark exists in baseline but not candidate, treat as regression."""
        bid = uuid.uuid4()
        baseline = [_make_score(bid, "t1", "planning", 0.9)]
        candidate = []
        b_caps = [_make_cap("planning", 0.9)]
        c_caps = []
        verdict = comparator.compare(
            experiment_id=uuid.uuid4(),
            baseline_run_id=uuid.uuid4(),
            candidate_run_id=uuid.uuid4(),
            baseline_scores=baseline,
            candidate_scores=candidate,
            baseline_capabilities=b_caps,
            candidate_capabilities=c_caps,
        )
        assert verdict.passed is False

    def test_summary_describes_regressions(self, comparator):
        bid = uuid.uuid4()
        baseline = [_make_score(bid, "t1", "planning", 0.9)]
        candidate = [_make_score(bid, "t1", "planning", 0.7)]
        b_caps = [_make_cap("planning", 0.9)]
        c_caps = [_make_cap("planning", 0.7)]
        verdict = comparator.compare(
            experiment_id=uuid.uuid4(),
            baseline_run_id=uuid.uuid4(),
            candidate_run_id=uuid.uuid4(),
            baseline_scores=baseline,
            candidate_scores=candidate,
            baseline_capabilities=b_caps,
            candidate_capabilities=c_caps,
        )
        assert "regression" in verdict.summary.lower() or "dropped" in verdict.summary.lower()
