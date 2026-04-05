"""Tests for Phase 6A tool models."""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from max.tools.models import AgentToolPolicy, ProviderHealth, ToolResult


class TestToolResult:
    def test_success_result(self):
        result = ToolResult(
            tool_id="file.read",
            success=True,
            output={"content": "hello"},
            duration_ms=42,
        )
        assert result.success is True
        assert result.output == {"content": "hello"}
        assert result.error is None

    def test_failure_result(self):
        result = ToolResult(
            tool_id="file.read",
            success=False,
            error="File not found",
        )
        assert result.success is False
        assert result.error == "File not found"

    def test_defaults(self):
        result = ToolResult(tool_id="test", success=True)
        assert result.output is None
        assert result.duration_ms == 0


class TestAgentToolPolicy:
    def test_explicit_tool_access(self):
        policy = AgentToolPolicy(
            agent_name="worker",
            allowed_tools=["file.read", "file.write"],
        )
        assert "file.read" in policy.allowed_tools
        assert policy.denied_tools == []

    def test_category_access(self):
        policy = AgentToolPolicy(
            agent_name="worker",
            allowed_categories=["code", "web"],
        )
        assert "code" in policy.allowed_categories

    def test_denied_tools(self):
        policy = AgentToolPolicy(
            agent_name="worker",
            allowed_categories=["code"],
            denied_tools=["shell.execute"],
        )
        assert "shell.execute" in policy.denied_tools

    def test_defaults(self):
        policy = AgentToolPolicy(agent_name="test")
        assert policy.allowed_tools == []
        assert policy.allowed_categories == []
        assert policy.denied_tools == []


class TestProviderHealth:
    def test_healthy_provider(self):
        health = ProviderHealth(provider_id="native")
        assert health.is_healthy is True
        assert health.error_count == 0

    def test_unhealthy_provider(self):
        health = ProviderHealth(
            provider_id="mcp-server",
            is_healthy=False,
            error_count=5,
            consecutive_failures=3,
            last_checked=datetime.now(UTC),
        )
        assert health.is_healthy is False
        assert health.consecutive_failures == 3
