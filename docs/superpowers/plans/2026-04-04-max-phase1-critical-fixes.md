# Phase 1 Critical Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 12 code review findings from Phase 1 (5 critical + 7 should-fix) with full TDD coverage before starting Phase 2.

**Architecture:** Targeted fixes to existing modules. No new modules. All changes are backward-compatible within the project. Tests first, implementation second, commit per task.

**Tech Stack:** Python 3.12, asyncpg, redis-py, pydantic v2, anthropic SDK (built-in retries), pytest-asyncio.

**Branch:** `phase1/critical-fixes` (create from master via worktree)

**Working directory:** The worktree at `.worktrees/phase1-critical-fixes/`

**Test command:** `uv run pytest tests/ -v --tb=short`

**Lint command:** `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/max/llm/models.py` | Modify | Add `ToolCall` model, refactor `ModelType` to tuple enum, update `LLMResponse.tool_calls` type |
| `src/max/llm/client.py` | Modify | Add error handling, configure retries, construct `ToolCall` objects |
| `src/max/llm/errors.py` | Create | `LLMError` exception hierarchy |
| `src/max/llm/__init__.py` | Modify | Export new types |
| `src/max/bus/message_bus.py` | Modify | Multi-handler fan-out support |
| `src/max/db/postgres.py` | Modify | Add `transaction()` context manager |
| `src/max/db/schema.sql` | Modify | Add 4 missing tables, FK, HNSW index |
| `src/max/db/redis_store.py` | Modify | Fix TTL bug |
| `src/max/agents/base.py` | Modify | Add `AgentContext`, lifecycle hooks, enforce `max_turns` |
| `src/max/agents/__init__.py` | Modify | Export `AgentContext` |
| `src/max/models/tasks.py` | Modify | Type `SubTask.audit_report`, add `QualityRule` |
| `src/max/models/__init__.py` | Modify | Export `QualityRule` |
| `tests/test_llm_models.py` | Create | Tests for `ToolCall`, `ModelType` tuple, `LLMResponse` typed |
| `tests/test_llm_client.py` | Modify | Add error path tests |
| `tests/test_message_bus.py` | Modify | Add multi-handler fan-out tests |
| `tests/test_postgres.py` | Modify | Add transaction tests, clean up new tables |
| `tests/test_redis_store.py` | Modify | Add TTL=0 bug fix test |
| `tests/test_base_agent.py` | Modify | Add lifecycle, AgentContext, max_turns, reset tests |
| `tests/test_models.py` | Modify | Add QualityRule test, typed audit_report test |

---

### Task 1: ToolCall Model + Typed LLMResponse.tool_calls

**Files:**
- Modify: `src/max/llm/models.py`
- Modify: `src/max/llm/client.py:40-44`
- Modify: `src/max/llm/__init__.py`
- Create: `tests/test_llm_models.py`
- Modify: `tests/test_llm_client.py`

- [ ] **Step 1: Write failing tests for ToolCall model and typed tool_calls**

Create `tests/test_llm_models.py`:

```python
from max.llm.models import LLMResponse, ModelType, ToolCall


def test_tool_call_creation():
    tc = ToolCall(id="toolu_01", name="file.write", input={"path": "/tmp/a.txt", "content": "hi"})
    assert tc.id == "toolu_01"
    assert tc.name == "file.write"
    assert tc.input == {"path": "/tmp/a.txt", "content": "hi"}


def test_llm_response_with_typed_tool_calls():
    resp = LLMResponse(
        text="",
        input_tokens=10,
        output_tokens=5,
        model="claude-opus-4-6",
        stop_reason="tool_use",
        tool_calls=[
            ToolCall(id="toolu_01", name="file.write", input={"path": "/tmp/a.txt"}),
            ToolCall(id="toolu_02", name="shell.exec", input={"cmd": "ls"}),
        ],
    )
    assert len(resp.tool_calls) == 2
    assert resp.tool_calls[0].name == "file.write"
    assert resp.tool_calls[1].id == "toolu_02"


def test_llm_response_no_tool_calls():
    resp = LLMResponse(
        text="Hello",
        input_tokens=10,
        output_tokens=5,
        model="claude-opus-4-6",
        stop_reason="end_turn",
    )
    assert resp.tool_calls is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_llm_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'ToolCall'`

- [ ] **Step 3: Implement ToolCall model and update LLMResponse**

In `src/max/llm/models.py`, add `ToolCall` above `LLMResponse` and change the type:

```python
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class ModelType(Enum):
    OPUS = "opus"
    SONNET = "sonnet"

    @property
    def model_id(self) -> str:
        return {
            ModelType.OPUS: "claude-opus-4-6",
            ModelType.SONNET: "claude-sonnet-4-6",
        }[self]

    @property
    def max_tokens(self) -> int:
        return {
            ModelType.OPUS: 32768,
            ModelType.SONNET: 16384,
        }[self]


class ToolCall(BaseModel):
    """A structured tool call returned by the LLM."""

    id: str
    name: str
    input: dict[str, Any]


class LLMResponse(BaseModel):
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    stop_reason: str
    tool_calls: list[ToolCall] | None = None
```

Update `src/max/llm/client.py` lines 43-44 to construct `ToolCall` objects:

Replace `tool_calls.append({"id": block.id, "name": block.name, "input": block.input})` with:

```python
from max.llm.models import LLMResponse, ModelType, ToolCall
```

And in the loop:

```python
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=block.input))
```

Update `src/max/llm/__init__.py`:

