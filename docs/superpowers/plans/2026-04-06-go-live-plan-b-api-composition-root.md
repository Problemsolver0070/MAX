# Plan B: API & Composition Root — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the FastAPI REST API layer and composition root that wires all 7 phases + Sentinel into a running application with health checks, authentication, rate limiting, introspection endpoints, admin controls, graceful shutdown, and task recovery.

**Architecture:** FastAPI app factory with lifespan context manager for startup/shutdown. All dependencies wired via manual constructor injection in a single `create_app_state()` function. AppState dataclass held on `app.state` provides FastAPI dependency injection to all endpoint handlers. Endpoint groups split into focused router modules.

**Tech Stack:** FastAPI, uvicorn, slowapi, httpx (testing), pydantic, Redis Streams, PostgreSQL, OpenTelemetry

**Depends on:** Plan A (Infrastructure Hardening) — circuit breaker, Redis Streams transport, scheduler, observability, config additions.

---

## File Structure

```
Create: src/max/api/__init__.py          — API package, create_api_app() factory
Create: src/max/api/dependencies.py      — AppState dataclass, get_app_state dependency
Create: src/max/api/auth.py              — API key verification FastAPI dependency
Create: src/max/api/rate_limit.py        — slowapi limiter configuration
Create: src/max/api/health.py            — GET /health, GET /ready (no auth)
Create: src/max/api/messaging.py         — POST/GET /api/v1/messages, webhook registration
Create: src/max/api/telegram.py          — POST /webhook/telegram
Create: src/max/api/introspection.py     — GET tasks, evolution, sentinel, dead-letters
Create: src/max/api/admin.py             — POST freeze/unfreeze, sentinel/run
Create: src/max/app.py                   — Composition root: create_app_state(), shutdown, lifespan
Create: src/max/__main__.py              — Entry point: python -m max, signal handling

Modify: src/max/memory/coordinator_state.py  — Add update_evolution_state()
Modify: src/max/command/task_store.py        — Add get_completed_tasks()
Modify: src/max/evolution/director.py        — Add stop() method
Modify: pyproject.toml                       — Add httpx dev dep, project.scripts entry

Test files:
Create: tests/test_api_auth.py           — 8 tests
Create: tests/test_api_rate_limit.py     — 4 tests
Create: tests/test_api_health.py         — 8 tests
Create: tests/test_api_messaging.py      — 7 tests
Create: tests/test_api_telegram.py       — 5 tests
Create: tests/test_api_introspection.py  — 10 tests
Create: tests/test_api_admin.py          — 6 tests
Create: tests/test_app_composition.py    — 8 tests
Create: tests/test_entry_point.py        — 4 tests
Create: tests/test_task_recovery.py      — 5 tests
```

Estimated total: ~65 new tests.

---

### Task 1: Prerequisite Gaps & Dev Dependencies

Fix three missing methods identified during codebase audit and add httpx for API testing.

**Files:**
- Modify: `src/max/memory/coordinator_state.py`
- Modify: `src/max/command/task_store.py`
- Modify: `src/max/evolution/director.py`
- Modify: `pyproject.toml`
- Test: `tests/test_prerequisite_gaps.py`

- [ ] **Step 1: Write tests for the three missing methods**

Create `tests/test_prerequisite_gaps.py`:

```python
"""Tests for prerequisite gap fixes needed by Plan B composition root."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestCoordinatorStateManagerUpdateEvolution:
    """CoordinatorStateManager.update_evolution_state()."""

    async def test_updates_evolution_fields_in_state(self):
        from max.memory.coordinator_state import CoordinatorStateManager
        from max.memory.models import CoordinatorState

        db = AsyncMock()
        warm = AsyncMock()
        mgr = CoordinatorStateManager(db, warm)

        # Pre-seed a state in warm memory
        initial = CoordinatorState(version=1)
        warm.get = AsyncMock(return_value=initial.model_dump(mode="json"))

        await mgr.update_evolution_state({"frozen": True, "last_experiment_id": "exp-1"})

        # Should have called save (which calls warm.set)
        warm.set.assert_called_once()
        saved_data = warm.set.call_args[0][1]
        assert saved_data["evolution_state"]["frozen"] is True
        assert saved_data["evolution_state"]["last_experiment_id"] == "exp-1"

    async def test_preserves_existing_evolution_state(self):
        from max.memory.coordinator_state import CoordinatorStateManager
        from max.memory.models import CoordinatorState

        db = AsyncMock()
        warm = AsyncMock()
        mgr = CoordinatorStateManager(db, warm)

        initial = CoordinatorState(version=1)
        initial_dump = initial.model_dump(mode="json")
        initial_dump["evolution_state"] = {"frozen": False, "existing_key": "keep"}
        warm.get = AsyncMock(return_value=initial_dump)

        await mgr.update_evolution_state({"frozen": True})

        saved_data = warm.set.call_args[0][1]
        assert saved_data["evolution_state"]["frozen"] is True
        assert saved_data["evolution_state"]["existing_key"] == "keep"


class TestTaskStoreGetCompletedTasks:
    """TaskStore.get_completed_tasks()."""

    async def test_returns_completed_tasks(self):
        from max.command.task_store import TaskStore

        db = AsyncMock()
        db.fetchall = AsyncMock(
            return_value=[
                {"id": uuid.uuid4(), "goal_anchor": "task 1", "status": "completed", "quality_criteria": "{}"},
                {"id": uuid.uuid4(), "goal_anchor": "task 2", "status": "completed", "quality_criteria": "{}"},
            ]
        )
        store = TaskStore(db)
        tasks = await store.get_completed_tasks(limit=10)
        assert len(tasks) == 2
        db.fetchall.assert_called_once()

    async def test_respects_limit(self):
        from max.command.task_store import TaskStore

        db = AsyncMock()
        db.fetchall = AsyncMock(return_value=[])
        store = TaskStore(db)
        await store.get_completed_tasks(limit=5)
        query = db.fetchall.call_args[0][0]
        assert "LIMIT" in query


class TestEvolutionDirectorStop:
    """EvolutionDirectorAgent.stop() unsubscribes from bus."""

    async def test_stop_unsubscribes_channels(self):
        from max.evolution.director import EvolutionDirectorAgent

        bus = AsyncMock()
        agent = EvolutionDirectorAgent.__new__(EvolutionDirectorAgent)
        agent._bus = bus

        await agent.stop()

        assert bus.unsubscribe.call_count == 2
        channels = [call.args[0] for call in bus.unsubscribe.call_args_list]
        assert "evolution.trigger" in channels
        assert "evolution.proposal" in channels
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_prerequisite_gaps.py -v`
Expected: FAIL — `update_evolution_state` not found, `get_completed_tasks` not found, `stop` not found.

- [ ] **Step 3: Implement update_evolution_state in CoordinatorStateManager**

Add to `src/max/memory/coordinator_state.py` after `backup_to_cold()`:

```python
    async def update_evolution_state(self, data: dict[str, Any]) -> None:
        """Merge evolution state fields into the coordinator state document.

        Args:
            data: Key-value pairs to merge into the evolution_state sub-document.
        """
        state = await self.load()
        current = state.model_dump(mode="json")
        evo = current.get("evolution_state") or {}
        evo.update(data)
        current["evolution_state"] = evo
        updated = CoordinatorState.model_validate(current)
        await self.save(updated)
```

Add `from typing import Any` to the file's imports.

- [ ] **Step 4: Implement get_completed_tasks in TaskStore**

Add to `src/max/command/task_store.py` after `create_result()`:

```python
    async def get_completed_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recently completed tasks, ordered by completion time descending."""
        rows = await self._db.fetchall(
            "SELECT * FROM tasks WHERE status = 'completed' "
            "ORDER BY completed_at DESC LIMIT $1",
            limit,
        )
        return [_parse_jsonb(r, _TASK_JSON_FIELDS) for r in rows]
```

- [ ] **Step 5: Implement stop() on EvolutionDirectorAgent**

Add to `src/max/evolution/director.py` after the `start()` method:

```python
    async def stop(self) -> None:
        """Unsubscribe from evolution bus channels."""
        await self._bus.unsubscribe("evolution.trigger")
        await self._bus.unsubscribe("evolution.proposal")
        logger.info("EvolutionDirectorAgent stopped")
```

- [ ] **Step 6: Add httpx dev dependency and project.scripts**

In `pyproject.toml`, add `"httpx>=0.27.0"` to the `dev` optional-dependencies list. Add a `[project.scripts]` section:

```toml
[project.scripts]
max = "max.__main__:main"
```

Run: `uv sync --extra dev`

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_prerequisite_gaps.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 8: Commit**

```bash
git add src/max/memory/coordinator_state.py src/max/command/task_store.py \
  src/max/evolution/director.py pyproject.toml uv.lock tests/test_prerequisite_gaps.py
git commit -m "fix: add missing methods needed by composition root

- CoordinatorStateManager.update_evolution_state(): merge evo fields
- TaskStore.get_completed_tasks(): query completed tasks with limit
- EvolutionDirectorAgent.stop(): unsubscribe from bus channels
- Add httpx dev dep and project.scripts entry"
```

---

### Task 2: API Dependencies & Auth

Create the shared AppState dataclass and API key authentication dependency.

**Files:**
- Create: `src/max/api/dependencies.py`
- Create: `src/max/api/auth.py`
- Test: `tests/test_api_auth.py`

- [ ] **Step 1: Write auth tests**

Create `tests/test_api_auth.py`:

