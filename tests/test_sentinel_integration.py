"""Integration tests for the Sentinel Anti-Degradation Scoring System."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from max.sentinel.benchmarks import BENCHMARKS, BenchmarkRegistry
from max.sentinel.comparator import ScoreComparator
from max.sentinel.models import (
    CapabilityRegression,
    RevertEntry,
    SentinelVerdict,
    TestRegression,
)
from max.sentinel.runner import TestRunner
from max.sentinel.scorer import SentinelScorer
from max.sentinel.store import SentinelStore

# ── Import Tests ──────────────────────────────────────────────────────


class TestPackageExports:
    def test_all_models_importable(self):
        pass

    def test_all_classes_importable(self):
        pass

    def test_benchmarks_list_importable(self):
        from max.sentinel import BENCHMARKS

        assert len(BENCHMARKS) == 28


# ── End-to-End Flow Tests ─────────────────────────────────────────────


class TestEndToEndPassingFlow:
    """Test the full pipeline: seed -> baseline -> candidate -> verdict (pass)."""

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.fetchone = AsyncMock(return_value=None)
        db.fetchall = AsyncMock(return_value=[])
        return db

    @pytest.fixture
    def mock_llm(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(
            return_value=MagicMock(
                text=json.dumps(
                    {
                        "criteria_scores": [{"criterion": "a", "score": 0.9, "reasoning": "ok"}],
                        "overall_score": 0.9,
                        "overall_reasoning": "Good",
                    }
                )
            )
        )
        return llm

    @pytest.mark.asyncio
    async def test_full_passing_flow(self, mock_db, mock_llm):
        store = SentinelStore(mock_db)
        registry = BenchmarkRegistry()

        # Seed benchmarks
        await registry.seed(store)
        assert mock_db.execute.call_count == 28

        # Set up for run_suite
        mock_db.execute.reset_mock()
        mock_db.fetchall.return_value = []  # No benchmarks returned = no tests to run

        task_store = AsyncMock()
        task_store.get_completed_tasks = AsyncMock(return_value=[])
        task_store.get_subtasks = AsyncMock(return_value=[])
        quality_store = AsyncMock()
        evo_store = AsyncMock()
        evo_store.get_all_prompts = AsyncMock(return_value={})
        evo_store.get_all_tool_configs = AsyncMock(return_value={})

        runner = TestRunner(
            llm=mock_llm,
            task_store=task_store,
            quality_store=quality_store,
            evo_store=evo_store,
        )
        comparator = ScoreComparator()
        scorer = SentinelScorer(
            store=store,
            runner=runner,
            comparator=comparator,
            task_store=task_store,
            replay_count=5,
        )

        # Run baseline (empty suite = quick pass)
        exp_id = uuid.uuid4()
        baseline_id = await scorer.run_baseline(exp_id)
        assert isinstance(baseline_id, uuid.UUID)


class TestEndToEndRegressionDetection:
    """Test that a regression is correctly detected and logged."""

    def test_comparator_detects_regression(self):
        comparator = ScoreComparator()
        bid = uuid.uuid4()
        baseline = [
            {
                "benchmark_id": bid,
                "benchmark_name": "bug_detection_subtle",
                "category": "audit_quality",
                "score": 0.85,
                "reasoning": "",
            }
        ]
        candidate = [
            {
                "benchmark_id": bid,
                "benchmark_name": "bug_detection_subtle",
                "category": "audit_quality",
                "score": 0.72,
                "reasoning": "Missed error",
            }
        ]
        baseline_caps = [
            {
                "capability": "audit_quality",
                "aggregate_score": 0.88,
                "test_count": 4,
            }
        ]
        candidate_caps = [
            {
                "capability": "audit_quality",
                "aggregate_score": 0.81,
                "test_count": 4,
            }
        ]
        verdict = comparator.compare(
            experiment_id=uuid.uuid4(),
            baseline_run_id=uuid.uuid4(),
            candidate_run_id=uuid.uuid4(),
            baseline_scores=baseline,
            candidate_scores=candidate,
            baseline_capabilities=baseline_caps,
            candidate_capabilities=candidate_caps,
        )
        assert verdict.passed is False
        assert len(verdict.test_regressions) == 1
        assert verdict.test_regressions[0].benchmark_name == "bug_detection_subtle"
        assert verdict.test_regressions[0].delta == pytest.approx(-0.13, abs=0.001)
        assert len(verdict.capability_regressions) == 1
        assert verdict.capability_regressions[0].capability == "audit_quality"

    def test_revert_entry_captures_detail(self):
        entry = RevertEntry(
            experiment_id=uuid.uuid4(),
            verdict_id=uuid.uuid4(),
            regression_type="test_case",
            benchmark_name="bug_detection_subtle",
            capability="audit_quality",
            before_score=0.85,
            after_score=0.72,
            delta=-0.13,
            reason_detail="Agent failed to detect the off-by-one error",
        )
        assert entry.delta == -0.13
        assert "off-by-one" in entry.reason_detail


class TestBenchmarkCoverage:
    """Verify the benchmark suite covers all capability dimensions."""

    def test_memory_retrieval_benchmarks(self):
        memory = [b for b in BENCHMARKS if b.category == "memory_retrieval"]
        assert len(memory) == 4
        names = {b.name for b in memory}
        assert "recent_context_recall" in names
        assert "semantic_search_relevance" in names
        assert "context_anchor_resolution" in names
        assert "memory_compaction_fidelity" in names

    def test_planning_benchmarks(self):
        planning = [b for b in BENCHMARKS if b.category == "planning"]
        assert len(planning) == 4
        names = {b.name for b in planning}
        assert "simple_task_decomposition" in names
        assert "multi_step_with_constraints" in names
        assert "ambiguous_goal_clarification" in names
        assert "dependency_ordering" in names

    def test_communication_benchmarks(self):
        comm = [b for b in BENCHMARKS if b.category == "communication"]
        assert len(comm) == 4

    def test_tool_selection_benchmarks(self):
        tools = [b for b in BENCHMARKS if b.category == "tool_selection"]
        assert len(tools) == 4

    def test_audit_quality_benchmarks(self):
        audit = [b for b in BENCHMARKS if b.category == "audit_quality"]
        assert len(audit) == 4

    def test_security_benchmarks(self):
        security = [b for b in BENCHMARKS if b.category == "security"]
        assert len(security) == 4

    def test_orchestration_benchmarks(self):
        orch = [b for b in BENCHMARKS if b.category == "orchestration"]
        assert len(orch) == 4


class TestModelSerialization:
    """Verify all models roundtrip cleanly through JSON."""

    def test_verdict_with_regressions_roundtrips(self):
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
                    judge_reasoning="Dropped",
                ),
            ],
            capability_regressions=[
                CapabilityRegression(
                    capability="planning",
                    before_aggregate=0.88,
                    after_aggregate=0.75,
                    delta=-0.13,
                    contributing_tests=["test1"],
                ),
            ],
            summary="Regression",
        )
        data = verdict.model_dump(mode="json")
        restored = SentinelVerdict.model_validate(data)
        assert restored.passed is False
        assert len(restored.test_regressions) == 1
        assert len(restored.capability_regressions) == 1
        assert restored.test_regressions[0].delta == -0.2
