# Phase 6A: Tool Framework + Core Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the tool execution infrastructure (providers, executor, registry, audit trail, agent tool loop) and 15 core tools so Max agents can discover, invoke, and audit tools during task execution.

**Architecture:** Three-layer system — ToolRegistry (metadata + permissions), ToolExecutor (permission → execute → audit pipeline), and ToolProviders (NativeToolProvider for Python functions, MCPToolProvider for MCP servers). Agent tool loop in BaseAgent.think_with_tools() wraps the existing think() with tool_use handling. 15 core tools (file, shell, git, web, process, search) prove the framework end-to-end.

**Tech Stack:** Python 3.12+, asyncio, pydantic v2, httpx, psutil, asyncio.subprocess, mcp SDK

---

## File Structure

```
src/max/tools/
├── __init__.py               # Package exports (update)
├── registry.py               # Enhanced ToolRegistry (update from Phase 1)
├── models.py                 # ToolResult, AgentToolPolicy, ProviderHealth (new)
├── executor.py               # ToolExecutor pipeline (new)
├── store.py                  # ToolInvocationStore (new)
├── providers/
│   ├── __init__.py           # Provider exports (new)
│   ├── base.py               # ToolProvider ABC (new)
│   ├── native.py             # NativeToolProvider (new)
│   └── mcp.py                # MCPToolProvider (new)
└── native/
    ├── __init__.py            # Native tool registration helper (new)
    ├── file_tools.py          # 6 file system tools (new)
    ├── shell_tools.py         # 1 shell tool (new)
    ├── git_tools.py           # 4 git tools (new)
    ├── web_tools.py           # 2 HTTP tools (new)
    ├── process_tools.py       # 1 process tool (new)
    └── search_tools.py        # 1 grep tool (new)

src/max/agents/base.py          # Add think_with_tools() (modify)
src/max/config.py               # Add tool settings (modify)
src/max/db/schema.sql           # Add tool_invocations table (modify)
src/max/db/migrations/006_tool_system.sql  # Migration (new)

tests/
├── test_tool_models.py         # ToolResult, AgentToolPolicy, ProviderHealth tests (new)
├── test_tool_executor.py       # Executor pipeline tests (new)
├── test_tool_store.py          # ToolInvocationStore tests (new)
├── test_tool_provider_native.py # NativeToolProvider tests (new)
├── test_tool_provider_mcp.py   # MCPToolProvider tests (new)
├── test_native_file_tools.py   # File tool tests (new)
├── test_native_shell_tools.py  # Shell tool tests (new)
├── test_native_git_tools.py    # Git tool tests (new)
├── test_native_web_tools.py    # Web tool tests (new)
├── test_native_process_tools.py # Process tool tests (new)
├── test_native_search_tools.py # Search tool tests (new)
├── test_agent_tool_loop.py     # think_with_tools() integration (new)
└── test_tool_registry.py       # Update existing tests (modify)
```

---

### Task 1: Config Settings + DB Migration

**Files:**
- Modify: `src/max/config.py`
- Create: `src/max/db/migrations/006_tool_system.sql`
- Modify: `src/max/db/schema.sql`
- Modify: `tests/test_config.py`
- Modify: `tests/test_postgres.py`

- [ ] **Step 1: Write the failing test for config settings**

Add to `tests/test_config.py`:

```python
def test_tool_system_settings_defaults(settings):
    assert settings.tool_execution_timeout_seconds == 60
    assert settings.tool_max_concurrent == 10
    assert settings.tool_audit_enabled is True
    assert settings.tool_shell_timeout_seconds == 30
    assert settings.tool_http_timeout_seconds == 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::test_tool_system_settings_defaults -v`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Add settings to config.py**

Add after the Quality Gate settings block (after line 81) in `src/max/config.py`:

```python
    # Tool system
    tool_execution_timeout_seconds: int = 60
    tool_max_concurrent: int = 10
    tool_audit_enabled: bool = True
    tool_shell_timeout_seconds: int = 30
    tool_http_timeout_seconds: int = 30
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py::test_tool_system_settings_defaults -v`
Expected: PASS

- [ ] **Step 5: Create migration file**

Create `src/max/db/migrations/006_tool_system.sql`:

```sql
-- Phase 6A: Tool System
CREATE TABLE IF NOT EXISTS tool_invocations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id VARCHAR(100) NOT NULL,
    tool_id VARCHAR(100) NOT NULL,
    inputs JSONB NOT NULL DEFAULT '{}',
    output JSONB,
    success BOOLEAN NOT NULL,
    error TEXT,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tool_invocations_agent ON tool_invocations(agent_id);
CREATE INDEX IF NOT EXISTS idx_tool_invocations_tool ON tool_invocations(tool_id);
CREATE INDEX IF NOT EXISTS idx_tool_invocations_created ON tool_invocations(created_at DESC);
```

- [ ] **Step 6: Append to schema.sql**

Add to the end of `src/max/db/schema.sql`:

```sql
-- ═════════════════════════════════════════════════════════════════════════════
-- Phase 6A: Tool System
-- ═════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS tool_invocations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id VARCHAR(100) NOT NULL,
    tool_id VARCHAR(100) NOT NULL,
    inputs JSONB NOT NULL DEFAULT '{}',
    output JSONB,
    success BOOLEAN NOT NULL,
    error TEXT,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tool_invocations_agent ON tool_invocations(agent_id);
CREATE INDEX IF NOT EXISTS idx_tool_invocations_tool ON tool_invocations(tool_id);
CREATE INDEX IF NOT EXISTS idx_tool_invocations_created ON tool_invocations(created_at DESC);
```

- [ ] **Step 7: Add postgres integration test**

Add to `tests/test_postgres.py`:

```python
@pytest.mark.asyncio
async def test_tool_invocations_table_exists(db):
    """Verify Phase 6A tool_invocations table is created."""
    tables = await db.fetchall("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    table_names = {row["tablename"] for row in tables}
    assert "tool_invocations" in table_names
```

- [ ] **Step 8: Run all config tests**

Run: `pytest tests/test_config.py -v`
Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
git add src/max/config.py src/max/db/migrations/006_tool_system.sql src/max/db/schema.sql tests/test_config.py tests/test_postgres.py
git commit -m "feat(config): add Phase 6A Tool System settings and DB migration"
```

---

### Task 2: Tool Models

**Files:**
- Create: `src/max/tools/models.py`
- Create: `tests/test_tool_models.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tool_models.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tool_models.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create the models file**

Create `src/max/tools/models.py`:

```python
"""Phase 6A Tool System models — results, policies, health."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Result of a tool invocation."""

    tool_id: str
    success: bool
    output: Any = None
    error: str | None = None
    duration_ms: int = 0


class AgentToolPolicy(BaseModel):
    """Per-agent tool access whitelist."""

    agent_name: str
    allowed_tools: list[str] = Field(default_factory=list)
    allowed_categories: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)


class ProviderHealth(BaseModel):
    """Health status for a tool provider."""

    provider_id: str
    is_healthy: bool = True
    last_checked: datetime | None = None
    error_count: int = 0
    consecutive_failures: int = 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tool_models.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/max/tools/models.py tests/test_tool_models.py
git commit -m "feat(tools): add Phase 6A tool models (ToolResult, AgentToolPolicy, ProviderHealth)"
```

---

### Task 3: ToolProvider ABC + NativeToolProvider

**Files:**
- Create: `src/max/tools/providers/__init__.py`
- Create: `src/max/tools/providers/base.py`
- Create: `src/max/tools/providers/native.py`
- Create: `tests/test_tool_provider_native.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tool_provider_native.py`:

```python
"""Tests for NativeToolProvider."""

import pytest

from max.tools.models import ToolResult
from max.tools.providers.native import NativeToolProvider
from max.tools.registry import ToolDefinition


class TestNativeToolProvider:
    @pytest.mark.asyncio
    async def test_register_and_list_tools(self):
        provider = NativeToolProvider()

        async def my_handler(inputs: dict) -> str:
            return "hello"

        tool_def = ToolDefinition(
            tool_id="test.hello",
            category="test",
            description="Say hello",
            provider_id="native",
        )
        provider.register_tool(tool_def, my_handler)
        tools = await provider.list_tools()
        assert len(tools) == 1
        assert tools[0].tool_id == "test.hello"

    @pytest.mark.asyncio
    async def test_execute_success(self):
        provider = NativeToolProvider()

        async def read_file(inputs: dict) -> dict:
            return {"content": f"Contents of {inputs['path']}"}

        provider.register_tool(
            ToolDefinition(
                tool_id="file.read",
                category="code",
                description="Read a file",
                provider_id="native",
            ),
            read_file,
        )
        result = await provider.execute("file.read", {"path": "/tmp/test.txt"})
        assert result.success is True
        assert result.output["content"] == "Contents of /tmp/test.txt"

    @pytest.mark.asyncio
    async def test_execute_not_found(self):
        provider = NativeToolProvider()
        result = await provider.execute("nonexistent", {})
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_handler_exception(self):
        provider = NativeToolProvider()

        async def bad_handler(inputs: dict) -> str:
            raise ValueError("Oops")

        provider.register_tool(
            ToolDefinition(
                tool_id="test.bad",
                category="test",
                description="A bad tool",
                provider_id="native",
            ),
            bad_handler,
        )
        result = await provider.execute("test.bad", {})
        assert result.success is False
        assert "Oops" in result.error

    @pytest.mark.asyncio
    async def test_health_check(self):
        provider = NativeToolProvider()
        assert await provider.health_check() is True

    def test_provider_id(self):
        provider = NativeToolProvider()
        assert provider.provider_id == "native"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tool_provider_native.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create provider base class**

Create `src/max/tools/providers/__init__.py`:

```python
"""Tool providers — abstractions for different tool sources."""

