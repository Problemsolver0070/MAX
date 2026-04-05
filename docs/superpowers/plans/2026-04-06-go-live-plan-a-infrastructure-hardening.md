# Go-Live Plan A: Infrastructure Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Max's internal infrastructure to be product-grade: durable Redis Streams bus, circuit breaker on LLM client, database-backed scheduler, structured logging with correlation IDs, and OpenTelemetry metrics.

**Architecture:** Replace the fire-and-forget Redis pub/sub bus with Redis Streams (consumer groups, acknowledgment, dead letter). Wrap the LLM client with a circuit breaker (closed/open/half-open). Add a scheduler that persists run timestamps to the database so it survives restarts. Add JSON structured logging with correlation IDs that trace requests across agents. Add OpenTelemetry metrics for messages, agents, LLM usage, and bus activity.

**Tech Stack:** Python 3.12, asyncpg, redis[hiredis] (Streams), opentelemetry-api, opentelemetry-sdk, pydantic-settings

**Spec:** `docs/superpowers/specs/2026-04-05-max-go-live-design.md` (Sections 5, 8, 9.1, 9.2)

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `src/max/bus/streams.py` | Redis Streams transport: consumer groups, acknowledgment, dead letter, stream trimming |
| `src/max/llm/circuit_breaker.py` | Circuit breaker state machine: closed → open → half-open → closed |
| `src/max/scheduler.py` | Database-backed periodic job scheduler with catch-up on restart |
| `src/max/observability.py` | JSON logging configuration, correlation ID context, OpenTelemetry metrics setup |

### Modified Files

| File | Changes |
|------|---------|
| `src/max/config.py` | Add 11 new settings fields (bus, circuit breaker, scheduler, observability, API) |
| `src/max/bus/message_bus.py` | Refactor to use Streams transport (with pub/sub fallback via config) |
| `src/max/bus/__init__.py` | Export `StreamsTransport` |
| `src/max/llm/client.py` | Accept optional `CircuitBreaker`, check before each API call |
| `src/max/llm/__init__.py` | Export `CircuitBreaker` |
| `src/max/db/schema.sql` | Add `scheduler_state` table |
| `pyproject.toml` | Add opentelemetry dependencies |

### Test Files

| File | What it tests |
|------|--------------|
| `tests/test_config_go_live.py` | New config fields and defaults |
| `tests/test_streams_transport.py` | Redis Streams transport: publish, consume, ack, dead letter, trimming |
| `tests/test_message_bus_streams.py` | MessageBus with Streams backend: subscribe, publish, handler invocation, fallback |
| `tests/test_circuit_breaker.py` | Circuit breaker state transitions: closed → open → half-open → closed |
| `tests/test_llm_circuit_breaker.py` | LLMClient with circuit breaker: normal flow, open rejection, recovery |
| `tests/test_observability.py` | JSON logging format, correlation ID propagation, metrics counters |
| `tests/test_scheduler.py` | Scheduler: job registration, execution, DB persistence, catch-up on restart |
| `tests/test_infra_integration.py` | Integration: bus + circuit breaker + scheduler + observability working together |

---

## Task 1: Config Additions

**Files:**
- Modify: `src/max/config.py:124` (after sentinel fields)
- Test: `tests/test_config_go_live.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config_go_live.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'bus_transport'`

- [ ] **Step 3: Add config fields to Settings**

Add the following block to `src/max/config.py` after line 124 (after `sentinel_judge_temperature`), before the `@property` line:

```python
    # ── Go-Live Infrastructure ─────────────────────────────────────────
    # API Server
    max_host: str = "0.0.0.0"
    max_port: int = 8080
    max_api_keys: str = ""  # comma-separated valid API keys

    # Rate Limiting
    rate_limit_api: str = "60/minute"
    rate_limit_messaging: str = "30/minute"

    # Circuit Breaker
    llm_circuit_breaker_threshold: int = 5
    llm_circuit_breaker_cooldown_seconds: int = 60

    # Bus Transport
    bus_transport: str = "streams"  # "streams" or "pubsub"
    bus_dead_letter_max_retries: int = 3
    bus_stream_max_len: int = 10000
    bus_consumer_group: str = "max_workers"
    bus_consumer_name: str = "worker-1"

    # Task Recovery
    task_recovery_enabled: bool = True
    task_timeout_watchdog_interval_seconds: int = 60

    # Observability
    otel_enabled: bool = False
    otel_service_name: str = "max"
    otel_exporter_endpoint: str = ""

    # Azure
    azure_key_vault_url: str = ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config_go_live.py -v`
Expected: ALL PASS (22 tests)

- [ ] **Step 5: Commit**

```bash
git add src/max/config.py tests/test_config_go_live.py
git commit -m "feat(config): add go-live infrastructure settings (bus, circuit breaker, scheduler, API, otel)"
```

---

## Task 2: Circuit Breaker

**Files:**
- Create: `src/max/llm/circuit_breaker.py`
- Test: `tests/test_circuit_breaker.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for LLM circuit breaker."""

from __future__ import annotations

import asyncio
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_circuit_breaker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'max.llm.circuit_breaker'`

- [ ] **Step 3: Implement the circuit breaker**

Create `src/max/llm/circuit_breaker.py`:

```python
"""Circuit breaker for LLM API calls.

Prevents cascading failures when the Anthropic API is down or rate-limited.
States: CLOSED (normal) → OPEN (failing fast) → HALF_OPEN (testing) → CLOSED.
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


class CircuitBreakerOpen(Exception):
    """Raised when a call is attempted while the circuit is open."""

    def __init__(self, retry_after: float = 0.0) -> None:
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker is OPEN. Retry after {retry_after:.1f}s."
        )


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
        state = self.state
        if state == CircuitState.CLOSED:
            return
        if state == CircuitState.HALF_OPEN:
            with self._lock:
                if self._half_open_allowed:
                    self._half_open_allowed = False
                    return
            remaining = self.cooldown_seconds - (
                time.monotonic() - self._opened_at
            )
            raise CircuitBreakerOpen(retry_after=max(0.0, remaining))
        # OPEN
        remaining = self.cooldown_seconds - (
            time.monotonic() - self._opened_at
        )
        raise CircuitBreakerOpen(retry_after=max(0.0, remaining))

    def record_success(self) -> None:
        """Record a successful call. Resets failure count, closes circuit."""
        with self._lock:
            self._failure_count = 0
            if self._state in (CircuitState.HALF_OPEN, CircuitState.OPEN):
                logger.info(
                    "Circuit breaker CLOSED after successful call"
                )
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
                    "Circuit breaker re-OPENED from HALF_OPEN "
                    "(failure_count=%d)",
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_circuit_breaker.py -v`
Expected: ALL PASS (15 tests)

- [ ] **Step 5: Commit**

```bash
git add src/max/llm/circuit_breaker.py tests/test_circuit_breaker.py
git commit -m "feat(llm): add circuit breaker with closed/open/half-open state machine"
```

---

## Task 3: LLM Client Circuit Breaker Integration