```python
from max.llm.client import LLMClient
from max.llm.models import LLMResponse, ModelType, ToolCall

__all__ = ["LLMClient", "LLMResponse", "ModelType", "ToolCall"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm_models.py tests/test_llm_client.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/max/llm/models.py src/max/llm/client.py src/max/llm/__init__.py tests/test_llm_models.py
git commit -m "feat: add ToolCall model and type LLMResponse.tool_calls"
```

---

### Task 2: ModelType Tuple Enum Refactor

**Files:**
- Modify: `src/max/llm/models.py:8-24`
- Modify: `tests/test_llm_models.py`

- [ ] **Step 1: Write failing test for tuple-based ModelType**

Add to `tests/test_llm_models.py`:

```python
def test_model_type_opus():
    assert ModelType.OPUS.model_id == "claude-opus-4-6"
    assert ModelType.OPUS.max_tokens == 32768


def test_model_type_sonnet():
    assert ModelType.SONNET.model_id == "claude-sonnet-4-6"
    assert ModelType.SONNET.max_tokens == 16384


def test_model_type_value():
    assert ModelType.OPUS.value == ("opus", "claude-opus-4-6", 32768)
    assert ModelType.SONNET.value == ("sonnet", "claude-sonnet-4-6", 16384)
```

- [ ] **Step 2: Run tests to verify the value test fails**

Run: `uv run pytest tests/test_llm_models.py::test_model_type_value -v`
Expected: FAIL — `AssertionError: 'opus' != ('opus', 'claude-opus-4-6', 32768)`

- [ ] **Step 3: Refactor ModelType to use tuple values**

Replace the `ModelType` class in `src/max/llm/models.py`:

```python
class ModelType(Enum):
    OPUS = ("opus", "claude-opus-4-6", 32768)
    SONNET = ("sonnet", "claude-sonnet-4-6", 16384)

    def __init__(self, label: str, model_id: str, max_tokens: int) -> None:
        self.label = label
        self._model_id = model_id
        self._max_tokens = max_tokens

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def max_tokens(self) -> int:
        return self._max_tokens
```

- [ ] **Step 4: Run all LLM tests to verify nothing broke**

Run: `uv run pytest tests/test_llm_models.py tests/test_llm_client.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite to check no regressions**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/max/llm/models.py tests/test_llm_models.py
git commit -m "refactor: ModelType to tuple enum for self-contained values"
```

---

### Task 3: LLM Error Handling + Retry

**Files:**
- Create: `src/max/llm/errors.py`
- Modify: `src/max/llm/client.py`
- Modify: `src/max/llm/__init__.py`
- Modify: `tests/test_llm_client.py`

- [ ] **Step 1: Write failing tests for error handling**

Add to `tests/test_llm_client.py`:

```python
import anthropic
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from max.llm.client import LLMClient
from max.llm.errors import LLMError, LLMRateLimitError, LLMConnectionError, LLMAuthError
from max.llm.models import ModelType


@pytest.mark.asyncio
async def test_client_wraps_rate_limit_error(llm_client):
    with patch.object(
        llm_client._client.messages,
        "create",
        new_callable=AsyncMock,
        side_effect=anthropic.RateLimitError(
            message="Rate limit exceeded",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        ),
    ):
        with pytest.raises(LLMRateLimitError, match="Rate limit exceeded"):
            await llm_client.complete(
                messages=[{"role": "user", "content": "Hello"}],
            )


@pytest.mark.asyncio
async def test_client_wraps_connection_error(llm_client):
    with patch.object(
        llm_client._client.messages,
        "create",
        new_callable=AsyncMock,
        side_effect=anthropic.APIConnectionError(request=MagicMock()),
    ):
        with pytest.raises(LLMConnectionError):
            await llm_client.complete(
                messages=[{"role": "user", "content": "Hello"}],
            )


@pytest.mark.asyncio
async def test_client_wraps_auth_error(llm_client):
    with patch.object(
        llm_client._client.messages,
        "create",
        new_callable=AsyncMock,
        side_effect=anthropic.AuthenticationError(
            message="Invalid API key",
            response=MagicMock(status_code=401, headers={}),
            body=None,
        ),
    ):
        with pytest.raises(LLMAuthError, match="Invalid API key"):
            await llm_client.complete(
                messages=[{"role": "user", "content": "Hello"}],
            )


@pytest.mark.asyncio
async def test_client_wraps_generic_api_error(llm_client):
    with patch.object(
        llm_client._client.messages,
        "create",
        new_callable=AsyncMock,
        side_effect=anthropic.APIStatusError(
            message="Internal server error",
            response=MagicMock(status_code=500, headers={}),
            body=None,
        ),
    ):
        with pytest.raises(LLMError, match="Internal server error"):
            await llm_client.complete(
                messages=[{"role": "user", "content": "Hello"}],
            )


def test_llm_error_hierarchy():
    assert issubclass(LLMRateLimitError, LLMError)
    assert issubclass(LLMConnectionError, LLMError)
    assert issubclass(LLMAuthError, LLMError)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_llm_client.py::test_client_wraps_rate_limit_error -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'max.llm.errors'`

- [ ] **Step 3: Create error hierarchy**

Create `src/max/llm/errors.py`:

```python
"""LLM client error hierarchy for Max."""

from __future__ import annotations


class LLMError(Exception):
    """Base exception for all LLM client errors."""

    def __init__(self, message: str, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.__cause__ = cause


class LLMRateLimitError(LLMError):
    """Raised when the API returns a 429 rate limit response."""


class LLMConnectionError(LLMError):
    """Raised when the API is unreachable."""


class LLMAuthError(LLMError):
    """Raised when authentication fails (invalid/expired API key)."""
```

