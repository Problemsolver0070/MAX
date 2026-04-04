"""Performance metric collection, baselines, and comparison."""

from __future__ import annotations

import json
import logging
import statistics
import uuid as uuid_mod
from datetime import UTC, datetime, timedelta
from typing import Any

from max.db.postgres import Database
from max.memory.models import ComparisonResult, MetricBaseline

logger = logging.getLogger(__name__)


class MetricCollector:
    """Collects, stores, and analyzes performance metrics."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self,
        metric_name: str,
        value: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self._db.execute(
            "INSERT INTO performance_metrics (id, metric_name, value, metadata) "
            "VALUES ($1, $2, $3, $4::jsonb)",
            uuid_mod.uuid4(),
            metric_name,
            value,
            json.dumps(metadata or {}),
        )

    async def get_baseline(
        self,
        metric_name: str,
        window_hours: int = 168,
    ) -> MetricBaseline | None:
        rows = await self._db.fetchall(
            "SELECT value FROM performance_metrics "
            "WHERE metric_name = $1 "
            "AND recorded_at >= NOW() - INTERVAL '1 hour' * $2 "
            "ORDER BY recorded_at",
            metric_name,
            window_hours,
        )
        if not rows:
            return None

        values = [float(r["value"]) for r in rows]
        sorted_values = sorted(values)
        n = len(sorted_values)
        now = datetime.now(UTC)

        return MetricBaseline(
            metric_name=metric_name,
            mean=statistics.mean(values),
            median=statistics.median(values),
            p95=sorted_values[min(int(n * 0.95), n - 1)],
            p99=sorted_values[min(int(n * 0.99), n - 1)],
            stddev=statistics.stdev(values) if n > 1 else 0.0,
            sample_count=n,
            window_start=now - timedelta(hours=window_hours),
            window_end=now,
        )

    async def compare(
        self,
        metric_name: str,
        system_a: list[float],
        system_b: list[float],
        lower_is_better: bool = True,
    ) -> ComparisonResult:
        if not system_a or not system_b:
            return ComparisonResult(
                metric_name=metric_name,
                system_a_mean=0.0,
                system_b_mean=0.0,
                difference_percent=0.0,
                is_significant=False,
                verdict="no_difference",
            )

        mean_a = statistics.mean(system_a)
        mean_b = statistics.mean(system_b)

        if mean_a == 0:
            diff_pct = 0.0 if mean_b == 0 else 100.0
        else:
            diff_pct = ((mean_b - mean_a) / abs(mean_a)) * 100.0

        is_significant = abs(diff_pct) > 5.0 and len(system_a) >= 3

        if not is_significant or abs(diff_pct) <= 5.0:
            verdict = "no_difference"
        elif lower_is_better:
            verdict = "a_better" if mean_a < mean_b else "b_better"
        else:
            verdict = "a_better" if mean_a > mean_b else "b_better"

        return ComparisonResult(
            metric_name=metric_name,
            system_a_mean=mean_a,
            system_b_mean=mean_b,
            difference_percent=diff_pct,
            is_significant=is_significant,
            verdict=verdict,
        )
