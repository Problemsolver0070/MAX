"""Tests for ToolInvocationStore."""

import uuid
from unittest.mock import AsyncMock

import pytest

from max.tools.store import ToolInvocationStore


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.fetchone = AsyncMock(return_value=None)
    db.fetchall = AsyncMock(return_value=[])
    return db


@pytest.fixture
def store(mock_db):
    return ToolInvocationStore(mock_db)


class TestRecord:
    @pytest.mark.asyncio
    async def test_inserts_invocation(self, store, mock_db):
        await store.record(
            agent_id="worker-123",
            tool_id="file.read",
            inputs={"path": "/tmp/test.txt"},
            output={"content": "hello"},
            success=True,
            error=None,
            duration_ms=42,
        )
        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args
        assert "INSERT INTO tool_invocations" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_records_failure(self, store, mock_db):
        await store.record(
            agent_id="worker-123",
            tool_id="file.read",
            inputs={"path": "/nonexistent"},
            output=None,
            success=False,
            error="File not found",
            duration_ms=5,
        )
        mock_db.execute.assert_called_once()


class TestGetInvocations:
    @pytest.mark.asyncio
    async def test_fetches_by_tool_id(self, store, mock_db):
        mock_db.fetchall.return_value = [
            {"id": uuid.uuid4(), "tool_id": "file.read", "success": True}
        ]
        rows = await store.get_invocations("file.read", limit=10)
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_fetches_by_agent_id(self, store, mock_db):
        mock_db.fetchall.return_value = [
            {"id": uuid.uuid4(), "agent_id": "worker-1", "tool_id": "file.read"}
        ]
        rows = await store.get_agent_invocations("worker-1", limit=10)
        assert len(rows) == 1


class TestGetStats:
    @pytest.mark.asyncio
    async def test_returns_stats(self, store, mock_db):
        mock_db.fetchone.return_value = {
            "total": 100,
            "success_count": 95,
            "avg_duration": 42.5,
        }
        stats = await store.get_stats("file.read", hours=24)
        assert stats["total"] == 100
        assert stats["success_count"] == 95
