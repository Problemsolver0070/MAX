"""SelfModel -- the system's internal self-awareness model.

Tracks capabilities, performance baselines, failure patterns,
confidence calibration, and an evolution journal.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from max.evolution.models import EvolutionJournalEntry

if TYPE_CHECKING:
    from max.evolution.store import EvolutionStore
    from max.memory.metrics import MetricCollector
    from max.memory.models import MetricBaseline

logger = logging.getLogger(__name__)

# Metrics the system actively monitors
TRACKED_METRICS = ["audit_score", "audit_duration_seconds"]

# Exponential moving average parameters
_EMA_DECAY = 0.9
_EMA_WEIGHT = 0.1


class SelfModel:
    """Maintains the system's self-model: what it is good at, where it
    fails, how well-calibrated its confidence estimates are, and a
    running journal of every evolutionary action.
    """

    def __init__(self, store: EvolutionStore, metrics: MetricCollector) -> None:
        self._store = store
        self._metrics = metrics

    # ── Capability Map ─────────────────────────────────────────────────

    async def record_capability(
        self, domain: str, task_type: str, score: float
    ) -> None:
        """Record a capability score, applying exponential moving average.

        If no prior score exists for the (domain, task_type) pair the raw
        *score* is stored.  Otherwise: ``new = existing * 0.9 + score * 0.1``.
        """
        cap_map = await self._store.get_capability_map()
        existing = cap_map.get(domain, {}).get(task_type)

        if existing is not None:
            score = existing * _EMA_DECAY + score * _EMA_WEIGHT

        await self._store.upsert_capability(domain, task_type, score)

    async def get_capability_map(self) -> dict[str, dict[str, float]]:
        """Return the full capability map ``{domain: {task_type: score}}``."""
        return await self._store.get_capability_map()

    # ── Performance Baselines ──────────────────────────────────────────

    async def update_baselines(self) -> dict[str, MetricBaseline]:
        """Query the metric collector for each tracked metric and return
        only those that have data.
        """
        baselines: dict[str, Any] = {}
        for metric_name in TRACKED_METRICS:
            baseline = await self._metrics.get_baseline(metric_name)
            if baseline is not None:
                baselines[metric_name] = baseline
        return baselines

    async def get_baseline(self, metric: str) -> MetricBaseline | None:
        """Get the current baseline for a single metric."""
        return await self._metrics.get_baseline(metric)

    # ── Failure Taxonomy ───────────────────────────────────────────────

    async def record_failure(
        self,
        category: str,
        details: dict[str, Any],
        subcategory: str | None = None,
    ) -> None:
        """Record a failure, categorised for pattern analysis."""
        await self._store.record_failure(
            category=category,
            subcategory=subcategory or "general",
            details=details,
        )

    async def get_failure_taxonomy(self) -> dict[str, int]:
        """Return failure counts grouped by category."""
        return await self._store.get_failure_counts()

    # ── Confidence Calibration ─────────────────────────────────────────

    async def record_prediction(
        self,
        predicted: float,
        actual: float,
        task_type: str | None = None,
    ) -> None:
        """Record a predicted-vs-actual pair for calibration tracking."""
        await self._store.record_prediction(
            predicted=predicted,
            actual=actual,
            task_type=task_type,
        )

    async def get_calibration_error(self) -> float:
        """Return the mean absolute calibration error over recent predictions."""
        return await self._store.get_calibration_error()

    # ── Evolution Journal ──────────────────────────────────────────────

    async def record_evolution(self, entry: EvolutionJournalEntry) -> None:
        """Persist an evolution journal entry."""
        await self._store.record_journal({
            "experiment_id": entry.experiment_id,
            "action": entry.action,
            "details": entry.details,
        })

    async def get_journal(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent evolution journal entries."""
        return await self._store.get_journal(limit=limit)
