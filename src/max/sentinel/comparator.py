"""ScoreComparator -- detects regressions between baseline and candidate runs."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from max.sentinel.models import (
    CapabilityRegression,
    SentinelVerdict,
    TestRegression,
)

logger = logging.getLogger(__name__)


class ScoreComparator:
    """Compares two test runs and detects regressions at both layers."""

    def compare(
        self,
        experiment_id: uuid.UUID,
        baseline_run_id: uuid.UUID,
        candidate_run_id: uuid.UUID,
        baseline_scores: list[dict[str, Any]],
        candidate_scores: list[dict[str, Any]],
        baseline_capabilities: list[dict[str, Any]],
        candidate_capabilities: list[dict[str, Any]],
    ) -> SentinelVerdict:
        """Compare baseline vs candidate runs.

        Returns a SentinelVerdict with passed=True only if BOTH:
        - No individual test score dropped
        - No capability aggregate dropped
        """
        test_regressions = self._check_test_regressions(baseline_scores, candidate_scores)
        capability_regressions = self._check_capability_regressions(
            baseline_capabilities, candidate_capabilities
        )

        passed = len(test_regressions) == 0 and len(capability_regressions) == 0

        summary = self._build_summary(passed, test_regressions, capability_regressions)

        return SentinelVerdict(
            experiment_id=experiment_id,
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
            passed=passed,
            test_regressions=test_regressions,
            capability_regressions=capability_regressions,
            summary=summary,
        )

    def _check_test_regressions(
        self,
        baseline_scores: list[dict[str, Any]],
        candidate_scores: list[dict[str, Any]],
    ) -> list[TestRegression]:
        """Check for per-test-case regressions."""
        candidate_map: dict[uuid.UUID, dict[str, Any]] = {}
        for s in candidate_scores:
            bid = s["benchmark_id"]
            if isinstance(bid, str):
                bid = uuid.UUID(bid)
            candidate_map[bid] = s

        regressions: list[TestRegression] = []
        for bs in baseline_scores:
            bid = bs["benchmark_id"]
            if isinstance(bid, str):
                bid = uuid.UUID(bid)

            cs = candidate_map.get(bid)
            if cs is None:
                # Missing in candidate = regression (score dropped to 0)
                regressions.append(
                    TestRegression(
                        benchmark_id=bid,
                        benchmark_name=bs.get("benchmark_name", "unknown"),
                        capability=bs.get("category", "unknown"),
                        before_score=bs["score"],
                        after_score=0.0,
                        delta=-bs["score"],
                        judge_reasoning="Benchmark missing from candidate run",
                    )
                )
                continue

            before = bs["score"]
            after = cs["score"]
            if after < before:
                regressions.append(
                    TestRegression(
                        benchmark_id=bid,
                        benchmark_name=bs.get("benchmark_name", bs.get("name", "unknown")),
                        capability=bs.get("category", "unknown"),
                        before_score=before,
                        after_score=after,
                        delta=after - before,
                        judge_reasoning=cs.get("reasoning", "Score decreased"),
                    )
                )

        return regressions

    def _check_capability_regressions(
        self,
        baseline_caps: list[dict[str, Any]],
        candidate_caps: list[dict[str, Any]],
    ) -> list[CapabilityRegression]:
        """Check for per-capability aggregate regressions."""
        candidate_map: dict[str, dict[str, Any]] = {c["capability"]: c for c in candidate_caps}

        regressions: list[CapabilityRegression] = []
        for bc in baseline_caps:
            cap_name = bc["capability"]
            cc = candidate_map.get(cap_name)

            if cc is None:
                regressions.append(
                    CapabilityRegression(
                        capability=cap_name,
                        before_aggregate=bc["aggregate_score"],
                        after_aggregate=0.0,
                        delta=-bc["aggregate_score"],
                        contributing_tests=["all (capability missing from candidate)"],
                    )
                )
                continue

            before = bc["aggregate_score"]
            after = cc["aggregate_score"]
            if after < before:
                regressions.append(
                    CapabilityRegression(
                        capability=cap_name,
                        before_aggregate=before,
                        after_aggregate=after,
                        delta=after - before,
                        contributing_tests=[],
                    )
                )

        return regressions

    def _build_summary(
        self,
        passed: bool,
        test_regs: list[TestRegression],
        cap_regs: list[CapabilityRegression],
    ) -> str:
        """Build a human-readable summary of the comparison."""
        if passed:
            return "All tests passed. No regressions detected."

        parts: list[str] = []
        if test_regs:
            names = [r.benchmark_name for r in test_regs]
            parts.append(f"{len(test_regs)} test(s) dropped: {', '.join(names)}")
        if cap_regs:
            caps = [r.capability for r in cap_regs]
            parts.append(f"{len(cap_regs)} capability(ies) dropped: {', '.join(caps)}")
        return "REVERT — " + "; ".join(parts)
