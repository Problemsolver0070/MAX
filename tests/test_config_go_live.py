"""Tests for go-live infrastructure config fields."""

from __future__ import annotations

import pytest

from max.config import Settings


@pytest.fixture
def go_live_settings():
    """Create Settings with required env vars."""
    env = {
        "ANTHROPIC_API_KEY": "test-key",
        "POSTGRES_PASSWORD": "test-pass",
    }
    with pytest.MonkeyPatch.context() as mp:
        for k, v in env.items():
            mp.setenv(k, v)
        yield Settings()


class TestBusConfig:
    def test_bus_transport_default(self, go_live_settings):
        assert go_live_settings.bus_transport == "streams"

    def test_bus_dead_letter_max_retries_default(self, go_live_settings):
        assert go_live_settings.bus_dead_letter_max_retries == 3

    def test_bus_stream_max_len_default(self, go_live_settings):
        assert go_live_settings.bus_stream_max_len == 10000

    def test_bus_consumer_group_default(self, go_live_settings):
        assert go_live_settings.bus_consumer_group == "max_workers"

    def test_bus_consumer_name_default(self, go_live_settings):
        assert go_live_settings.bus_consumer_name == "worker-1"


class TestCircuitBreakerConfig:
    def test_llm_circuit_breaker_threshold_default(self, go_live_settings):
        assert go_live_settings.llm_circuit_breaker_threshold == 5

    def test_llm_circuit_breaker_cooldown_default(self, go_live_settings):
        assert go_live_settings.llm_circuit_breaker_cooldown_seconds == 60


class TestSchedulerConfig:
    def test_task_recovery_enabled_default(self, go_live_settings):
        assert go_live_settings.task_recovery_enabled is True

    def test_task_timeout_watchdog_interval_default(self, go_live_settings):
        assert go_live_settings.task_timeout_watchdog_interval_seconds == 60


class TestApiConfig:
    def test_max_host_default(self, go_live_settings):
        assert go_live_settings.max_host == "0.0.0.0"

    def test_max_port_default(self, go_live_settings):
        assert go_live_settings.max_port == 8080

    def test_max_api_keys_default(self, go_live_settings):
        assert go_live_settings.max_api_keys == ""

    def test_rate_limit_api_default(self, go_live_settings):
        assert go_live_settings.rate_limit_api == "60/minute"

    def test_rate_limit_messaging_default(self, go_live_settings):
        assert go_live_settings.rate_limit_messaging == "30/minute"


class TestObservabilityConfig:
    def test_otel_enabled_default(self, go_live_settings):
        assert go_live_settings.otel_enabled is False

    def test_otel_service_name_default(self, go_live_settings):
        assert go_live_settings.otel_service_name == "max"

    def test_otel_exporter_endpoint_default(self, go_live_settings):
        assert go_live_settings.otel_exporter_endpoint == ""


class TestAzureConfig:
    def test_azure_key_vault_url_default(self, go_live_settings):
        assert go_live_settings.azure_key_vault_url == ""


class TestOverrideViaEnv:
    def test_override_bus_and_api_settings(self):
        env = {
            "ANTHROPIC_API_KEY": "test-key",
            "POSTGRES_PASSWORD": "test-pass",
            "BUS_TRANSPORT": "pubsub",
            "MAX_PORT": "9090",
            "LLM_CIRCUIT_BREAKER_THRESHOLD": "10",
            "OTEL_ENABLED": "true",
        }
        with pytest.MonkeyPatch.context() as mp:
            for k, v in env.items():
                mp.setenv(k, v)
            settings = Settings()
        assert settings.bus_transport == "pubsub"
        assert settings.max_port == 9090
        assert settings.llm_circuit_breaker_threshold == 10
        assert settings.otel_enabled is True
