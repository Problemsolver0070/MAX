"""Tests for Sentinel domain models."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from pydantic import ValidationError

from max.sentinel.models import (
    Benchmark,
    BenchmarkScenario,
    CapabilityRegression,
    CapabilityScore,
    RevertEntry,
    ScheduledRunSummary,
    SentinelVerdict,
    TestRegression,
    TestRun,
    TestScore,
)

# ── Benchmark ──────────────────────────────────────────────────────────


class TestBenchmark:
    def test_defaults(self):
        b = Benchmark(
            name="test_benchmark",
            category="planning",
            description="A test benchmark",
            scenario={"prompt": "Plan a task"},
            evaluation_criteria=["completeness", "accuracy"],
        )
        assert b.name == "test_benchmark"
        assert b.category == "planning"
        assert b.weight == 1.0
        assert b.version == 1
        assert b.active is True
        assert isinstance(b.id, uuid.UUID)
        assert isinstance(b.created_at, datetime)

    def test_custom_weight(self):
        b = Benchmark(
            name="weighted",
            category="security",
            description="Weighted benchmark",
            scenario={"input": "test"},
            evaluation_criteria=["detection"],
            weight=2.5,
        )
        assert b.weight == 2.5

    def test_weight_cannot_be_negative(self):
        with pytest.raises(ValidationError):
            Benchmark(
                name="bad",
                category="x",
                description="x",
                scenario={},
                evaluation_criteria=[],
                weight=-1.0,
            )

    def test_serialization_roundtrip(self):
        b = Benchmark(
            name="roundtrip",
            category="memory_retrieval",
            description="Test roundtrip",
            scenario={"data": [1, 2, 3]},
            evaluation_criteria=["a", "b"],
            weight=1.5,
            version=2,
        )
        data = b.model_dump(mode="json")
        restored = Benchmark.model_validate(data)
        assert restored.name == "roundtrip"
        assert restored.scenario == {"data": [1, 2, 3]}
        assert restored.weight == 1.5


# ── BenchmarkScenario ──────────────────────────────────────────────────


class TestBenchmarkScenario:
    def test_defaults(self):
        s = BenchmarkScenario(
            system_prompt="You are a planner",
            user_message="Plan this task",
        )
        assert s.system_prompt == "You are a planner"
        assert s.user_message == "Plan this task"
        assert s.context == {}

    def test_with_context(self):
        s = BenchmarkScenario(
            system_prompt="p",
            user_message="m",
            context={"tools": ["shell", "http"]},
        )
        assert s.context["tools"] == ["shell", "http"]


# ── TestRun ────────────────────────────────────────────────────────────


class TestTestRun:
    def test_defaults(self):
        run = TestRun(run_type="baseline")
        assert run.run_type == "baseline"
        assert run.status == "running"
        assert run.experiment_id is None
        assert run.completed_at is None
        assert isinstance(run.id, uuid.UUID)

    def test_with_experiment(self):
        exp_id = uuid.uuid4()
        run = TestRun(run_type="candidate", experiment_id=exp_id)
        assert run.experiment_id == exp_id

    def test_scheduled_run(self):
        run = TestRun(run_type="scheduled")
        assert run.run_type == "scheduled"
        assert run.experiment_id is None


# ── TestScore ──────────────────────────────────────────────────────────


class TestTestScore:
    def test_defaults(self):
        run_id = uuid.uuid4()
        bench_id = uuid.uuid4()
        score = TestScore(run_id=run_id, benchmark_id=bench_id, score=0.85)
        assert score.score == 0.85
        assert score.criteria_scores == []
        assert score.reasoning == ""

    def test_score_bounds(self):
        with pytest.raises(ValidationError):
            TestScore(
                run_id=uuid.uuid4(),
                benchmark_id=uuid.uuid4(),
                score=1.5,
            )

    def test_score_lower_bound(self):
        with pytest.raises(ValidationError):
            TestScore(
                run_id=uuid.uuid4(),
                benchmark_id=uuid.uuid4(),
                score=-0.1,
            )

    def test_with_criteria(self):
        score = TestScore(
            run_id=uuid.uuid4(),
            benchmark_id=uuid.uuid4(),
            score=0.9,
            criteria_scores=[
                {"criterion": "completeness", "score": 0.95, "reasoning": "Good"},
                {"criterion": "accuracy", "score": 0.85, "reasoning": "Minor issue"},
            ],
            reasoning="Overall strong",
        )
        assert len(score.criteria_scores) == 2
        assert score.reasoning == "Overall strong"


# ── CapabilityScore ────────────────────────────────────────────────────


class TestCapabilityScore:
    def test_defaults(self):
        cs = CapabilityScore(
            run_id=uuid.uuid4(),
            capability="planning",
            aggregate_score=0.88,
            test_count=4,
        )
        assert cs.capability == "planning"
        assert cs.aggregate_score == 0.88
        assert cs.test_count == 4

    def test_score_bounds(self):
        with pytest.raises(ValidationError):
            CapabilityScore(
                run_id=uuid.uuid4(),
                capability="x",
                aggregate_score=1.1,
                test_count=1,
            )


# ── TestRegression ─────────────────────────────────────────────────────


class TestTestRegression:
    def test_creation(self):
        reg = TestRegression(
            benchmark_id=uuid.uuid4(),
            benchmark_name="bug_detection_subtle",
            capability="audit_quality",
            before_score=0.85,
            after_score=0.72,
            delta=-0.13,
            judge_reasoning="Failed to detect off-by-one error",
        )
        assert reg.delta == -0.13
        assert reg.capability == "audit_quality"

    def test_serialization(self):
        reg = TestRegression(
            benchmark_id=uuid.uuid4(),
            benchmark_name="test",
            capability="planning",
            before_score=0.9,
            after_score=0.8,
            delta=-0.1,
            judge_reasoning="Missed constraint",
        )
        data = reg.model_dump(mode="json")
        restored = TestRegression.model_validate(data)
        assert restored.benchmark_name == "test"


# ── CapabilityRegression ──────────────────────────────────────────────


class TestCapabilityRegression:
    def test_creation(self):
        reg = CapabilityRegression(
            capability="audit_quality",
            before_aggregate=0.88,
            after_aggregate=0.81,
            delta=-0.07,
            contributing_tests=["bug_detection_subtle", "quality_rule_extraction"],
        )
        assert len(reg.contributing_tests) == 2
        assert reg.delta == -0.07


# ── SentinelVerdict ────────────────────────────────────────────────────


class TestSentinelVerdict:
    def test_passing_verdict(self):
        exp_id = uuid.uuid4()
        verdict = SentinelVerdict(
            experiment_id=exp_id,
            baseline_run_id=uuid.uuid4(),
            candidate_run_id=uuid.uuid4(),
            passed=True,
            summary="All tests passed",
        )
        assert verdict.passed is True
        assert verdict.test_regressions == []
        assert verdict.capability_regressions == []

    def test_failing_verdict_with_regressions(self):
        verdict = SentinelVerdict(
            experiment_id=uuid.uuid4(),
            baseline_run_id=uuid.uuid4(),
            candidate_run_id=uuid.uuid4(),
            passed=False,
            test_regressions=[
                TestRegression(
                    benchmark_id=uuid.uuid4(),
                    benchmark_name="test1",
                    capability="planning",
                    before_score=0.9,
                    after_score=0.7,
                    delta=-0.2,
                    judge_reasoning="Regression detected",
                )
            ],
            capability_regressions=[
                CapabilityRegression(
                    capability="planning",
                    before_aggregate=0.88,
                    after_aggregate=0.75,
                    delta=-0.13,
                    contributing_tests=["test1"],
                )
            ],
            summary="1 test regression, 1 capability regression",
        )
        assert verdict.passed is False
        assert len(verdict.test_regressions) == 1
        assert len(verdict.capability_regressions) == 1

    def test_serialization_roundtrip(self):
        verdict = SentinelVerdict(
            experiment_id=uuid.uuid4(),
            baseline_run_id=uuid.uuid4(),
            candidate_run_id=uuid.uuid4(),
            passed=True,
            summary="Clean",
        )
        data = verdict.model_dump(mode="json")
        restored = SentinelVerdict.model_validate(data)
        assert restored.passed is True


# ── RevertEntry ────────────────────────────────────────────────────────


class TestRevertEntry:
    def test_test_case_revert(self):
        entry = RevertEntry(
            experiment_id=uuid.uuid4(),
            verdict_id=uuid.uuid4(),
            regression_type="test_case",
            benchmark_name="bug_detection_subtle",
            capability="audit_quality",
            before_score=0.85,
            after_score=0.72,
            delta=-0.13,
            reason_detail="Agent missed the off-by-one error",
        )
        assert entry.regression_type == "test_case"
        assert entry.benchmark_name == "bug_detection_subtle"

    def test_capability_revert(self):
        entry = RevertEntry(
            experiment_id=uuid.uuid4(),
            verdict_id=uuid.uuid4(),
            regression_type="capability",
            benchmark_name=None,
            capability="planning",
            before_score=0.88,
            after_score=0.81,
            delta=-0.07,
            reason_detail="Aggregate planning score dropped",
        )
        assert entry.regression_type == "capability"
        assert entry.benchmark_name is None


# ── ScheduledRunSummary ────────────────────────────────────────────────


class TestScheduledRunSummary:
    def test_creation(self):
        s = ScheduledRunSummary(
            run_id=uuid.uuid4(),
            capability_scores={"planning": 0.88, "security": 0.92},
            total_benchmarks=28,
            completed_benchmarks=28,
        )
        assert s.total_benchmarks == 28
        assert s.capability_scores["planning"] == 0.88