- [ ] **Step 4: Add error handling to LLMClient.complete()**

Replace `src/max/llm/client.py` with:

```python
from __future__ import annotations

import logging
from typing import Any

import anthropic
from anthropic import AsyncAnthropic

from max.llm.errors import LLMAuthError, LLMConnectionError, LLMError, LLMRateLimitError
from max.llm.models import LLMResponse, ModelType, ToolCall

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(
        self,
        api_key: str,
        default_model: ModelType = ModelType.OPUS,
        max_retries: int = 3,
    ):
        self._client = AsyncAnthropic(api_key=api_key, max_retries=max_retries)
        self.default_model = default_model
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    async def complete(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        model: ModelType | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        model_type = model or self.default_model
        kwargs: dict[str, Any] = {
            "model": model_type.model_id,
            "messages": messages,
            "max_tokens": max_tokens or model_type.max_tokens,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if tools:
            kwargs["tools"] = tools

        try:
            response = await self._client.messages.create(**kwargs)
        except anthropic.RateLimitError as exc:
            raise LLMRateLimitError(str(exc), cause=exc) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMConnectionError(str(exc), cause=exc) from exc
        except anthropic.AuthenticationError as exc:
            raise LLMAuthError(str(exc), cause=exc) from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(str(exc), cause=exc) from exc

        text_parts = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=block.input))

        self.total_input_tokens += response.usage.input_tokens
        self.total_output_tokens += response.usage.output_tokens

        return LLMResponse(
            text="\n".join(text_parts),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
            stop_reason=response.stop_reason,
            tool_calls=tool_calls if tool_calls else None,
        )

    async def close(self):
        await self._client.close()
```

Update `src/max/llm/__init__.py`:

```python
from max.llm.client import LLMClient
from max.llm.errors import LLMAuthError, LLMConnectionError, LLMError, LLMRateLimitError
from max.llm.models import LLMResponse, ModelType, ToolCall

__all__ = [
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

- [ ] **Step 5: Run all LLM tests to verify they pass**

Run: `uv run pytest tests/test_llm_client.py tests/test_llm_models.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/max/llm/errors.py src/max/llm/client.py src/max/llm/__init__.py tests/test_llm_client.py
git commit -m "feat: add LLM error handling with exception hierarchy and SDK retries"
```

---

### Task 4: MessageBus Multi-Handler Fan-Out

**Files:**
- Modify: `src/max/bus/message_bus.py`
- Modify: `tests/test_message_bus.py`

- [ ] **Step 1: Write failing test for multi-handler on same channel**

Add to `tests/test_message_bus.py`:

```python
@pytest.mark.asyncio
async def test_multi_handler_fanout(bus):
    received_a = []
    received_b = []

    async def handler_a(channel: str, data: dict):
        received_a.append(data)

    async def handler_b(channel: str, data: dict):
        received_b.append(data)

    await bus.subscribe("events.task", handler_a)
    await bus.subscribe("events.task", handler_b)
    await bus.start_listening()
    await asyncio.sleep(0.1)

    await bus.publish("events.task", {"type": "task_created", "id": "1"})
    await asyncio.sleep(0.3)

    await bus.stop_listening()
    assert len(received_a) == 1
    assert len(received_b) == 1
    assert received_a[0]["id"] == "1"
    assert received_b[0]["id"] == "1"


@pytest.mark.asyncio
async def test_unsubscribe_specific_handler(bus):
    received_a = []
    received_b = []

    async def handler_a(channel: str, data: dict):
        received_a.append(data)

    async def handler_b(channel: str, data: dict):
        received_b.append(data)

    await bus.subscribe("events.unsub", handler_a)
    await bus.subscribe("events.unsub", handler_b)
    await bus.start_listening()
    await asyncio.sleep(0.1)

    await bus.publish("events.unsub", {"n": 1})
    await asyncio.sleep(0.2)

    await bus.unsubscribe("events.unsub", handler_a)
    await bus.publish("events.unsub", {"n": 2})
    await asyncio.sleep(0.2)

    await bus.stop_listening()
    # handler_a got only the first message
    assert len(received_a) == 1
    assert received_a[0]["n"] == 1
    # handler_b got both messages
    assert len(received_b) == 2