```python
"""Tests for API key authentication."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from max.api.auth import verify_api_key
from max.api.dependencies import AppState


def _make_state(**overrides: Any) -> AppState:
    """Create a minimal AppState for testing."""
    defaults: dict[str, Any] = {
        "settings": MagicMock(max_api_keys="key-alpha,key-beta"),
        "db": MagicMock(),
        "redis_client": MagicMock(),
        "bus": MagicMock(),
        "transport": None,
        "warm_memory": MagicMock(),
        "llm": MagicMock(),
        "circuit_breaker": MagicMock(),
        "task_store": MagicMock(),
        "quality_store": MagicMock(),
        "evolution_store": MagicMock(),
        "sentinel_store": MagicMock(),
        "state_manager": MagicMock(),
        "scheduler": MagicMock(),
        "tool_registry": MagicMock(),
        "tool_executor": MagicMock(),
        "agents": {},
        "start_time": 0.0,
    }
    defaults.update(overrides)
    return AppState(**defaults)


def _make_app(state: AppState) -> FastAPI:
    """Create a test FastAPI app with a protected endpoint."""
    from fastapi import Depends

    app = FastAPI()
    app.state.app_state = state

    @app.get("/protected")
    async def protected(key: str = Depends(verify_api_key)):
        return {"key": key}

    return app


class TestApiKeyAuth:

    async def test_valid_key_returns_200(self):
        app = _make_app(_make_state())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/protected", headers={"Authorization": "Bearer key-alpha"})
        assert r.status_code == 200
        assert r.json()["key"] == "key-alpha"

    async def test_second_valid_key_accepted(self):
        app = _make_app(_make_state())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/protected", headers={"Authorization": "Bearer key-beta"})
        assert r.status_code == 200

    async def test_invalid_key_returns_401(self):
        app = _make_app(_make_state())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/protected", headers={"Authorization": "Bearer wrong-key"})
        assert r.status_code == 401

    async def test_missing_auth_header_returns_403(self):
        app = _make_app(_make_state())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/protected")
        assert r.status_code == 403

    async def test_no_keys_configured_returns_503(self):
        state = _make_state(settings=MagicMock(max_api_keys=""))
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/protected", headers={"Authorization": "Bearer anything"})
        assert r.status_code == 503

    async def test_whitespace_in_keys_stripped(self):
        state = _make_state(settings=MagicMock(max_api_keys=" key-alpha , key-beta "))
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/protected", headers={"Authorization": "Bearer key-alpha"})
        assert r.status_code == 200

    async def test_empty_bearer_token_returns_401(self):
        app = _make_app(_make_state())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/protected", headers={"Authorization": "Bearer "})
        assert r.status_code == 401

    async def test_key_returned_to_caller(self):
        app = _make_app(_make_state())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/protected", headers={"Authorization": "Bearer key-beta"})
        assert r.json()["key"] == "key-beta"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api_auth.py -v`
Expected: FAIL — `max.api.dependencies` and `max.api.auth` not found.

- [ ] **Step 3: Create dependencies.py**

Create `src/max/api/dependencies.py`:

```python
"""Shared FastAPI dependencies and application state container."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import Request


@dataclass
class AppState:
    """Holds all wired dependencies, stored on FastAPI app.state."""

    settings: Any
    db: Any
    redis_client: Any
    bus: Any
    transport: Any
    warm_memory: Any
    llm: Any
    circuit_breaker: Any
    task_store: Any
    quality_store: Any
    evolution_store: Any
    sentinel_store: Any
    state_manager: Any
    scheduler: Any
    tool_registry: Any
    tool_executor: Any
    agents: dict[str, Any] = field(default_factory=dict)
    start_time: float = 0.0


def get_app_state(request: Request) -> AppState:
    """FastAPI dependency: extract AppState from request."""
    return request.app.state.app_state
```

- [ ] **Step 4: Create auth.py**

Create `src/max/api/auth.py`:

```python
"""API key authentication for FastAPI endpoints."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from max.api.dependencies import AppState, get_app_state

_bearer = HTTPBearer()


async def verify_api_key(
    app_state: AppState = Depends(get_app_state),
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> str:
    """Validate the Bearer token against configured API keys.

    Returns the matched key string for downstream use (e.g., rate limiting key).
    """
    valid_keys = [k.strip() for k in app_state.settings.max_api_keys.split(",") if k.strip()]

    if not valid_keys:
        raise HTTPException(status_code=503, detail="No API keys configured")

    if not credentials.credentials or credentials.credentials not in valid_keys:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return credentials.credentials
```

- [ ] **Step 5: Create src/max/api/__init__.py (empty for now)**

```python
"""Max REST API package."""
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_api_auth.py -v`
Expected: All 8 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/max/api/__init__.py src/max/api/dependencies.py src/max/api/auth.py \
  tests/test_api_auth.py
git commit -m "feat(api): add AppState container and API key auth dependency"
```

---

### Task 3: Rate Limiting

Configure slowapi rate limiting middleware.

**Files:**
- Create: `src/max/api/rate_limit.py`
- Test: `tests/test_api_rate_limit.py`

- [ ] **Step 1: Write rate limiting tests**

Create `tests/test_api_rate_limit.py`:

```python
"""Tests for rate limiting setup."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from max.api.rate_limit import create_limiter, rate_limit_key_func


class TestCreateLimiter:

    def test_creates_limiter_instance(self):
        limiter = create_limiter()
        assert limiter is not None

    def test_limiter_has_key_func(self):
        limiter = create_limiter()
        assert limiter._key_func is not None


class TestRateLimitKeyFunc:

    def test_extracts_client_host(self):
        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = "1.2.3.4"
        key = rate_limit_key_func(request)
        assert key == "1.2.3.4"

    def test_returns_unknown_when_no_client(self):
        request = MagicMock(spec=Request)
        request.client = None
        key = rate_limit_key_func(request)
        assert key == "unknown"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api_rate_limit.py -v`
Expected: FAIL — `max.api.rate_limit` not found.

- [ ] **Step 3: Implement rate_limit.py**

Create `src/max/api/rate_limit.py`:

```python
"""Rate limiting configuration using slowapi."""

from __future__ import annotations

from fastapi import Request
from slowapi import Limiter


def rate_limit_key_func(request: Request) -> str:
    """Extract rate limit key from request (client IP)."""
    if request.client is not None:
        return request.client.host
    return "unknown"


def create_limiter() -> Limiter:
    """Create a slowapi Limiter instance."""
    return Limiter(key_func=rate_limit_key_func)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_api_rate_limit.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/max/api/rate_limit.py tests/test_api_rate_limit.py
git commit -m "feat(api): add slowapi rate limiter configuration"
```

---

### Task 4: Health & Readiness Endpoints

Public endpoints (no auth) for infrastructure health checks and Azure Container Apps liveness/readiness probes.

**Files:**
- Create: `src/max/api/health.py`
- Test: `tests/test_api_health.py`

- [ ] **Step 1: Write health endpoint tests**

Create `tests/test_api_health.py`:

```python
"""Tests for health and readiness endpoints."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from max.api.dependencies import AppState
from max.api.health import router


def _make_state(**overrides) -> AppState:
    defaults = {
        "settings": MagicMock(),
        "db": AsyncMock(),
        "redis_client": AsyncMock(),
        "bus": MagicMock(_running=True),
        "transport": None,
        "warm_memory": MagicMock(),
        "llm": MagicMock(),
        "circuit_breaker": MagicMock(state=MagicMock(value="closed")),
        "task_store": MagicMock(),
        "quality_store": MagicMock(),
        "evolution_store": MagicMock(),
        "sentinel_store": MagicMock(),
        "state_manager": MagicMock(),
        "scheduler": MagicMock(),
        "tool_registry": MagicMock(),
        "tool_executor": MagicMock(),
        "agents": {"coordinator": MagicMock(), "planner": MagicMock()},
        "start_time": time.time() - 100,
    }
    defaults.update(overrides)
    return AppState(**defaults)


def _make_app(state: AppState) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.app_state = state
    return app


class TestHealthEndpoint:

    async def test_returns_200_when_healthy(self):
        state = _make_state()
        state.db.fetchone = AsyncMock(return_value={"?column?": 1})
        state.redis_client.ping = AsyncMock(return_value=True)
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["uptime_seconds"] >= 100

    async def test_includes_agent_statuses(self):
        state = _make_state()
        state.db.fetchone = AsyncMock(return_value={"?column?": 1})
        state.redis_client.ping = AsyncMock(return_value=True)
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/health")
        agents = r.json()["agents"]
        assert "coordinator" in agents
        assert "planner" in agents

    async def test_shows_db_disconnected(self):
        state = _make_state()
        state.db.fetchone = AsyncMock(side_effect=Exception("down"))
        state.redis_client.ping = AsyncMock(return_value=True)
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/health")
        assert r.json()["infrastructure"]["database"] == "disconnected"

    async def test_shows_circuit_breaker_state(self):
        state = _make_state(circuit_breaker=MagicMock(state=MagicMock(value="open")))
        state.db.fetchone = AsyncMock(return_value={"?column?": 1})
        state.redis_client.ping = AsyncMock(return_value=True)
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/health")
        assert r.json()["infrastructure"]["circuit_breaker"] == "open"