from max.tools.providers.base import ToolProvider
from max.tools.providers.native import NativeToolProvider

__all__ = ["NativeToolProvider", "ToolProvider"]
```

Create `src/max/tools/providers/base.py`:

```python
"""ToolProvider ABC — base class for all tool sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from max.tools.models import ToolResult
from max.tools.registry import ToolDefinition


class ToolProvider(ABC):
    """Base class for all tool sources."""

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Unique identifier for this provider."""

    @abstractmethod
    async def list_tools(self) -> list[ToolDefinition]:
        """List all tools available from this provider."""

    @abstractmethod
    async def execute(self, tool_id: str, inputs: dict[str, Any]) -> ToolResult:
        """Execute a tool and return the result."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is healthy and responsive."""
```

- [ ] **Step 4: Create NativeToolProvider**

Create `src/max/tools/providers/native.py`:

```python
"""NativeToolProvider — wraps Python async functions as tools."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

from max.tools.models import ToolResult
from max.tools.providers.base import ToolProvider
from max.tools.registry import ToolDefinition

logger = logging.getLogger(__name__)

ToolHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, Any]]


class NativeToolProvider(ToolProvider):
    """Provides tools implemented as Python async functions."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, ToolHandler] = {}

    @property
    def provider_id(self) -> str:
        return "native"

    def register_tool(self, definition: ToolDefinition, handler: ToolHandler) -> None:
        """Register a native tool with its handler function."""
        self._tools[definition.tool_id] = definition
        self._handlers[definition.tool_id] = handler
        logger.debug("Registered native tool: %s", definition.tool_id)

    async def list_tools(self) -> list[ToolDefinition]:
        """Return all registered native tools."""
        return list(self._tools.values())

    async def execute(self, tool_id: str, inputs: dict[str, Any]) -> ToolResult:
        """Execute a native tool handler."""
        handler = self._handlers.get(tool_id)
        if handler is None:
            return ToolResult(
                tool_id=tool_id,
                success=False,
                error=f"Tool not found: {tool_id}",
            )

        start = time.monotonic()
        try:
            output = await handler(inputs)
            duration_ms = int((time.monotonic() - start) * 1000)
            return ToolResult(
                tool_id=tool_id,
                success=True,
                output=output,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.exception("Native tool %s failed", tool_id)
            return ToolResult(
                tool_id=tool_id,
                success=False,
                error=str(exc),
                duration_ms=duration_ms,
            )

    async def health_check(self) -> bool:
        """Native provider is always healthy."""
        return True
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_tool_provider_native.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/max/tools/providers/ tests/test_tool_provider_native.py
git commit -m "feat(tools): add ToolProvider ABC and NativeToolProvider"
```

---

### Task 4: ToolInvocationStore

**Files:**
- Create: `src/max/tools/store.py`
- Create: `tests/test_tool_store.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tool_store.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tool_store.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create the store**

Create `src/max/tools/store.py`:

```python
"""ToolInvocationStore — audit trail for tool invocations."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from max.db.postgres import Database

logger = logging.getLogger(__name__)


class ToolInvocationStore:
    """Persistence layer for tool invocation audit trail."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self,
        agent_id: str,
        tool_id: str,
        inputs: dict[str, Any],
        output: Any,
        success: bool,
        error: str | None,
        duration_ms: int,
    ) -> None:
        """Record a tool invocation."""
        await self._db.execute(
            "INSERT INTO tool_invocations "
            "(id, agent_id, tool_id, inputs, output, success, error, duration_ms) "
            "VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7, $8)",
            uuid.uuid4(),
            agent_id,
            tool_id,
            json.dumps(inputs),
            json.dumps(output) if output is not None else None,
            success,
            error,
            duration_ms,
        )

    async def get_invocations(self, tool_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent invocations for a tool."""
        return await self._db.fetchall(
            "SELECT * FROM tool_invocations WHERE tool_id = $1 "
            "ORDER BY created_at DESC LIMIT $2",
            tool_id,
            limit,
        )

    async def get_agent_invocations(self, agent_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent invocations by an agent."""
        return await self._db.fetchall(
            "SELECT * FROM tool_invocations WHERE agent_id = $1 "
            "ORDER BY created_at DESC LIMIT $2",
            agent_id,
            limit,
        )

    async def get_stats(self, tool_id: str, hours: int = 24) -> dict[str, Any]:
        """Get aggregated stats for a tool."""
        row = await self._db.fetchone(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN success THEN 1 ELSE 0 END) AS success_count, "
            "AVG(duration_ms) AS avg_duration "
            "FROM tool_invocations WHERE tool_id = $1 "
            "AND created_at > NOW() - INTERVAL '1 hour' * $2",
            tool_id,
            hours,
        )
        if row is None:
            return {"total": 0, "success_count": 0, "avg_duration": 0.0}
        return {
            "total": row["total"] or 0,
            "success_count": row["success_count"] or 0,
            "avg_duration": float(row["avg_duration"]) if row["avg_duration"] else 0.0,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tool_store.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/max/tools/store.py tests/test_tool_store.py
git commit -m "feat(tools): add ToolInvocationStore for audit trail"
```

---

### Task 5: Enhanced ToolRegistry + ToolExecutor

**Files:**
- Modify: `src/max/tools/registry.py`
- Create: `src/max/tools/executor.py`
- Create: `tests/test_tool_executor.py`
- Modify: `tests/test_tool_registry.py`

- [ ] **Step 1: Write the failing tests for enhanced registry**

Add to `tests/test_tool_registry.py`:

```python
from unittest.mock import AsyncMock

import pytest

from max.tools.models import AgentToolPolicy
from max.tools.providers.native import NativeToolProvider


class TestProviderManagement:
    @pytest.mark.asyncio
    async def test_register_provider_discovers_tools(self, registry):
        provider = NativeToolProvider()

        async def handler(inputs):
            return "ok"

        provider.register_tool(
            ToolDefinition(
                tool_id="test.tool",
                category="test",
                description="A test tool",
                provider_id="native",
            ),
            handler,
        )
        await registry.register_provider(provider)
        assert registry.get("test.tool") is not None

    @pytest.mark.asyncio
    async def test_get_provider(self, registry):
        provider = NativeToolProvider()
        await registry.register_provider(provider)
        assert registry.get_provider("native") is provider

    @pytest.mark.asyncio
    async def test_get_provider_not_found(self, registry):
        assert registry.get_provider("nonexistent") is None


class TestAgentAccess:
    def test_check_agent_access_allowed_tool(self, registry):
        registry.register(
            ToolDefinition(
                tool_id="file.read",
                category="code",
                description="Read",
                provider_id="native",
            )
        )
        policy = AgentToolPolicy(
            agent_name="worker",
            allowed_tools=["file.read"],
        )
        registry.set_agent_policy(policy)
        assert registry.check_agent_access("worker", "file.read") is True

    def test_check_agent_access_denied(self, registry):
        registry.register(
            ToolDefinition(
                tool_id="shell.execute",
                category="code",
                description="Shell",
                provider_id="native",
            )
        )
        policy = AgentToolPolicy(
            agent_name="worker",
            allowed_tools=["file.read"],
        )
        registry.set_agent_policy(policy)
        assert registry.check_agent_access("worker", "shell.execute") is False

    def test_check_agent_access_by_category(self, registry):
        registry.register(
            ToolDefinition(
                tool_id="file.read",
                category="code",
                description="Read",
                provider_id="native",
            )
        )
        policy = AgentToolPolicy(
            agent_name="worker",
            allowed_categories=["code"],
        )
        registry.set_agent_policy(policy)
        assert registry.check_agent_access("worker", "file.read") is True

    def test_denied_overrides_allowed(self, registry):
        registry.register(
            ToolDefinition(
                tool_id="shell.execute",
                category="code",
                description="Shell",
                provider_id="native",
            )
        )
        policy = AgentToolPolicy(
            agent_name="worker",
            allowed_categories=["code"],
            denied_tools=["shell.execute"],
        )
        registry.set_agent_policy(policy)
        assert registry.check_agent_access("worker", "shell.execute") is False

    def test_no_policy_denies_all(self, registry):
        registry.register(
            ToolDefinition(
                tool_id="file.read",
                category="code",
                description="Read",
                provider_id="native",
            )
        )
        assert registry.check_agent_access("unknown_agent", "file.read") is False
```

- [ ] **Step 2: Write the failing tests for executor**

Create `tests/test_tool_executor.py`:

```python
"""Tests for ToolExecutor pipeline."""

import uuid
from unittest.mock import AsyncMock

import pytest

from max.tools.executor import ToolExecutor
from max.tools.models import AgentToolPolicy, ToolResult
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
    for tool in [t for t in [registry.get("file.read"), registry.get("test.slow")] if t]:
        pass
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
        # test.slow has timeout_seconds=1 but sleeps for 999s
        # Override to very short timeout
        executor._default_timeout = 0.01
        tool = registry.get("test.slow")
        tool.timeout_seconds = 0
        result = await executor.execute("worker", "test.slow", {})
        assert result.success is False
        assert "timed out" in result.error.lower()


class TestAuditDisabled:
    @pytest.mark.asyncio
    async def test_no_audit_when_disabled(self):
        executor, registry, store, provider = _make_executor()
        executor._audit_enabled = False
        await executor.execute("worker", "file.read", {"path": "/tmp"})
        store.record.assert_not_called()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_tool_executor.py tests/test_tool_registry.py -v`
Expected: FAIL

- [ ] **Step 4: Update ToolRegistry with provider management and agent access**

Update `src/max/tools/registry.py`:

```python
"""Tool registry for managing Max's tool catalog.

Handles registration, permission checking, category filtering,
provider management, per-agent access policies, and conversion
to Anthropic API format for LLM tool_use calls.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from max.tools.models import AgentToolPolicy

if TYPE_CHECKING:
    from max.tools.providers.base import ToolProvider

logger = logging.getLogger(__name__)


class ToolDefinition(BaseModel):
    """Definition of a tool available to Max agents."""

    tool_id: str
    category: str
    description: str
    permissions: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )
    cost_tier: str = "low"
    reliability: float = 1.0
    avg_latency_ms: int = 0
    provider_id: str = "native"
    timeout_seconds: int | None = None


class ToolRegistry:
    """Registry that manages the tool catalog for Max.

    The Orchestrator uses this to assign tools to sub-agents
    based on task requirements and permissions.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._providers: dict[str, ToolProvider] = {}
        self._policies: dict[str, AgentToolPolicy] = {}

    # ── Tool registration ──────────────────────────────────────────────

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool definition in the registry."""
        self._tools[tool.tool_id] = tool
        logger.debug("Registered tool: %s", tool.tool_id)

    def get(self, tool_id: str) -> ToolDefinition | None:
        """Get a tool by its ID, or None if not found."""
        return self._tools.get(tool_id)

    def list_all(self) -> list[ToolDefinition]:
        """Return all registered tools."""
        return list(self._tools.values())

    def list_by_category(self, category: str) -> list[ToolDefinition]:
        """Return all tools in a given category."""
        return [t for t in self._tools.values() if t.category == category]

    # ── Permission checking ────────────────────────────────────────────

    def check_permission(self, tool_id: str, allowed: list[str]) -> bool:
        """Check if a tool's required permissions are all in the allowed set."""
        tool = self._tools.get(tool_id)
        if tool is None:
            return False
        return all(perm in allowed for perm in tool.permissions)

    # ── Provider management ────────────────────────────────────────────

    async def register_provider(self, provider: ToolProvider) -> None:
        """Register a provider and discover its tools."""
        self._providers[provider.provider_id] = provider
        tools = await provider.list_tools()
        for tool in tools:
            self.register(tool)
        logger.info(
            "Registered provider %s with %d tools",
            provider.provider_id,
            len(tools),
        )

    def get_provider(self, provider_id: str) -> ToolProvider | None:
        """Get a provider by its ID."""
        return self._providers.get(provider_id)

    # ── Agent access policies ──────────────────────────────────────────

    def set_agent_policy(self, policy: AgentToolPolicy) -> None:
        """Set the tool access policy for an agent."""
        self._policies[policy.agent_name] = policy

    def check_agent_access(self, agent_name: str, tool_id: str) -> bool:
        """Check if an agent is allowed to use a tool."""
        policy = self._policies.get(agent_name)
        if policy is None:
            return False

        # Denied tools always override
        if tool_id in policy.denied_tools:
            return False

        # Check explicit tool allowlist
        if tool_id in policy.allowed_tools:
            return True

        # Check category allowlist
        tool = self._tools.get(tool_id)
        if tool and tool.category in policy.allowed_categories:
            return True

        return False

    def get_agent_tools(self, agent_name: str) -> list[ToolDefinition]:
        """Get all tools an agent is allowed to use."""
        return [t for t in self._tools.values() if self.check_agent_access(agent_name, t.tool_id)]

    # ── Anthropic API format ───────────────────────────────────────────

    def to_anthropic_tools(self, tool_ids: list[str]) -> list[dict[str, Any]]:
        """Convert selected tools to Anthropic API tool_use format."""
        result = []
        for tool_id in tool_ids:
            tool = self._tools.get(tool_id)
            if tool is None:
                continue
            result.append(
                {
                    "name": tool.tool_id,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
            )
        return result
```

- [ ] **Step 5: Create ToolExecutor**

Create `src/max/tools/executor.py`:

```python
"""ToolExecutor — central pipeline for all tool invocations."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from max.tools.models import ToolResult
from max.tools.registry import ToolRegistry
from max.tools.store import ToolInvocationStore

logger = logging.getLogger(__name__)


class ToolExecutor:
    """Executes tools through the permission → execute → audit pipeline."""

    def __init__(
        self,
        registry: ToolRegistry,
        store: ToolInvocationStore | None = None,
        default_timeout: int = 60,
        audit_enabled: bool = True,
    ) -> None:
        self._registry = registry
        self._store = store
        self._default_timeout = default_timeout
        self._audit_enabled = audit_enabled

    async def execute(
        self,
        agent_name: str,
        tool_id: str,
        inputs: dict[str, Any],
    ) -> ToolResult:
        """Execute a tool through the full pipeline."""
        start = time.monotonic()

        # 1. Resolve tool
        tool_def = self._registry.get(tool_id)
        if tool_def is None:
            result = ToolResult(
                tool_id=tool_id,
                success=False,
                error=f"Tool not found: {tool_id}",
            )
            await self._audit(agent_name, result, inputs)
            return result

        # 2. Permission check
        if not self._registry.check_agent_access(agent_name, tool_id):
            result = ToolResult(
                tool_id=tool_id,
                success=False,
                error=f"Permission denied: {agent_name} cannot use {tool_id}",
            )
            await self._audit(agent_name, result, inputs)
            return result

        # 3. Get provider
        provider = self._registry.get_provider(tool_def.provider_id)
        if provider is None:
            result = ToolResult(
                tool_id=tool_id,
                success=False,
                error=f"Provider not found: {tool_def.provider_id}",
            )
            await self._audit(agent_name, result, inputs)
            return result

        # 4. Execute with timeout
        timeout = tool_def.timeout_seconds or self._default_timeout
        try:
            result = await asyncio.wait_for(
                provider.execute(tool_id, inputs),
                timeout=timeout,
            )
        except TimeoutError:
            duration_ms = int((time.monotonic() - start) * 1000)
            result = ToolResult(
                tool_id=tool_id,
                success=False,
                error=f"Tool execution timed out after {timeout}s",
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.exception("Tool %s execution failed", tool_id)
            result = ToolResult(
                tool_id=tool_id,
                success=False,
                error=str(exc),
                duration_ms=duration_ms,
            )

        # 5. Audit log
        await self._audit(agent_name, result, inputs)
        return result

    async def _audit(
        self,
        agent_name: str,
        result: ToolResult,
        inputs: dict[str, Any],
    ) -> None:
        """Record invocation to audit store if enabled."""
        if not self._audit_enabled or self._store is None:
            return
        try:
            await self._store.record(
                agent_id=agent_name,
                tool_id=result.tool_id,
                inputs=inputs,
                output=result.output,
                success=result.success,
                error=result.error,
                duration_ms=result.duration_ms,
            )
        except Exception:
            logger.warning("Failed to record tool audit for %s", result.tool_id)
```

- [ ] **Step 6: Run all tests**

Run: `pytest tests/test_tool_executor.py tests/test_tool_registry.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/max/tools/registry.py src/max/tools/executor.py tests/test_tool_executor.py tests/test_tool_registry.py
git commit -m "feat(tools): add ToolExecutor pipeline and enhanced ToolRegistry"
```

---

### Task 6: Agent Tool Loop (think_with_tools)

**Files:**
- Modify: `src/max/agents/base.py`
- Create: `tests/test_agent_tool_loop.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_tool_loop.py`:

```python
"""Tests for BaseAgent.think_with_tools() — agent tool loop."""

import json
from unittest.mock import AsyncMock

import pytest

from max.agents.base import AgentConfig, BaseAgent
from max.llm.models import LLMResponse, ModelType, ToolCall
from max.tools.executor import ToolExecutor
from max.tools.models import AgentToolPolicy, ToolResult
from max.tools.providers.native import NativeToolProvider
from max.tools.registry import ToolDefinition, ToolRegistry


class ConcreteAgent(BaseAgent):
    async def run(self, input_data):
        return {}


def _make_agent_with_tools():
    llm = AsyncMock()
    config = AgentConfig(name="test_agent", system_prompt="You are a test agent")
    agent = ConcreteAgent(config=config, llm=llm)

    registry = ToolRegistry()
    provider = NativeToolProvider()

    async def read_file(inputs):
        return {"content": f"File contents of {inputs['path']}"}

    tool_def = ToolDefinition(
        tool_id="file.read",
        category="code",
        description="Read a file",
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    )
    provider.register_tool(tool_def, read_file)
    registry.register(tool_def)
    registry._providers["native"] = provider

    policy = AgentToolPolicy(agent_name="test_agent", allowed_categories=["code"])
    registry.set_agent_policy(policy)

    store = AsyncMock()
    store.record = AsyncMock()
    executor = ToolExecutor(registry=registry, store=store, audit_enabled=False)

    tools_anthropic = registry.to_anthropic_tools(["file.read"])
    return agent, llm, executor, tools_anthropic


class TestThinkWithToolsNoToolUse:
    @pytest.mark.asyncio
    async def test_returns_response_when_no_tool_calls(self):
        agent, llm, executor, tools = _make_agent_with_tools()
        llm.complete = AsyncMock(
            return_value=LLMResponse(
                text="The answer is 42",
                input_tokens=10,
                output_tokens=5,
                model="claude-opus-4-6",
                stop_reason="end_turn",
                tool_calls=None,
            )
        )
        response = await agent.think_with_tools(
            messages=[{"role": "user", "content": "What is the answer?"}],
            tools=tools,
            tool_executor=executor,
        )
        assert response.text == "The answer is 42"
        assert llm.complete.call_count == 1


class TestThinkWithToolsSingleToolCall:
    @pytest.mark.asyncio
    async def test_executes_tool_and_continues(self):
        agent, llm, executor, tools = _make_agent_with_tools()

        # First call: LLM requests tool use
        tool_response = LLMResponse(
            text="",
            input_tokens=10,
            output_tokens=5,
            model="claude-opus-4-6",
            stop_reason="tool_use",
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="file.read",
                    input={"path": "/tmp/test.txt"},
                )
            ],
        )
        # Second call: LLM gives final answer
        final_response = LLMResponse(
            text="The file contains: File contents of /tmp/test.txt",
            input_tokens=20,
            output_tokens=10,
            model="claude-opus-4-6",
            stop_reason="end_turn",
            tool_calls=None,
        )
        llm.complete = AsyncMock(side_effect=[tool_response, final_response])

        response = await agent.think_with_tools(
            messages=[{"role": "user", "content": "Read /tmp/test.txt"}],
            tools=tools,
            tool_executor=executor,
        )
        assert "File contents of /tmp/test.txt" in response.text
        assert llm.complete.call_count == 2


class TestThinkWithToolsMaxTurns:
    @pytest.mark.asyncio
    async def test_stops_at_max_turns(self):
        agent, llm, executor, tools = _make_agent_with_tools()
        agent.config.max_turns = 2

        # LLM always requests tool use (infinite loop)
        tool_response = LLMResponse(
            text="",
            input_tokens=10,
            output_tokens=5,
            model="claude-opus-4-6",
            stop_reason="tool_use",
            tool_calls=[
                ToolCall(id="call_1", name="file.read", input={"path": "/tmp/test"})
            ],
        )
        llm.complete = AsyncMock(return_value=tool_response)

        with pytest.raises(RuntimeError, match="exceeded max_turns"):
            await agent.think_with_tools(
                messages=[{"role": "user", "content": "Read it"}],
                tools=tools,
                tool_executor=executor,
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_tool_loop.py -v`
Expected: FAIL with `AttributeError: 'ConcreteAgent' object has no attribute 'think_with_tools'`

- [ ] **Step 3: Add think_with_tools() to BaseAgent**

Add the following method to `BaseAgent` in `src/max/agents/base.py`, after the `think()` method:

```python
    async def think_with_tools(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        model: ModelType | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_executor: Any = None,
    ) -> LLMResponse:
        """Think with tool-use loop: call LLM, execute tools, feed results back.

        Loops until the LLM responds without tool calls or max_turns is hit.
        """
        import json as _json

        conversation = list(messages)

        while True:
            response = await self.think(
                messages=conversation,
                system_prompt=system_prompt,
                model=model,
                tools=tools,
            )

            if not response.tool_calls or tool_executor is None:
                return response

            # Build assistant message with tool_use blocks
            assistant_content: list[dict[str, Any]] = []
            if response.text:
                assistant_content.append({"type": "text", "text": response.text})
            for tc in response.tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.input,
                })
            conversation.append({"role": "assistant", "content": assistant_content})

            # Execute each tool and build tool_result messages
            tool_results_content: list[dict[str, Any]] = []
            for tc in response.tool_calls:
                result = await tool_executor.execute(
                    self.config.name,
                    tc.name,
                    tc.input,
                )
                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": _json.dumps(result.output) if result.success else result.error,
                    "is_error": not result.success,
                })
            conversation.append({"role": "user", "content": tool_results_content})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_tool_loop.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run existing BaseAgent tests to verify no regressions**

Run: `pytest tests/ -v --ignore=tests/test_postgres.py -q`
Expected: ALL PASS (existing tests unaffected since think_with_tools is additive)

- [ ] **Step 6: Commit**

```bash
git add src/max/agents/base.py tests/test_agent_tool_loop.py
git commit -m "feat(agents): add think_with_tools() agent tool loop to BaseAgent"
```

---

### Task 7: File System Tools (6 tools)

**Files:**
- Create: `src/max/tools/native/__init__.py`
- Create: `src/max/tools/native/file_tools.py`
- Create: `tests/test_native_file_tools.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_native_file_tools.py`:

```python
"""Tests for native file system tools."""

import os
import tempfile

import pytest

from max.tools.native.file_tools import (
    handle_directory_list,
    handle_file_delete,
    handle_file_edit,
    handle_file_glob,
    handle_file_read,
    handle_file_write,
)


class TestFileRead:
    @pytest.mark.asyncio
    async def test_reads_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        result = await handle_file_read({"path": str(f)})
        assert result["content"] == "hello world"

    @pytest.mark.asyncio
    async def test_reads_with_offset_limit(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3\nline4\n")
        result = await handle_file_read({"path": str(f), "offset": 1, "limit": 2})
        assert "line2" in result["content"]
        assert "line3" in result["content"]
        assert "line4" not in result["content"]

    @pytest.mark.asyncio
    async def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            await handle_file_read({"path": str(tmp_path / "nonexistent.txt")})


class TestFileWrite:
    @pytest.mark.asyncio
    async def test_writes_file(self, tmp_path):
        f = tmp_path / "output.txt"
        result = await handle_file_write({"path": str(f), "content": "hello"})
        assert result["bytes_written"] == 5
        assert f.read_text() == "hello"

    @pytest.mark.asyncio
    async def test_creates_parent_dirs(self, tmp_path):
        f = tmp_path / "sub" / "dir" / "output.txt"
        await handle_file_write({"path": str(f), "content": "hello"})
        assert f.read_text() == "hello"


class TestFileEdit:
    @pytest.mark.asyncio
    async def test_search_and_replace(self, tmp_path):
        f = tmp_path / "edit.txt"
        f.write_text("hello world\nfoo bar\n")
        result = await handle_file_edit({
            "path": str(f),
            "old_string": "foo bar",
            "new_string": "baz qux",
        })
        assert result["replacements"] == 1
        assert "baz qux" in f.read_text()

    @pytest.mark.asyncio
    async def test_no_match(self, tmp_path):
        f = tmp_path / "edit.txt"
        f.write_text("hello world\n")
        result = await handle_file_edit({
            "path": str(f),
            "old_string": "nonexistent",
            "new_string": "replaced",
        })
        assert result["replacements"] == 0


class TestDirectoryList:
    @pytest.mark.asyncio
    async def test_lists_directory(self, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        (tmp_path / "subdir").mkdir()
        result = await handle_directory_list({"path": str(tmp_path)})
        names = [e["name"] for e in result["entries"]]
        assert "a.txt" in names
        assert "subdir" in names


class TestFileGlob:
    @pytest.mark.asyncio
    async def test_glob_pattern(self, tmp_path):
        (tmp_path / "a.py").write_text("a")
        (tmp_path / "b.py").write_text("b")
        (tmp_path / "c.txt").write_text("c")
        result = await handle_file_glob({"path": str(tmp_path), "pattern": "*.py"})
        assert len(result["matches"]) == 2


class TestFileDelete:
    @pytest.mark.asyncio
    async def test_deletes_file(self, tmp_path):
        f = tmp_path / "delete_me.txt"
        f.write_text("bye")
        result = await handle_file_delete({"path": str(f)})
        assert result["deleted"] is True
        assert not f.exists()

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            await handle_file_delete({"path": str(tmp_path / "nope.txt")})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_native_file_tools.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create file tools**

Create `src/max/tools/native/__init__.py`:

```python
"""Native tool implementations for Max."""
```

Create `src/max/tools/native/file_tools.py`:

```python
"""File system tools — read, write, edit, list, glob, delete."""

from __future__ import annotations

import glob as glob_mod
import os
from pathlib import Path
from typing import Any

from max.tools.registry import ToolDefinition

TOOL_DEFINITIONS = [
    ToolDefinition(
        tool_id="file.read",
        category="code",
        description="Read a file's contents. Supports optional line offset and limit.",
        permissions=["fs.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute file path"},
                "offset": {"type": "integer", "description": "Line offset (0-based)", "default": 0},
                "limit": {"type": "integer", "description": "Max lines to read", "default": 0},
            },
            "required": ["path"],
        },
    ),
    ToolDefinition(
        tool_id="file.write",
        category="code",
        description="Write content to a file. Creates parent directories if needed.",
        permissions=["fs.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute file path"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        },
    ),
    ToolDefinition(
        tool_id="file.edit",
        category="code",
        description="Search and replace text in a file.",
        permissions=["fs.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute file path"},
                "old_string": {"type": "string", "description": "Text to find"},
                "new_string": {"type": "string", "description": "Replacement text"},
            },
            "required": ["path", "old_string", "new_string"],
        },
    ),
    ToolDefinition(
        tool_id="directory.list",
        category="code",
        description="List directory contents with file metadata.",
        permissions=["fs.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute directory path"},
            },
            "required": ["path"],
        },
    ),
    ToolDefinition(
        tool_id="file.glob",
        category="code",
        description="Search for files matching a glob pattern.",
        permissions=["fs.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Base directory"},
                "pattern": {"type": "string", "description": "Glob pattern (e.g. '*.py')"},
            },
            "required": ["path", "pattern"],
        },
    ),
    ToolDefinition(
        tool_id="file.delete",
        category="code",
        description="Delete a file.",
        permissions=["fs.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute file path"},
            },
            "required": ["path"],
        },
    ),
]


async def handle_file_read(inputs: dict[str, Any]) -> dict[str, Any]:
    """Read a file, optionally with line offset and limit."""
    path = Path(inputs["path"])
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    text = path.read_text()
    offset = inputs.get("offset", 0)
    limit = inputs.get("limit", 0)

    if offset or limit:
        lines = text.splitlines(keepends=True)
        if limit:
            lines = lines[offset : offset + limit]
        else:
            lines = lines[offset:]
        text = "".join(lines)

    return {"content": text, "size": path.stat().st_size}


async def handle_file_write(inputs: dict[str, Any]) -> dict[str, Any]:
    """Write content to a file, creating parent dirs if needed."""
    path = Path(inputs["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    content = inputs["content"]
    path.write_text(content)
    return {"bytes_written": len(content.encode())}


async def handle_file_edit(inputs: dict[str, Any]) -> dict[str, Any]:
    """Search and replace text in a file."""
    path = Path(inputs["path"])
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    text = path.read_text()
    old_string = inputs["old_string"]
    new_string = inputs["new_string"]
    count = text.count(old_string)
    if count > 0:
        text = text.replace(old_string, new_string)
        path.write_text(text)
    return {"replacements": count}


async def handle_directory_list(inputs: dict[str, Any]) -> dict[str, Any]:
    """List directory contents with metadata."""
    path = Path(inputs["path"])
    if not path.is_dir():
        raise NotADirectoryError(f"Not a directory: {path}")

    entries = []
    for entry in sorted(path.iterdir()):
        stat = entry.stat()
        entries.append({
            "name": entry.name,
            "type": "directory" if entry.is_dir() else "file",
            "size": stat.st_size if entry.is_file() else 0,
        })
    return {"entries": entries}


async def handle_file_glob(inputs: dict[str, Any]) -> dict[str, Any]:
    """Search for files matching a glob pattern."""
    base = Path(inputs["path"])
    pattern = inputs["pattern"]
    matches = sorted(str(p) for p in base.glob(pattern))
    return {"matches": matches}


async def handle_file_delete(inputs: dict[str, Any]) -> dict[str, Any]:
    """Delete a file."""
    path = Path(inputs["path"])
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    path.unlink()
    return {"deleted": True}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_native_file_tools.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/max/tools/native/ tests/test_native_file_tools.py
git commit -m "feat(tools): add 6 native file system tools"
```

---

### Task 8: Shell + Process + Search Tools

**Files:**
- Create: `src/max/tools/native/shell_tools.py`
- Create: `src/max/tools/native/process_tools.py`
- Create: `src/max/tools/native/search_tools.py`
- Create: `tests/test_native_shell_tools.py`
- Create: `tests/test_native_process_tools.py`
- Create: `tests/test_native_search_tools.py`

- [ ] **Step 1: Write shell tool tests**

Create `tests/test_native_shell_tools.py`:

```python
"""Tests for shell.execute tool."""

import pytest

from max.tools.native.shell_tools import handle_shell_execute


class TestShellExecute:
    @pytest.mark.asyncio
    async def test_runs_command(self):
        result = await handle_shell_execute({"command": "echo hello"})
        assert result["exit_code"] == 0
        assert "hello" in result["stdout"]

    @pytest.mark.asyncio
    async def test_captures_stderr(self):
        result = await handle_shell_execute({"command": "echo error >&2"})
        assert "error" in result["stderr"]

    @pytest.mark.asyncio
    async def test_nonzero_exit_code(self):
        result = await handle_shell_execute({"command": "exit 1"})
        assert result["exit_code"] == 1

    @pytest.mark.asyncio
    async def test_timeout(self):
        result = await handle_shell_execute({"command": "sleep 60", "timeout": 1})
        assert result["exit_code"] == -1
        assert "timed out" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_working_directory(self, tmp_path):
        result = await handle_shell_execute({"command": "pwd", "cwd": str(tmp_path)})
        assert str(tmp_path) in result["stdout"]
```

- [ ] **Step 2: Write process tool tests**

Create `tests/test_native_process_tools.py`:

```python
"""Tests for process.list tool."""

import pytest

from max.tools.native.process_tools import handle_process_list


class TestProcessList:
    @pytest.mark.asyncio
    async def test_lists_processes(self):
        result = await handle_process_list({})
        assert len(result["processes"]) > 0
        proc = result["processes"][0]
        assert "pid" in proc
        assert "name" in proc
```

- [ ] **Step 3: Write search tool tests**

Create `tests/test_native_search_tools.py`:

```python
"""Tests for grep.search tool."""

import pytest

from max.tools.native.search_tools import handle_grep_search


class TestGrepSearch:
    @pytest.mark.asyncio
    async def test_finds_pattern(self, tmp_path):
        (tmp_path / "a.py").write_text("def hello():\n    pass\n")
        (tmp_path / "b.py").write_text("def world():\n    pass\n")
        result = await handle_grep_search({
            "path": str(tmp_path),
            "pattern": "hello",
        })
        assert len(result["matches"]) == 1
        assert "hello" in result["matches"][0]["line"]

    @pytest.mark.asyncio
    async def test_glob_filter(self, tmp_path):
        (tmp_path / "a.py").write_text("target\n")
        (tmp_path / "b.txt").write_text("target\n")
        result = await handle_grep_search({
            "path": str(tmp_path),
            "pattern": "target",
            "glob": "*.py",
        })
        assert len(result["matches"]) == 1

    @pytest.mark.asyncio
    async def test_no_matches(self, tmp_path):
        (tmp_path / "a.txt").write_text("nothing here\n")
        result = await handle_grep_search({
            "path": str(tmp_path),
            "pattern": "nonexistent",
        })
        assert len(result["matches"]) == 0
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/test_native_shell_tools.py tests/test_native_process_tools.py tests/test_native_search_tools.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 5: Create shell tools**

Create `src/max/tools/native/shell_tools.py`:

```python
"""Shell execution tool — sandboxed command execution."""

from __future__ import annotations

import asyncio
from typing import Any

from max.tools.registry import ToolDefinition

TOOL_DEFINITIONS = [
    ToolDefinition(
        tool_id="shell.execute",
        category="code",
        description="Execute a shell command. Returns stdout, stderr, and exit code.",
        permissions=["system.shell"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "cwd": {"type": "string", "description": "Working directory"},
                "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30},
            },
            "required": ["command"],
        },
    ),
]


async def handle_shell_execute(inputs: dict[str, Any]) -> dict[str, Any]:
    """Execute a shell command with timeout."""
    command = inputs["command"]
    cwd = inputs.get("cwd")
    timeout = inputs.get("timeout", 30)

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
            "exit_code": proc.returncode or 0,
            "error": None,
        }
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return {
            "stdout": "",
            "stderr": "",
            "exit_code": -1,
            "error": f"Command timed out after {timeout}s",
        }
```

- [ ] **Step 6: Create process tools**

Create `src/max/tools/native/process_tools.py`:

```python
"""Process listing tool."""

from __future__ import annotations

from typing import Any

import psutil

from max.tools.registry import ToolDefinition

TOOL_DEFINITIONS = [
    ToolDefinition(
        tool_id="process.list",
        category="code",
        description="List running processes with PID, name, CPU, and memory info.",
        permissions=["system.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max processes to return", "default": 50},
            },
        },
    ),
]