**Files:**
- Modify: `src/max/llm/client.py:16-21` (constructor), `src/max/llm/client.py:27-34` (complete method)
- Modify: `src/max/llm/__init__.py` (export CircuitBreaker)
- Test: `tests/test_llm_circuit_breaker.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for LLMClient with circuit breaker integration."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from max.llm.circuit_breaker import CircuitBreaker, CircuitBreakerOpen, CircuitState
from max.llm.client import LLMClient
from max.llm.errors import LLMConnectionError


@pytest.fixture
def circuit_breaker():
    return CircuitBreaker(threshold=3, cooldown_seconds=60)


@pytest.fixture
def client_with_cb(circuit_breaker):
    return LLMClient(
        api_key="test-key",
        circuit_breaker=circuit_breaker,
    )


@pytest.fixture
def client_without_cb():
    return LLMClient(api_key="test-key")


class TestClientAcceptsCircuitBreaker:
    def test_constructor_accepts_circuit_breaker(self, client_with_cb, circuit_breaker):
        assert client_with_cb._circuit_breaker is circuit_breaker

    def test_constructor_works_without_circuit_breaker(self, client_without_cb):
        assert client_without_cb._circuit_breaker is None


class TestCircuitBreakerBlocking:
    async def test_raises_when_circuit_open(self, client_with_cb, circuit_breaker):
        # Force circuit open
        for _ in range(3):
            circuit_breaker.record_failure()
        assert circuit_breaker.state == CircuitState.OPEN

        with pytest.raises(CircuitBreakerOpen):
            await client_with_cb.complete(
                messages=[{"role": "user", "content": "hello"}]
            )

    async def test_no_api_call_when_circuit_open(self, client_with_cb, circuit_breaker):
        for _ in range(3):
            circuit_breaker.record_failure()

        with patch.object(client_with_cb._client.messages, "create") as mock_create:
            with pytest.raises(CircuitBreakerOpen):
                await client_with_cb.complete(
                    messages=[{"role": "user", "content": "hello"}]
                )
            mock_create.assert_not_called()


class TestCircuitBreakerRecording:
    async def test_records_success_on_successful_call(self, client_with_cb, circuit_breaker):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="hi")]
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5

        with patch.object(
            client_with_cb._client.messages,
            "create",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            await client_with_cb.complete(
                messages=[{"role": "user", "content": "hello"}]
            )
        assert circuit_breaker.failure_count == 0

    async def test_records_failure_on_connection_error(
        self, client_with_cb, circuit_breaker
    ):
        import anthropic

        with patch.object(
            client_with_cb._client.messages,
            "create",
            new_callable=AsyncMock,
            side_effect=anthropic.APIConnectionError(request=MagicMock()),
        ):
            with pytest.raises(LLMConnectionError):
                await client_with_cb.complete(
                    messages=[{"role": "user", "content": "hello"}]
                )
        assert circuit_breaker.failure_count == 1


class TestWithoutCircuitBreaker:
    async def test_works_normally_without_cb(self, client_without_cb):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="hi")]
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5

        with patch.object(
            client_without_cb._client.messages,
            "create",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await client_without_cb.complete(
                messages=[{"role": "user", "content": "hello"}]
            )
        assert result.text == "hi"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_llm_circuit_breaker.py -v`
Expected: FAIL — `TypeError: LLMClient.__init__() got an unexpected keyword argument 'circuit_breaker'`

- [ ] **Step 3: Modify LLMClient to accept and use circuit breaker**

Read `src/max/llm/client.py` first. Then modify:

In `__init__` (around line 16), add `circuit_breaker` parameter:

```python
    def __init__(
        self,
        api_key: str,
        default_model: ModelType = ModelType.OPUS,
        max_retries: int = 3,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self._client = AsyncAnthropic(api_key=api_key, max_retries=max_retries)
        self.default_model = default_model
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self._circuit_breaker = circuit_breaker
```

Add import at the top of the file:

```python
from max.llm.circuit_breaker import CircuitBreaker, CircuitBreakerOpen
```

In the `complete` method, add circuit breaker check at the very start (before building kwargs):

```python
    async def complete(self, ...) -> LLMResponse:
        # Circuit breaker gate
        if self._circuit_breaker is not None:
            self._circuit_breaker.check()

        # ... existing kwargs building code ...
```

In the `complete` method, after the successful response (after token accumulation, before return), add:

```python
        # Record success
        if self._circuit_breaker is not None:
            self._circuit_breaker.record_success()

        return LLMResponse(...)
```

In each exception handler (RateLimitError, ConnectionError, AuthError, StatusError), add before re-raising:

```python
        if self._circuit_breaker is not None:
            self._circuit_breaker.record_failure()
```

- [ ] **Step 4: Update `src/max/llm/__init__.py` exports**

Add `CircuitBreaker`, `CircuitBreakerOpen`, and `CircuitState` to the exports:

```python
from max.llm.circuit_breaker import CircuitBreaker, CircuitBreakerOpen, CircuitState

__all__ = [
    "CircuitBreaker",
    "CircuitBreakerOpen",
    "CircuitState",
    "LLMAuthError",
    "LLMClient",
    "LLMConnectionError",
    "LLMError",
    "LLMRateLimitError",
    "LLMResponse",
    "ModelType",
    "ToolCall",
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm_circuit_breaker.py tests/test_circuit_breaker.py -v`
Expected: ALL PASS

Also verify existing LLM tests still pass:
Run: `uv run pytest tests/test_llm*.py -v`
Expected: ALL PASS (zero regressions — circuit_breaker defaults to None)

- [ ] **Step 6: Commit**

```bash
git add src/max/llm/client.py src/max/llm/__init__.py src/max/llm/circuit_breaker.py tests/test_llm_circuit_breaker.py
git commit -m "feat(llm): integrate circuit breaker into LLMClient"
```

---

## Task 4: Redis Streams Transport

**Files:**
- Create: `src/max/bus/streams.py`
- Test: `tests/test_streams_transport.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for Redis Streams transport layer."""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from max.bus.streams import StreamsTransport


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.xadd = AsyncMock(return_value=b"1234567890-0")
    redis.xreadgroup = AsyncMock(return_value=[])
    redis.xack = AsyncMock(return_value=1)
    redis.xgroup_create = AsyncMock()
    redis.xlen = AsyncMock(return_value=0)
    redis.xtrim = AsyncMock()
    redis.xinfo_groups = AsyncMock(return_value=[])
    redis.xrange = AsyncMock(return_value=[])
    redis.xpending_range = AsyncMock(return_value=[])
    return redis


@pytest.fixture
def transport(mock_redis):
    return StreamsTransport(
        redis_client=mock_redis,
        consumer_group="test_group",
        consumer_name="test_worker",
        max_retries=3,
        stream_max_len=1000,
    )


class TestPublish:
    async def test_publishes_to_stream(self, transport, mock_redis):
        await transport.publish("test_channel", {"key": "value"})
        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "stream:test_channel"
        fields = call_args[0][1]
        assert "data" in fields
        parsed = json.loads(fields["data"])
        assert parsed["key"] == "value"

    async def test_publish_includes_message_id(self, transport, mock_redis):
        await transport.publish("ch", {"x": 1})
        call_args = mock_redis.xadd.call_args
        fields = call_args[0][1]
        assert "message_id" in fields

    async def test_publish_trims_stream(self, transport, mock_redis):
        await transport.publish("ch", {"x": 1})
        call_args = mock_redis.xadd.call_args
        assert call_args[1].get("maxlen") == 1000 or "maxlen" in str(call_args)


class TestConsumerGroupSetup:
    async def test_creates_consumer_group(self, transport, mock_redis):
        await transport.ensure_group("test_channel")
        mock_redis.xgroup_create.assert_called_once_with(
            "stream:test_channel",
            "test_group",
            id="0",
            mkstream=True,
        )

    async def test_ignores_existing_group(self, transport, mock_redis):
        from redis.exceptions import ResponseError

        mock_redis.xgroup_create.side_effect = ResponseError("BUSYGROUP")
        await transport.ensure_group("test_channel")  # should not raise


class TestConsume:
    async def test_calls_xreadgroup(self, transport, mock_redis):
        mock_redis.xreadgroup.return_value = []
        messages = await transport.read_messages(["test_channel"], timeout_ms=100)
        mock_redis.xreadgroup.assert_called_once()
        assert messages == []

    async def test_parses_stream_messages(self, transport, mock_redis):
        mock_redis.xreadgroup.return_value = [
            (
                b"stream:test_channel",
                [
                    (
                        b"1234-0",
                        {
                            b"data": json.dumps({"key": "value"}).encode(),
                            b"message_id": b"abc-123",
                        },
                    )
                ],
            )
        ]
        messages = await transport.read_messages(["test_channel"], timeout_ms=100)
        assert len(messages) == 1
        assert messages[0]["channel"] == "test_channel"
        assert messages[0]["data"]["key"] == "value"
        assert messages[0]["stream_id"] == "1234-0"


class TestAcknowledge:
    async def test_acknowledges_message(self, transport, mock_redis):
        await transport.ack("test_channel", "1234-0")
        mock_redis.xack.assert_called_once_with(
            "stream:test_channel", "test_group", "1234-0"
        )


class TestDeadLetter:
    async def test_sends_to_dead_letter_stream(self, transport, mock_redis):
        await transport.dead_letter(
            channel="test_channel",
            stream_id="1234-0",
            data={"key": "value"},
            error="Handler failed",
            attempt=3,
        )
        mock_redis.xadd.assert_called()
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "dead_letter:test_channel"

    async def test_dead_letter_includes_error_info(self, transport, mock_redis):
        await transport.dead_letter(
            channel="ch",
            stream_id="1-0",
            data={"x": 1},
            error="boom",
            attempt=3,
        )
        call_args = mock_redis.xadd.call_args
        fields = call_args[0][1]
        parsed = json.loads(fields["data"])
        assert parsed["original_data"]["x"] == 1
        assert parsed["error"] == "boom"
        assert parsed["attempt"] == 3


class TestGetDeadLetters:
    async def test_returns_dead_letter_entries(self, transport, mock_redis):
        mock_redis.xrange.return_value = [
            (
                b"1-0",
                {
                    b"data": json.dumps({
                        "original_data": {"x": 1},
                        "error": "boom",
                        "attempt": 3,
                        "channel": "ch",
                    }).encode()
                },
            )
        ]
        entries = await transport.get_dead_letters("ch", count=10)
        assert len(entries) == 1
        assert entries[0]["original_data"]["x"] == 1
        assert entries[0]["error"] == "boom"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_streams_transport.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'max.bus.streams'`

