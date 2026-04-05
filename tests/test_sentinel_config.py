"""Tests for Sentinel config fields."""

from __future__ import annotations

import os

import pytest

from max.config import Settings


@pytest.fixture
def sentinel_settings():
    """Create Settings with required env vars."""
    env = {
        "ANTHROPIC_API_KEY": "test-key",
        "POSTGRES_PASSWORD": "test-pass",
    }
    with pytest.MonkeyPatch.context() as mp:
        for k, v in env.items():
            mp.setenv(k, v)
        yield Settings()


class TestSentinelConfig:
    def test_sentinel_model_default(self, sentinel_settings):
        assert sentinel_settings.sentinel_model == "claude-opus-4-6"

    def test_sentinel_replay_count_default(self, sentinel_settings):
        assert sentinel_settings.sentinel_replay_count == 10

    def test_sentinel_monitor_interval_hours_default(self, sentinel_settings):
        assert sentinel_settings.sentinel_monitor_interval_hours == 12

    def test_sentinel_timeout_seconds_default(self, sentinel_settings):
        assert sentinel_settings.sentinel_timeout_seconds == 600

    def test_sentinel_judge_temperature_default(self, sentinel_settings):
        assert sentinel_settings.sentinel_judge_temperature == 0.0

    def test_override_via_env(self):
        env = {
            "ANTHROPIC_API_KEY": "test-key",
            "POSTGRES_PASSWORD": "test-pass",
            "SENTINEL_REPLAY_COUNT": "20",
            "SENTINEL_MONITOR_INTERVAL_HOURS": "6",
        }
        with pytest.MonkeyPatch.context() as mp:
            for k, v in env.items():
                mp.setenv(k, v)
            settings = Settings()
        assert settings.sentinel_replay_count == 20
        assert settings.sentinel_monitor_interval_hours == 6
