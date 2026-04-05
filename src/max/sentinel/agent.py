"""SentinelAgent -- bus integration and scheduled monitoring for the Sentinel."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from max.bus.message_bus import MessageBus
    from max.sentinel.benchmarks import BenchmarkRegistry
    from max.sentinel.scorer import SentinelScorer
    from max.sentinel.store import SentinelStore

logger = logging.getLogger(__name__)


class SentinelAgent:
    """Provides bus-based access to the Sentinel scorer and scheduled monitoring."""

    def __init__(
        self,
        bus: MessageBus,
        scorer: SentinelScorer,
        registry: BenchmarkRegistry,
        store: SentinelStore,
    ) -> None:
        self._bus = bus
        self._scorer = scorer
        self._registry = registry
        self._store = store

    async def start(self) -> None:
        """Subscribe to bus channels and seed benchmarks."""
        await self._registry.seed(self._store)
        await self._bus.subscribe("sentinel.run_request", self._on_run_request)
        logger.info("SentinelAgent started and subscribed to bus channels")

    async def stop(self) -> None:
        """Unsubscribe from bus channels."""
        await self._bus.unsubscribe("sentinel.run_request", self._on_run_request)
        logger.info("SentinelAgent stopped")

    async def _on_run_request(
        self, channel: str, data: dict[str, Any]
    ) -> None:
        """Handle a sentinel run request from the bus."""
        try:
            exp_id_str = data.get("experiment_id")
            exp_id = uuid.UUID(exp_id_str) if exp_id_str else None
            run_type = data.get("run_type", "baseline")

            if run_type == "baseline" and exp_id is not None:
                run_id = await self._scorer.run_baseline(exp_id)
                await self._bus.publish(
                    "sentinel.baseline_complete",
                    {"experiment_id": str(exp_id), "run_id": str(run_id)},
                )
            elif run_type == "candidate" and exp_id is not None:
                run_id = await self._scorer.run_candidate(exp_id)
                await self._bus.publish(
                    "sentinel.candidate_complete",
                    {"experiment_id": str(exp_id), "run_id": str(run_id)},
                )
            elif run_type == "verdict" and exp_id is not None:
                verdict = await self._scorer.compare_and_verdict(exp_id)
                await self._bus.publish(
                    "sentinel.verdict",
                    verdict.model_dump(mode="json"),
                )
            else:
                logger.warning(
                    "Unknown sentinel run_type: %s (experiment_id: %s)",
                    run_type,
                    exp_id,
                )

        except Exception:
            logger.exception("Error handling sentinel run request")

    async def run_scheduled_monitoring(self) -> uuid.UUID:
        """Run the benchmark suite for trend monitoring. Publishes summary to bus."""
        run_id = await self._scorer.run_scheduled()
        cap_scores = await self._store.get_capability_scores(run_id)
        scores_dict = {c["capability"]: c["aggregate_score"] for c in cap_scores}

        await self._bus.publish(
            "sentinel.scheduled_complete",
            {
                "run_id": str(run_id),
                "capability_scores": scores_dict,
            },
        )
        logger.info("Scheduled monitoring run %s complete", run_id)
        return run_id