class TestReadyEndpoint:

    async def test_ready_when_all_ok(self):
        state = _make_state()
        state.db.fetchone = AsyncMock(return_value={"?column?": 1})
        state.redis_client.ping = AsyncMock(return_value=True)
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/ready")
        assert r.status_code == 200
        assert r.json()["ready"] is True

    async def test_not_ready_when_db_down(self):
        state = _make_state()
        state.db.fetchone = AsyncMock(side_effect=Exception("down"))
        state.redis_client.ping = AsyncMock(return_value=True)
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/ready")
        assert r.status_code == 503
        assert r.json()["ready"] is False

    async def test_not_ready_when_redis_down(self):
        state = _make_state()
        state.db.fetchone = AsyncMock(return_value={"?column?": 1})
        state.redis_client.ping = AsyncMock(side_effect=Exception("down"))
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/ready")
        assert r.status_code == 503
        assert r.json()["checks"]["redis"] == "failed"

    async def test_no_auth_required(self):
        state = _make_state()
        state.db.fetchone = AsyncMock(return_value={"?column?": 1})
        state.redis_client.ping = AsyncMock(return_value=True)
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/health")
        # No auth header, should still work
        assert r.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api_health.py -v`
Expected: FAIL — `max.api.health` not found.

- [ ] **Step 3: Implement health.py**

Create `src/max/api/health.py`:

```python
"""Health and readiness endpoints — no authentication required."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from max.api.dependencies import AppState, get_app_state

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict:
    """Liveness check with infrastructure and agent status."""
    state: AppState = get_app_state(request)

    # Database check
    db_status = "connected"
    try:
        await state.db.fetchone("SELECT 1")
    except Exception:
        db_status = "disconnected"

    # Redis check
    redis_status = "connected"
    try:
        await state.redis_client.ping()
    except Exception:
        redis_status = "disconnected"

    # Agent statuses
    agent_statuses = {name: "running" for name in state.agents}

    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - state.start_time, 1),
        "agents": agent_statuses,
        "infrastructure": {
            "database": db_status,
            "redis": redis_status,
            "bus": "listening" if state.bus._running else "stopped",
            "circuit_breaker": state.circuit_breaker.state.value,
        },
    }


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Readiness check — verifies DB and Redis connectivity."""
    state: AppState = get_app_state(request)
    checks: dict[str, str] = {}
    all_ok = True

    try:
        await state.db.fetchone("SELECT 1")
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "failed"
        all_ok = False

    try:
        await state.redis_client.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "failed"
        all_ok = False

    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"ready": all_ok, "checks": checks},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_api_health.py -v`
Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/max/api/health.py tests/test_api_health.py
git commit -m "feat(api): add health and readiness endpoints"
```

---

### Task 5: Messaging Endpoints

Authenticated endpoints for sending messages to Max and polling for responses.

**Files:**
- Create: `src/max/api/messaging.py`
- Test: `tests/test_api_messaging.py`

- [ ] **Step 1: Write messaging tests**

Create `tests/test_api_messaging.py`:

```python
"""Tests for messaging endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from max.api.auth import verify_api_key
from max.api.dependencies import AppState
from max.api.messaging import router

AUTH = {"Authorization": "Bearer test-key"}


def _make_state(**overrides) -> AppState:
    defaults = {
        "settings": MagicMock(max_api_keys="test-key"),
        "db": MagicMock(),
        "redis_client": MagicMock(),
        "bus": AsyncMock(),
        "transport": None,
        "warm_memory": AsyncMock(),
        "llm": MagicMock(),
        "circuit_breaker": MagicMock(),
        "task_store": MagicMock(),
        "quality_store": MagicMock(),
        "evolution_store": MagicMock(),
        "sentinel_store": MagicMock(),
        "state_manager": MagicMock(),
        "scheduler": MagicMock(),
        "tool_registry": MagicMock(),
        "tool_executor": MagicMock(),
        "agents": {},
        "start_time": 0.0,
    }
    defaults.update(overrides)
    return AppState(**defaults)


def _make_app(state: AppState) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.app_state = state
    return app


class TestSendMessage:

    async def test_publishes_intent_to_bus(self):
        state = _make_state()
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/v1/messages",
                json={"text": "Hello Max", "user_id": "user-1"},
                headers=AUTH,
            )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "accepted"
        assert "message_id" in body
        state.bus.publish.assert_called_once()
        call_args = state.bus.publish.call_args
        assert call_args[0][0] == "intents.new"
        assert call_args[0][1]["user_message"] == "Hello Max"
        assert call_args[0][1]["source_platform"] == "api"

    async def test_returns_401_without_auth(self):
        app = _make_app(_make_state())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/v1/messages", json={"text": "hi", "user_id": "u1"})
        assert r.status_code == 403

    async def test_returns_422_missing_text(self):
        app = _make_app(_make_state())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/v1/messages", json={"user_id": "u1"}, headers=AUTH)
        assert r.status_code == 422


class TestGetMessages:

    async def test_returns_pending_responses(self):
        state = _make_state()
        state.warm_memory.list_range = AsyncMock(
            return_value=[{"text": "Hello!", "timestamp": "2026-01-01T00:00:00"}]
        )
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/messages?user_id=user-1", headers=AUTH)
        assert r.status_code == 200
        assert len(r.json()["messages"]) == 1

    async def test_returns_empty_when_no_responses(self):
        state = _make_state()
        state.warm_memory.list_range = AsyncMock(return_value=[])
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/messages?user_id=user-1", headers=AUTH)
        assert r.json()["messages"] == []

    async def test_clears_after_read(self):
        state = _make_state()
        state.warm_memory.list_range = AsyncMock(return_value=[{"text": "hi"}])
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.get("/api/v1/messages?user_id=user-1", headers=AUTH)
        state.warm_memory.delete.assert_called_once()


class TestRegisterWebhook:

    async def test_stores_webhook_url(self):
        state = _make_state()
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/v1/messages/webhook",
                json={"url": "https://example.com/hook", "user_id": "u1"},
                headers=AUTH,
            )
        assert r.status_code == 200
        state.warm_memory.set.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api_messaging.py -v`
Expected: FAIL — `max.api.messaging` not found.

- [ ] **Step 3: Implement messaging.py**

Create `src/max/api/messaging.py`:

```python
"""Messaging endpoints — send messages to Max and poll for responses."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from max.api.auth import verify_api_key
from max.api.dependencies import AppState, get_app_state

router = APIRouter(prefix="/api/v1", tags=["messaging"])


class MessageRequest(BaseModel):
    text: str
    user_id: str


class WebhookRegistration(BaseModel):
    url: str
    user_id: str


@router.post("/messages")
async def send_message(
    body: MessageRequest,
    app_state: AppState = Depends(get_app_state),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """Accept a message and publish it to the agent pipeline."""
    message_id = str(uuid.uuid4())

    await app_state.bus.publish(
        "intents.new",
        {
            "id": message_id,
            "user_message": body.text,
            "source_platform": "api",
            "goal_anchor": body.text,
            "priority": "normal",
            "attachments": [],
            "user_id": body.user_id,
        },
    )

    return {"message_id": message_id, "status": "accepted"}


@router.get("/messages")
async def get_messages(
    user_id: str,
    app_state: AppState = Depends(get_app_state),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """Poll for pending responses for a user."""
    key = f"api_responses:{user_id}"
    responses = await app_state.warm_memory.list_range(key, 0, -1)

    if responses:
        await app_state.warm_memory.delete(key)

    return {"messages": responses}


@router.post("/messages/webhook")
async def register_webhook(
    body: WebhookRegistration,
    app_state: AppState = Depends(get_app_state),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """Register a webhook URL for push delivery of responses."""
    await app_state.warm_memory.set(
        f"api_webhook:{body.user_id}",
        {"url": body.url, "user_id": body.user_id},
    )
    return {"status": "registered", "user_id": body.user_id}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_api_messaging.py -v`
Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/max/api/messaging.py tests/test_api_messaging.py
git commit -m "feat(api): add messaging endpoints (send, poll, webhook registration)"
```

---

### Task 6: Telegram Webhook Endpoint

Receives Telegram updates via webhook, verified by secret token header.

**Files:**
- Create: `src/max/api/telegram.py`
- Modify: `src/max/comm/telegram_adapter.py` (add `feed_webhook_update`)
- Test: `tests/test_api_telegram.py`

- [ ] **Step 1: Write telegram webhook tests**

Create `tests/test_api_telegram.py`:

```python
"""Tests for Telegram webhook endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from max.api.dependencies import AppState
from max.api.telegram import router


def _make_state(**overrides) -> AppState:
    defaults = {
        "settings": MagicMock(comm_webhook_secret="my-secret"),
        "db": MagicMock(),
        "redis_client": MagicMock(),
        "bus": AsyncMock(),
        "transport": None,
        "warm_memory": MagicMock(),
        "llm": MagicMock(),
        "circuit_breaker": MagicMock(),
        "task_store": MagicMock(),
        "quality_store": MagicMock(),
        "evolution_store": MagicMock(),
        "sentinel_store": MagicMock(),
        "state_manager": MagicMock(),
        "scheduler": MagicMock(),
        "tool_registry": MagicMock(),
        "tool_executor": MagicMock(),
        "agents": {},
        "start_time": 0.0,
    }
    defaults.update(overrides)
    return AppState(**defaults)


def _make_app(state: AppState) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.app_state = state
    return app


TELEGRAM_UPDATE = {
    "update_id": 123456,
    "message": {
        "message_id": 1,
        "from": {"id": 999, "is_bot": False, "first_name": "Test"},
        "chat": {"id": 999, "type": "private"},
        "date": 1700000000,
        "text": "Hello from Telegram",
    },
}


class TestTelegramWebhook:

    async def test_valid_secret_returns_200(self):
        state = _make_state()
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/webhook/telegram",
                json=TELEGRAM_UPDATE,
                headers={"X-Telegram-Bot-Api-Secret-Token": "my-secret"},
            )
        assert r.status_code == 200

    async def test_invalid_secret_returns_401(self):
        state = _make_state()
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/webhook/telegram",
                json=TELEGRAM_UPDATE,
                headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
            )
        assert r.status_code == 401

    async def test_missing_secret_returns_401(self):
        state = _make_state()
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/webhook/telegram", json=TELEGRAM_UPDATE)
        assert r.status_code == 401

    async def test_publishes_intent_for_text_message(self):
        state = _make_state()
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.post(
                "/webhook/telegram",
                json=TELEGRAM_UPDATE,
                headers={"X-Telegram-Bot-Api-Secret-Token": "my-secret"},
            )
        state.bus.publish.assert_called_once()
        call_data = state.bus.publish.call_args[0][1]
        assert call_data["user_message"] == "Hello from Telegram"
        assert call_data["source_platform"] == "telegram"

    async def test_ignores_non_message_updates(self):
        state = _make_state()
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/webhook/telegram",
                json={"update_id": 999},  # no message field
                headers={"X-Telegram-Bot-Api-Secret-Token": "my-secret"},
            )
        assert r.status_code == 200
        state.bus.publish.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api_telegram.py -v`
Expected: FAIL — `max.api.telegram` not found.

- [ ] **Step 3: Implement telegram.py**

Create `src/max/api/telegram.py`:

```python
"""Telegram webhook endpoint — verified by secret token header."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from max.api.dependencies import AppState, get_app_state