async def handle_process_list(inputs: dict[str, Any]) -> dict[str, Any]:
    """List running processes."""
    limit = inputs.get("limit", 50)
    processes = []
    for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            info = proc.info
            processes.append({
                "pid": info["pid"],
                "name": info["name"],
                "cpu_percent": info.get("cpu_percent", 0.0),
                "memory_percent": round(info.get("memory_percent", 0.0), 2),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if len(processes) >= limit:
            break
    return {"processes": processes}
```

- [ ] **Step 7: Create search tools**

Create `src/max/tools/native/search_tools.py`:

```python
"""Grep/search tool — regex search across files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from max.tools.registry import ToolDefinition

TOOL_DEFINITIONS = [
    ToolDefinition(
        tool_id="grep.search",
        category="code",
        description="Search for a regex pattern across files in a directory.",
        permissions=["fs.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory to search in"},
                "pattern": {"type": "string", "description": "Regex pattern to search for"},
                "glob": {"type": "string", "description": "File glob filter (e.g. '*.py')", "default": "*"},
                "max_results": {"type": "integer", "description": "Max matches to return", "default": 100},
            },
            "required": ["path", "pattern"],
        },
    ),
]


async def handle_grep_search(inputs: dict[str, Any]) -> dict[str, Any]:
    """Search for a regex pattern across files."""
    base = Path(inputs["path"])
    pattern = re.compile(inputs["pattern"])
    file_glob = inputs.get("glob", "*")
    max_results = inputs.get("max_results", 100)

    matches = []
    for filepath in sorted(base.rglob(file_glob)):
        if not filepath.is_file():
            continue
        try:
            text = filepath.read_text(errors="replace")
        except (PermissionError, OSError):
            continue
        for line_num, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                matches.append({
                    "file": str(filepath),
                    "line_number": line_num,
                    "line": line.rstrip(),
                })
                if len(matches) >= max_results:
                    return {"matches": matches}
    return {"matches": matches}
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_native_shell_tools.py tests/test_native_process_tools.py tests/test_native_search_tools.py -v`
Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
git add src/max/tools/native/shell_tools.py src/max/tools/native/process_tools.py src/max/tools/native/search_tools.py tests/test_native_shell_tools.py tests/test_native_process_tools.py tests/test_native_search_tools.py
git commit -m "feat(tools): add shell, process, and search native tools"
```

---

### Task 9: Git + Web Tools

**Files:**
- Create: `src/max/tools/native/git_tools.py`
- Create: `src/max/tools/native/web_tools.py`
- Create: `tests/test_native_git_tools.py`
- Create: `tests/test_native_web_tools.py`

- [ ] **Step 1: Write git tool tests**

Create `tests/test_native_git_tools.py`:

```python
"""Tests for git tools."""

import pytest

from max.tools.native.git_tools import (
    handle_git_commit,
    handle_git_diff,
    handle_git_log,
    handle_git_status,
)


class TestGitStatus:
    @pytest.mark.asyncio
    async def test_returns_status(self, tmp_path):
        # Init a git repo
        import subprocess
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path), capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path), capture_output=True,
        )
        (tmp_path / "test.txt").write_text("hello")
        result = await handle_git_status({"cwd": str(tmp_path)})
        assert "test.txt" in result["stdout"]


class TestGitDiff:
    @pytest.mark.asyncio
    async def test_returns_diff(self, tmp_path):
        import subprocess
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path), capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path), capture_output=True,
        )
        (tmp_path / "test.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=str(tmp_path), capture_output=True,
        )
        (tmp_path / "test.txt").write_text("hello world")
        result = await handle_git_diff({"cwd": str(tmp_path)})
        assert "hello world" in result["stdout"]


class TestGitLog:
    @pytest.mark.asyncio
    async def test_returns_log(self, tmp_path):
        import subprocess
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path), capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path), capture_output=True,
        )
        (tmp_path / "test.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial commit"],
            cwd=str(tmp_path), capture_output=True,
        )
        result = await handle_git_log({"cwd": str(tmp_path), "count": 5})
        assert "initial commit" in result["stdout"]


class TestGitCommit:
    @pytest.mark.asyncio
    async def test_commits_changes(self, tmp_path):
        import subprocess
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path), capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path), capture_output=True,
        )
        (tmp_path / "test.txt").write_text("hello")
        result = await handle_git_commit({
            "cwd": str(tmp_path),
            "message": "test commit",
            "files": ["test.txt"],
        })
        assert result["exit_code"] == 0
```

- [ ] **Step 2: Write web tool tests**

Create `tests/test_native_web_tools.py`:

```python
"""Tests for HTTP tools."""

from unittest.mock import AsyncMock, patch

import pytest

from max.tools.native.web_tools import handle_http_fetch, handle_http_request


class TestHttpFetch:
    @pytest.mark.asyncio
    async def test_fetch_success(self):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.text = "Hello World"
        mock_response.headers = {"content-type": "text/plain"}

        with patch("max.tools.native.web_tools.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await handle_http_fetch({"url": "https://example.com"})
            assert result["status_code"] == 200
            assert result["body"] == "Hello World"


class TestHttpRequest:
    @pytest.mark.asyncio
    async def test_put_request(self):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.text = '{"ok": true}'
        mock_response.headers = {"content-type": "application/json"}

        with patch("max.tools.native.web_tools.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await handle_http_request({
                "url": "https://api.example.com/data",
                "method": "PUT",
                "body": '{"key": "value"}',
                "headers": {"Content-Type": "application/json"},
            })
            assert result["status_code"] == 200
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_native_git_tools.py tests/test_native_web_tools.py -v`
Expected: FAIL

- [ ] **Step 4: Create git tools**

Create `src/max/tools/native/git_tools.py`:

```python
"""Git tools — status, diff, commit, log."""

from __future__ import annotations

import asyncio
from typing import Any

from max.tools.registry import ToolDefinition

TOOL_DEFINITIONS = [
    ToolDefinition(
        tool_id="git.status",
        category="code",
        description="Show git working tree status.",
        permissions=["fs.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Repository directory"},
            },
            "required": ["cwd"],
        },
    ),
    ToolDefinition(
        tool_id="git.diff",
        category="code",
        description="Show git diff of staged and unstaged changes.",
        permissions=["fs.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Repository directory"},
                "staged": {"type": "boolean", "description": "Show staged changes only", "default": False},
            },
            "required": ["cwd"],
        },
    ),
    ToolDefinition(
        tool_id="git.log",
        category="code",
        description="Show recent git commit history.",
        permissions=["fs.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Repository directory"},
                "count": {"type": "integer", "description": "Number of commits", "default": 10},
            },
            "required": ["cwd"],
        },
    ),
    ToolDefinition(
        tool_id="git.commit",
        category="code",
        description="Stage files and create a git commit.",
        permissions=["fs.write", "git.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Repository directory"},
                "message": {"type": "string", "description": "Commit message"},
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Files to stage (relative paths)",
                },
            },
            "required": ["cwd", "message", "files"],
        },
    ),
]


async def _run_git(args: list[str], cwd: str) -> dict[str, Any]:
    """Run a git command and return stdout, stderr, exit_code."""
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout, stderr = await proc.communicate()
    return {
        "stdout": stdout.decode(errors="replace"),
        "stderr": stderr.decode(errors="replace"),
        "exit_code": proc.returncode or 0,
    }


async def handle_git_status(inputs: dict[str, Any]) -> dict[str, Any]:
    """Show git status."""
    return await _run_git(["status", "--short"], inputs["cwd"])


async def handle_git_diff(inputs: dict[str, Any]) -> dict[str, Any]:
    """Show git diff."""
    args = ["diff"]
    if inputs.get("staged"):
        args.append("--staged")
    return await _run_git(args, inputs["cwd"])


async def handle_git_log(inputs: dict[str, Any]) -> dict[str, Any]:
    """Show git log."""
    count = inputs.get("count", 10)
    return await _run_git(["log", f"--max-count={count}", "--oneline"], inputs["cwd"])


async def handle_git_commit(inputs: dict[str, Any]) -> dict[str, Any]:
    """Stage files and commit."""
    cwd = inputs["cwd"]
    files = inputs["files"]
    message = inputs["message"]

    # Stage files
    add_result = await _run_git(["add"] + files, cwd)
    if add_result["exit_code"] != 0:
        return add_result

    # Commit
    return await _run_git(["commit", "-m", message], cwd)
```

- [ ] **Step 5: Create web tools**

Create `src/max/tools/native/web_tools.py`:

```python
"""HTTP tools — fetch and full request support."""

from __future__ import annotations

from typing import Any

import httpx

from max.tools.registry import ToolDefinition

TOOL_DEFINITIONS = [
    ToolDefinition(
        tool_id="http.fetch",
        category="web",
        description="HTTP GET/POST request. Returns status, headers, and body.",
        permissions=["network.http"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
                "method": {"type": "string", "description": "HTTP method (GET or POST)", "default": "GET"},
                "headers": {"type": "object", "description": "Request headers"},
                "body": {"type": "string", "description": "Request body (for POST)"},
                "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30},
            },
            "required": ["url"],
        },
    ),
    ToolDefinition(
        tool_id="http.request",
        category="web",
        description="Full HTTP request with any method (GET/POST/PUT/DELETE/PATCH/HEAD).",
        permissions=["network.http"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL"},
                "method": {"type": "string", "description": "HTTP method"},
                "headers": {"type": "object", "description": "Request headers"},
                "body": {"type": "string", "description": "Request body"},
                "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30},
            },
            "required": ["url", "method"],
        },
    ),
]


async def _do_request(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """Perform an HTTP request."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        response = await client.request(
            method=method,
            url=url,
            headers=headers,
            content=body,
        )
        return {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": response.text[:50000],  # Cap at 50KB
        }


async def handle_http_fetch(inputs: dict[str, Any]) -> dict[str, Any]:
    """HTTP GET/POST request."""
    return await _do_request(
        url=inputs["url"],
        method=inputs.get("method", "GET"),
        headers=inputs.get("headers"),
        body=inputs.get("body"),
        timeout=inputs.get("timeout", 30),
    )


async def handle_http_request(inputs: dict[str, Any]) -> dict[str, Any]:
    """Full HTTP request with any method."""
    return await _do_request(
        url=inputs["url"],
        method=inputs["method"],
        headers=inputs.get("headers"),
        body=inputs.get("body"),
        timeout=inputs.get("timeout", 30),
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_native_git_tools.py tests/test_native_web_tools.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/max/tools/native/git_tools.py src/max/tools/native/web_tools.py tests/test_native_git_tools.py tests/test_native_web_tools.py
git commit -m "feat(tools): add git and HTTP native tools"
```

---

### Task 10: MCPToolProvider

**Files:**
- Create: `src/max/tools/providers/mcp.py`
- Create: `tests/test_tool_provider_mcp.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tool_provider_mcp.py`:

```python
"""Tests for MCPToolProvider."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from max.tools.providers.mcp import MCPToolProvider


class TestMCPToolProvider:
    @pytest.mark.asyncio
    async def test_provider_id(self):
        provider = MCPToolProvider(server_command=["echo", "test"], server_id="test-mcp")
        assert provider.provider_id == "test-mcp"

    @pytest.mark.asyncio
    async def test_list_tools_maps_to_tool_definitions(self):
        provider = MCPToolProvider(server_command=["echo"], server_id="test-mcp")

        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = "A test tool"
        mock_tool.inputSchema = {"type": "object", "properties": {"arg": {"type": "string"}}}

        provider._session = AsyncMock()
        provider._session.list_tools = AsyncMock(
            return_value=MagicMock(tools=[mock_tool])
        )
        provider._connected = True

        tools = await provider.list_tools()
        assert len(tools) == 1
        assert tools[0].tool_id == "test_tool"
        assert tools[0].provider_id == "test-mcp"

    @pytest.mark.asyncio
    async def test_execute_success(self):
        provider = MCPToolProvider(server_command=["echo"], server_id="test-mcp")

        mock_result = MagicMock()
        mock_result.isError = False
        mock_content = MagicMock()
        mock_content.text = '{"result": "ok"}'
        mock_result.content = [mock_content]

        provider._session = AsyncMock()
        provider._session.call_tool = AsyncMock(return_value=mock_result)
        provider._connected = True

        result = await provider.execute("test_tool", {"arg": "value"})
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_error(self):
        provider = MCPToolProvider(server_command=["echo"], server_id="test-mcp")

        mock_result = MagicMock()
        mock_result.isError = True
        mock_content = MagicMock()
        mock_content.text = "Something went wrong"
        mock_result.content = [mock_content]

        provider._session = AsyncMock()
        provider._session.call_tool = AsyncMock(return_value=mock_result)
        provider._connected = True

        result = await provider.execute("test_tool", {"arg": "value"})
        assert result.success is False
        assert "Something went wrong" in result.error

    @pytest.mark.asyncio
    async def test_health_check_when_not_connected(self):
        provider = MCPToolProvider(server_command=["echo"], server_id="test-mcp")
        assert await provider.health_check() is False

    @pytest.mark.asyncio
    async def test_health_check_when_connected(self):
        provider = MCPToolProvider(server_command=["echo"], server_id="test-mcp")
        provider._connected = True
        provider._session = AsyncMock()
        provider._session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))
        assert await provider.health_check() is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tool_provider_mcp.py -v`
Expected: FAIL

- [ ] **Step 3: Create MCPToolProvider**

Create `src/max/tools/providers/mcp.py`:

```python
"""MCPToolProvider — proxies tool calls to MCP servers."""

from __future__ import annotations

import logging
import time
from typing import Any

from max.tools.models import ToolResult
from max.tools.providers.base import ToolProvider
from max.tools.registry import ToolDefinition

logger = logging.getLogger(__name__)


class MCPToolProvider(ToolProvider):
    """Connects to an MCP server and proxies tool calls.

    Uses stdio transport to communicate with an MCP server subprocess.
    """

    def __init__(
        self,
        server_command: list[str],
        server_id: str,
        env: dict[str, str] | None = None,
    ) -> None:
        self._server_command = server_command
        self._server_id = server_id
        self._env = env
        self._session: Any = None
        self._connected = False

    @property
    def provider_id(self) -> str:
        return self._server_id

    async def connect(self) -> None:
        """Connect to the MCP server via stdio transport."""
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            params = StdioServerParameters(
                command=self._server_command[0],
                args=self._server_command[1:] if len(self._server_command) > 1 else [],
                env=self._env,
            )
            self._transport_ctx = stdio_client(params)
            transport = await self._transport_ctx.__aenter__()
            self._session = ClientSession(*transport)
            await self._session.__aenter__()
            await self._session.initialize()
            self._connected = True
            logger.info("Connected to MCP server: %s", self._server_id)
        except ImportError:
            logger.warning("mcp package not installed — MCPToolProvider unavailable")
            self._connected = False
        except Exception:
            logger.exception("Failed to connect to MCP server: %s", self._server_id)
            self._connected = False

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
                await self._transport_ctx.__aexit__(None, None, None)
            except Exception:
                logger.warning("Error disconnecting from MCP server: %s", self._server_id)
            self._session = None
            self._connected = False

    async def list_tools(self) -> list[ToolDefinition]:
        """List tools available from the MCP server."""
        if not self._connected or not self._session:
            return []

        result = await self._session.list_tools()
        definitions = []
        for tool in result.tools:
            definitions.append(
                ToolDefinition(
                    tool_id=tool.name,
                    category="mcp",
                    description=tool.description or "",
                    provider_id=self._server_id,
                    input_schema=tool.inputSchema if hasattr(tool, "inputSchema") else {},
                )
            )
        return definitions

    async def execute(self, tool_id: str, inputs: dict[str, Any]) -> ToolResult:
        """Execute a tool on the MCP server."""
        if not self._connected or not self._session:
            return ToolResult(
                tool_id=tool_id,
                success=False,
                error=f"MCP server {self._server_id} not connected",
            )

        start = time.monotonic()
        try:
            result = await self._session.call_tool(tool_id, arguments=inputs)
            duration_ms = int((time.monotonic() - start) * 1000)

            if result.isError:
                error_text = " ".join(c.text for c in result.content if hasattr(c, "text"))
                return ToolResult(
                    tool_id=tool_id,
                    success=False,
                    error=error_text or "MCP tool returned error",
                    duration_ms=duration_ms,
                )

            output_parts = []
            for content in result.content:
                if hasattr(content, "text"):
                    output_parts.append(content.text)
            output = "\n".join(output_parts)

            return ToolResult(
                tool_id=tool_id,
                success=True,
                output=output,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.exception("MCP tool %s execution failed", tool_id)
            return ToolResult(
                tool_id=tool_id,
                success=False,
                error=str(exc),
                duration_ms=duration_ms,
            )

    async def health_check(self) -> bool:
        """Check if the MCP server is responsive."""
        if not self._connected or not self._session:
            return False
        try:
            await self._session.list_tools()
            return True
        except Exception:
            return False
```

- [ ] **Step 4: Update providers __init__.py**

Update `src/max/tools/providers/__init__.py`:

```python
"""Tool providers — abstractions for different tool sources."""

from max.tools.providers.base import ToolProvider
from max.tools.providers.mcp import MCPToolProvider
from max.tools.providers.native import NativeToolProvider

__all__ = ["MCPToolProvider", "NativeToolProvider", "ToolProvider"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_tool_provider_mcp.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/max/tools/providers/ tests/test_tool_provider_mcp.py
git commit -m "feat(tools): add MCPToolProvider for MCP server integration"
```

---

### Task 11: Package Exports + Native Tool Registration

**Files:**
- Modify: `src/max/tools/__init__.py`
- Modify: `src/max/tools/native/__init__.py`

- [ ] **Step 1: Update tools package exports**

Update `src/max/tools/__init__.py`:

```python
"""Phase 6A: Tool System — providers, executor, registry, native tools."""

from max.tools.executor import ToolExecutor
from max.tools.models import AgentToolPolicy, ProviderHealth, ToolResult
from max.tools.providers.base import ToolProvider
from max.tools.providers.mcp import MCPToolProvider
from max.tools.providers.native import NativeToolProvider
from max.tools.registry import ToolDefinition, ToolRegistry
from max.tools.store import ToolInvocationStore

__all__ = [
    "AgentToolPolicy",
    "MCPToolProvider",
    "NativeToolProvider",
    "ProviderHealth",
    "ToolDefinition",
    "ToolExecutor",
    "ToolInvocationStore",
    "ToolProvider",
    "ToolRegistry",
    "ToolResult",
]
```

- [ ] **Step 2: Create native tool registration helper**

Update `src/max/tools/native/__init__.py`:

```python
"""Native tool implementations for Max.

Call ``register_all_native_tools(provider)`` to register every built-in tool.
"""

from __future__ import annotations

from max.tools.native.file_tools import (
    TOOL_DEFINITIONS as FILE_TOOLS,
    handle_directory_list,
    handle_file_delete,
    handle_file_edit,
    handle_file_glob,
    handle_file_read,
    handle_file_write,
)
from max.tools.native.git_tools import (
    TOOL_DEFINITIONS as GIT_TOOLS,
    handle_git_commit,
    handle_git_diff,
    handle_git_log,
    handle_git_status,
)
from max.tools.native.process_tools import (
    TOOL_DEFINITIONS as PROCESS_TOOLS,
    handle_process_list,
)
from max.tools.native.search_tools import (
    TOOL_DEFINITIONS as SEARCH_TOOLS,
    handle_grep_search,
)
from max.tools.native.shell_tools import (
    TOOL_DEFINITIONS as SHELL_TOOLS,
    handle_shell_execute,
)
from max.tools.native.web_tools import (
    TOOL_DEFINITIONS as WEB_TOOLS,
    handle_http_fetch,
    handle_http_request,
)
from max.tools.providers.native import NativeToolProvider

_HANDLER_MAP = {
    "file.read": handle_file_read,
    "file.write": handle_file_write,
    "file.edit": handle_file_edit,
    "directory.list": handle_directory_list,
    "file.glob": handle_file_glob,
    "file.delete": handle_file_delete,
    "shell.execute": handle_shell_execute,
    "git.status": handle_git_status,
    "git.diff": handle_git_diff,
    "git.log": handle_git_log,
    "git.commit": handle_git_commit,
    "http.fetch": handle_http_fetch,
    "http.request": handle_http_request,
    "process.list": handle_process_list,
    "grep.search": handle_grep_search,
}

ALL_TOOL_DEFINITIONS = FILE_TOOLS + SHELL_TOOLS + GIT_TOOLS + WEB_TOOLS + PROCESS_TOOLS + SEARCH_TOOLS


def register_all_native_tools(provider: NativeToolProvider) -> None:
    """Register all built-in native tools on the given provider."""
    for tool_def in ALL_TOOL_DEFINITIONS:
        handler = _HANDLER_MAP.get(tool_def.tool_id)
        if handler:
            provider.register_tool(tool_def, handler)
```

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v --ignore=tests/test_postgres.py -q`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add src/max/tools/__init__.py src/max/tools/native/__init__.py
git commit -m "feat(tools): update package exports and native tool registration"
```

---

### Task 12: Full Integration Test + Lint

**Files:**
- Create: `tests/test_tool_integration.py`

- [ ] **Step 1: Write integration test**

Create `tests/test_tool_integration.py`:

```python
"""End-to-end integration test for the tool system.

Tests: Registry → Provider → Executor → Agent tool loop.
All LLM calls mocked. Tools execute for real (file ops on tmp_path).
"""

import json
from unittest.mock import AsyncMock

import pytest

from max.agents.base import AgentConfig, BaseAgent
from max.llm.models import LLMResponse, ModelType, ToolCall
from max.tools.executor import ToolExecutor
from max.tools.models import AgentToolPolicy
from max.tools.native import register_all_native_tools
from max.tools.providers.native import NativeToolProvider
from max.tools.registry import ToolRegistry


class TestAgent(BaseAgent):
    async def run(self, input_data):
        return {}


class TestToolIntegration:
    @pytest.mark.asyncio
    async def test_agent_reads_file_via_tool_loop(self, tmp_path):
        """Agent uses file.read tool to read a file, then answers."""
        # Setup real file
        test_file = tmp_path / "hello.txt"
        test_file.write_text("Hello from Max!")

        # Setup provider + registry
        provider = NativeToolProvider()
        register_all_native_tools(provider)
        registry = ToolRegistry()
        await registry.register_provider(provider)

        policy = AgentToolPolicy(agent_name="test_agent", allowed_categories=["code"])
        registry.set_agent_policy(policy)

        store = AsyncMock()
        store.record = AsyncMock()
        executor = ToolExecutor(registry=registry, store=store, audit_enabled=True)

        # Setup agent with mocked LLM
        llm = AsyncMock()
        config = AgentConfig(name="test_agent", system_prompt="You are a test agent")
        agent = TestAgent(config=config, llm=llm)

        # LLM call 1: request file.read tool
        tool_response = LLMResponse(
            text="",
            input_tokens=10,
            output_tokens=5,
            model="claude-opus-4-6",
            stop_reason="tool_use",
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="file.read",
                    input={"path": str(test_file)},
                )
            ],
        )
        # LLM call 2: final answer using tool result
        final_response = LLMResponse(
            text="The file contains: Hello from Max!",
            input_tokens=20,
            output_tokens=10,
            model="claude-opus-4-6",
            stop_reason="end_turn",
            tool_calls=None,
        )
        llm.complete = AsyncMock(side_effect=[tool_response, final_response])

        tools = registry.to_anthropic_tools(
            [t.tool_id for t in registry.get_agent_tools("test_agent")]
        )
        response = await agent.think_with_tools(
            messages=[{"role": "user", "content": f"Read {test_file}"}],
            tools=tools,
            tool_executor=executor,
        )

        assert "Hello from Max!" in response.text
        assert llm.complete.call_count == 2
        # Audit should have recorded one tool invocation
        store.record.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_all_native_tools(self):
        """All 15 native tools register correctly."""
        provider = NativeToolProvider()
        register_all_native_tools(provider)
        tools = await provider.list_tools()
        assert len(tools) == 15
        tool_ids = {t.tool_id for t in tools}
        expected = {
            "file.read", "file.write", "file.edit",
            "directory.list", "file.glob", "file.delete",
            "shell.execute",
            "git.status", "git.diff", "git.log", "git.commit",
            "http.fetch", "http.request",
            "process.list",
            "grep.search",
        }
        assert expected == tool_ids
```

- [ ] **Step 2: Run the integration test**

Run: `pytest tests/test_tool_integration.py -v`
Expected: ALL PASS

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v --ignore=tests/test_postgres.py -q`
Expected: ALL PASS

- [ ] **Step 4: Lint and format**

Run: `ruff check src/max/tools/ src/max/agents/base.py tests/test_tool_*.py tests/test_native_*.py tests/test_agent_tool_loop.py`
Run: `ruff format src/max/tools/ src/max/agents/base.py tests/test_tool_*.py tests/test_native_*.py tests/test_agent_tool_loop.py`

Fix any issues.

- [ ] **Step 5: Commit**

```bash
git add tests/test_tool_integration.py
git commit -m "test(tools): add end-to-end tool system integration test"
```

- [ ] **Step 6: Run final full test suite**

Run: `pytest tests/ -v --ignore=tests/test_postgres.py`
Expected: ALL PASS — record final test count.
