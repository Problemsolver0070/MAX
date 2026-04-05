"""Tests for ToolExecutor pipeline."""

from unittest.mock import AsyncMock

import pytest

from max.tools.executor import ToolExecutor
from max.tools.models import AgentToolPolicy
from max.tools.providers.native import NativeToolProvider
from max.tools.registry import ToolDefinition, ToolRegistry


def _make_executor():
    registry = ToolRegistry()
    store = AsyncMock()
    store.record = AsyncMock()

    provider = NativeToolProvider()

    async def read_handler(inputs):
        return {"content": f"Contents of {inputs['path']}"}

    provider.register_tool(
        ToolDefinition(
            tool_id="file.read",
            category="code",
            description="Read a file",
            permissions=["fs.read"],
            provider_id="native",
        ),
        read_handler,
    )

    async def slow_handler(inputs):
        import asyncio

        await asyncio.sleep(999)
        return "done"

    provider.register_tool(
        ToolDefinition(
            tool_id="test.slow",
            category="test",
            description="Slow tool",
            provider_id="native",
            timeout_seconds=1,
        ),
        slow_handler,
    )

    registry._providers["native"] = provider
    # Register tools directly
    for tool_def in [
        ToolDefinition(
            tool_id="file.read",
            category="code",
            description="Read a file",
            permissions=["fs.read"],
            provider_id="native",
        ),
        ToolDefinition(
            tool_id="test.slow",
            category="test",
            description="Slow tool",
            provider_id="native",
            timeout_seconds=1,
        ),
    ]:
        registry.register(tool_def)

    policy = AgentToolPolicy(
        agent_name="worker",
        allowed_categories=["code", "test"],
    )
    registry.set_agent_policy(policy)

    executor = ToolExecutor(
        registry=registry,
        store=store,
        default_timeout=60,
        audit_enabled=True,
    )
    return executor, registry, store, provider


class TestExecuteSuccess:
    @pytest.mark.asyncio
    async def test_executes_and_returns_result(self):
        executor, registry, store, provider = _make_executor()
        result = await executor.execute("worker", "file.read", {"path": "/tmp/test"})
        assert result.success is True
        assert result.output["content"] == "Contents of /tmp/test"

    @pytest.mark.asyncio
    async def test_records_audit_log(self):
        executor, registry, store, provider = _make_executor()
        await executor.execute("worker", "file.read", {"path": "/tmp/test"})
        store.record.assert_called_once()
        call_kwargs = store.record.call_args[1]
        assert call_kwargs["tool_id"] == "file.read"
        assert call_kwargs["success"] is True


class TestPermissionDenied:
    @pytest.mark.asyncio
    async def test_denies_unauthorized_agent(self):
        executor, registry, store, provider = _make_executor()
        result = await executor.execute("unauthorized_agent", "file.read", {"path": "/tmp"})
        assert result.success is False
        assert "permission denied" in result.error.lower()


class TestToolNotFound:
    @pytest.mark.asyncio
    async def test_not_found(self):
        executor, registry, store, provider = _make_executor()
        result = await executor.execute("worker", "nonexistent", {})
        assert result.success is False
        assert "not found" in result.error.lower()


class TestTimeout:
    @pytest.mark.asyncio
    async def test_timeout_returns_error(self):
        executor, registry, store, provider = _make_executor()
        # Override to very short timeout
        executor._default_timeout = 0.01
        tool = registry.get("test.slow")
        tool.timeout_seconds = 0
        result = await executor.execute("worker", "test.slow", {})
        assert result.success is False
        assert "timed out" in result.error.lower()


class TestProviderUnhealthy:
    @pytest.mark.asyncio
    async def test_rejects_when_provider_unhealthy(self):
        executor, registry, store, provider = _make_executor()
        # Mock provider to be unhealthy
        provider.health_check = AsyncMock(return_value=False)
        result = await executor.execute("worker", "file.read", {"path": "/tmp"})
        assert result.success is False
        assert "unhealthy" in result.error.lower()


class TestAuditDisabled:
    @pytest.mark.asyncio
    async def test_no_audit_when_disabled(self):
        executor, registry, store, provider = _make_executor()
        executor._audit_enabled = False
        await executor.execute("worker", "file.read", {"path": "/tmp"})
        store.record.assert_not_called()
