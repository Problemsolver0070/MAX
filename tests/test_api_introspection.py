"""Tests for introspection endpoints."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

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
        assert r.status_code == 401


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