- [ ] **Step 3: Implement the Streams transport**

Create `src/max/bus/streams.py`:

```python
"""Redis Streams transport for the MessageBus.

Provides durable message delivery with consumer groups, acknowledgment,
and dead letter handling. Replaces fire-and-forget pub/sub.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class StreamsTransport:
    """Redis Streams transport with consumer groups and dead letter support.

    Args:
        redis_client: An async Redis client instance.
        consumer_group: Name of the consumer group (shared across replicas).
        consumer_name: Unique name for this consumer (unique per replica).
        max_retries: Max delivery attempts before dead-lettering.
        stream_max_len: Approximate max length for each stream (XTRIM MAXLEN ~).
    """

    def __init__(
        self,
        redis_client: aioredis.Redis,
        consumer_group: str = "max_workers",
        consumer_name: str = "worker-1",
        max_retries: int = 3,
        stream_max_len: int = 10000,
    ) -> None:
        self._redis = redis_client
        self._consumer_group = consumer_group
        self._consumer_name = consumer_name
        self._max_retries = max_retries
        self._stream_max_len = stream_max_len
        self._ensured_groups: set[str] = set()

    def _stream_key(self, channel: str) -> str:
        """Map a logical channel name to a Redis stream key."""
        return f"stream:{channel}"

    def _dead_letter_key(self, channel: str) -> str:
        """Map a logical channel name to its dead letter stream key."""
        return f"dead_letter:{channel}"

    async def ensure_group(self, channel: str) -> None:
        """Create a consumer group for the channel if it doesn't exist."""
        stream_key = self._stream_key(channel)
        if stream_key in self._ensured_groups:
            return
        try:
            await self._redis.xgroup_create(
                stream_key,
                self._consumer_group,
                id="0",
                mkstream=True,
            )
        except Exception as exc:
            if "BUSYGROUP" in str(exc):
                pass  # Group already exists
            else:
                raise
        self._ensured_groups.add(stream_key)

    async def publish(self, channel: str, data: dict[str, Any]) -> str:
        """Publish a message to a stream.

        Returns the stream entry ID.
        """
        stream_key = self._stream_key(channel)
        message_id = str(uuid.uuid4())
        fields = {
            "data": json.dumps(data, default=str),
            "message_id": message_id,
        }
        entry_id = await self._redis.xadd(
            stream_key,
            fields,
            maxlen=self._stream_max_len,
        )
        return entry_id if isinstance(entry_id, str) else entry_id.decode()

    async def read_messages(
        self,
        channels: list[str],
        timeout_ms: int = 1000,
    ) -> list[dict[str, Any]]:
        """Read new messages from streams using consumer group.

        Returns a list of parsed messages with channel, data, and stream_id.
        """
        streams = {
            self._stream_key(ch): ">" for ch in channels
        }
        if not streams:
            return []

        raw = await self._redis.xreadgroup(
            self._consumer_group,
            self._consumer_name,
            streams,
            count=10,
            block=timeout_ms,
        )
        if not raw:
            return []

        messages: list[dict[str, Any]] = []
        for stream_bytes, entries in raw:
            stream_name = (
                stream_bytes.decode()
                if isinstance(stream_bytes, bytes)
                else stream_bytes
            )
            # Extract channel from "stream:channel_name"
            channel = stream_name.removeprefix("stream:")

            for entry_id_bytes, fields in entries:
                entry_id = (
                    entry_id_bytes.decode()
                    if isinstance(entry_id_bytes, bytes)
                    else entry_id_bytes
                )
                data_raw = fields.get(b"data") or fields.get("data", "{}")
                if isinstance(data_raw, bytes):
                    data_raw = data_raw.decode()
                message_id_raw = (
                    fields.get(b"message_id") or fields.get("message_id", "")
                )
                if isinstance(message_id_raw, bytes):
                    message_id_raw = message_id_raw.decode()

                try:
                    data = json.loads(data_raw)
                except (json.JSONDecodeError, TypeError):
                    data = {}

                messages.append({
                    "channel": channel,
                    "data": data,
                    "stream_id": entry_id,
                    "message_id": message_id_raw,
                })

        return messages

    async def ack(self, channel: str, stream_id: str) -> None:
        """Acknowledge a processed message."""
        await self._redis.xack(
            self._stream_key(channel),
            self._consumer_group,
            stream_id,
        )

    async def dead_letter(
        self,
        channel: str,
        stream_id: str,
        data: dict[str, Any],
        error: str,
        attempt: int,
    ) -> None:
        """Move a failed message to the dead letter stream."""
        dl_key = self._dead_letter_key(channel)
        dl_data = {
            "original_data": data,
            "error": error,
            "attempt": attempt,
            "channel": channel,
            "original_stream_id": stream_id,
        }
        await self._redis.xadd(
            dl_key,
            {"data": json.dumps(dl_data, default=str)},
        )
        # Acknowledge the original message so it's not re-delivered
        await self.ack(channel, stream_id)
        logger.warning(
            "Message dead-lettered on %s (attempt %d): %s",
            channel,
            attempt,
            error,
        )

    async def get_dead_letters(
        self, channel: str, count: int = 50
    ) -> list[dict[str, Any]]:
        """Retrieve dead letter entries for a channel."""
        dl_key = self._dead_letter_key(channel)
        raw = await self._redis.xrange(dl_key, count=count)
        entries: list[dict[str, Any]] = []
        for _entry_id, fields in raw:
            data_raw = fields.get(b"data") or fields.get("data", "{}")
            if isinstance(data_raw, bytes):
                data_raw = data_raw.decode()
            try:
                entries.append(json.loads(data_raw))
            except (json.JSONDecodeError, TypeError):
                pass
        return entries

    @property
    def max_retries(self) -> int:
        """Maximum delivery attempts before dead-lettering."""
        return self._max_retries
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_streams_transport.py -v`
Expected: ALL PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add src/max/bus/streams.py tests/test_streams_transport.py
git commit -m "feat(bus): add Redis Streams transport with consumer groups and dead letter"
```

---

## Task 5: MessageBus Upgrade (Streams Backend)

**Files:**
- Modify: `src/max/bus/message_bus.py`
- Modify: `src/max/bus/__init__.py`
- Test: `tests/test_message_bus_streams.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for MessageBus with Redis Streams backend."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from max.bus.message_bus import MessageBus
from max.bus.streams import StreamsTransport


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.pubsub.return_value = AsyncMock()
    return redis


