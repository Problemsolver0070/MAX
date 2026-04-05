"""SnapshotManager -- capture and restore system state for evolution experiments."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from max.evolution.store import EvolutionStore
    from max.memory.metrics import MetricCollector

logger = logging.getLogger(__name__)

# Metrics to capture in every snapshot
_BASELINE_METRICS = ["audit_score", "audit_duration_seconds"]


class SnapshotManager:
    """Captures and restores full system state around evolution experiments.

    A snapshot includes all live prompts, tool configurations, and metric
    baselines.  Before an experiment mutates anything the caller should
    ``capture()``; if the experiment degrades quality, ``restore()`` rolls
    back to the saved state.
    """

    def __init__(self, store: EvolutionStore, metrics: MetricCollector) -> None:
        self._store = store
        self._metrics = metrics

    # ── Public API ─────────────────────────────────────────────────────

    async def capture(self, experiment_id: UUID) -> UUID:
        """Capture current system state before an experiment.

        Collects all live prompts, tool configs, and metric baselines,
        persists them as a snapshot, and returns the snapshot UUID.
        """
        prompts = await self._store.get_all_prompts()
        tool_configs = await self._store.get_all_tool_configs()

        metrics_baseline: dict[str, float] = {}
        for metric_name in _BASELINE_METRICS:
            baseline = await self._metrics.get_baseline(metric_name)
            if baseline is not None:
                metrics_baseline[metric_name] = baseline.mean

        snapshot_data = {
            "prompts": prompts,
            "tool_configs": tool_configs,
            "context_rules": [],
            "metrics_baseline": metrics_baseline,
        }

        snap_id = await self._store.create_snapshot(experiment_id, snapshot_data)
        logger.info(
            "Captured snapshot %s for experiment %s (%d prompts, %d tool configs)",
            snap_id,
            experiment_id,
            len(prompts),
            len(tool_configs),
        )
        return snap_id

    async def restore(self, experiment_id: UUID) -> None:
        """Restore system state from the snapshot taken for *experiment_id*.

        Raises ``ValueError`` if no snapshot exists for the experiment.
        """
        row = await self._store.get_snapshot(experiment_id)
        if row is None:
            raise ValueError(f"No snapshot found for experiment {experiment_id}")

        raw = row["snapshot_data"]
        data = json.loads(raw) if isinstance(raw, str) else raw

        for agent_type, prompt_text in data.get("prompts", {}).items():
            await self._store.set_prompt(agent_type, prompt_text)

        for tool_id, config in data.get("tool_configs", {}).items():
            await self._store.set_tool_config(tool_id, config)

        logger.info(
            "Restored snapshot for experiment %s (%d prompts, %d tool configs)",
            experiment_id,
            len(data.get("prompts", {})),
            len(data.get("tool_configs", {})),
        )
