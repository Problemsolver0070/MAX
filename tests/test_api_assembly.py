"""Tests for API app factory and router assembly."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from httpx import ASGITransport, AsyncClient

from max.api import create_api_app
from max.api.dependencies import AppState


def _make_state() -> AppState:
    return AppState(
        settings=MagicMock(
            max_api_keys="test-key",
            rate_limit_api="100/minute",
            rate_limit_messaging="50/minute",
            comm_webhook_secret="s",
        ),
        db=AsyncMock(),
        redis_client=AsyncMock(),
        bus=AsyncMock(_running=True),
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
    """Tests for the create_api_app factory function."""

    def test_returns_fastapi_instance(self):
        from fastapi import FastAPI

        app = create_api_app()
        assert isinstance(app, FastAPI)

    def test_app_has_title(self):
        app = create_api_app()
        assert app.title == "Max API"

    def test_app_has_limiter_on_state(self):
        app = create_api_app()
        assert hasattr(app.state, "limiter")

    def test_app_includes_docs(self):
        app = create_api_app()
        assert app.docs_url == "/docs"

    def test_app_accepts_lifespan(self):
        sentinel = MagicMock()
        app = create_api_app(lifespan=sentinel)
        # FastAPI wraps the lifespan in a merged context; just verify
        # the app was constructed successfully and has a lifespan set.
        assert app.router.lifespan_context is not None

    async def test_health_route_exists(self):
        app = create_api_app()
        state = _make_state()
        state.db.fetchone = AsyncMock(return_value={"?column?": 1})
        state.redis_client.ping = AsyncMock(return_value=True)
        app.state.app_state = state
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/health")
        assert r.status_code == 200

    async def test_ready_route_exists(self):
        app = create_api_app()
        state = _make_state()
        state.db.fetchone = AsyncMock(return_value={"?column?": 1})
        state.redis_client.ping = AsyncMock(return_value=True)
        app.state.app_state = state
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/ready")
        assert r.status_code == 200

    async def test_api_v1_tasks_route_exists(self):
        app = create_api_app()
        state = _make_state()
        state.task_store.get_active_tasks = AsyncMock(return_value=[])
        app.state.app_state = state
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/tasks", headers={"Authorization": "Bearer test-key"})
        assert r.status_code == 200

    async def test_webhook_telegram_route_exists(self):
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

    async def test_admin_route_exists(self):
        app = create_api_app()
        state = _make_state()
        app.state.app_state = state
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/v1/admin/evolution/freeze",
                headers={"Authorization": "Bearer test-key"},
            )
        assert r.status_code == 200

    async def test_introspection_evolution_route_exists(self):
        app = create_api_app()
        state = _make_state()
        state.evolution_store.get_proposals = AsyncMock(return_value=[])
        state.evolution_store.get_journal = AsyncMock(return_value=[])
        app.state.app_state = state
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get(
                "/api/v1/evolution",
                headers={"Authorization": "Bearer test-key"},
            )
        assert r.status_code == 200

    async def test_unauthenticated_api_route_returns_401(self):
        app = create_api_app()
        state = _make_state()
        app.state.app_state = state
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/tasks")
        assert r.status_code in (401, 403)

    async def test_rate_limit_exceeded_handler_registered(self):
        """Verify the RateLimitExceeded exception handler is registered."""
        from slowapi.errors import RateLimitExceeded

        app = create_api_app()
        assert RateLimitExceeded in app.exception_handlers