@pytest.fixture
def mock_transport():
    transport = AsyncMock(spec=StreamsTransport)
    transport.read_messages = AsyncMock(return_value=[])
    transport.publish = AsyncMock(return_value="1-0")
    transport.ack = AsyncMock()
    transport.dead_letter = AsyncMock()
    transport.ensure_group = AsyncMock()
    transport.max_retries = 3
    return transport


@pytest.fixture
def bus_with_streams(mock_redis, mock_transport):
    return MessageBus(
        redis_client=mock_redis,
        transport=mock_transport,
    )


@pytest.fixture
def bus_with_pubsub(mock_redis):
    return MessageBus(redis_client=mock_redis, transport=None)


class TestSubscribeWithStreams:
    async def test_subscribe_registers_handler(self, bus_with_streams):
        handler = AsyncMock()
        await bus_with_streams.subscribe("test_channel", handler)
        assert "test_channel" in bus_with_streams._handlers

    async def test_subscribe_ensures_consumer_group(
        self, bus_with_streams, mock_transport
    ):
        handler = AsyncMock()
        await bus_with_streams.subscribe("test_channel", handler)
        mock_transport.ensure_group.assert_called_with("test_channel")


class TestPublishWithStreams:
    async def test_publish_uses_transport(self, bus_with_streams, mock_transport):
        await bus_with_streams.publish("ch", {"key": "value"})
        mock_transport.publish.assert_called_once_with("ch", {"key": "value"})


class TestPublishFallbackPubSub:
    async def test_publish_uses_redis_publish(self, bus_with_pubsub, mock_redis):
        await bus_with_pubsub.publish("ch", {"key": "value"})
        mock_redis.publish.assert_called_once()


class TestStreamListenLoop:
    async def test_dispatches_to_handler(self, bus_with_streams, mock_transport):
        handler = AsyncMock()
        await bus_with_streams.subscribe("ch", handler)

        # Simulate one message then empty
        mock_transport.read_messages.side_effect = [
            [
                {
                    "channel": "ch",
                    "data": {"key": "value"},
                    "stream_id": "1-0",
                    "message_id": "abc",
                }
            ],
            [],  # second read returns empty, loop continues
        ]

        # Start listening, let it process one cycle, then stop
        await bus_with_streams.start_listening()
        await asyncio.sleep(0.1)
        await bus_with_streams.stop_listening()

        handler.assert_called_once_with("ch", {"key": "value"})

    async def test_acks_after_successful_handler(
        self, bus_with_streams, mock_transport
    ):
        handler = AsyncMock()
        await bus_with_streams.subscribe("ch", handler)

        mock_transport.read_messages.side_effect = [
            [
                {
                    "channel": "ch",
                    "data": {"x": 1},
                    "stream_id": "1-0",
                    "message_id": "abc",
                }
            ],
            [],
        ]

        await bus_with_streams.start_listening()
        await asyncio.sleep(0.1)
        await bus_with_streams.stop_listening()

        mock_transport.ack.assert_called_once_with("ch", "1-0")

    async def test_dead_letters_after_handler_failure(
        self, bus_with_streams, mock_transport
    ):
        handler = AsyncMock(side_effect=Exception("boom"))
        await bus_with_streams.subscribe("ch", handler)

        mock_transport.read_messages.side_effect = [
            [
                {
                    "channel": "ch",
                    "data": {"x": 1},
                    "stream_id": "1-0",
                    "message_id": "abc",
                    "_retry_count": 3,
                }
            ],
            [],
        ]

        await bus_with_streams.start_listening()
        await asyncio.sleep(0.1)
        await bus_with_streams.stop_listening()

        mock_transport.dead_letter.assert_called_once()


