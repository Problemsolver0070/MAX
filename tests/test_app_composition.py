"""Tests for the composition root — src/max/app.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from max.api.dependencies import AppState
from max.config import Settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides) -> Settings:
    """Create a Settings instance with sensible test defaults."""
    defaults = {
        "anthropic_api_key": "test-key",
        "postgres_password": "test-pw",
        "redis_url": "redis://localhost:6379/0",
        "bus_transport": "streams",
    }
    defaults.update(overrides)
    return Settings(**defaults)


# ---------------------------------------------------------------------------
# Tests for create_app_state
# ---------------------------------------------------------------------------


class TestCreateAppState:
    """Verify create_app_state wires all dependencies into AppState."""

    @pytest.mark.asyncio
    async def test_returns_app_state_with_all_fields(self):
        """create_app_state should return an AppState with all fields populated."""
        settings = _make_settings()

        mock_redis = MagicMock()
        mock_redis.close = AsyncMock()

        with (
            patch("max.app.aioredis.from_url", return_value=mock_redis),
            patch("max.app.Database") as mock_db_cls,
            patch("max.app.configure_logging"),
            patch("max.app.configure_metrics") as mock_metrics,
        ):
            mock_db_cls.return_value = MagicMock()
            mock_metrics.return_value = MagicMock()

            from max.app import create_app_state

            state = create_app_state(settings)

        assert isinstance(state, AppState)
        assert state.settings is settings
        assert state.db is not None
        assert state.redis_client is mock_redis
        assert state.bus is not None
        assert state.warm_memory is not None
        assert state.llm is not None
        assert state.circuit_breaker is not None
        assert state.task_store is not None
        assert state.quality_store is not None
        assert state.evolution_store is not None
        assert state.sentinel_store is not None
        assert state.state_manager is not None
        assert state.scheduler is not None
        assert state.tool_registry is not None
        assert state.tool_executor is not None
        assert "coordinator" in state.agents
        assert "planner" in state.agents
        assert "orchestrator" in state.agents
        assert "quality_director" in state.agents
        assert "evolution_director" in state.agents
        assert "sentinel" in state.agents

    @pytest.mark.asyncio
    async def test_base_url_passed_to_llm_client(self):
        """create_app_state should pass anthropic_base_url to LLMClient."""
        settings = _make_settings(anthropic_base_url="https://example.com/anthropic")
        mock_redis = MagicMock()
        mock_redis.close = AsyncMock()

        with (
            patch("max.app.aioredis.from_url", return_value=mock_redis),
            patch("max.app.Database") as mock_db_cls,
            patch("max.app.configure_logging"),
            patch("max.app.configure_metrics") as mock_metrics,
        ):
            mock_db_cls.return_value = MagicMock()
            mock_metrics.return_value = MagicMock()
            from max.app import create_app_state

            state = create_app_state(settings)

        assert "example.com" in str(state.llm._client.base_url)

    @pytest.mark.asyncio
    async def test_streams_transport_when_configured(self):
        """When bus_transport='streams', transport should be a StreamsTransport."""
        settings = _make_settings(bus_transport="streams")

        mock_redis = MagicMock()

        with (
            patch("max.app.aioredis.from_url", return_value=mock_redis),
            patch("max.app.Database") as mock_db_cls,
            patch("max.app.configure_logging"),
            patch("max.app.configure_metrics") as mock_metrics,
        ):
            mock_db_cls.return_value = MagicMock()
            mock_metrics.return_value = MagicMock()

            from max.app import create_app_state

            state = create_app_state(settings)

        from max.bus.streams import StreamsTransport

        assert isinstance(state.transport, StreamsTransport)

    @pytest.mark.asyncio
    async def test_message_router_created_with_telegram_token(self):
        """MessageRouter should be in agents when telegram_bot_token is set."""
        settings = _make_settings(
            telegram_bot_token="123:faketoken",
            max_owner_telegram_id="999",
        )
        mock_redis = MagicMock()
        mock_redis.close = AsyncMock()

        with (
            patch("max.app.aioredis.from_url", return_value=mock_redis),
            patch("max.app.Database") as mock_db_cls,
            patch("max.app.configure_logging"),
            patch("max.app.configure_metrics") as mock_metrics,
        ):
            mock_db_cls.return_value = MagicMock()
            mock_metrics.return_value = MagicMock()
            from max.app import create_app_state

            state = create_app_state(settings)

        assert "message_router" in state.agents

    @pytest.mark.asyncio
    async def test_message_router_not_created_without_telegram_token(self):
        """MessageRouter should NOT be in agents when telegram_bot_token is empty."""
        settings = _make_settings()  # no telegram_bot_token
        mock_redis = MagicMock()
        mock_redis.close = AsyncMock()

        with (
            patch("max.app.aioredis.from_url", return_value=mock_redis),
            patch("max.app.Database") as mock_db_cls,
            patch("max.app.configure_logging"),
            patch("max.app.configure_metrics") as mock_metrics,
        ):
            mock_db_cls.return_value = MagicMock()
            mock_metrics.return_value = MagicMock()
            from max.app import create_app_state

            state = create_app_state(settings)

        assert "message_router" not in state.agents

    @pytest.mark.asyncio
    async def test_pubsub_fallback_when_not_streams(self):
        """When bus_transport!='streams', transport should be None (pubsub fallback)."""
        settings = _make_settings(bus_transport="pubsub")

        mock_redis = MagicMock()

        with (
            patch("max.app.aioredis.from_url", return_value=mock_redis),
            patch("max.app.Database") as mock_db_cls,
            patch("max.app.configure_logging"),
            patch("max.app.configure_metrics") as mock_metrics,
        ):
            mock_db_cls.return_value = MagicMock()
            mock_metrics.return_value = MagicMock()

            from max.app import create_app_state

            state = create_app_state(settings)

        assert state.transport is None


# ---------------------------------------------------------------------------
# Tests for shutdown_app_state
# ---------------------------------------------------------------------------


class TestShutdownAppState:
    """Verify shutdown_app_state stops everything cleanly."""

    @pytest.mark.asyncio
    async def test_stops_agents_and_infrastructure(self):
        """shutdown_app_state should stop scheduler, agents, bus, LLM, DB, Redis."""
        from max.app import shutdown_app_state

        mock_agent = AsyncMock()
        mock_agent.stop = AsyncMock()

        state = AppState(
            settings=_make_settings(),
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
            agents={
                "coordinator": mock_agent,
                "planner": mock_agent,
            },
        )

        await shutdown_app_state(state)

        state.scheduler.stop.assert_awaited_once()
        assert mock_agent.stop.await_count == 2
        state.bus.close.assert_awaited_once()
        state.llm.close.assert_awaited_once()
        state.db.close.assert_awaited_once()
        state.redis_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_tolerates_agents_without_stop(self):
        """shutdown_app_state should not crash on agents missing stop()."""
        from max.app import shutdown_app_state

        agent_no_stop = MagicMock(spec=[])  # no stop attribute

        state = AppState(
            settings=_make_settings(),
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
            agents={"no_stop": agent_no_stop},
        )

        # Should not raise
        await shutdown_app_state(state)


# ---------------------------------------------------------------------------
# Tests for create_app
# ---------------------------------------------------------------------------


class TestCreateApp:
    """Verify create_app returns a properly configured FastAPI application."""

    def test_returns_fastapi_app(self):
        """create_app should return a FastAPI instance."""
        from max.app import create_app

        app = create_app()

        from fastapi import FastAPI

        assert isinstance(app, FastAPI)
