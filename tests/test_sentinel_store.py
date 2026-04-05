"""Tests for SentinelStore -- async CRUD for sentinel tables."""

import uuid
from unittest.mock import AsyncMock

import pytest

from max.sentinel.store import SentinelStore


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.fetchone = AsyncMock(return_value=None)
    db.fetchall = AsyncMock(return_value=[])
    return db


@pytest.fixture
def store(mock_db):
    return SentinelStore(mock_db)


# ── Benchmarks ────────────────────────────────────────────────────────


class TestCreateBenchmark:
    @pytest.mark.asyncio
    async def test_inserts_benchmark(self, store, mock_db):
        benchmark = {
            "id": uuid.uuid4(),
            "name": "test_bench",
            "category": "planning",
            "description": "A test benchmark",
            "scenario": {"prompt": "Test"},
            "evaluation_criteria": ["accuracy"],
            "weight": 1.0,
            "version": 1,
            "active": True,
        }
        await store.create_benchmark(benchmark)
        mock_db.execute.assert_called_once()
        sql = mock_db.execute.call_args[0][0]
        assert "INSERT INTO sentinel_benchmarks" in sql

    @pytest.mark.asyncio
    async def test_upsert_on_conflict(self, store, mock_db):
        benchmark = {
            "id": uuid.uuid4(),
            "name": "existing_bench",
            "category": "security",
            "description": "Update test",
            "scenario": {},
            "evaluation_criteria": [],
            "weight": 1.0,
            "version": 1,
            "active": True,
        }
        await store.create_benchmark(benchmark)
        sql = mock_db.execute.call_args[0][0]
        assert "ON CONFLICT (name)" in sql


class TestGetBenchmarks:
    @pytest.mark.asyncio
    async def test_get_active_benchmarks(self, store, mock_db):
        mock_db.fetchall.return_value = [
            {"id": uuid.uuid4(), "name": "b1", "category": "planning", "active": True}
        ]
        results = await store.get_benchmarks()
        assert len(results) == 1
        sql = mock_db.fetchall.call_args[0][0]
        assert "WHERE active = TRUE" in sql

    @pytest.mark.asyncio
    async def test_get_all_benchmarks(self, store, mock_db):
        await store.get_benchmarks(active_only=False)
        sql = mock_db.fetchall.call_args[0][0]
        assert "WHERE active" not in sql

    @pytest.mark.asyncio
    async def test_get_benchmarks_by_category(self, store, mock_db):
        await store.get_benchmarks(category="security")
        sql = mock_db.fetchall.call_args[0][0]
        assert "category = $1" in sql


class TestGetBenchmark:
    @pytest.mark.asyncio
    async def test_get_existing(self, store, mock_db):
        bid = uuid.uuid4()
        mock_db.fetchone.return_value = {"id": bid, "name": "test"}
        result = await store.get_benchmark(bid)
        assert result is not None
        assert result["name"] == "test"

    @pytest.mark.asyncio
    async def test_get_missing(self, store, mock_db):
        result = await store.get_benchmark(uuid.uuid4())
        assert result is None


# ── Test Runs ──────────────────────────────────────────────────────────


class TestCreateTestRun:
    @pytest.mark.asyncio
    async def test_creates_run(self, store, mock_db):
        run_id = await store.create_test_run(
            experiment_id=uuid.uuid4(), run_type="baseline"
        )
        assert isinstance(run_id, uuid.UUID)
        sql = mock_db.execute.call_args[0][0]
        assert "INSERT INTO sentinel_test_runs" in sql

    @pytest.mark.asyncio
    async def test_creates_scheduled_run(self, store, mock_db):
        run_id = await store.create_test_run(
            experiment_id=None, run_type="scheduled"
        )
        assert isinstance(run_id, uuid.UUID)


class TestCompleteTestRun:
    @pytest.mark.asyncio
    async def test_marks_completed(self, store, mock_db):
        run_id = uuid.uuid4()
        await store.complete_test_run(run_id, "completed")
        sql = mock_db.execute.call_args[0][0]
        assert "UPDATE sentinel_test_runs" in sql
        assert "status = $1" in sql
        assert "completed_at = NOW()" in sql