class TestCloseWithStreams:
    async def test_close_stops_listening(self, bus_with_streams):
        await bus_with_streams.start_listening()
        await bus_with_streams.close()
        assert bus_with_streams._listen_task is None or bus_with_streams._listen_task.done()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_message_bus_streams.py -v`
Expected: FAIL — `TypeError: MessageBus.__init__() got an unexpected keyword argument 'transport'`

- [ ] **Step 3: Refactor MessageBus to support Streams transport**

Read `src/max/bus/message_bus.py` first. Then rewrite the file:

```python
"""MessageBus — async message broker with pluggable transport.

Supports two transports:
- Redis Streams (default): durable, with consumer groups and dead letter
- Redis pub/sub (fallback): fire-and-forget, for backward compatibility
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import redis.asyncio as aioredis

    from max.bus.streams import StreamsTransport

logger = logging.getLogger(__name__)

Handler = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


class MessageBus:
    """Async message bus with pluggable Redis transport.

    Args:
        redis_client: An async Redis client instance.
        transport: Optional StreamsTransport. If None, falls back to pub/sub.
    """

    def __init__(
        self,
        redis_client: aioredis.Redis,
        transport: StreamsTransport | None = None,
    ) -> None:
        self._redis = redis_client
        self._transport = transport
        self._handlers: dict[str, list[Handler]] = {}
        self._listen_task: asyncio.Task | None = None
        self._running = False

        # Pub/sub fallback
        if self._transport is None:
            self._pubsub = redis_client.pubsub()
        else:
            self._pubsub = None

    async def subscribe(self, channel: str, handler: Handler) -> None:
        """Register a handler for a channel."""
        if channel not in self._handlers:
            self._handlers[channel] = []
            if self._transport is not None:
                await self._transport.ensure_group(channel)
            elif self._pubsub is not None:
                await self._pubsub.subscribe(channel)

        self._handlers[channel].append(handler)
        logger.debug("Subscribed handler to %s", channel)

    async def unsubscribe(self, channel: str, handler: Handler | None = None) -> None:
        """Remove a handler (or all handlers) for a channel."""
        if channel not in self._handlers:
            return

        if handler is None:
            del self._handlers[channel]
        else:
            self._handlers[channel] = [
                h for h in self._handlers[channel] if h is not handler
            ]
            if not self._handlers[channel]:
                del self._handlers[channel]

        if channel not in self._handlers:
            if self._pubsub is not None:
                await self._pubsub.unsubscribe(channel)

    async def publish(self, channel: str, data: dict[str, Any]) -> None:
        """Publish a message to a channel."""
        if self._transport is not None:
            await self._transport.publish(channel, data)
        else:
            payload = json.dumps(data, default=str)
            await self._redis.publish(channel, payload)

    async def start_listening(self) -> None:
        """Start the background listener loop."""
        if self._listen_task is not None and not self._listen_task.done():
            return
        self._running = True
        if self._transport is not None:
            self._listen_task = asyncio.create_task(self._streams_listen_loop())
        else:
            self._listen_task = asyncio.create_task(self._pubsub_listen_loop())

    async def stop_listening(self) -> None:
        """Stop the background listener loop."""
        self._running = False
        if self._listen_task is not None:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

    async def close(self) -> None:
        """Stop listening and release resources."""
        await self.stop_listening()
        if self._pubsub is not None:
            await self._pubsub.aclose()

    # ── Streams listener ────────────────────────────────────────────────

    async def _streams_listen_loop(self) -> None:
        """Listen loop using Redis Streams with consumer groups."""
        logger.info("Streams listen loop started")
        while self._running:
            try:
                channels = list(self._handlers.keys())
                if not channels:
                    await asyncio.sleep(0.1)
                    continue

                messages = await self._transport.read_messages(
                    channels, timeout_ms=1000
                )

                for msg in messages:
                    channel = msg["channel"]
                    data = msg["data"]
                    stream_id = msg["stream_id"]
                    retry_count = msg.get("_retry_count", 0)

                    handlers = self._handlers.get(channel, [])
                    success = True

                    for handler in handlers:
                        try:
                            await handler(channel, data)
                        except Exception:
                            success = False
                            logger.exception(
                                "Handler error on %s (stream_id=%s)",
                                channel,
                                stream_id,
                            )

                    if success:
                        await self._transport.ack(channel, stream_id)
                    elif retry_count >= self._transport.max_retries:
                        await self._transport.dead_letter(
                            channel=channel,
                            stream_id=stream_id,
                            data=data,
                            error="Handler failed after max retries",
                            attempt=retry_count,
                        )
                    else:
                        # NACK: don't ack, message will be re-delivered
                        # via pending entries list on next consumer read
                        await self._transport.ack(channel, stream_id)
                        # Re-publish with incremented retry count
                        data["_retry_count"] = retry_count + 1
                        await self._transport.publish(channel, data)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in streams listen loop")
                await asyncio.sleep(1)

        logger.info("Streams listen loop stopped")

    # ── Pub/sub listener (fallback) ──────────────────────────────────────

    async def _pubsub_listen_loop(self) -> None:
        """Listen loop using Redis pub/sub (legacy fallback)."""
        logger.info("Pub/sub listen loop started")
        try:
            async for message in self._pubsub.listen():
                if not self._running:
                    break
                if message["type"] != "message":
                    continue

                channel = message["channel"]
                if isinstance(channel, bytes):
                    channel = channel.decode()

                try:
                    data = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    continue

                for handler in self._handlers.get(channel, []):
                    try:
                        await handler(channel, data)
                    except Exception:
                        logger.exception(
                            "Handler error on %s (pubsub)", channel
                        )
        except asyncio.CancelledError:
            pass
        logger.info("Pub/sub listen loop stopped")
```

- [ ] **Step 4: Update `src/max/bus/__init__.py`**

```python
"""Bus package — async message bus with pluggable transport."""

from max.bus.message_bus import MessageBus
from max.bus.streams import StreamsTransport

__all__ = ["MessageBus", "StreamsTransport"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_message_bus_streams.py -v`
Expected: ALL PASS (8 tests)

Also verify existing bus tests still pass:
Run: `uv run pytest tests/test_bus*.py tests/test_message_bus*.py -v`
Expected: ALL PASS (zero regressions — transport defaults to None = pub/sub fallback)

- [ ] **Step 6: Commit**

```bash
git add src/max/bus/message_bus.py src/max/bus/__init__.py tests/test_message_bus_streams.py
git commit -m "feat(bus): upgrade MessageBus to support Redis Streams with pub/sub fallback"
```

---

## Task 6: Structured Logging & Correlation ID

**Files:**
- Create: `src/max/observability.py`
- Test: `tests/test_observability.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for observability: structured logging, correlation ID, metrics."""

from __future__ import annotations

import json
import logging
import uuid

import pytest

from max.observability import (
    CorrelationContext,
    JsonFormatter,
    configure_logging,
    get_correlation_id,
    set_correlation_id,
)


