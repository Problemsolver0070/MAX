"""Continuous compaction engine — relevance scoring and tier management."""

from __future__ import annotations

import logging
import math

from max.memory.models import CompactionTier

logger = logging.getLogger(__name__)


class CompactionEngine:
    """Manages relevance-based compaction of memory items.

    CRITICAL CONSTRAINT: No hard cuts, ever. Content transitions through
    tiers smoothly. Even under maximum pressure, the system summarizes
    faster but never drops content.
    """

    @staticmethod
    def calculate_relevance(
        base_relevance: float,
        hours_since_last_access: float,
        access_count: int,
        max_access_count: int,
        decay_rate: float,
        is_anchored: bool,
    ) -> float:
        """Calculate current relevance score for a memory item.

        relevance = base_relevance * recency_factor * usage_factor * anchor_boost
        """
        recency_factor = math.exp(-decay_rate * hours_since_last_access)
        if max_access_count > 0:
            usage_factor = math.log(1 + access_count) / math.log(1 + max_access_count)
        else:
            usage_factor = 1.0
        anchor_boost = 10.0 if is_anchored else 1.0
        return min(1.0, base_relevance * recency_factor * usage_factor * anchor_boost)

    @staticmethod
    def determine_tier(relevance: float) -> CompactionTier:
        """Determine the compaction tier for a given relevance score."""
        if relevance > 0.7:
            return CompactionTier.FULL
        if relevance > 0.3:
            return CompactionTier.SUMMARIZED
        if relevance > 0.1:
            return CompactionTier.POINTER
        return CompactionTier.COLD_ONLY

    @staticmethod
    def pressure_multiplier(pressure: float) -> float:
        """Calculate the decay rate multiplier based on memory pressure.

        pressure = current_warm_tokens / budget_limit (0.0 to 1.0+)

        Soft budget: gradually increases decay rates, NEVER hard-cuts.
        """
        if pressure < 0.7:
            return 1.0
        if pressure < 0.9:
            return 1.0 + (pressure - 0.7) * 3.0
        return 1.6 + (pressure - 0.9) * 10.0

    @staticmethod
    def promotion_boost(current_relevance: float) -> float:
        """Boost relevance when a cold/low-tier item is retrieved."""
        return min(1.0, current_relevance + 0.4)