class TestGetTestRuns:
    @pytest.mark.asyncio
    async def test_by_experiment(self, store, mock_db):
        exp_id = uuid.uuid4()
        await store.get_test_runs(experiment_id=exp_id)
        sql = mock_db.fetchall.call_args[0][0]
        assert "experiment_id = $1" in sql

    @pytest.mark.asyncio
    async def test_by_run_type(self, store, mock_db):
        await store.get_test_runs(run_type="scheduled")
        sql = mock_db.fetchall.call_args[0][0]
        assert "run_type = $1" in sql

    @pytest.mark.asyncio
    async def test_no_filter(self, store, mock_db):
        await store.get_test_runs()
        sql = mock_db.fetchall.call_args[0][0]
        assert "WHERE" not in sql


# ── Scores ─────────────────────────────────────────────────────────────


class TestRecordScore:
    @pytest.mark.asyncio
    async def test_inserts_score(self, store, mock_db):
        score = {
            "run_id": uuid.uuid4(),
            "benchmark_id": uuid.uuid4(),
            "score": 0.85,
            "criteria_scores": [{"criterion": "a", "score": 0.9}],
            "reasoning": "Good",
        }
        await store.record_score(score)
        sql = mock_db.execute.call_args[0][0]
        assert "INSERT INTO sentinel_scores" in sql


class TestGetScores:
    @pytest.mark.asyncio
    async def test_by_run_id(self, store, mock_db):
        run_id = uuid.uuid4()
        mock_db.fetchall.return_value = [
            {"score": 0.9, "benchmark_id": uuid.uuid4()}
        ]
        results = await store.get_scores(run_id)
        assert len(results) == 1


# ── Capability Scores ──────────────────────────────────────────────────


class TestRecordCapabilityScore:
    @pytest.mark.asyncio
    async def test_inserts_capability_score(self, store, mock_db):
        cap = {
            "run_id": uuid.uuid4(),
            "capability": "planning",
            "aggregate_score": 0.88,
            "test_count": 4,
        }
        await store.record_capability_score(cap)
        sql = mock_db.execute.call_args[0][0]
        assert "INSERT INTO sentinel_capability_scores" in sql


class TestGetCapabilityScores:
    @pytest.mark.asyncio
    async def test_by_run_id(self, store, mock_db):
        run_id = uuid.uuid4()
        await store.get_capability_scores(run_id)
        sql = mock_db.fetchall.call_args[0][0]
        assert "run_id = $1" in sql


# ── Verdicts ───────────────────────────────────────────────────────────


class TestRecordVerdict:
    @pytest.mark.asyncio
    async def test_inserts_verdict(self, store, mock_db):
        verdict = {
            "id": uuid.uuid4(),
            "experiment_id": uuid.uuid4(),
            "baseline_run_id": uuid.uuid4(),
            "candidate_run_id": uuid.uuid4(),
            "passed": False,
            "test_regressions": [{"benchmark_name": "t1", "delta": -0.1}],
            "capability_regressions": [],
            "summary": "1 regression",
        }
        await store.record_verdict(verdict)
        sql = mock_db.execute.call_args[0][0]
        assert "INSERT INTO sentinel_verdicts" in sql


class TestGetVerdict:
    @pytest.mark.asyncio
    async def test_get_by_experiment(self, store, mock_db):
        exp_id = uuid.uuid4()
        mock_db.fetchone.return_value = {"passed": True}
        result = await store.get_verdict(exp_id)
        assert result is not None


# ── Revert Log ─────────────────────────────────────────────────────────


class TestRecordRevert:
    @pytest.mark.asyncio
    async def test_inserts_revert(self, store, mock_db):
        entry = {
            "experiment_id": uuid.uuid4(),
            "verdict_id": uuid.uuid4(),
            "regression_type": "test_case",
            "benchmark_name": "bug_detection",
            "capability": "audit_quality",
            "before_score": 0.85,
            "after_score": 0.72,
            "delta": -0.13,
            "reason_detail": "Missed error",
        }
        await store.record_revert(entry)
        sql = mock_db.execute.call_args[0][0]
        assert "INSERT INTO sentinel_revert_log" in sql


class TestGetReverts:
    @pytest.mark.asyncio
    async def test_by_experiment(self, store, mock_db):
        exp_id = uuid.uuid4()
        await store.get_reverts(exp_id)
        sql = mock_db.fetchall.call_args[0][0]
        assert "experiment_id = $1" in sql


# ── Quality Ledger ─────────────────────────────────────────────────────


class TestRecordToLedger:
    @pytest.mark.asyncio
    async def test_writes_to_ledger(self, store, mock_db):
        await store.record_to_ledger("sentinel_revert", {"detail": "test"})
        sql = mock_db.execute.call_args[0][0]
        assert "INSERT INTO quality_ledger" in sql