class TestJsonFormatter:
    def test_formats_as_json(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="max.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["message"] == "test message"
        assert parsed["level"] == "INFO"
        assert parsed["module"] == "max.test"

    def test_includes_timestamp(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hi", args=(), exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "timestamp" in parsed

    def test_includes_correlation_id_when_set(self):
        formatter = JsonFormatter()
        token = set_correlation_id("test-corr-123")
        try:
            record = logging.LogRecord(
                name="test", level=logging.INFO, pathname="", lineno=0,
                msg="hi", args=(), exc_info=None,
            )
            output = formatter.format(record)
            parsed = json.loads(output)
            assert parsed["correlation_id"] == "test-corr-123"
        finally:
            CorrelationContext.reset(token)

    def test_correlation_id_null_when_not_set(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hi", args=(), exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["correlation_id"] is None

    def test_includes_exception_info(self):
        formatter = JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = logging.LogRecord(
                name="test", level=logging.ERROR, pathname="", lineno=0,
                msg="error", args=(), exc_info=sys.exc_info(),
            )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "exception" in parsed
        assert "ValueError: boom" in parsed["exception"]


class TestCorrelationContext:
    def test_set_and_get(self):
        token = set_correlation_id("abc-123")
        try:
            assert get_correlation_id() == "abc-123"
        finally:
            CorrelationContext.reset(token)

    def test_get_returns_none_by_default(self):
        assert get_correlation_id() is None

    def test_context_isolation(self):
        token = set_correlation_id("outer")
        try:
            assert get_correlation_id() == "outer"
            inner_token = set_correlation_id("inner")
            assert get_correlation_id() == "inner"
            CorrelationContext.reset(inner_token)
            assert get_correlation_id() == "outer"
        finally:
            CorrelationContext.reset(token)


class TestConfigureLogging:
    def test_sets_log_level(self):
        configure_logging(level="WARNING")
        root = logging.getLogger()
        assert root.level == logging.WARNING
        # Reset
        configure_logging(level="DEBUG")

    def test_adds_json_handler(self):
        configure_logging(level="DEBUG", json_format=True)
        root = logging.getLogger()
        json_handlers = [
            h
            for h in root.handlers
            if isinstance(h.formatter, JsonFormatter)
        ]
        assert len(json_handlers) >= 1
        # Cleanup
        for h in json_handlers:
            root.removeHandler(h)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_observability.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'max.observability'`

- [ ] **Step 3: Implement observability module**

Create `src/max/observability.py`:

```python
"""Observability: structured JSON logging, correlation ID context, metrics setup.

Usage:
    from max.observability import configure_logging, set_correlation_id

    configure_logging(level="DEBUG", json_format=True)
    token = set_correlation_id("req-abc-123")
    # ... all log messages now include correlation_id ...
"""

from __future__ import annotations

import contextvars
import json
import logging
import traceback
from datetime import UTC, datetime
from typing import Any

# ── Correlation ID Context ──────────────────────────────────────────────

CorrelationContext: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


def set_correlation_id(correlation_id: str) -> contextvars.Token:
    """Set the correlation ID for the current async context. Returns a reset token."""
    return CorrelationContext.set(correlation_id)


def get_correlation_id() -> str | None:
    """Get the correlation ID for the current async context."""
    return CorrelationContext.get()


# ── JSON Formatter ──────────────────────────────────────────────────────


class JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON for structured log ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id(),
        }

        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = "".join(
                traceback.format_exception(*record.exc_info)
            )

        return json.dumps(log_entry, default=str)


# ── Logging Configuration ───────────────────────────────────────────────


def configure_logging(
    level: str = "DEBUG",
    json_format: bool = False,
) -> None:
    """Configure the root logger with optional JSON formatting.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        json_format: If True, use JsonFormatter for structured output.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.DEBUG))

    if json_format:
        # Remove existing handlers to avoid duplicate output
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
    elif not root.handlers:
        logging.basicConfig(level=root.level)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_observability.py -v`
Expected: ALL PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add src/max/observability.py tests/test_observability.py
git commit -m "feat(observability): add structured JSON logging with correlation ID context"
```

---

## Task 7: OpenTelemetry Metrics Setup

**Files:**
- Modify: `src/max/observability.py` (add metrics)
- Modify: `pyproject.toml` (add opentelemetry dependency)
- Test: `tests/test_observability.py` (add metrics tests)

- [ ] **Step 1: Add opentelemetry dependencies to pyproject.toml**

Add to the core dependencies list in `pyproject.toml`:

```toml
    "opentelemetry-api>=1.20.0",
    "opentelemetry-sdk>=1.20.0",
```

Run: `uv sync --all-extras` to install.

- [ ] **Step 2: Write the failing metrics tests**

Add to `tests/test_observability.py`:

```python
from max.observability import MetricsRegistry, configure_metrics


class TestMetricsRegistry:
    def test_creates_counter(self):
        registry = MetricsRegistry()
        counter = registry.counter("test.counter", "A test counter")
        assert counter is not None

    def test_creates_histogram(self):
        registry = MetricsRegistry()
        histogram = registry.histogram("test.histogram", "A test histogram")
        assert histogram is not None

    def test_creates_gauge(self):
        registry = MetricsRegistry()
        gauge = registry.gauge("test.gauge", "A test gauge")
        assert gauge is not None

    def test_same_name_returns_same_instrument(self):
        registry = MetricsRegistry()
        c1 = registry.counter("test.dup", "counter")
        c2 = registry.counter("test.dup", "counter")
        assert c1 is c2

    def test_counter_add(self):
        registry = MetricsRegistry()
        counter = registry.counter("test.add", "counter")
        counter.add(1)  # should not raise

    def test_histogram_record(self):
        registry = MetricsRegistry()
        histogram = registry.histogram("test.record", "histogram")
        histogram.record(1.5)  # should not raise


class TestConfigureMetrics:
    def test_returns_registry(self):
        registry = configure_metrics(service_name="test-max", enabled=True)
        assert isinstance(registry, MetricsRegistry)

    def test_disabled_returns_noop_registry(self):
        registry = configure_metrics(service_name="test-max", enabled=False)
        assert isinstance(registry, MetricsRegistry)
        counter = registry.counter("noop.counter", "noop")
        counter.add(1)  # should not raise even when disabled
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_observability.py::TestMetricsRegistry -v`
Expected: FAIL — `ImportError: cannot import name 'MetricsRegistry'`

- [ ] **Step 4: Implement MetricsRegistry**

Add to `src/max/observability.py`:

```python
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    PeriodicExportingMetricReader,
)


class MetricsRegistry:
    """Centralized registry for OpenTelemetry metrics instruments.

    Provides typed factory methods for counters, histograms, and gauges.
    Deduplicates instruments by name.
    """

    def __init__(self, meter_name: str = "max") -> None:
        self._meter = metrics.get_meter(meter_name)
        self._instruments: dict[str, Any] = {}

    def counter(self, name: str, description: str = "") -> metrics.Counter:
        """Get or create a counter."""
        if name not in self._instruments:
            self._instruments[name] = self._meter.create_counter(
                name, description=description
            )
        return self._instruments[name]

    def histogram(self, name: str, description: str = "") -> metrics.Histogram:
        """Get or create a histogram."""
        if name not in self._instruments:
            self._instruments[name] = self._meter.create_histogram(
                name, description=description
            )
        return self._instruments[name]

    def gauge(self, name: str, description: str = "") -> metrics.Gauge:
        """Get or create a gauge."""
        if name not in self._instruments:
            self._instruments[name] = self._meter.create_gauge(
                name, description=description
            )
        return self._instruments[name]


def configure_metrics(
    service_name: str = "max",
    enabled: bool = False,
    exporter_endpoint: str = "",
) -> MetricsRegistry:
    """Configure OpenTelemetry metrics.

    Args:
        service_name: Service name for metric labeling.
        enabled: If True, set up a real meter provider with exporters.
        exporter_endpoint: OTLP exporter endpoint (if empty, uses console).
    """
    if enabled:
        reader = PeriodicExportingMetricReader(
            ConsoleMetricExporter(),
            export_interval_millis=60000,
        )
        provider = MeterProvider(metric_readers=[reader])
        metrics.set_meter_provider(provider)

    return MetricsRegistry(meter_name=service_name)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_observability.py -v`
Expected: ALL PASS (19 tests total)

- [ ] **Step 6: Commit**

```bash
git add src/max/observability.py tests/test_observability.py pyproject.toml
git commit -m "feat(observability): add OpenTelemetry metrics registry with counters, histograms, gauges"
```

---

## Task 8: Scheduler DB Schema

**Files:**
- Modify: `src/max/db/schema.sql` (append scheduler_state table)
- Test: Verified via integration in Task 9

- [ ] **Step 1: Add scheduler_state table to schema.sql**

Append to the end of `src/max/db/schema.sql`:

```sql
-- ── Scheduler ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS scheduler_state (
    job_name         VARCHAR(100) PRIMARY KEY,
    last_run_at      TIMESTAMPTZ,
    next_run_at      TIMESTAMPTZ NOT NULL,
    interval_seconds INTEGER NOT NULL CHECK (interval_seconds > 0),
    enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scheduler_state_next_run
    ON scheduler_state (next_run_at)
    WHERE enabled = TRUE;
```

- [ ] **Step 2: Commit**

```bash
git add src/max/db/schema.sql
git commit -m "feat(schema): add scheduler_state table for persistent job scheduling"
```

---

## Task 9: Scheduler Implementation

**Files:**
- Create: `src/max/scheduler.py`
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the database-backed job scheduler."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from max.scheduler import Scheduler, SchedulerJob


class TestSchedulerJob:
    def test_creates_job(self):
        callback = AsyncMock()
        job = SchedulerJob(
            name="test_job",
            interval_seconds=3600,
            callback=callback,
        )
        assert job.name == "test_job"
        assert job.interval_seconds == 3600

    def test_is_due_when_next_run_in_past(self):
        job = SchedulerJob(
            name="test",
            interval_seconds=60,
            callback=AsyncMock(),
        )
        job.next_run_at = datetime.now(UTC) - timedelta(seconds=10)
        assert job.is_due() is True

    def test_not_due_when_next_run_in_future(self):
        job = SchedulerJob(
            name="test",
            interval_seconds=60,
            callback=AsyncMock(),
        )
        job.next_run_at = datetime.now(UTC) + timedelta(seconds=60)
        assert job.is_due() is False


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.fetchone = AsyncMock(return_value=None)
    db.fetchall = AsyncMock(return_value=[])
    db.execute = AsyncMock()
    return db


@pytest.fixture
def scheduler(mock_db):
    return Scheduler(db=mock_db)


class TestRegisterJob:
    async def test_registers_job(self, scheduler):
        callback = AsyncMock()
        scheduler.register("my_job", 3600, callback)
        assert "my_job" in scheduler._jobs

    async def test_register_duplicate_raises(self, scheduler):
        scheduler.register("dup", 60, AsyncMock())
        with pytest.raises(ValueError, match="already registered"):
            scheduler.register("dup", 60, AsyncMock())


class TestLoadState:
    async def test_loads_next_run_from_db(self, scheduler, mock_db):
        callback = AsyncMock()
        scheduler.register("persisted_job", 3600, callback)

        next_run = datetime.now(UTC) + timedelta(hours=1)
        mock_db.fetchone.return_value = {
            "job_name": "persisted_job",
            "last_run_at": datetime.now(UTC) - timedelta(hours=1),
            "next_run_at": next_run,
            "interval_seconds": 3600,
        }

        await scheduler.load_state()
        assert scheduler._jobs["persisted_job"].next_run_at == next_run

    async def test_catch_up_when_next_run_in_past(self, scheduler, mock_db):
        callback = AsyncMock()
        scheduler.register("late_job", 3600, callback)

        past = datetime.now(UTC) - timedelta(hours=2)
        mock_db.fetchone.return_value = {
            "job_name": "late_job",
            "last_run_at": past - timedelta(hours=1),
            "next_run_at": past,
            "interval_seconds": 3600,
        }

        await scheduler.load_state()
        assert scheduler._jobs["late_job"].is_due() is True


class TestTick:
    async def test_executes_due_job(self, scheduler, mock_db):
        callback = AsyncMock()
        scheduler.register("due_job", 60, callback)
        scheduler._jobs["due_job"].next_run_at = datetime.now(UTC) - timedelta(
            seconds=10
        )

        await scheduler.tick()
        callback.assert_called_once()

    async def test_skips_not_due_job(self, scheduler, mock_db):
        callback = AsyncMock()
        scheduler.register("future_job", 60, callback)
        scheduler._jobs["future_job"].next_run_at = datetime.now(UTC) + timedelta(
            hours=1
        )

        await scheduler.tick()
        callback.assert_not_called()

    async def test_updates_next_run_after_execution(self, scheduler, mock_db):
        callback = AsyncMock()
        scheduler.register("update_job", 60, callback)
        scheduler._jobs["update_job"].next_run_at = datetime.now(UTC) - timedelta(
            seconds=10
        )

        await scheduler.tick()
        # Next run should be ~60 seconds from now
        job = scheduler._jobs["update_job"]
        assert job.next_run_at > datetime.now(UTC)

    async def test_persists_state_after_execution(self, scheduler, mock_db):
        callback = AsyncMock()
        scheduler.register("persist_job", 60, callback)
        scheduler._jobs["persist_job"].next_run_at = datetime.now(UTC) - timedelta(
            seconds=10
        )

        await scheduler.tick()
        mock_db.execute.assert_called()

    async def test_handles_callback_error_gracefully(self, scheduler, mock_db):
        callback = AsyncMock(side_effect=Exception("boom"))
        scheduler.register("error_job", 60, callback)
        scheduler._jobs["error_job"].next_run_at = datetime.now(UTC) - timedelta(
            seconds=10
        )

        await scheduler.tick()  # should not raise
        # next_run should still advance to prevent infinite retry loops
        assert scheduler._jobs["error_job"].next_run_at > datetime.now(UTC)


class TestStartStop:
    async def test_start_creates_task(self, scheduler):
        await scheduler.start()
        assert scheduler._task is not None
        await scheduler.stop()

    async def test_stop_cancels_task(self, scheduler):
        await scheduler.start()
        await scheduler.stop()
        assert scheduler._task is None or scheduler._task.done()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'max.scheduler'`

- [ ] **Step 3: Implement the scheduler**

Create `src/max/scheduler.py`:

```python
"""Database-backed periodic job scheduler.

Persists job run timestamps to PostgreSQL so schedules survive restarts.
Catches up on missed runs when the application restarts.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from max.db.postgres import Database

logger = logging.getLogger(__name__)

JobCallback = Callable[[], Coroutine[Any, Any, None]]


class SchedulerJob:
    """A registered periodic job."""

    def __init__(
        self,
        name: str,
        interval_seconds: int,
        callback: JobCallback,
    ) -> None:
        self.name = name
        self.interval_seconds = interval_seconds
        self.callback = callback
        self.next_run_at: datetime = datetime.now(UTC)
        self.last_run_at: datetime | None = None

    def is_due(self) -> bool:
        """Return True if the job should run now."""
        return datetime.now(UTC) >= self.next_run_at

    def advance(self) -> None:
        """Advance next_run_at by the interval from now."""
        self.last_run_at = datetime.now(UTC)
        self.next_run_at = self.last_run_at + timedelta(
            seconds=self.interval_seconds
        )


class Scheduler:
    """Database-backed periodic job scheduler.

    Jobs are registered in-memory with callbacks. Run timestamps are
    persisted to the `scheduler_state` table so schedules survive restarts.
    On startup, `load_state()` restores next_run_at from the database;
    if a job's next_run_at is in the past, it fires immediately (catch-up).
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._jobs: dict[str, SchedulerJob] = {}
        self._task: asyncio.Task | None = None
        self._running = False

    def register(
        self,
        name: str,
        interval_seconds: int,
        callback: JobCallback,
    ) -> None:
        """Register a periodic job.

        Raises ValueError if a job with the same name is already registered.
        """
        if name in self._jobs:
            raise ValueError(f"Job '{name}' already registered")
        self._jobs[name] = SchedulerJob(name, interval_seconds, callback)

    async def load_state(self) -> None:
        """Load persisted job state from the database.

        For each registered job, check if there's a saved state row.
        If next_run_at is in the past, the job will fire on the next tick.
        If no row exists, the job starts due immediately.
        """
        for job in self._jobs.values():
            row = await self._db.fetchone(
                "SELECT job_name, last_run_at, next_run_at, interval_seconds "
                "FROM scheduler_state WHERE job_name = $1",
                job.name,
            )
            if row:
                job.last_run_at = row["last_run_at"]
                job.next_run_at = row["next_run_at"]
                logger.info(
                    "Loaded scheduler state for %s: next_run=%s",
                    job.name,
                    job.next_run_at,
                )
            else:
                logger.info(
                    "No persisted state for %s, starting due now", job.name
                )

    async def _persist_state(self, job: SchedulerJob) -> None:
        """Save job state to the database (upsert)."""
        await self._db.execute(
            """
            INSERT INTO scheduler_state
                (job_name, last_run_at, next_run_at, interval_seconds, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (job_name) DO UPDATE SET
                last_run_at = EXCLUDED.last_run_at,
                next_run_at = EXCLUDED.next_run_at,
                interval_seconds = EXCLUDED.interval_seconds,
                updated_at = NOW()
            """,
            job.name,
            job.last_run_at,
            job.next_run_at,
            job.interval_seconds,
        )

    async def tick(self) -> None:
        """Check all jobs and execute any that are due."""
        for job in list(self._jobs.values()):
            if not job.is_due():
                continue
            try:
                logger.info("Executing scheduled job: %s", job.name)
                await job.callback()
            except Exception:
                logger.exception(
                    "Scheduled job %s failed", job.name
                )
            finally:
                job.advance()
                try:
                    await self._persist_state(job)
                except Exception:
                    logger.exception(
                        "Failed to persist state for job %s", job.name
                    )

    async def start(self) -> None:
        """Start the scheduler background loop."""
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Scheduler started with %d jobs", len(self._jobs))

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Scheduler stopped")

    async def _run_loop(self) -> None:
        """Background loop that ticks every second."""
        while self._running:
            try:
                await self.tick()
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Scheduler loop error")
                await asyncio.sleep(5)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: ALL PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add src/max/scheduler.py tests/test_scheduler.py
git commit -m "feat(scheduler): add database-backed periodic job scheduler with restart catch-up"
```

---

## Task 10: pyproject.toml Dependency Updates

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Verify opentelemetry was added in Task 7**

Check that `pyproject.toml` already has `opentelemetry-api` and `opentelemetry-sdk` from Task 7. If not, add them now.

- [ ] **Step 2: Add FastAPI and related dependencies for Plan B**

Add to the core dependencies (these are needed for Plan B but adding now avoids a separate dep-install step later):

```toml
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "slowapi>=0.1.9",
```

- [ ] **Step 3: Sync dependencies**

Run: `uv sync --all-extras`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore(deps): add opentelemetry, fastapi, uvicorn, slowapi"
```

---

## Task 11: Integration Tests

**Files:**
- Create: `tests/test_infra_integration.py`

- [ ] **Step 1: Write integration tests**

```python
"""Integration tests for infrastructure hardening components."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from max.bus.message_bus import MessageBus
from max.bus.streams import StreamsTransport
from max.llm.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpen,
    CircuitState,
)
from max.observability import (
    JsonFormatter,
    MetricsRegistry,
    configure_logging,
    configure_metrics,
    get_correlation_id,
    set_correlation_id,
)
from max.scheduler import Scheduler, SchedulerJob


class TestCircuitBreakerFullCycle:
    """Test the full circuit breaker lifecycle: closed → open → half-open → closed."""

    def test_full_lifecycle(self):
        cb = CircuitBreaker(threshold=2, cooldown_seconds=0.1)

        # Start closed
        assert cb.state == CircuitState.CLOSED
        cb.check()  # no error

        # Two failures open it
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Can't call while open
        with pytest.raises(CircuitBreakerOpen):
            cb.check()

        # Wait for cooldown
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

        # One test call allowed
        cb.check()

        # Success closes it
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0


class TestStreamsBusIntegration:
    """Test MessageBus with mocked StreamsTransport end-to-end."""

    async def test_publish_subscribe_ack_cycle(self):
        mock_redis = AsyncMock()
        transport = AsyncMock(spec=StreamsTransport)
        transport.ensure_group = AsyncMock()
        transport.publish = AsyncMock(return_value="1-0")
        transport.ack = AsyncMock()
        transport.dead_letter = AsyncMock()
        transport.max_retries = 3

        bus = MessageBus(redis_client=mock_redis, transport=transport)
        received = []

        async def handler(channel: str, data: dict) -> None:
            received.append((channel, data))

        await bus.subscribe("test.channel", handler)
        transport.ensure_group.assert_called_with("test.channel")

        # Simulate incoming message
        transport.read_messages = AsyncMock(
            side_effect=[
                [
                    {
                        "channel": "test.channel",
                        "data": {"msg": "hello"},
                        "stream_id": "1-0",
                        "message_id": "abc",
                    }
                ],
                [],  # empty on second read
            ]
        )

        await bus.start_listening()
        await asyncio.sleep(0.1)
        await bus.stop_listening()

        assert len(received) == 1
        assert received[0] == ("test.channel", {"msg": "hello"})
        transport.ack.assert_called_with("test.channel", "1-0")


class TestObservabilityIntegration:
    """Test logging + correlation ID + metrics together."""

    def test_correlation_flows_through_json_log(self):
        import io
        import logging

        # Set up a JSON handler on a test logger
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())
        test_logger = logging.getLogger("test.integration.obs")
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.DEBUG)

        token = set_correlation_id("req-abc-123")
        try:
            test_logger.info("Processing request")
            output = stream.getvalue()
            parsed = json.loads(output.strip())
            assert parsed["correlation_id"] == "req-abc-123"
            assert parsed["message"] == "Processing request"
        finally:
            from max.observability import CorrelationContext

            CorrelationContext.reset(token)
            test_logger.removeHandler(handler)

    def test_metrics_registry_instruments_work(self):
        registry = configure_metrics(service_name="test-integration", enabled=False)
        counter = registry.counter("max.test.messages", "Test counter")
        histogram = registry.histogram("max.test.latency", "Test histogram")

        counter.add(1, {"channel": "telegram"})
        histogram.record(0.5, {"agent": "coordinator"})
        # No assertions on values (OpenTelemetry doesn't expose sync reads),
        # just verify no exceptions


