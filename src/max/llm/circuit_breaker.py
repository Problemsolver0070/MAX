"""Circuit breaker for LLM API calls.

Prevents cascading failures when the Anthropic API is down or rate-limited.
States: CLOSED (normal) -> OPEN (failing fast) -> HALF_OPEN (testing) -> CLOSED.
"""

from __future__ import annotations

import enum
import logging
import threading
import time

logger = logging.getLogger(__name__)


class CircuitState(enum.Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpen(Exception):  # noqa: N818 — conventional name for circuit breaker pattern
    """Raised when a call is attempted while the circuit is open."""

    def __init__(self, retry_after: float = 0.0) -> None:
        self.retry_after = retry_after
        super().__init__(f"Circuit breaker is OPEN. Retry after {retry_after:.1f}s.")


class CircuitBreaker:
    """Circuit breaker state machine for protecting external API calls.

    Args:
        threshold: Number of consecutive failures before opening.
        cooldown_seconds: Seconds to wait in OPEN state before trying HALF_OPEN.
    """

    def __init__(self, threshold: int = 5, cooldown_seconds: float = 60.0) -> None:
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds

        self._failure_count: int = 0
        self._state: CircuitState = CircuitState.CLOSED
        self._opened_at: float = 0.0
        self._half_open_allowed: bool = False
        self._lock = threading.Lock()

    @property
    def failure_count(self) -> int:
        """Current consecutive failure count."""
        with self._lock:
            return self._failure_count

    @property
    def state(self) -> CircuitState:
        """Current state, accounting for cooldown expiry."""
        with self._lock:
            if (
                self._state == CircuitState.OPEN
                and time.monotonic() - self._opened_at >= self.cooldown_seconds
            ):
                self._state = CircuitState.HALF_OPEN
                self._half_open_allowed = True
                logger.info("Circuit breaker transitioned to HALF_OPEN")
            return self._state

    @property
    def state_gauge(self) -> int:
        """Numeric state for metrics: 0=closed, 1=open, 2=half_open."""
        state = self.state
        if state == CircuitState.CLOSED:
            return 0
        if state == CircuitState.OPEN:
            return 1
        return 2

    def check(self) -> None:
        """Check if a request is allowed. Raises CircuitBreakerOpen if not."""
        with self._lock:
            # Inline the OPEN->HALF_OPEN transition check
            if (
                self._state == CircuitState.OPEN
                and time.monotonic() - self._opened_at >= self.cooldown_seconds
            ):
                self._state = CircuitState.HALF_OPEN
                self._half_open_allowed = True
                logger.info("Circuit breaker transitioned to HALF_OPEN")

            if self._state == CircuitState.CLOSED:
                return
            if self._state == CircuitState.HALF_OPEN and self._half_open_allowed:
                self._half_open_allowed = False
                return

            remaining = self.cooldown_seconds - (time.monotonic() - self._opened_at)
            raise CircuitBreakerOpen(retry_after=max(0.0, remaining))

    def record_success(self) -> None:
        """Record a successful call. Resets failure count, closes circuit."""
        with self._lock:
            self._failure_count = 0
            if self._state in (CircuitState.HALF_OPEN, CircuitState.OPEN):
                logger.info("Circuit breaker CLOSED after successful call")
            self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Record a failed call. May open the circuit."""
        with self._lock:
            self._failure_count += 1
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                self._half_open_allowed = False
                logger.warning(
                    "Circuit breaker re-OPENED from HALF_OPEN (failure_count=%d)",
                    self._failure_count,
                )
            elif self._failure_count >= self.threshold:
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                self._half_open_allowed = False
                logger.warning(
                    "Circuit breaker OPENED after %d consecutive failures",
                    self._failure_count,
                )
