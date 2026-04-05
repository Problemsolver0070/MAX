"""Tests for Phase 7 Evolution System config additions."""

from max.config import Settings


def test_evolution_config_defaults(settings):
    """All evolution config fields have correct defaults."""
    assert settings.evolution_scout_interval_hours == 6
    assert settings.evolution_canary_replay_count == 5
    assert settings.evolution_min_priority == 0.3
    assert settings.evolution_max_concurrent == 1
    assert settings.evolution_freeze_consecutive_drops == 2
    assert settings.evolution_preference_refresh_signals == 10
    assert settings.evolution_canary_timeout_seconds == 300
    assert settings.evolution_snapshot_retention_days == 30


def test_evolution_scout_interval_override(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    monkeypatch.setenv("EVOLUTION_SCOUT_INTERVAL_HOURS", "12")
    s = Settings()
    assert s.evolution_scout_interval_hours == 12


def test_evolution_canary_replay_count_override(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    monkeypatch.setenv("EVOLUTION_CANARY_REPLAY_COUNT", "10")
    s = Settings()
    assert s.evolution_canary_replay_count == 10


def test_evolution_min_priority_override(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    monkeypatch.setenv("EVOLUTION_MIN_PRIORITY", "0.5")
    s = Settings()
    assert s.evolution_min_priority == 0.5


def test_evolution_max_concurrent_override(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    monkeypatch.setenv("EVOLUTION_MAX_CONCURRENT", "3")
    s = Settings()
    assert s.evolution_max_concurrent == 3


def test_evolution_freeze_consecutive_drops_override(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    monkeypatch.setenv("EVOLUTION_FREEZE_CONSECUTIVE_DROPS", "5")
    s = Settings()
    assert s.evolution_freeze_consecutive_drops == 5


def test_evolution_preference_refresh_signals_override(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    monkeypatch.setenv("EVOLUTION_PREFERENCE_REFRESH_SIGNALS", "20")
    s = Settings()
    assert s.evolution_preference_refresh_signals == 20


def test_evolution_canary_timeout_override(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    monkeypatch.setenv("EVOLUTION_CANARY_TIMEOUT_SECONDS", "600")
    s = Settings()
    assert s.evolution_canary_timeout_seconds == 600


def test_evolution_snapshot_retention_override(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    monkeypatch.setenv("EVOLUTION_SNAPSHOT_RETENTION_DAYS", "90")
    s = Settings()
    assert s.evolution_snapshot_retention_days == 90