class TestSchedulerJobModel:
    """Test SchedulerJob due/advance logic."""

    def test_job_due_and_advance(self):
        job = SchedulerJob("test", 3600, AsyncMock())
        job.next_run_at = datetime.now(UTC) - timedelta(seconds=1)
        assert job.is_due() is True

        job.advance()
        assert job.is_due() is False
        assert job.last_run_at is not None
        # next_run should be ~3600s from now
        delta = (job.next_run_at - datetime.now(UTC)).total_seconds()
        assert 3590 < delta < 3610


class TestPubSubFallback:
    """Test that MessageBus works in pub/sub mode when transport is None."""

    async def test_publish_uses_redis_directly(self):
        mock_redis = AsyncMock()
        mock_redis.pubsub.return_value = AsyncMock()
        bus = MessageBus(redis_client=mock_redis, transport=None)

        await bus.publish("ch", {"key": "value"})
        mock_redis.publish.assert_called_once()
        call_args = mock_redis.publish.call_args
        assert call_args[0][0] == "ch"
        payload = json.loads(call_args[0][1])
        assert payload["key"] == "value"
```

- [ ] **Step 2: Run integration tests**

Run: `uv run pytest tests/test_infra_integration.py -v`
Expected: ALL PASS (5 tests)

- [ ] **Step 3: Commit**

```bash
git add tests/test_infra_integration.py
git commit -m "test(infra): add integration tests for bus, circuit breaker, observability, scheduler"
```

---

## Task 12: Full Suite Run + Lint

- [ ] **Step 1: Run linter on all new and modified files**

```bash
uv run ruff check src/max/bus/ src/max/llm/ src/max/scheduler.py src/max/observability.py src/max/config.py tests/test_circuit_breaker.py tests/test_llm_circuit_breaker.py tests/test_streams_transport.py tests/test_message_bus_streams.py tests/test_observability.py tests/test_scheduler.py tests/test_config_go_live.py tests/test_infra_integration.py
```

Fix any issues found.

- [ ] **Step 2: Run ruff format**

```bash
uv run ruff format src/max/bus/ src/max/llm/ src/max/scheduler.py src/max/observability.py tests/test_circuit_breaker.py tests/test_llm_circuit_breaker.py tests/test_streams_transport.py tests/test_message_bus_streams.py tests/test_observability.py tests/test_scheduler.py tests/test_config_go_live.py tests/test_infra_integration.py
```

- [ ] **Step 3: Run all new tests**

```bash
uv run pytest tests/test_config_go_live.py tests/test_circuit_breaker.py tests/test_llm_circuit_breaker.py tests/test_streams_transport.py tests/test_message_bus_streams.py tests/test_observability.py tests/test_scheduler.py tests/test_infra_integration.py -v
```

Expected: ALL PASS (~91 new tests)

- [ ] **Step 4: Run full test suite for regression check**

```bash
uv run pytest --continue-on-collection-errors -q --tb=short
```

Expected: All previously passing tests still pass. Zero regressions on sentinel, evolution, quality, command, memory, communication, or tool tests.

- [ ] **Step 5: Fix any issues and commit**

```bash
git add -A
git commit -m "chore(infra): lint fixes, formatting, full suite verification"
```

---

## Summary

| Task | Component | New Tests | Key Files |
|------|-----------|-----------|-----------|
| 1 | Config additions | 22 | `config.py` |
| 2 | Circuit breaker | 15 | `llm/circuit_breaker.py` |
| 3 | LLM + circuit breaker | 6 | `llm/client.py` |
| 4 | Streams transport | 13 | `bus/streams.py` |
| 5 | MessageBus upgrade | 8 | `bus/message_bus.py` |
| 6 | Structured logging | 11 | `observability.py` |
| 7 | OpenTelemetry metrics | 8 | `observability.py` |
| 8 | Scheduler schema | 0 | `schema.sql` |
| 9 | Scheduler | 13 | `scheduler.py` |
| 10 | Dependencies | 0 | `pyproject.toml` |
| 11 | Integration tests | 5 | `test_infra_integration.py` |
| 12 | Full suite + lint | 0 | — |
| **Total** | | **~101** | |