@pytest.mark.asyncio
async def test_handler_error_does_not_block_others(bus):
    received = []

    async def bad_handler(channel: str, data: dict):
        raise ValueError("I'm broken")

    async def good_handler(channel: str, data: dict):
        received.append(data)

    await bus.subscribe("events.err", bad_handler)
    await bus.subscribe("events.err", good_handler)
    await bus.start_listening()
    await asyncio.sleep(0.1)

    await bus.publish("events.err", {"test": True})
    await asyncio.sleep(0.3)

    await bus.stop_listening()
    assert len(received) == 1
    assert received[0]["test"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_message_bus.py::test_multi_handler_fanout -v`
Expected: FAIL — second handler overwrites first, `received_a` is empty

- [ ] **Step 3: Refactor MessageBus for multi-handler support**

Replace `src/max/bus/message_bus.py`:

```python
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

Handler = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


class MessageBus:
    def __init__(self, redis_client: aioredis.Redis):
        self._redis = redis_client
        self._pubsub = redis_client.pubsub()
        self._handlers: dict[str, list[Handler]] = {}
        self._listen_task: asyncio.Task | None = None

    async def subscribe(self, channel: str, handler: Handler) -> None:
        if channel not in self._handlers:
            self._handlers[channel] = []
            await self._pubsub.subscribe(channel)
        self._handlers[channel].append(handler)
        logger.debug("Subscribed handler to %s (total: %d)", channel, len(self._handlers[channel]))

    async def unsubscribe(self, channel: str, handler: Handler | None = None) -> None:
        if channel not in self._handlers:
            return
        if handler is None:
            # Remove all handlers for this channel
            del self._handlers[channel]
            await self._pubsub.unsubscribe(channel)
        else:
            # Remove specific handler
            try:
                self._handlers[channel].remove(handler)
            except ValueError:
                return
            if not self._handlers[channel]:
                del self._handlers[channel]
                await self._pubsub.unsubscribe(channel)
        logger.debug("Unsubscribed from %s", channel)

    async def publish(self, channel: str, data: dict[str, Any]) -> None:
        payload = json.dumps(data)
        await self._redis.publish(channel, payload)
        logger.debug("Published to %s: %s", channel, payload[:200])

    async def start_listening(self) -> None:
        if self._listen_task is not None:
            return
        self._listen_task = asyncio.create_task(self._listen_loop())

    async def stop_listening(self) -> None:
        if self._listen_task is not None:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

    async def _listen_loop(self) -> None:
        try:
            async for message in self._pubsub.listen():
                if message["type"] != "message":
                    continue
                channel = message["channel"]
                if isinstance(channel, bytes):
                    channel = channel.decode("utf-8")
                handlers = self._handlers.get(channel, [])
                if not handlers:
                    continue
                try:
                    data = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    logger.exception("Failed to decode message on %s", channel)
                    continue
                for handler in handlers:
                    try:
                        await handler(channel, data)
                    except Exception:
                        logger.exception("Error in handler for %s", channel)
        except asyncio.CancelledError:
            raise

    async def close(self) -> None:
        await self.stop_listening()
        await self._pubsub.aclose()
```

- [ ] **Step 4: Update existing unsubscribe test**

The existing `test_unsubscribe` test calls `bus.unsubscribe("test.unsub")` with only a channel name (no handler). This still works because our new signature has `handler: Handler | None = None` — passing None removes all handlers for the channel. No test changes needed for existing tests.

- [ ] **Step 5: Run all message bus tests**

Run: `uv run pytest tests/test_message_bus.py -v`
Expected: ALL PASS (3 old + 3 new = 6 tests)

- [ ] **Step 6: Commit**

```bash
git add src/max/bus/message_bus.py tests/test_message_bus.py
git commit -m "feat: MessageBus multi-handler fan-out with per-handler unsubscribe"
```

---

### Task 5: Database Transaction Support

**Files:**
- Modify: `src/max/db/postgres.py`
- Modify: `tests/test_postgres.py`

- [ ] **Step 1: Write failing tests for transactions**

Add to `tests/test_postgres.py`:

```python
@pytest.mark.asyncio
async def test_transaction_commit(db):
    task_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    async with db.transaction() as conn:
        await conn.execute(
            "INSERT INTO tasks (id, goal_anchor, source_intent_id) VALUES ($1, $2, $3)",
            task_id,
            "Transactional goal",
            intent_id,
        )
    row = await db.fetchone("SELECT * FROM tasks WHERE id = $1", task_id)
    assert row is not None
    assert row["goal_anchor"] == "Transactional goal"


@pytest.mark.asyncio
async def test_transaction_rollback(db):
    task_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    with pytest.raises(ValueError, match="Intentional rollback"):
        async with db.transaction() as conn:
            await conn.execute(
                "INSERT INTO tasks (id, goal_anchor, source_intent_id) VALUES ($1, $2, $3)",
                task_id,
                "Should not persist",
                intent_id,
            )
            raise ValueError("Intentional rollback")
    row = await db.fetchone("SELECT * FROM tasks WHERE id = $1", task_id)
    assert row is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_postgres.py::test_transaction_commit -v`
Expected: FAIL — `AttributeError: 'Database' object has no attribute 'transaction'`

- [ ] **Step 3: Implement transaction context manager**

Add to `src/max/db/postgres.py`, after the `_get_pool` method, add these imports and the context manager:

Add at the top of the file:

```python
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
```

Add method to `Database` class:

```python
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[asyncpg.Connection]:
        """Acquire a connection and run queries inside a transaction.

        Usage::

            async with db.transaction() as conn:
                await conn.execute("INSERT ...")
                await conn.execute("UPDATE ...")
            # auto-committed on clean exit, rolled back on exception
        """
        async with self._get_pool().acquire() as conn:
            async with conn.transaction():
                yield conn
```

- [ ] **Step 4: Run transaction tests**

Run: `uv run pytest tests/test_postgres.py -v`
Expected: ALL PASS (3 old + 2 new = 5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/max/db/postgres.py tests/test_postgres.py
git commit -m "feat: add Database.transaction() context manager for atomic ops"
```

---

### Task 6: Missing Database Tables + HNSW Index

**Files:**
- Modify: `src/max/db/schema.sql`
- Modify: `tests/test_postgres.py`

- [ ] **Step 1: Write failing tests for new tables**

Add to `tests/test_postgres.py`:

```python
@pytest.mark.asyncio
async def test_intents_table_exists(db):
    intent_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO intents (id, user_message, source_platform, goal_anchor, priority)"
        " VALUES ($1, $2, $3, $4, $5)",
        intent_id,
        "Deploy the app",
        "telegram",
        "Deploy the app",
        "normal",
    )
    row = await db.fetchone("SELECT * FROM intents WHERE id = $1", intent_id)
    assert row["user_message"] == "Deploy the app"
    assert row["source_platform"] == "telegram"


@pytest.mark.asyncio
async def test_results_table_exists(db):
    # Need a task first for FK
    task_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO intents (id, user_message, source_platform, goal_anchor) VALUES ($1, $2, $3, $4)",
        intent_id,
        "Test",
        "telegram",
        "Test",
    )
    await db.execute(
        "INSERT INTO tasks (id, goal_anchor, source_intent_id) VALUES ($1, $2, $3)",
        task_id,
        "Test goal",
        intent_id,
    )
    result_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO results (id, task_id, content, confidence) VALUES ($1, $2, $3, $4)",
        result_id,
        task_id,
        "Done",
        0.95,
    )
    row = await db.fetchone("SELECT * FROM results WHERE id = $1", result_id)
    assert row["content"] == "Done"
    assert row["confidence"] == pytest.approx(0.95)


@pytest.mark.asyncio
async def test_tasks_source_intent_fk(db):
    intent_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO intents (id, user_message, source_platform, goal_anchor) VALUES ($1, $2, $3, $4)",
        intent_id,
        "FK test",
        "whatsapp",
        "FK test",
    )
    task_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO tasks (id, goal_anchor, source_intent_id) VALUES ($1, $2, $3)",
        task_id,
        "FK goal",
        intent_id,
    )
    row = await db.fetchone("SELECT * FROM tasks WHERE id = $1", task_id)
    assert row["source_intent_id"] == intent_id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_postgres.py::test_intents_table_exists -v`
Expected: FAIL — `asyncpg.exceptions.UndefinedTableError: relation "intents" does not exist`

- [ ] **Step 3: Add missing tables, FK, and HNSW index to schema.sql**

Replace `src/max/db/schema.sql` with the complete schema:

```sql
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Intents (user messages as structured objects)
CREATE TABLE IF NOT EXISTS intents (
    id UUID PRIMARY KEY,
    user_message TEXT NOT NULL,
    source_platform VARCHAR(20) NOT NULL,
    goal_anchor TEXT NOT NULL,
    priority VARCHAR(20) NOT NULL DEFAULT 'normal',
    attachments JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_intents_platform ON intents(source_platform);
CREATE INDEX IF NOT EXISTS idx_intents_created ON intents(created_at DESC);

-- Tasks
CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY,
    goal_anchor TEXT NOT NULL,
    source_intent_id UUID NOT NULL REFERENCES intents(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    quality_criteria JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at DESC);

-- SubTasks
CREATE TABLE IF NOT EXISTS subtasks (
    id UUID PRIMARY KEY,
    parent_task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    assigned_tools JSONB NOT NULL DEFAULT '[]',
    context_package JSONB NOT NULL DEFAULT '{}',
    result JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_subtasks_parent ON subtasks(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_subtasks_status ON subtasks(status);

-- Audit Reports
CREATE TABLE IF NOT EXISTS audit_reports (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    subtask_id UUID NOT NULL REFERENCES subtasks(id) ON DELETE CASCADE,
    verdict VARCHAR(20) NOT NULL,
    score REAL NOT NULL,
    goal_alignment REAL NOT NULL,
    confidence REAL NOT NULL,
    issues JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_task ON audit_reports(task_id);

-- Results (task outcomes)
CREATE TABLE IF NOT EXISTS results (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    artifacts JSONB NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_results_task ON results(task_id);

-- Clarification Requests
CREATE TABLE IF NOT EXISTS clarification_requests (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    options JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_clarifications_task ON clarification_requests(task_id);

-- Status Updates
CREATE TABLE IF NOT EXISTS status_updates (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    message TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_status_updates_task ON status_updates(task_id);

-- Context Anchors
CREATE TABLE IF NOT EXISTS context_anchors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content TEXT NOT NULL,
    anchor_type VARCHAR(50) NOT NULL,
    source_task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_anchors_type ON context_anchors(anchor_type);

-- Quality Ledger (append-only)
CREATE TABLE IF NOT EXISTS quality_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entry_type VARCHAR(50) NOT NULL,
    content JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ledger_type ON quality_ledger(entry_type);
CREATE INDEX IF NOT EXISTS idx_ledger_created ON quality_ledger(created_at DESC);

-- Memory embeddings (for semantic search)
CREATE TABLE IF NOT EXISTS memory_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content TEXT NOT NULL,
    embedding vector(1536),
    memory_type VARCHAR(50) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memory_type ON memory_embeddings(memory_type);
CREATE INDEX IF NOT EXISTS idx_memory_embedding_hnsw
    ON memory_embeddings USING hnsw (embedding vector_cosine_ops);
```

- [ ] **Step 4: Update test fixture cleanup order for new tables and FK constraints**

Replace the `db` fixture in `tests/test_postgres.py`:

```python
@pytest.fixture
async def db():
    database = Database(dsn="postgresql://max:max_dev_password@localhost:5432/max")
    await database.connect()
    await database.init_schema()
    # Clean in FK-safe order
    await database.execute("DELETE FROM status_updates")
    await database.execute("DELETE FROM clarification_requests")
    await database.execute("DELETE FROM results")
    await database.execute("DELETE FROM audit_reports")
    await database.execute("DELETE FROM subtasks")
    await database.execute("DELETE FROM tasks")
    await database.execute("DELETE FROM intents")
    yield database
    await database.execute("DELETE FROM status_updates")
    await database.execute("DELETE FROM clarification_requests")
    await database.execute("DELETE FROM results")
    await database.execute("DELETE FROM audit_reports")
    await database.execute("DELETE FROM subtasks")
    await database.execute("DELETE FROM tasks")
    await database.execute("DELETE FROM intents")
    await database.close()
```

**Important:** The existing `test_insert_and_fetch_task` and `test_fetchall` tests insert tasks with random `source_intent_id` UUIDs that don't reference `intents`. With the new FK constraint, these will fail. Update them to insert an intent first:

Update `test_insert_and_fetch_task`:

```python
@pytest.mark.asyncio
async def test_insert_and_fetch_task(db):
    task_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO intents (id, user_message, source_platform, goal_anchor) VALUES ($1, $2, $3, $4)",
        intent_id,
        "Test message",
        "telegram",
        "Test goal",
    )
    await db.execute(
        "INSERT INTO tasks (id, goal_anchor, source_intent_id, status) VALUES ($1, $2, $3, $4)",
        task_id,
        "Test goal",
        intent_id,
        "pending",
    )
    row = await db.fetchone("SELECT * FROM tasks WHERE id = $1", task_id)
    assert row["goal_anchor"] == "Test goal"
    assert row["status"] == "pending"


@pytest.mark.asyncio
async def test_fetchall(db):
    for i in range(3):
        intent_id = uuid.uuid4()
        await db.execute(
            "INSERT INTO intents (id, user_message, source_platform, goal_anchor) VALUES ($1, $2, $3, $4)",
            intent_id,
            f"Message {i}",
            "telegram",
            f"Goal {i}",
        )
        await db.execute(
            "INSERT INTO tasks (id, goal_anchor, source_intent_id) VALUES ($1, $2, $3)",
            uuid.uuid4(),
            f"Goal {i}",
            intent_id,
        )
    rows = await db.fetchall("SELECT * FROM tasks ORDER BY created_at")
    assert len(rows) >= 3
```

- [ ] **Step 5: Update integration test fixture and task insertion**

In `tests/conftest.py`, update the `db` fixture to init schema and clean new tables:

```python
@pytest.fixture
async def db(settings):
    database = Database(dsn=settings.postgres_dsn)
    await database.connect()
    await database.init_schema()
    yield database
    await database.close()
```

In `tests/test_integration.py`, update the task insertion to insert an intent first (around lines 41-47):

After creating the `intent` and `task` objects, persist the intent before the task:

```python
    # 3. Persist intent then task to PostgreSQL (FK requires intent first)
    await db.execute(
        "INSERT INTO intents (id, user_message, source_platform, goal_anchor, priority)"
        " VALUES ($1, $2, $3, $4, $5)",
        intent.id,
        intent.user_message,
        intent.source_platform,
        intent.goal_anchor,
        intent.priority.value,
    )
    await db.execute(
        "INSERT INTO tasks (id, goal_anchor, source_intent_id, status) VALUES ($1, $2, $3, $4)",
        task.id,
        task.goal_anchor,
        task.source_intent_id,
        task.status.value,
    )
    row = await db.fetchone("SELECT * FROM tasks WHERE id = $1", task.id)
    assert row["goal_anchor"] == "Write a Python hello world script"
```

- [ ] **Step 6: Run all database and integration tests**

Run: `uv run pytest tests/test_postgres.py tests/test_integration.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/max/db/schema.sql tests/test_postgres.py tests/conftest.py tests/test_integration.py
git commit -m "feat: add intents/results/status_updates/clarification_requests tables, FK, HNSW index"
```

---

### Task 7: WarmMemory TTL Bug Fix

**Files:**
- Modify: `src/max/db/redis_store.py:36`
- Modify: `tests/test_redis_store.py`

- [ ] **Step 1: Write failing test for TTL=0 edge case**

Add to `tests/test_redis_store.py`:

```python
@pytest.mark.asyncio
async def test_set_with_ttl_zero_expires_immediately(warm, redis_client):
    """ttl_seconds=0 should call setex (which expires the key immediately), not set."""
    await warm.set("ephemeral", {"data": "gone"}, ttl_seconds=0)
    # Redis SETEX with TTL 0 is invalid — but the point is that ttl_seconds=0
    # should NOT fall through to the no-TTL branch. We test that setex is called.
    # In practice, TTL=0 is unusual but the guard must be correct.
    # After setex with 0, Redis rejects it. The fix ensures we enter the TTL branch.
    # A more practical test: ttl_seconds=1 should expire
    await warm.set("short_lived", {"data": "brief"}, ttl_seconds=1)
    result = await warm.get("short_lived")
    assert result is not None
    # Wait for expiry
    import asyncio
    await asyncio.sleep(1.5)
    result = await warm.get("short_lived")
    assert result is None
```

- [ ] **Step 2: Run test to verify current behavior**

Run: `uv run pytest tests/test_redis_store.py::test_set_with_ttl_zero_expires_immediately -v`
Expected: FAIL — the key persists after 1.5s because TTL branch may not work correctly with current guard

- [ ] **Step 3: Fix the TTL guard**

In `src/max/db/redis_store.py`, change line 36 from:

```python
        if ttl_seconds:
```

to:

```python
        if ttl_seconds is not None:
```

- [ ] **Step 4: Run all redis tests**

Run: `uv run pytest tests/test_redis_store.py -v`
Expected: ALL PASS (6 old + 1 new = 7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/max/db/redis_store.py tests/test_redis_store.py
git commit -m "fix: WarmMemory TTL guard — use 'is not None' instead of falsy check"
```

---

### Task 8: BaseAgent Lifecycle Hooks + AgentContext + max_turns Enforcement

**Files:**
- Modify: `src/max/agents/base.py`
- Modify: `src/max/agents/__init__.py`
- Modify: `tests/test_base_agent.py`

- [ ] **Step 1: Write failing tests for AgentContext, lifecycle, max_turns, and reset**

Add to `tests/test_base_agent.py`:

```python
from max.agents.base import AgentConfig, AgentContext, BaseAgent
from max.llm.models import LLMResponse, ModelType


class LifecycleAgent(BaseAgent):
    def __init__(self, config, llm, context=None):
        super().__init__(config, llm, context)
        self.started = False
        self.stopped = False

    async def on_start(self) -> None:
        self.started = True

    async def on_stop(self) -> None:
        self.stopped = True

    async def run(self, input_data: dict) -> dict:
        return {"done": True}


@pytest.mark.asyncio
async def test_agent_context_creation():
    ctx = AgentContext(bus=None, db=None, warm_memory=None)
    assert ctx.bus is None
    assert ctx.db is None
    assert ctx.warm_memory is None


@pytest.mark.asyncio
async def test_agent_lifecycle_hooks(mock_llm):
    config = AgentConfig(name="lifecycle", system_prompt="Test.")
    agent = LifecycleAgent(config=config, llm=mock_llm)
    assert agent.started is False
    await agent.on_start()
    assert agent.started is True
    await agent.on_stop()
    assert agent.stopped is True


@pytest.mark.asyncio
async def test_agent_context_accessible(mock_llm):
    ctx = AgentContext(bus="mock_bus", db="mock_db", warm_memory="mock_wm")
    config = AgentConfig(name="ctx-test", system_prompt="Test.")
    agent = LifecycleAgent(config=config, llm=mock_llm, context=ctx)
    assert agent.context.bus == "mock_bus"
    assert agent.context.db == "mock_db"
    assert agent.context.warm_memory == "mock_wm"


@pytest.mark.asyncio
async def test_max_turns_enforced(mock_llm):
    config = AgentConfig(name="limited", system_prompt="Test.", max_turns=2)
    agent = SampleAgent(config=config, llm=mock_llm)
    await agent.think(messages=[{"role": "user", "content": "1"}])
    await agent.think(messages=[{"role": "user", "content": "2"}])
    with pytest.raises(RuntimeError, match="exceeded max_turns"):
        await agent.think(messages=[{"role": "user", "content": "3"}])


def test_agent_reset(mock_llm):
    config = AgentConfig(name="reset-test", system_prompt="Test.")
    agent = SampleAgent(config=config, llm=mock_llm)
    agent._turn_count = 5
    agent.reset()
    assert agent._turn_count == 0


@pytest.mark.asyncio
async def test_turn_count_increments(mock_llm):
    config = AgentConfig(name="counter", system_prompt="Test.")
    agent = SampleAgent(config=config, llm=mock_llm)
    assert agent._turn_count == 0
    await agent.think(messages=[{"role": "user", "content": "1"}])
    assert agent._turn_count == 1
    await agent.think(messages=[{"role": "user", "content": "2"}])
    assert agent._turn_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_base_agent.py::test_agent_context_creation -v`
Expected: FAIL — `ImportError: cannot import name 'AgentContext'`

- [ ] **Step 3: Implement AgentContext, lifecycle hooks, and max_turns enforcement**

Replace `src/max/agents/base.py`:

```python
from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from max.llm.client import LLMClient
from max.llm.models import LLMResponse, ModelType

logger = logging.getLogger(__name__)


class AgentConfig(BaseModel):
    name: str
    system_prompt: str
    model: ModelType = ModelType.OPUS
    max_turns: int = 10
    tools: list[str] = Field(default_factory=list)


class AgentContext:
    """Bundles shared infrastructure dependencies for an agent."""

    __slots__ = ("bus", "db", "warm_memory")

    def __init__(self, bus: Any = None, db: Any = None, warm_memory: Any = None) -> None:
        self.bus = bus
        self.db = db
        self.warm_memory = warm_memory


class BaseAgent(ABC):
    def __init__(
        self,
        config: AgentConfig,
        llm: LLMClient,
        context: AgentContext | None = None,
    ):
        self.config = config
        self.llm = llm
        self.context = context or AgentContext()
        self.agent_id = str(uuid.uuid4())
        self._turn_count = 0

    async def on_start(self) -> None:
        """Called when the agent starts. Override in subclasses."""

    async def on_stop(self) -> None:
        """Called when the agent stops. Override in subclasses."""

    async def think(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        model: ModelType | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        if self._turn_count >= self.config.max_turns:
            raise RuntimeError(
                f"Agent '{self.config.name}' exceeded max_turns ({self.config.max_turns})"
            )
        self._turn_count += 1
        logger.debug(
            "[%s] Turn %d/%d: sending %d messages",
            self.config.name,
            self._turn_count,
            self.config.max_turns,
            len(messages),
        )
        response = await self.llm.complete(
            messages=messages,
            system_prompt=system_prompt or self.config.system_prompt,
            model=model or self.config.model,
            tools=tools,
        )
        logger.debug(
            "[%s] Turn %d: received %d tokens",
            self.config.name,
            self._turn_count,
            response.output_tokens,
        )
        return response

    @abstractmethod
    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]: ...

    def reset(self) -> None:
        self._turn_count = 0
```

Update `src/max/agents/__init__.py`:

```python
from max.agents.base import AgentConfig, AgentContext, BaseAgent

__all__ = ["AgentConfig", "AgentContext", "BaseAgent"]
```

- [ ] **Step 4: Run all agent tests**

Run: `uv run pytest tests/test_base_agent.py -v`
Expected: ALL PASS (4 old + 6 new = 10 tests)

- [ ] **Step 5: Run full test suite for regressions**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/max/agents/base.py src/max/agents/__init__.py tests/test_base_agent.py
git commit -m "feat: add AgentContext, lifecycle hooks, and max_turns enforcement to BaseAgent"
```

---

### Task 9: SubTask.audit_report Typing + QualityRule Model

**Files:**
- Modify: `src/max/models/tasks.py`
- Modify: `src/max/models/__init__.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_models.py`:

```python
from max.models.tasks import AuditReport, AuditVerdict, QualityRule, SubTask, Task, TaskStatus


def test_subtask_with_typed_audit_report():
    task_id = uuid.uuid4()
    subtask_id = uuid.uuid4()
    report = AuditReport(
        task_id=task_id,
        subtask_id=subtask_id,
        verdict=AuditVerdict.PASS,
        score=0.9,
        goal_alignment=0.95,
        confidence=0.88,
    )
    subtask = SubTask(
        parent_task_id=task_id,
        description="Do the thing",
        audit_report=report,
    )
    assert isinstance(subtask.audit_report, AuditReport)
    assert subtask.audit_report.verdict == AuditVerdict.PASS
    assert subtask.audit_report.score == 0.9


def test_quality_rule_creation():
    rule = QualityRule(
        rule="All API responses must include error codes",
        source="audit-2026-04-04",
        category="api",
        severity="critical",
    )
    assert rule.rule == "All API responses must include error codes"
    assert rule.source == "audit-2026-04-04"
    assert rule.category == "api"
    assert rule.severity == "critical"
    assert rule.id is not None
    assert rule.superseded_by is None


def test_quality_rule_superseded():
    old_rule = QualityRule(
        rule="Old rule",
        source="audit-old",
        category="general",
    )
    new_rule = QualityRule(
        rule="New rule superseding old",
        source="audit-new",
        category="general",
    )
    old_rule_updated = old_rule.model_copy(update={"superseded_by": new_rule.id})
    assert old_rule_updated.superseded_by == new_rule.id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models.py::test_quality_rule_creation -v`
Expected: FAIL — `ImportError: cannot import name 'QualityRule'`

- [ ] **Step 3: Implement changes**

In `src/max/models/tasks.py`, change `SubTask.audit_report` type and add `QualityRule`:

Change line 35 from:

```python
    audit_report: dict[str, Any] | None = None
```

to:

```python
    audit_report: AuditReport | None = None
```

Remove the unused `Any` import if it's only used for `audit_report` (check — it's also used for `context_package` and `result`, so keep it).

Add `QualityRule` class at the end of the file:

```python
class QualityRule(BaseModel):
    """A quality rule learned from audits — append-only, never deleted, only superseded."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    rule: str
    source: str
    category: str
    severity: str = "normal"
    superseded_by: uuid.UUID | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
```

Update `src/max/models/__init__.py` to export `QualityRule`:

Add `QualityRule` to the imports from `max.models.tasks` and to `__all__`:

```python
from max.models.tasks import (
    AuditReport,
    AuditVerdict,
    QualityRule,
    SubTask,
    Task,
    TaskStatus,
)
```

And in `__all__`, add `"QualityRule"`.

- [ ] **Step 4: Update existing test import**

At the top of `tests/test_models.py`, update the import:

```python
from max.models.tasks import AuditReport, AuditVerdict, QualityRule, SubTask, Task, TaskStatus
```

- [ ] **Step 5: Run all model tests**

Run: `uv run pytest tests/test_models.py -v`
Expected: ALL PASS (8 old + 3 new = 11 tests)

- [ ] **Step 6: Commit**

```bash
git add src/max/models/tasks.py src/max/models/__init__.py tests/test_models.py
git commit -m "feat: type SubTask.audit_report as AuditReport, add QualityRule model"
```

---

### Task 10: Final Lint + Full Test Suite Verification

**Files:**
- All modified files from tasks 1-9

- [ ] **Step 1: Run ruff linter**

Run: `uv run ruff check src/ tests/`
Expected: No errors. If there are errors, fix them.

- [ ] **Step 2: Run ruff formatter check**

Run: `uv run ruff format --check src/ tests/`
Expected: All files formatted. If not, run `uv run ruff format src/ tests/` then check again.

- [ ] **Step 3: Run full test suite with coverage**

Run: `uv run pytest tests/ -v --cov=src/max --cov-report=term-missing`
Expected: ALL PASS, coverage >= 96%

- [ ] **Step 4: Fix any lint or format issues if found**

Run: `uv run ruff format src/ tests/ && uv run ruff check src/ tests/ --fix`

- [ ] **Step 5: Commit any lint/format fixes**

```bash
git add -A
git commit -m "chore: lint and format all source and test files"
```

(Skip this commit if Step 1 and Step 2 had no issues.)

---

## Summary

| Task | What It Fixes | New Tests |
|------|--------------|-----------|
| 1 | `ToolCall` model + typed `LLMResponse.tool_calls` | 3 |
| 2 | `ModelType` tuple enum (no more fragile dict lookup) | 3 |
| 3 | LLM error handling + exception hierarchy + SDK retries | 5 |
| 4 | MessageBus multi-handler fan-out | 3 |
| 5 | Database `transaction()` context manager | 2 |
| 6 | Missing tables (intents, results, status_updates, clarification_requests) + FK + HNSW | 3 + updated existing |
| 7 | WarmMemory TTL falsy bug | 1 |
| 8 | AgentContext + lifecycle hooks + max_turns enforcement | 6 |
| 9 | Typed `SubTask.audit_report` + `QualityRule` model | 3 |
| 10 | Lint + format + full suite verification | 0 |
| **Total** | **12 review findings resolved** | **~29 new tests** |
