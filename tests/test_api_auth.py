"""Tests for API key authentication."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

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

    async def test_missing_auth_header_returns_401(self):
        app = _make_app(_make_state())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/protected")
        assert r.status_code == 401

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
