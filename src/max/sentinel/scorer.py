"""SentinelScorer -- orchestrates baseline -> candidate -> compare -> verdict."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from max.sentinel.models import SentinelVerdict

if TYPE_CHECKING:
    from max.sentinel.comparator import ScoreComparator
    from max.sentinel.runner import TestRunner
    from max.sentinel.store import SentinelStore

logger = logging.getLogger(__name__)


class SentinelScorer:
    """Orchestrates the full Sentinel scoring flow."""

    def __init__(
        self,
        store: SentinelStore,
        runner: TestRunner,
        comparator: ScoreComparator,
        task_store: Any,
        replay_count: int = 10,
    ) -> None:
        self._store = store
        self._runner = runner
        self._comparator = comparator
        self._task_store = task_store
        self._replay_count = replay_count

    async def run_baseline(self, experiment_id: uuid.UUID) -> uuid.UUID:
        """Run the full benchmark + replay suite as a baseline. Returns the run_id."""
        return await self._run_suite(experiment_id, "baseline")

    async def run_candidate(self, experiment_id: uuid.UUID) -> uuid.UUID:
        """Run the full benchmark + replay suite as a candidate evaluation. Returns the run_id."""
        return await self._run_suite(experiment_id, "candidate")

    async def run_scheduled(self) -> uuid.UUID:
        """Run the full suite for trend monitoring (no experiment). Returns the run_id."""
        return await self._run_suite(None, "scheduled")

    async def compare_and_verdict(
        self, experiment_id: uuid.UUID
    ) -> SentinelVerdict:
        """Compare baseline vs candidate runs and produce a verdict."""
        runs = await self._store.get_test_runs(experiment_id=experiment_id)
        baseline_run = next(
            (r for r in runs if r["run_type"] == "baseline"), None
        )
        candidate_run = next(
            (r for r in runs if r["run_type"] == "candidate"), None
        )

        if baseline_run is None or candidate_run is None:
            logger.error(
                "Missing runs for experiment %s (baseline=%s, candidate=%s)",
                experiment_id,
                baseline_run is not None,
                candidate_run is not None,
            )
            return SentinelVerdict(
                experiment_id=experiment_id,
                baseline_run_id=uuid.uuid4(),
                candidate_run_id=uuid.uuid4(),
                passed=False,
                summary="Missing baseline or candidate run",
            )

        baseline_run_id = baseline_run["id"]
        candidate_run_id = candidate_run["id"]

        baseline_scores = await self._store.get_scores(baseline_run_id)
        candidate_scores = await self._store.get_scores(candidate_run_id)
        baseline_caps = await self._store.get_capability_scores(baseline_run_id)
        candidate_caps = await self._store.get_capability_scores(candidate_run_id)

        verdict = self._comparator.compare(
            experiment_id=experiment_id,
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
            baseline_scores=baseline_scores,
            candidate_scores=candidate_scores,
            baseline_capabilities=baseline_caps,
            candidate_capabilities=candidate_caps,
        )

        # Persist verdict
        await self._store.record_verdict(verdict.model_dump(mode="json"))

        # If failed, log each regression
        if not verdict.passed:
            await self._log_regressions(verdict)

        return verdict

    # ── Private ───────────────────────────────────────────────────────

    async def _run_suite(
        self,
        experiment_id: uuid.UUID | None,
        run_type: str,
    ) -> uuid.UUID:
        """Run all benchmarks + replays and record scores."""
        run_id = await self._store.create_test_run(
            experiment_id=experiment_id, run_type=run_type
        )

        try:
            benchmarks = await self._store.get_benchmarks(active_only=True)
            capability_totals: dict[str, list[tuple[float, float]]] = {}

            # Run fixed benchmarks
            for bench in benchmarks:
                result = await self._runner.run_benchmark(bench)
                await self._store.record_score({
                    "run_id": run_id,
                    "benchmark_id": bench["id"],
                    "score": result["score"],
                    "criteria_scores": result["criteria_scores"],
                    "reasoning": result["reasoning"],
                })
                cat = bench.get("category", "unknown")
                weight = bench.get("weight", 1.0)
                capability_totals.setdefault(cat, []).append(
                    (result["score"], weight)
                )

            # Run replay tasks
            replay_tasks = await self._runner.get_replay_tasks(
                limit=self._replay_count
            )
            for task in replay_tasks:
                task_id = task["id"]
                subtasks = await self._task_store.get_subtasks(task_id)
                result = await self._runner.run_replay(task, subtasks)
                capability_totals.setdefault("replay", []).append(
                    (result["score"], 1.0)
                )

            # Compute and record capability aggregates
            for cap, scores in capability_totals.items():
                total_weighted = sum(s * w for s, w in scores)
                total_weight = sum(w for _, w in scores)
                aggregate = total_weighted / total_weight if total_weight > 0 else 0.0
                await self._store.record_capability_score({
                    "run_id": run_id,
                    "capability": cap,
                    "aggregate_score": aggregate,
                    "test_count": len(scores),
                })

            await self._store.complete_test_run(run_id, "completed")

        except Exception:
            logger.error("Suite run failed", exc_info=True)
            await self._store.complete_test_run(run_id, "failed")

        return run_id

    async def _log_regressions(self, verdict: SentinelVerdict) -> None:
        """Log each regression to the revert log and quality ledger."""
        for reg in verdict.test_regressions:
            await self._store.record_revert({
                "experiment_id": verdict.experiment_id,
                "verdict_id": verdict.id,
                "regression_type": "test_case",
                "benchmark_name": reg.benchmark_name,
                "capability": reg.capability,
                "before_score": reg.before_score,
                "after_score": reg.after_score,
                "delta": reg.delta,
                "reason_detail": reg.judge_reasoning,
            })

        for reg in verdict.capability_regressions:
            await self._store.record_revert({
                "experiment_id": verdict.experiment_id,
                "verdict_id": verdict.id,
                "regression_type": "capability",
                "benchmark_name": None,
                "capability": reg.capability,
                "before_score": reg.before_aggregate,
                "after_score": reg.after_aggregate,
                "delta": reg.delta,
                "reason_detail": f"Capability aggregate dropped. Contributing: {', '.join(reg.contributing_tests)}",
            })

        await self._store.record_to_ledger(
            "sentinel_revert",
            {
                "experiment_id": str(verdict.experiment_id),
                "test_regressions": len(verdict.test_regressions),
                "capability_regressions": len(verdict.capability_regressions),
                "summary": verdict.summary,
            },
        )