router = APIRouter(tags=["telegram"])


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request) -> dict:
    """Receive a Telegram update via webhook.

    Validates the X-Telegram-Bot-Api-Secret-Token header, extracts
    the message text, and publishes an intent to the bus.
    """
    state: AppState = get_app_state(request)

    # Verify secret token
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    expected = state.settings.comm_webhook_secret
    if not expected or secret != expected:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    body: dict[str, Any] = await request.json()

    # Extract message text (if present)
    message = body.get("message")
    if message is None:
        return {"ok": True}

    text = message.get("text", "")
    from_user = message.get("from", {})
    user_id = str(from_user.get("id", "unknown"))

    await state.bus.publish(
        "intents.new",
        {
            "id": str(uuid.uuid4()),
            "user_message": text,
            "source_platform": "telegram",
            "goal_anchor": text,
            "priority": "normal",
            "attachments": [],
            "user_id": user_id,
        },
    )

    return {"ok": True}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_api_telegram.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/max/api/telegram.py tests/test_api_telegram.py
git commit -m "feat(api): add Telegram webhook endpoint with secret verification"
```

---

### Task 7: Introspection Endpoints

Authenticated read-only endpoints for viewing tasks, evolution state, sentinel scores, and dead letters.

**Files:**
- Create: `src/max/api/introspection.py`
- Test: `tests/test_api_introspection.py`

- [ ] **Step 1: Write introspection tests**

Create `tests/test_api_introspection.py`:

```python
"""Tests for introspection endpoints."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from max.api.dependencies import AppState
from max.api.introspection import router

AUTH = {"Authorization": "Bearer test-key"}


def _make_state(**overrides) -> AppState:
    defaults = {
        "settings": MagicMock(max_api_keys="test-key"),
        "db": MagicMock(),
        "redis_client": MagicMock(),
        "bus": MagicMock(),
        "transport": AsyncMock(),
        "warm_memory": MagicMock(),
        "llm": MagicMock(),
        "circuit_breaker": MagicMock(),
        "task_store": AsyncMock(),
        "quality_store": MagicMock(),
        "evolution_store": AsyncMock(),
        "sentinel_store": AsyncMock(),
        "state_manager": MagicMock(),
        "scheduler": MagicMock(),
        "tool_registry": MagicMock(),
        "tool_executor": MagicMock(),
        "agents": {},
        "start_time": 0.0,
    }
    defaults.update(overrides)
    return AppState(**defaults)


def _make_app(state: AppState) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.app_state = state
    return app


class TestListTasks:

    async def test_returns_active_tasks(self):
        state = _make_state()
        task_id = str(uuid.uuid4())
        state.task_store.get_active_tasks = AsyncMock(
            return_value=[{"id": task_id, "goal_anchor": "test", "status": "in_progress"}]
        )
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/tasks", headers=AUTH)
        assert r.status_code == 200
        assert len(r.json()["tasks"]) == 1

    async def test_requires_auth(self):
        app = _make_app(_make_state())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/tasks")
        assert r.status_code == 403


class TestGetTask:

    async def test_returns_task_with_subtasks(self):
        state = _make_state()
        task_id = uuid.uuid4()
        state.task_store.get_task = AsyncMock(
            return_value={"id": str(task_id), "goal_anchor": "test", "status": "in_progress"}
        )
        state.task_store.get_subtasks = AsyncMock(return_value=[])
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get(f"/api/v1/tasks/{task_id}", headers=AUTH)
        assert r.status_code == 200
        assert "subtasks" in r.json()

    async def test_returns_404_for_missing_task(self):
        state = _make_state()
        state.task_store.get_task = AsyncMock(return_value=None)
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get(f"/api/v1/tasks/{uuid.uuid4()}", headers=AUTH)
        assert r.status_code == 404


class TestEvolutionState:

    async def test_returns_evolution_state(self):
        state = _make_state()
        state.evolution_store.get_proposals = AsyncMock(
            return_value=[{"id": "p1", "status": "pending"}]
        )
        state.evolution_store.get_journal = AsyncMock(return_value=[])
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/evolution", headers=AUTH)
        assert r.status_code == 200
        assert "proposals" in r.json()


class TestSentinelState:

    async def test_returns_sentinel_scores(self):
        state = _make_state()
        state.sentinel_store.get_test_runs = AsyncMock(
            return_value=[{"id": "r1", "run_type": "scheduled", "status": "completed"}]
        )
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/sentinel", headers=AUTH)
        assert r.status_code == 200
        assert "test_runs" in r.json()


class TestDeadLetters:

    async def test_returns_dead_letters_with_transport(self):
        state = _make_state()
        state.transport.get_dead_letters = AsyncMock(
            return_value=[{"data": "msg1", "error": "handler failed"}]
        )
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/dead-letters", headers=AUTH)
        assert r.status_code == 200
        assert len(r.json()["dead_letters"]) == 1

    async def test_returns_empty_without_transport(self):
        state = _make_state(transport=None)
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/dead-letters", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["dead_letters"] == []

    async def test_accepts_channel_param(self):
        state = _make_state()
        state.transport.get_dead_letters = AsyncMock(return_value=[])
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.get("/api/v1/dead-letters?channel=intents.new", headers=AUTH)
        state.transport.get_dead_letters.assert_called_once_with("intents.new", count=100)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api_introspection.py -v`
Expected: FAIL — `max.api.introspection` not found.

- [ ] **Step 3: Implement introspection.py**

Create `src/max/api/introspection.py`:

```python
"""Introspection endpoints — read-only views into Max's state."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from max.api.auth import verify_api_key
from max.api.dependencies import AppState, get_app_state

router = APIRouter(prefix="/api/v1", tags=["introspection"])


