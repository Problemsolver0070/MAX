"""SentinelStore -- async CRUD for all sentinel scoring tables."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from max.db.postgres import Database

logger = logging.getLogger(__name__)


class SentinelStore:
    """Persistence layer for the Sentinel Anti-Degradation Scoring System.

    Manages benchmarks, test runs, scores, capability aggregates,
    verdicts, and revert log entries.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Benchmarks ────────────────────────────────────────────────────

    async def create_benchmark(self, benchmark: dict[str, Any]) -> None:
        """Upsert a benchmark test case."""
        await self._db.execute(
            "INSERT INTO sentinel_benchmarks "
            "(id, name, category, description, scenario, evaluation_criteria, "
            "weight, version, active) "
            "VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8, $9) "
            "ON CONFLICT (name) DO UPDATE SET "
            "category = EXCLUDED.category, "
            "description = EXCLUDED.description, "
            "scenario = EXCLUDED.scenario, "
            "evaluation_criteria = EXCLUDED.evaluation_criteria, "
            "weight = EXCLUDED.weight, "
            "version = EXCLUDED.version, "
            "active = EXCLUDED.active",
            benchmark["id"],
            benchmark["name"],
            benchmark["category"],
            benchmark["description"],
            json.dumps(benchmark["scenario"]),
            json.dumps(benchmark["evaluation_criteria"]),
            benchmark.get("weight", 1.0),
            benchmark.get("version", 1),
            benchmark.get("active", True),
        )

    async def get_benchmarks(
        self,
        active_only: bool = True,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get benchmarks, optionally filtered."""
        if category:
            if active_only:
                return await self._db.fetchall(
                    "SELECT * FROM sentinel_benchmarks "
                    "WHERE active = TRUE AND category = $1 "
                    "ORDER BY category, name",
                    category,
                )
            return await self._db.fetchall(
                "SELECT * FROM sentinel_benchmarks WHERE category = $1 ORDER BY category, name",
                category,
            )
        if active_only:
            return await self._db.fetchall(
                "SELECT * FROM sentinel_benchmarks WHERE active = TRUE ORDER BY category, name"
            )
        return await self._db.fetchall("SELECT * FROM sentinel_benchmarks ORDER BY category, name")

    async def get_benchmark(self, benchmark_id: uuid.UUID) -> dict[str, Any] | None:
        """Get a single benchmark by ID."""
        return await self._db.fetchone(
            "SELECT * FROM sentinel_benchmarks WHERE id = $1",
            benchmark_id,
        )

    # ── Test Runs ─────────────────────────────────────────────────────

    async def create_test_run(
        self,
        experiment_id: uuid.UUID | None,
        run_type: str,
    ) -> uuid.UUID:
        """Create a test run. Returns the run UUID."""
        run_id = uuid.uuid4()
        await self._db.execute(
            "INSERT INTO sentinel_test_runs "
            "(id, experiment_id, run_type, status) "
            "VALUES ($1, $2, $3, $4)",
            run_id,
            experiment_id,
            run_type,
            "running",
        )
        return run_id

    async def complete_test_run(self, run_id: uuid.UUID, status: str) -> None:
        """Mark a test run as completed or failed."""
        await self._db.execute(
            "UPDATE sentinel_test_runs SET status = $1, completed_at = NOW() WHERE id = $2",
            status,
            run_id,
        )

    async def get_test_run(self, run_id: uuid.UUID) -> dict[str, Any] | None:
        """Get a single test run by ID."""
        return await self._db.fetchone(
            "SELECT * FROM sentinel_test_runs WHERE id = $1",
            run_id,
        )

    async def get_test_runs(
        self,
        experiment_id: uuid.UUID | None = None,
        run_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get test runs, optionally filtered."""
        if experiment_id is not None:
            return await self._db.fetchall(
                "SELECT * FROM sentinel_test_runs "
                "WHERE experiment_id = $1 ORDER BY started_at DESC LIMIT $2",
                experiment_id,
                limit,
            )
        if run_type is not None:
            return await self._db.fetchall(
                "SELECT * FROM sentinel_test_runs "
                "WHERE run_type = $1 ORDER BY started_at DESC LIMIT $2",
                run_type,
                limit,
            )
        return await self._db.fetchall(
            "SELECT * FROM sentinel_test_runs ORDER BY started_at DESC LIMIT $1",
            limit,
        )

    # ── Scores ────────────────────────────────────────────────────────

    async def record_score(self, score: dict[str, Any]) -> None:
        """Record a single benchmark score."""
        await self._db.execute(
            "INSERT INTO sentinel_scores "
            "(id, run_id, benchmark_id, score, criteria_scores, reasoning) "
            "VALUES ($1, $2, $3, $4, $5::jsonb, $6)",
            uuid.uuid4(),
            score["run_id"],
            score["benchmark_id"],
            score["score"],
            json.dumps(score.get("criteria_scores", [])),
            score.get("reasoning", ""),
        )

    async def get_scores(self, run_id: uuid.UUID) -> list[dict[str, Any]]:
        """Get all scores for a test run."""
        return await self._db.fetchall(
            "SELECT s.*, b.name AS benchmark_name, b.category "
            "FROM sentinel_scores s "
            "JOIN sentinel_benchmarks b ON s.benchmark_id = b.id "
            "WHERE s.run_id = $1 ORDER BY b.category, b.name",
            run_id,
        )

    # ── Capability Scores ─────────────────────────────────────────────

    async def record_capability_score(self, cap: dict[str, Any]) -> None:
        """Record an aggregated capability score."""
        await self._db.execute(
            "INSERT INTO sentinel_capability_scores "
            "(id, run_id, capability, aggregate_score, test_count) "
            "VALUES ($1, $2, $3, $4, $5)",
            uuid.uuid4(),
            cap["run_id"],
            cap["capability"],
            cap["aggregate_score"],
            cap["test_count"],
        )

    async def get_capability_scores(self, run_id: uuid.UUID) -> list[dict[str, Any]]:
        """Get capability aggregate scores for a test run."""
        return await self._db.fetchall(
            "SELECT * FROM sentinel_capability_scores WHERE run_id = $1 ORDER BY capability",
            run_id,
        )

    # ── Verdicts ──────────────────────────────────────────────────────

    async def record_verdict(self, verdict: dict[str, Any]) -> None:
        """Record a sentinel verdict."""
        await self._db.execute(
            "INSERT INTO sentinel_verdicts "
            "(id, experiment_id, baseline_run_id, candidate_run_id, "
            "passed, test_regressions, capability_regressions, summary) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8)",
            verdict.get("id", uuid.uuid4()),
            verdict["experiment_id"],
            verdict["baseline_run_id"],
            verdict["candidate_run_id"],
            verdict["passed"],
            json.dumps(verdict.get("test_regressions", [])),
            json.dumps(verdict.get("capability_regressions", [])),
            verdict.get("summary", ""),
        )

    async def get_verdict(self, experiment_id: uuid.UUID) -> dict[str, Any] | None:
        """Get the verdict for an experiment."""
        return await self._db.fetchone(
            "SELECT * FROM sentinel_verdicts WHERE experiment_id = $1",
            experiment_id,
        )

    # ── Revert Log ────────────────────────────────────────────────────

    async def record_revert(self, entry: dict[str, Any]) -> None:
        """Record a single revert log entry."""
        await self._db.execute(
            "INSERT INTO sentinel_revert_log "
            "(id, experiment_id, verdict_id, regression_type, "
            "benchmark_name, capability, before_score, after_score, "
            "delta, reason_detail) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
            uuid.uuid4(),
            entry["experiment_id"],
            entry["verdict_id"],
            entry["regression_type"],
            entry.get("benchmark_name"),
            entry["capability"],
            entry["before_score"],
            entry["after_score"],
            entry["delta"],
            entry["reason_detail"],
        )

    async def get_reverts(self, experiment_id: uuid.UUID) -> list[dict[str, Any]]:
        """Get all revert log entries for an experiment."""
        return await self._db.fetchall(
            "SELECT * FROM sentinel_revert_log WHERE experiment_id = $1 ORDER BY logged_at DESC",
            experiment_id,
        )

    # ── Quality Ledger ────────────────────────────────────────────────

    async def record_to_ledger(self, entry_type: str, content: dict[str, Any]) -> None:
        """Write an entry to the quality_ledger table."""
        await self._db.execute(
            "INSERT INTO quality_ledger (id, entry_type, content) VALUES ($1, $2, $3::jsonb)",
            uuid.uuid4(),
            entry_type,
            json.dumps(content),
        )
