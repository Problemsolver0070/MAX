"""Tests for compaction engine."""

from __future__ import annotations

import pytest

from max.memory.compaction import CompactionEngine
from max.memory.models import CompactionTier


class TestRelevanceScoring:
    def test_fresh_item_high_relevance(self):
        score = CompactionEngine.calculate_relevance(
            base_relevance=0.8,
            hours_since_last_access=0.0,
            access_count=5,
            max_access_count=10,
            decay_rate=0.01,
            is_anchored=False,
        )
        assert score > 0.5

    def test_old_item_decays(self):
        fresh = CompactionEngine.calculate_relevance(
            base_relevance=0.8,
            hours_since_last_access=0.0,
            access_count=1,
            max_access_count=10,
            decay_rate=0.05,
            is_anchored=False,
        )
        old = CompactionEngine.calculate_relevance(
            base_relevance=0.8,
            hours_since_last_access=48.0,
            access_count=1,
            max_access_count=10,
            decay_rate=0.05,
            is_anchored=False,
        )
        assert old < fresh

    def test_anchored_item_boosted(self):
        normal = CompactionEngine.calculate_relevance(
            base_relevance=0.3,
            hours_since_last_access=24.0,
            access_count=1,
            max_access_count=10,
            decay_rate=0.05,
            is_anchored=False,
        )
        anchored = CompactionEngine.calculate_relevance(
            base_relevance=0.3,
            hours_since_last_access=24.0,
            access_count=1,
            max_access_count=10,
            decay_rate=0.05,
            is_anchored=True,
        )
        assert anchored > normal
        assert anchored >= normal * 9  # anchor_boost = 10x

    def test_frequently_accessed_higher(self):
        low_access = CompactionEngine.calculate_relevance(
            base_relevance=0.5,
            hours_since_last_access=5.0,
            access_count=1,
            max_access_count=100,
            decay_rate=0.01,
            is_anchored=False,
        )
        high_access = CompactionEngine.calculate_relevance(
            base_relevance=0.5,
            hours_since_last_access=5.0,
            access_count=50,
            max_access_count=100,
            decay_rate=0.01,
            is_anchored=False,
        )
        assert high_access > low_access


class TestTierDetermination:
    def test_high_relevance_full_tier(self):
        assert CompactionEngine.determine_tier(0.85) == CompactionTier.FULL

    def test_mid_relevance_summarized_tier(self):
        assert CompactionEngine.determine_tier(0.5) == CompactionTier.SUMMARIZED

    def test_low_relevance_pointer_tier(self):
        assert CompactionEngine.determine_tier(0.2) == CompactionTier.POINTER

    def test_very_low_relevance_cold_tier(self):
        assert CompactionEngine.determine_tier(0.05) == CompactionTier.COLD_ONLY

    def test_boundary_values(self):
        assert CompactionEngine.determine_tier(0.7) == CompactionTier.SUMMARIZED
        assert CompactionEngine.determine_tier(0.71) == CompactionTier.FULL
        assert CompactionEngine.determine_tier(0.3) == CompactionTier.POINTER
        assert CompactionEngine.determine_tier(0.31) == CompactionTier.SUMMARIZED
        assert CompactionEngine.determine_tier(0.1) == CompactionTier.COLD_ONLY
        assert CompactionEngine.determine_tier(0.11) == CompactionTier.POINTER


class TestPressureMultiplier:
    def test_low_pressure(self):
        assert CompactionEngine.pressure_multiplier(0.5) == pytest.approx(1.0)

    def test_medium_pressure(self):
        mult = CompactionEngine.pressure_multiplier(0.8)
        assert mult > 1.0
        assert mult < 1.6

    def test_high_pressure(self):
        mult = CompactionEngine.pressure_multiplier(0.95)
        assert mult > 1.6

    def test_no_pressure(self):
        assert CompactionEngine.pressure_multiplier(0.0) == pytest.approx(1.0)


class TestPromotionBoost:
    def test_boost_within_bounds(self):
        boosted = CompactionEngine.promotion_boost(0.05)
        assert boosted == pytest.approx(0.45)

    def test_boost_capped_at_one(self):
        boosted = CompactionEngine.promotion_boost(0.8)
        assert boosted == pytest.approx(1.0)