@router.get("/tasks")
async def list_tasks(
    app_state: AppState = Depends(get_app_state),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """List active (non-terminal) tasks."""
    tasks = await app_state.task_store.get_active_tasks()
    return {"tasks": tasks}


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: uuid.UUID,
    app_state: AppState = Depends(get_app_state),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """Get a task with its subtasks."""
    task = await app_state.task_store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    subtasks = await app_state.task_store.get_subtasks(task_id)
    return {**task, "subtasks": subtasks}


@router.get("/evolution")
async def evolution_state(
    app_state: AppState = Depends(get_app_state),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """View evolution system state: proposals and journal."""
    proposals = await app_state.evolution_store.get_proposals()
    journal = await app_state.evolution_store.get_journal(limit=20)
    return {"proposals": proposals, "journal": journal}


@router.get("/sentinel")
async def sentinel_state(
    app_state: AppState = Depends(get_app_state),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """View recent sentinel test runs."""
    runs = await app_state.sentinel_store.get_test_runs(limit=10)
    return {"test_runs": runs}


@router.get("/dead-letters")
async def dead_letters(
    channel: str = "dead_letter",
    count: int = 100,
    app_state: AppState = Depends(get_app_state),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """View dead-lettered messages from the bus."""
    if app_state.transport is None:
        return {"dead_letters": []}

    entries = await app_state.transport.get_dead_letters(channel, count=count)
    return {"dead_letters": entries}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_api_introspection.py -v`
Expected: All 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/max/api/introspection.py tests/test_api_introspection.py
git commit -m "feat(api): add introspection endpoints for tasks, evolution, sentinel, dead-letters"
```

---

### Task 8: Admin Endpoints

Authenticated admin actions: evolution freeze/unfreeze, trigger sentinel run.

**Files:**
- Create: `src/max/api/admin.py`
- Test: `tests/test_api_admin.py`

- [ ] **Step 1: Write admin tests**

Create `tests/test_api_admin.py`:

```python
"""Tests for admin endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from max.api.dependencies import AppState
from max.api.admin import router

AUTH = {"Authorization": "Bearer test-key"}


def _make_state(**overrides) -> AppState:
    defaults = {
        "settings": MagicMock(max_api_keys="test-key"),
        "db": MagicMock(),
        "redis_client": MagicMock(),
        "bus": AsyncMock(),
        "transport": None,
        "warm_memory": MagicMock(),
        "llm": MagicMock(),
        "circuit_breaker": MagicMock(),
        "task_store": MagicMock(),
        "quality_store": MagicMock(),
        "evolution_store": MagicMock(),
        "sentinel_store": MagicMock(),
        "state_manager": MagicMock(),
        "scheduler": MagicMock(),
        "tool_registry": MagicMock(),
        "tool_executor": MagicMock(),
        "agents": {},
        "start_time": 0.0,
    }
    defaults.update(overrides)
    return AppState(**defaults)


def _make_app(state: AppState) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.app_state = state
    return app


class TestEvolutionFreeze:

    async def test_freeze_publishes_to_bus(self):
        state = _make_state()
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/v1/admin/evolution/freeze", headers=AUTH)
        assert r.status_code == 200
        state.bus.publish.assert_called_once_with("evolution.freeze", {"source": "admin_api"})

    async def test_unfreeze_publishes_to_bus(self):
        state = _make_state()
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/v1/admin/evolution/unfreeze", headers=AUTH)
        assert r.status_code == 200
        state.bus.publish.assert_called_once_with("evolution.unfreeze", {"source": "admin_api"})


class TestSentinelRun:

    async def test_trigger_publishes_to_bus(self):
        state = _make_state()
        app = _make_app(state)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/v1/admin/sentinel/run", headers=AUTH)
        assert r.status_code == 200
        state.bus.publish.assert_called_once_with(
            "sentinel.run_request", {"source": "admin_api", "scheduled": False}
        )


class TestAdminAuth:

    async def test_freeze_requires_auth(self):
        app = _make_app(_make_state())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/v1/admin/evolution/freeze")
        assert r.status_code == 403

    async def test_sentinel_run_requires_auth(self):
        app = _make_app(_make_state())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/v1/admin/sentinel/run")
        assert r.status_code == 403

    async def test_invalid_key_returns_401(self):
        app = _make_app(_make_state())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/v1/admin/evolution/freeze",
                headers={"Authorization": "Bearer invalid"},
            )
        assert r.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api_admin.py -v`
Expected: FAIL — `max.api.admin` not found.

- [ ] **Step 3: Implement admin.py**

Create `src/max/api/admin.py`:

```python
"""Admin endpoints — evolution control and sentinel triggers."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from max.api.auth import verify_api_key
from max.api.dependencies import AppState, get_app_state

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.post("/evolution/freeze")
async def freeze_evolution(
    app_state: AppState = Depends(get_app_state),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """Manually freeze evolution — no new experiments will start."""
    await app_state.bus.publish("evolution.freeze", {"source": "admin_api"})
    return {"status": "freeze_requested"}


@router.post("/evolution/unfreeze")
async def unfreeze_evolution(
    app_state: AppState = Depends(get_app_state),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """Manually unfreeze evolution — resume experiments."""
    await app_state.bus.publish("evolution.unfreeze", {"source": "admin_api"})
    return {"status": "unfreeze_requested"}


@router.post("/sentinel/run")
async def trigger_sentinel(
    app_state: AppState = Depends(get_app_state),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """Manually trigger a sentinel monitoring run."""
    await app_state.bus.publish(
        "sentinel.run_request", {"source": "admin_api", "scheduled": False}
    )
    return {"status": "sentinel_run_requested"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_api_admin.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/max/api/admin.py tests/test_api_admin.py
git commit -m "feat(api): add admin endpoints for evolution control and sentinel triggers"
```

---

### Task 9: API App Factory & Package Assembly

Wire all routers into a single FastAPI application factory with rate limiting middleware.

**Files:**
- Modify: `src/max/api/__init__.py`
- Test: `tests/test_api_assembly.py`

- [ ] **Step 1: Write assembly tests**

Create `tests/test_api_assembly.py`:

```python
"""Tests for API app factory and router assembly."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from max.api import create_api_app
from max.api.dependencies import AppState


def _make_state() -> AppState:
    return AppState(
        settings=MagicMock(max_api_keys="test-key", rate_limit_api="100/minute",
                           rate_limit_messaging="50/minute", comm_webhook_secret="s"),
        db=AsyncMock(),
        redis_client=AsyncMock(),
        bus=AsyncMock(),
        transport=AsyncMock(),
        warm_memory=AsyncMock(),
        llm=MagicMock(),
        circuit_breaker=MagicMock(state=MagicMock(value="closed")),
        task_store=AsyncMock(),
        quality_store=MagicMock(),
        evolution_store=AsyncMock(),
        sentinel_store=AsyncMock(),
        state_manager=MagicMock(),
        scheduler=MagicMock(),
        tool_registry=MagicMock(),
        tool_executor=MagicMock(),
        agents={"coordinator": MagicMock()},
        start_time=0.0,
    )


class TestCreateApiApp:

    def test_returns_fastapi_instance(self):
        from fastapi import FastAPI
        app = create_api_app()
        assert isinstance(app, FastAPI)

    async def test_health_route_exists(self):
        app = create_api_app()
        state = _make_state()
        state.db.fetchone = AsyncMock(return_value={"?column?": 1})
        state.redis_client.ping = AsyncMock(return_value=True)
        app.state.app_state = state
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/health")
        assert r.status_code == 200

    async def test_api_v1_route_exists(self):
        app = create_api_app()
        state = _make_state()
        state.task_store.get_active_tasks = AsyncMock(return_value=[])
        app.state.app_state = state
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/tasks", headers={"Authorization": "Bearer test-key"})
        assert r.status_code == 200

    async def test_webhook_route_exists(self):
        app = create_api_app()
        state = _make_state()
        app.state.app_state = state
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/webhook/telegram",
                json={"update_id": 1},
                headers={"X-Telegram-Bot-Api-Secret-Token": "s"},
            )
        assert r.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api_assembly.py -v`
Expected: FAIL — `create_api_app` not importable.

- [ ] **Step 3: Implement create_api_app in __init__.py**

Replace `src/max/api/__init__.py`:

```python
"""Max REST API package — app factory and router assembly."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from max.api.admin import router as admin_router
from max.api.health import router as health_router
from max.api.introspection import router as introspection_router
from max.api.messaging import router as messaging_router
from max.api.rate_limit import create_limiter
from max.api.telegram import router as telegram_router


def create_api_app(lifespan: Any = None) -> FastAPI:
    """Create the FastAPI application with all routers and middleware.

    Args:
        lifespan: Optional async context manager for startup/shutdown.
    """
    app = FastAPI(
        title="Max API",
        version="0.1.0",
        docs_url="/docs",
        lifespan=lifespan,
    )

    # Rate limiting
    limiter = create_limiter()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Routers
    app.include_router(health_router)
    app.include_router(messaging_router)
    app.include_router(telegram_router)
    app.include_router(introspection_router)
    app.include_router(admin_router)

    return app
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_api_assembly.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/max/api/__init__.py tests/test_api_assembly.py
git commit -m "feat(api): assemble all routers into FastAPI app factory"
```

---

### Task 10: Composition Root

The single wiring point that creates all infrastructure, stores, agents, and starts the system.

**Files:**
- Create: `src/max/app.py`
- Test: `tests/test_app_composition.py`

- [ ] **Step 1: Write composition root tests**

Create `tests/test_app_composition.py`:

```python
"""Tests for the composition root (app.py)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from max.api.dependencies import AppState


class TestCreateAppState:
    """Test create_app_state wiring logic."""

    @patch("max.app.Database")
    @patch("max.app.aioredis")
    @patch("max.app.LLMClient")
    @patch("max.app.Settings")
    async def test_creates_app_state(self, MockSettings, MockLLM, mock_redis_mod, MockDB):
        from max.app import create_app_state

        settings = MagicMock()
        settings.postgres_dsn = "postgresql://test"
        settings.redis_url = "redis://localhost"
        settings.anthropic_api_key = "test-key"
        settings.bus_transport = "pubsub"
        settings.bus_consumer_group = "test"
        settings.bus_consumer_name = "w1"
        settings.bus_dead_letter_max_retries = 3
        settings.bus_stream_max_len = 1000
        settings.llm_circuit_breaker_threshold = 5
        settings.llm_circuit_breaker_cooldown_seconds = 60
        settings.telegram_bot_token = ""
        settings.max_owner_telegram_id = ""
        settings.coordinator_model = "claude-opus-4-6"
        settings.planner_model = "claude-opus-4-6"
        settings.orchestrator_model = "claude-opus-4-6"
        settings.worker_model = "claude-opus-4-6"
        settings.quality_director_model = "claude-opus-4-6"
        settings.auditor_model = "claude-opus-4-6"
        settings.sentinel_model = "claude-opus-4-6"
        settings.coordinator_max_active_tasks = 5
        settings.planner_max_subtasks = 10
        settings.worker_max_retries = 2
        settings.worker_timeout_seconds = 300
        settings.quality_max_fix_attempts = 2
        settings.quality_audit_timeout_seconds = 120
        settings.quality_pass_threshold = 0.7
        settings.quality_high_score_threshold = 0.9
        settings.quality_max_rules_per_audit = 5
        settings.quality_max_recent_verdicts = 50
        settings.tool_execution_timeout_seconds = 60
        settings.tool_max_concurrent = 10
        settings.tool_audit_enabled = True
        settings.evolution_canary_replay_count = 5
        settings.sentinel_replay_count = 10
        settings.memory_compaction_interval_seconds = 60
        settings.evolution_scout_interval_hours = 6
        settings.sentinel_monitor_interval_hours = 12
        settings.memory_anchor_re_evaluation_interval_hours = 6
        settings.comm_batch_interval_seconds = 30
        settings.comm_max_batch_size = 10
        settings.comm_context_window_size = 20

        # Mock infrastructure
        db = AsyncMock()
        MockDB.return_value = db
        redis_client = AsyncMock()
        mock_redis_mod.from_url.return_value = redis_client

        llm = AsyncMock()
        MockLLM.return_value = llm

        state = await create_app_state(settings)

        assert isinstance(state, AppState)
        assert state.db is db
        assert state.settings is settings
        db.connect.assert_called_once()
        db.init_schema.assert_called_once()

    @patch("max.app.Database")
    @patch("max.app.aioredis")
    @patch("max.app.LLMClient")
    async def test_selects_streams_transport(self, MockLLM, mock_redis_mod, MockDB):
        from max.app import create_app_state

        settings = MagicMock()
        settings.postgres_dsn = "postgresql://test"
        settings.redis_url = "redis://localhost"
        settings.bus_transport = "streams"
        settings.bus_consumer_group = "grp"
        settings.bus_consumer_name = "w1"
        settings.bus_dead_letter_max_retries = 3
        settings.bus_stream_max_len = 1000
        settings.anthropic_api_key = "key"
        settings.llm_circuit_breaker_threshold = 5
        settings.llm_circuit_breaker_cooldown_seconds = 60
        settings.telegram_bot_token = ""
        settings.max_owner_telegram_id = ""
        # Set all model/config attrs to avoid AttributeError
        for attr in ["coordinator_model", "planner_model", "orchestrator_model",
                      "worker_model", "quality_director_model", "auditor_model",
                      "sentinel_model"]:
            setattr(settings, attr, "claude-opus-4-6")
        for attr in ["coordinator_max_active_tasks", "planner_max_subtasks",
                      "worker_max_retries", "worker_timeout_seconds",
                      "quality_max_fix_attempts", "quality_audit_timeout_seconds",
                      "quality_pass_threshold", "quality_high_score_threshold",
                      "quality_max_rules_per_audit", "quality_max_recent_verdicts",
                      "tool_execution_timeout_seconds", "tool_max_concurrent",
                      "tool_audit_enabled", "evolution_canary_replay_count",
                      "sentinel_replay_count", "memory_compaction_interval_seconds",
                      "evolution_scout_interval_hours", "sentinel_monitor_interval_hours",
                      "memory_anchor_re_evaluation_interval_hours",
                      "comm_batch_interval_seconds", "comm_max_batch_size",
                      "comm_context_window_size"]:
            setattr(settings, attr, 5)

        MockDB.return_value = AsyncMock()
        mock_redis_mod.from_url.return_value = AsyncMock()
        MockLLM.return_value = AsyncMock()

        state = await create_app_state(settings)
        assert state.transport is not None

    @patch("max.app.Database")
    @patch("max.app.aioredis")
    @patch("max.app.LLMClient")
    async def test_selects_pubsub_fallback(self, MockLLM, mock_redis_mod, MockDB):
        from max.app import create_app_state

        settings = MagicMock()
        settings.postgres_dsn = "postgresql://test"
        settings.redis_url = "redis://localhost"
        settings.bus_transport = "pubsub"
        settings.anthropic_api_key = "key"
        settings.llm_circuit_breaker_threshold = 5
        settings.llm_circuit_breaker_cooldown_seconds = 60
        settings.telegram_bot_token = ""
        settings.max_owner_telegram_id = ""
        for attr in ["coordinator_model", "planner_model", "orchestrator_model",
                      "worker_model", "quality_director_model", "auditor_model",
                      "sentinel_model"]:
            setattr(settings, attr, "claude-opus-4-6")
        for attr in ["coordinator_max_active_tasks", "planner_max_subtasks",
                      "worker_max_retries", "worker_timeout_seconds",
                      "quality_max_fix_attempts", "quality_audit_timeout_seconds",
                      "quality_pass_threshold", "quality_high_score_threshold",
                      "quality_max_rules_per_audit", "quality_max_recent_verdicts",
                      "tool_execution_timeout_seconds", "tool_max_concurrent",
                      "tool_audit_enabled", "evolution_canary_replay_count",
                      "sentinel_replay_count", "memory_compaction_interval_seconds",
                      "evolution_scout_interval_hours", "sentinel_monitor_interval_hours",
                      "memory_anchor_re_evaluation_interval_hours",
                      "comm_batch_interval_seconds", "comm_max_batch_size",
                      "comm_context_window_size"]:
            setattr(settings, attr, 5)

        db = AsyncMock()
        MockDB.return_value = db
        redis_client = AsyncMock()
        redis_client.pubsub = MagicMock(return_value=AsyncMock())
        mock_redis_mod.from_url.return_value = redis_client
        MockLLM.return_value = AsyncMock()

        state = await create_app_state(settings)
        assert state.transport is None


class TestShutdownAppState:

    async def test_stops_agents_and_infrastructure(self):
        from max.app import shutdown_app_state

        agent1 = AsyncMock()
        agent2 = AsyncMock()
        state = AppState(
            settings=MagicMock(),
            db=AsyncMock(),
            redis_client=AsyncMock(),
            bus=AsyncMock(),
            transport=None,
            warm_memory=MagicMock(),
            llm=AsyncMock(),
            circuit_breaker=MagicMock(),
            task_store=MagicMock(),
            quality_store=MagicMock(),
            evolution_store=MagicMock(),
            sentinel_store=MagicMock(),
            state_manager=MagicMock(),
            scheduler=AsyncMock(),
            tool_registry=MagicMock(),
            tool_executor=MagicMock(),
            agents={"coordinator": agent1, "planner": agent2},
            start_time=0.0,
        )

        await shutdown_app_state(state)

        state.scheduler.stop.assert_called_once()
        agent1.stop.assert_called_once()
        agent2.stop.assert_called_once()
        state.bus.close.assert_called_once()
        state.db.close.assert_called_once()
        state.llm.close.assert_called_once()
        state.redis_client.aclose.assert_called_once()

    async def test_shutdown_tolerates_agent_without_stop(self):
        from max.app import shutdown_app_state

        agent_no_stop = MagicMock(spec=[])  # no stop method
        state = AppState(
            settings=MagicMock(), db=AsyncMock(), redis_client=AsyncMock(),
            bus=AsyncMock(), transport=None, warm_memory=MagicMock(),
            llm=AsyncMock(), circuit_breaker=MagicMock(),
            task_store=MagicMock(), quality_store=MagicMock(),
            evolution_store=MagicMock(), sentinel_store=MagicMock(),
            state_manager=MagicMock(), scheduler=AsyncMock(),
            tool_registry=MagicMock(), tool_executor=MagicMock(),
            agents={"worker": agent_no_stop}, start_time=0.0,
        )
        # Should not raise
        await shutdown_app_state(state)


class TestCreateApp:

    def test_returns_fastapi_app(self):
        from fastapi import FastAPI
        from max.app import create_app

        app = create_app()
        assert isinstance(app, FastAPI)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_app_composition.py -v`
Expected: FAIL — `max.app` not found.

- [ ] **Step 3: Implement app.py**

Create `src/max/app.py`:

```python
"""Composition root — wires all Max subsystems into a running application."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as aioredis
from fastapi import FastAPI

from max.agents.base import AgentConfig
from max.api import create_api_app
from max.api.dependencies import AppState
from max.bus import MessageBus, StreamsTransport
from max.command.orchestrator import OrchestratorAgent
from max.command.planner import PlannerAgent
from max.command.runner import InProcessRunner
from max.command.task_store import TaskStore
from max.config import Settings
from max.db.postgres import Database
from max.db.redis_store import WarmMemory
from max.evolution.canary import CanaryRunner
from max.evolution.director import EvolutionDirectorAgent
from max.evolution.improver import ImprovementAgent
from max.evolution.self_model import SelfModel
from max.evolution.snapshot import SnapshotManager
from max.evolution.store import EvolutionStore
from max.llm import CircuitBreaker, LLMClient
from max.llm.models import ModelType
from max.memory.coordinator_state import CoordinatorStateManager
from max.quality.director import QualityDirectorAgent
from max.quality.rules import RuleEngine
from max.quality.store import QualityStore
from max.scheduler import Scheduler
from max.sentinel.agent import SentinelAgent
from max.sentinel.benchmarks import BenchmarkRegistry
from max.sentinel.comparator import ScoreComparator
from max.sentinel.runner import TestRunner
from max.sentinel.scorer import SentinelScorer
from max.sentinel.store import SentinelStore
from max.tools.executor import ToolExecutor
from max.tools.registry import ToolRegistry
from max.tools.store import ToolInvocationStore

logger = logging.getLogger(__name__)

MODEL_MAP = {
    "claude-opus-4-6": ModelType.OPUS,
}


def _model(name: str) -> ModelType:
    return MODEL_MAP.get(name, ModelType.OPUS)


async def create_app_state(settings: Settings) -> AppState:
    """Create and wire all dependencies. This is the single wiring point."""

    # ── 1. Infrastructure ────────────────────────────────────────────────
    db = Database(dsn=settings.postgres_dsn)
    await db.connect()
    await db.init_schema()

    redis_client = aioredis.from_url(settings.redis_url)
    warm_memory = WarmMemory(redis_client)

    # Bus transport
    transport: StreamsTransport | None = None
    if settings.bus_transport == "streams":
        transport = StreamsTransport(
            redis_client=redis_client,
            consumer_group=settings.bus_consumer_group,
            consumer_name=settings.bus_consumer_name,
            max_retries=settings.bus_dead_letter_max_retries,
            stream_max_len=settings.bus_stream_max_len,
        )
    bus = MessageBus(redis_client=redis_client, transport=transport)

    # LLM + Circuit Breaker
    circuit_breaker = CircuitBreaker(
        threshold=settings.llm_circuit_breaker_threshold,
        cooldown_seconds=settings.llm_circuit_breaker_cooldown_seconds,
    )
    llm = LLMClient(
        api_key=settings.anthropic_api_key,
        circuit_breaker=circuit_breaker,
    )

    # ── 2. Stores ────────────────────────────────────────────────────────
    task_store = TaskStore(db)
    quality_store = QualityStore(db)
    evolution_store = EvolutionStore(db)
    sentinel_store = SentinelStore(db)
    state_manager = CoordinatorStateManager(db, warm_memory)

    # ── 3. Tools ─────────────────────────────────────────────────────────
    tool_registry = ToolRegistry()
    tool_store = ToolInvocationStore(db)
    tool_executor = ToolExecutor(
        registry=tool_registry,
        store=tool_store,
        default_timeout=settings.tool_execution_timeout_seconds,
        audit_enabled=settings.tool_audit_enabled,
    )

    # ── 4. Agents ────────────────────────────────────────────────────────
    runner = InProcessRunner(llm, default_model=_model(settings.worker_model))

    from max.command.coordinator import CoordinatorAgent

    coordinator = CoordinatorAgent(
        config=AgentConfig(
            name="coordinator",
            system_prompt="You are Max's Coordinator.",
            model=_model(settings.coordinator_model),
            max_turns=settings.coordinator_max_active_tasks,
        ),
        llm=llm,
        bus=bus,
        db=db,
        warm_memory=warm_memory,
        settings=settings,
        state_manager=state_manager,
        task_store=task_store,
    )

    planner = PlannerAgent(
        config=AgentConfig(
            name="planner",
            system_prompt="You are Max's Planner.",
            model=_model(settings.planner_model),
            max_turns=settings.planner_max_subtasks,
        ),
        llm=llm,
        bus=bus,
        db=db,
        warm_memory=warm_memory,
        settings=settings,
        task_store=task_store,
    )

    orchestrator = OrchestratorAgent(
        config=AgentConfig(
            name="orchestrator",
            system_prompt="You are Max's Orchestrator.",
            model=_model(settings.orchestrator_model),
            max_turns=100,
        ),
        llm=llm,
        bus=bus,
        db=db,
        warm_memory=warm_memory,
        settings=settings,
        task_store=task_store,
        runner=runner,
        quality_store=quality_store,
    )

    rule_engine = RuleEngine(
        llm=llm,
        quality_store=quality_store,
        max_rules_per_audit=settings.quality_max_rules_per_audit,
    )
    quality_director = QualityDirectorAgent(
        config=AgentConfig(
            name="quality_director",
            system_prompt="You are Max's Quality Director.",
            model=_model(settings.quality_director_model),
            max_turns=50,
        ),
        llm=llm,
        bus=bus,
        db=db,
        warm_memory=warm_memory,
        settings=settings,
        task_store=task_store,
        quality_store=quality_store,
        rule_engine=rule_engine,
        state_manager=state_manager,
    )

    snapshot_manager = SnapshotManager(evolution_store)
    improver = ImprovementAgent(llm)
    canary_runner = CanaryRunner(
        llm=llm,
        task_store=task_store,
        quality_store=quality_store,
        replay_count=settings.evolution_canary_replay_count,
    )
    self_model = SelfModel(llm, evolution_store)

    # Sentinel
    sentinel_runner = TestRunner(llm, task_store, quality_store, evolution_store)
    comparator = ScoreComparator()
    sentinel_scorer = SentinelScorer(
        store=sentinel_store,
        runner=sentinel_runner,
        comparator=comparator,
        task_store=task_store,
        replay_count=settings.sentinel_replay_count,
    )
    benchmark_registry = BenchmarkRegistry()
    sentinel = SentinelAgent(
        bus=bus,
        scorer=sentinel_scorer,
        registry=benchmark_registry,
        store=sentinel_store,
    )

    evolution_director = EvolutionDirectorAgent(
        llm=llm,
        bus=bus,
        evo_store=evolution_store,
        quality_store=quality_store,
        snapshot_manager=snapshot_manager,
        improver=improver,
        canary_runner=canary_runner,
        self_model=self_model,
        settings=settings,
        state_manager=state_manager,
        task_store=task_store,
        sentinel_scorer=sentinel_scorer,
    )

    agents: dict[str, Any] = {
        "coordinator": coordinator,
        "planner": planner,
        "orchestrator": orchestrator,
        "quality_director": quality_director,
        "evolution_director": evolution_director,
        "sentinel": sentinel,
    }

    # Scheduler
    scheduler = Scheduler(db)

    return AppState(
        settings=settings,
        db=db,
        redis_client=redis_client,
        bus=bus,
        transport=transport,
        warm_memory=warm_memory,
        llm=llm,
        circuit_breaker=circuit_breaker,
        task_store=task_store,
        quality_store=quality_store,
        evolution_store=evolution_store,
        sentinel_store=sentinel_store,
        state_manager=state_manager,
        scheduler=scheduler,
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        agents=agents,
        start_time=time.time(),
    )


async def start_agents(state: AppState) -> None:
    """Start all agents (subscribe to bus channels)."""
    for name, agent in state.agents.items():
        if hasattr(agent, "start"):
            await agent.start()
            logger.info("Started agent: %s", name)


async def start_scheduler_jobs(state: AppState) -> None:
    """Register and start scheduled jobs."""
    s = state.settings
    state.scheduler.register(
        "evolution_trigger",
        s.evolution_scout_interval_hours * 3600,
        lambda: state.bus.publish("evolution.trigger", {"source": "scheduler"}),
    )
    state.scheduler.register(
        "sentinel_monitor",
        s.sentinel_monitor_interval_hours * 3600,
        lambda: state.bus.publish("sentinel.run_request", {"source": "scheduler", "scheduled": True}),
    )
    state.scheduler.register(
        "memory_compaction",
        s.memory_compaction_interval_seconds,
        lambda: state.warm_memory.compact() if hasattr(state.warm_memory, "compact") else None,
    )
    state.scheduler.register(
        "anchor_re_evaluation",
        s.memory_anchor_re_evaluation_interval_hours * 3600,
        lambda: state.bus.publish("anchors.re_evaluate", {"source": "scheduler"}),
    )
    await state.scheduler.load_state()
    await state.scheduler.start()
    logger.info("Scheduler started with %d jobs", len(state.scheduler._jobs))


async def shutdown_app_state(state: AppState) -> None:
    """Graceful shutdown in reverse dependency order."""
    logger.info("Shutting down Max...")

    # 1. Stop scheduler
    if hasattr(state.scheduler, "stop"):
        await state.scheduler.stop()

    # 2. Stop agents in reverse order
    for name in reversed(list(state.agents.keys())):
        agent = state.agents[name]
        if hasattr(agent, "stop"):
            try:
                await agent.stop()
                logger.info("Stopped agent: %s", name)
            except Exception:
                logger.exception("Error stopping agent: %s", name)

    # 3. Stop bus
    await state.bus.close()

    # 4. Close DB
    await state.db.close()

    # 5. Close LLM
    await state.llm.close()

    # 6. Close Redis
    await state.redis_client.aclose()

    logger.info("Max shutdown complete")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: wire, start, yield, shutdown."""
    from max.observability import configure_logging, configure_metrics

    settings = Settings()
    configure_logging(level=settings.max_log_level, json_format=True)
    configure_metrics(service_name=settings.otel_service_name, enabled=settings.otel_enabled)

    state = await create_app_state(settings)
    app.state.app_state = state

    await start_agents(state)
    await state.bus.start_listening()
    await start_scheduler_jobs(state)

    logger.info("Max is live on %s:%d", settings.max_host, settings.max_port)
    yield

    await shutdown_app_state(state)


def create_app() -> FastAPI:
    """Create the fully wired FastAPI application."""
    return create_api_app(lifespan=lifespan)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_app_composition.py -v`
Expected: All 6 tests PASS.

Note: Some tests may need adjustments based on import resolution. The subagent should fix any import issues that arise during testing.

- [ ] **Step 5: Commit**

```bash
git add src/max/app.py tests/test_app_composition.py
git commit -m "feat: add composition root wiring all Max subsystems"
```

---

### Task 11: Entry Point & Graceful Shutdown

Create `__main__.py` so Max can run as `python -m max` with proper signal handling.

**Files:**
- Create: `src/max/__main__.py`
- Test: `tests/test_entry_point.py`

- [ ] **Step 1: Write entry point tests**

Create `tests/test_entry_point.py`:

```python
"""Tests for the Max entry point."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestEntryPoint:

    def test_module_importable(self):
        import max.__main__
        assert hasattr(max.__main__, "main")

    @patch("max.__main__.uvicorn")
    @patch("max.__main__.create_app")
    def test_main_calls_uvicorn_run(self, mock_create, mock_uvicorn):
        from max.__main__ import main

        mock_app = MagicMock()
        mock_create.return_value = mock_app

        # Patch Settings to avoid needing env vars
        with patch("max.__main__.Settings") as MockSettings:
            MockSettings.return_value = MagicMock(max_host="0.0.0.0", max_port=8080)
            main()

        mock_uvicorn.run.assert_called_once()
        call_kwargs = mock_uvicorn.run.call_args
        assert call_kwargs[1]["host"] == "0.0.0.0"
        assert call_kwargs[1]["port"] == 8080

    @patch("max.__main__.uvicorn")
    @patch("max.__main__.create_app")
    def test_main_uses_settings_port(self, mock_create, mock_uvicorn):
        from max.__main__ import main

        mock_create.return_value = MagicMock()

        with patch("max.__main__.Settings") as MockSettings:
            MockSettings.return_value = MagicMock(max_host="127.0.0.1", max_port=9090)
            main()

        call_kwargs = mock_uvicorn.run.call_args
        assert call_kwargs[1]["host"] == "127.0.0.1"
        assert call_kwargs[1]["port"] == 9090

    def test_creates_fastapi_app(self):
        from max.app import create_app
        from fastapi import FastAPI

        app = create_app()
        assert isinstance(app, FastAPI)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_entry_point.py -v`
Expected: FAIL — `max.__main__` not found or incomplete.

- [ ] **Step 3: Implement __main__.py**

Create `src/max/__main__.py`:

```python
"""Entry point for Max: python -m max."""

from __future__ import annotations

import logging

import uvicorn

from max.app import create_app
from max.config import Settings

logger = logging.getLogger(__name__)


def main() -> None:
    """Start Max with uvicorn."""
    settings = Settings()
    app = create_app()

    uvicorn.run(
        app,
        host=settings.max_host,
        port=settings.max_port,
        log_level="info",
        access_log=False,  # We use structured JSON logging instead
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_entry_point.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/max/__main__.py tests/test_entry_point.py
git commit -m "feat: add entry point (python -m max) with uvicorn server"
```

---

### Task 12: Task Recovery

On startup, recover orphaned in-flight tasks from previous runs by re-publishing them to the appropriate bus channels.

**Files:**
- Create: `src/max/recovery.py`
- Test: `tests/test_task_recovery.py`

- [ ] **Step 1: Write task recovery tests**

Create `tests/test_task_recovery.py`:

```python
"""Tests for orphaned task recovery on startup."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from max.api.dependencies import AppState


def _make_state(**overrides) -> AppState:
    defaults = {
        "settings": MagicMock(task_recovery_enabled=True),
        "db": MagicMock(),
        "redis_client": MagicMock(),
        "bus": AsyncMock(),
        "transport": None,
        "warm_memory": MagicMock(),
        "llm": MagicMock(),
        "circuit_breaker": MagicMock(),
        "task_store": AsyncMock(),
        "quality_store": MagicMock(),
        "evolution_store": MagicMock(),
        "sentinel_store": MagicMock(),
        "state_manager": MagicMock(),
        "scheduler": MagicMock(),
        "tool_registry": MagicMock(),
        "tool_executor": MagicMock(),
        "agents": {},
        "start_time": 0.0,
    }
    defaults.update(overrides)
    return AppState(**defaults)


class TestRecoverOrphanedTasks:

    async def test_republishes_planned_tasks(self):
        from max.recovery import recover_orphaned_tasks

        task_id = uuid.uuid4()
        state = _make_state()
        state.task_store.get_active_tasks = AsyncMock(
            return_value=[{"id": str(task_id), "status": "planned", "goal_anchor": "do thing"}]
        )
        count = await recover_orphaned_tasks(state)
        assert count == 1
        state.bus.publish.assert_called_once_with(
            "tasks.execute", {"task_id": str(task_id), "recovery": True}
        )

    async def test_republishes_executing_tasks(self):
        from max.recovery import recover_orphaned_tasks

        task_id = uuid.uuid4()
        state = _make_state()
        state.task_store.get_active_tasks = AsyncMock(
            return_value=[{"id": str(task_id), "status": "executing", "goal_anchor": "run"}]
        )
        count = await recover_orphaned_tasks(state)
        assert count == 1
        state.bus.publish.assert_called_once_with(
            "tasks.execute", {"task_id": str(task_id), "recovery": True}
        )

    async def test_republishes_auditing_tasks(self):
        from max.recovery import recover_orphaned_tasks

        task_id = uuid.uuid4()
        state = _make_state()
        state.task_store.get_active_tasks = AsyncMock(
            return_value=[{"id": str(task_id), "status": "auditing", "goal_anchor": "check"}]
        )
        count = await recover_orphaned_tasks(state)
        assert count == 1
        state.bus.publish.assert_called_once_with(
            "audit.request", {"task_id": str(task_id), "recovery": True}
        )

    async def test_skips_pending_tasks(self):
        from max.recovery import recover_orphaned_tasks

        state = _make_state()
        state.task_store.get_active_tasks = AsyncMock(
            return_value=[{"id": str(uuid.uuid4()), "status": "pending", "goal_anchor": "wait"}]
        )
        count = await recover_orphaned_tasks(state)
        assert count == 0
        state.bus.publish.assert_not_called()

    async def test_handles_empty_task_list(self):
        from max.recovery import recover_orphaned_tasks

        state = _make_state()
        state.task_store.get_active_tasks = AsyncMock(return_value=[])
        count = await recover_orphaned_tasks(state)
        assert count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_task_recovery.py -v`
Expected: FAIL — `max.recovery` not found.

- [ ] **Step 3: Implement recovery.py**

Create `src/max/recovery.py`:

```python
"""Task recovery — re-queue orphaned in-flight tasks after a restart."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from max.api.dependencies import AppState

logger = logging.getLogger(__name__)

# Map task status to the bus channel for recovery
_RECOVERY_CHANNELS: dict[str, str] = {
    "planned": "tasks.execute",
    "executing": "tasks.execute",
    "auditing": "audit.request",
}


async def recover_orphaned_tasks(state: AppState) -> int:
    """Find in-flight tasks from a previous run and re-publish them.

    Returns the number of tasks recovered.
    """
    active_tasks = await state.task_store.get_active_tasks()
    recovered = 0

    for task in active_tasks:
        status = task.get("status", "")
        channel = _RECOVERY_CHANNELS.get(status)

        if channel is None:
            continue

        task_id = str(task["id"])
        await state.bus.publish(channel, {"task_id": task_id, "recovery": True})
        recovered += 1
        logger.info("Recovered orphaned task %s (status=%s) → %s", task_id, status, channel)

    if recovered:
        logger.info("Recovered %d orphaned task(s)", recovered)

    return recovered
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_task_recovery.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Wire recovery into composition root**

In `src/max/app.py`, add import at top:

```python
from max.recovery import recover_orphaned_tasks
```

In the `lifespan()` function, after `await start_scheduler_jobs(state)`, add:

```python
    if settings.task_recovery_enabled:
        recovered = await recover_orphaned_tasks(state)
        if recovered:
            logger.info("Recovered %d orphaned tasks from previous run", recovered)
```

- [ ] **Step 6: Run recovery tests again to confirm**

Run: `uv run pytest tests/test_task_recovery.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/max/recovery.py src/max/app.py tests/test_task_recovery.py
git commit -m "feat: add orphaned task recovery on startup"
```

---

### Task 13: Full Suite Run + Lint

Run all new Plan B tests, full regression suite, and fix any lint/format issues.

**Files:**
- All files from Tasks 1-12

- [ ] **Step 1: Run ruff check**

Run: `uv run ruff check src/max/api/ src/max/app.py src/max/__main__.py src/max/recovery.py tests/test_api_*.py tests/test_app_composition.py tests/test_entry_point.py tests/test_task_recovery.py tests/test_prerequisite_gaps.py`

Fix any errors.

- [ ] **Step 2: Run ruff format**

Run: `uv run ruff format src/max/api/ src/max/app.py src/max/__main__.py src/max/recovery.py tests/test_api_*.py tests/test_app_composition.py tests/test_entry_point.py tests/test_task_recovery.py tests/test_prerequisite_gaps.py`

- [ ] **Step 3: Run all Plan B tests**

Run: `uv run pytest tests/test_prerequisite_gaps.py tests/test_api_auth.py tests/test_api_rate_limit.py tests/test_api_health.py tests/test_api_messaging.py tests/test_api_telegram.py tests/test_api_introspection.py tests/test_api_admin.py tests/test_api_assembly.py tests/test_app_composition.py tests/test_entry_point.py tests/test_task_recovery.py -v`

Expected: All ~65 tests PASS.

- [ ] **Step 4: Run full regression suite**

Run: `uv run pytest --continue-on-collection-errors -q --tb=short`

Verify no new failures introduced by Plan B. Pre-existing failures (psutil, max.tools.native) are expected and not from Plan B.

- [ ] **Step 5: Commit lint/format fixes (if any)**

```bash
git add -u
git commit -m "style: fix lint and format for Plan B files"
```

---

## Spec Coverage Verification

| Spec Section | Task(s) | Status |
|---|---|---|
| §3 Composition Root & Lifecycle | Task 10, 11 | Covered |
| §3 create_app() wiring | Task 10 | Covered |
| §3 Entry point (__main__.py) | Task 11 | Covered |
| §4.1 API Key Auth | Task 2 | Covered |
| §4.2 Rate Limiting | Task 3 | Covered |
| §4.3 Health/Ready endpoints | Task 4 | Covered |
| §4.3 Messaging endpoints | Task 5 | Covered |
| §4.3 Telegram webhook | Task 6 | Covered |
| §4.3 Introspection endpoints | Task 7 | Covered |
| §4.3 Admin endpoints | Task 8 | Covered |
| §4.4 API versioning (/api/v1/) | Task 5-8 | Covered |
| §5 Scheduler jobs | Task 10 | Covered |
| §9.3 Task durability/recovery | Task 12 | Covered |
| §9.4 Graceful shutdown | Task 10 | Covered |
| §11 Missing methods (gaps) | Task 1 | Covered |

All spec sections for Plan B scope are covered.
