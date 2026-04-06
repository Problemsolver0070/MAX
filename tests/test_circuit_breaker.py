"""Tests for LLM circuit breaker."""

from __future__ import annotations

import time

import pytest

from max.llm.circuit_breaker import CircuitBreaker, CircuitBreakerOpen, CircuitState


class TestCircuitBreakerInit:
    def test_starts_closed(self):
        cb = CircuitBreaker(threshold=5, cooldown_seconds=60)
        assert cb.state == CircuitState.CLOSED

    def test_custom_threshold(self):
        cb = CircuitBreaker(threshold=10, cooldown_seconds=30)
        assert cb.threshold == 10
        assert cb.cooldown_seconds == 30

    def test_initial_failure_count_zero(self):
        cb = CircuitBreaker(threshold=5, cooldown_seconds=60)
        assert cb.failure_count == 0


class TestClosedState:
    def test_record_success_resets_count(self):
        cb = CircuitBreaker(threshold=5, cooldown_seconds=60)
        cb._failure_count = 3
        cb.record_success()
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED

    def test_record_failure_increments_count(self):
        cb = CircuitBreaker(threshold=5, cooldown_seconds=60)
        cb.record_failure()
        assert cb.failure_count == 1
        assert cb.state == CircuitState.CLOSED

    def test_check_passes_when_closed(self):
        cb = CircuitBreaker(threshold=5, cooldown_seconds=60)
        cb.check()  # should not raise

    def test_transitions_to_open_at_threshold(self):
        cb = CircuitBreaker(threshold=3, cooldown_seconds=60)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN


class TestOpenState:
    def test_check_raises_when_open(self):
        cb = CircuitBreaker(threshold=1, cooldown_seconds=60)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        with pytest.raises(CircuitBreakerOpen):
            cb.check()

    def test_transitions_to_half_open_after_cooldown(self):
        cb = CircuitBreaker(threshold=1, cooldown_seconds=0.1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

    def test_check_passes_when_half_open(self):
        cb = CircuitBreaker(threshold=1, cooldown_seconds=0.1)
        cb.record_failure()
        time.sleep(0.15)
        cb.check()  # should not raise (allows one test request)


class TestHalfOpenState:
    def test_success_transitions_to_closed(self):
        cb = CircuitBreaker(threshold=1, cooldown_seconds=0.1)
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_failure_transitions_back_to_open(self):
        cb = CircuitBreaker(threshold=1, cooldown_seconds=0.1)
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_only_one_request_allowed_in_half_open(self):
        cb = CircuitBreaker(threshold=1, cooldown_seconds=0.1)
        cb.record_failure()
        time.sleep(0.15)
        cb.check()  # first call succeeds
        with pytest.raises(CircuitBreakerOpen):
            cb.check()  # second call blocked until verdict


class TestStateProperty:
    def test_state_gauge_value_closed(self):
        cb = CircuitBreaker(threshold=5, cooldown_seconds=60)
        assert cb.state_gauge == 0

    def test_state_gauge_value_open(self):
        cb = CircuitBreaker(threshold=1, cooldown_seconds=60)
        cb.record_failure()
        assert cb.state_gauge == 1

    def test_state_gauge_value_half_open(self):
        cb = CircuitBreaker(threshold=1, cooldown_seconds=0.1)
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state_gauge == 2
