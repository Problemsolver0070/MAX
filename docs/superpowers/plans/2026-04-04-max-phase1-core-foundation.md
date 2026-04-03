# Max Phase 1: Core Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundational infrastructure that every subsequent phase of Max depends on — project structure, configuration, LLM client, message bus, database layer, base agent framework, data models, and tool registry skeleton.

**Architecture:** Modular monolith with clean module boundaries. Each subsystem (LLM, bus, db, agents, tools) is an independent Python package inside `src/max/`. Communication between modules uses typed data models. All I/O is async (asyncio). Local development uses Docker Compose for Redis + PostgreSQL.

**Tech Stack:** Python 3.12+, anthropic SDK 0.88+, asyncpg, redis-py (async), pydantic v2, pytest + pytest-asyncio, Docker Compose, uv (package manager)

---

## File Structure

```
max/
├── pyproject.toml                    # Project metadata, dependencies, tool config
├── .env.example                      # Environment variable template
├── .gitignore
├── docker-compose.yml                # Local dev: Redis + PostgreSQL + pgvector
├── scripts/
│   └── init_db.py                    # Database schema initialization
├── src/
│   └── max/
│       ├── __init__.py               # Package version
│       ├── config.py                 # Centralized configuration (env vars → typed settings)
│       ├── models/
│       │   ├── __init__.py
│       │   ├── messages.py           # Intent, Result, ClarificationRequest, StatusUpdate
│       │   └── tasks.py              # Task, SubTask, AuditReport, QualityRule
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── client.py             # Async Anthropic client wrapper
│       │   └── models.py             # Model enum (OPUS, SONNET) + usage tracking
│       ├── bus/
│       │   ├── __init__.py
│       │   └── message_bus.py        # Redis pub/sub async message bus
│       ├── db/
│       │   ├── __init__.py
│       │   ├── postgres.py           # Async connection pool + query helpers
│       │   ├── redis_store.py        # Warm memory: key-value + expiry
│       │   └── schema.sql            # Table definitions (tasks, anchors, quality_ledger, etc.)
│       ├── agents/
│       │   ├── __init__.py
│       │   └── base.py               # BaseAgent class: lifecycle, LLM call, tool use, state
│       └── tools/
│           ├── __init__.py
│           └── registry.py           # ToolRegistry: register, discover, permission check
└── tests/
    ├── __init__.py
    ├── conftest.py                   # Shared fixtures (db, redis, bus, llm mock)
    ├── test_config.py
    ├── test_models.py
    ├── test_llm_client.py
    ├── test_message_bus.py
    ├── test_postgres.py
    ├── test_redis_store.py
    ├── test_base_agent.py
    └── test_tool_registry.py
```

---

### Task 1: Project Setup

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `src/max/__init__.py`

- [ ] **Step 1: Initialize uv project**

Run:
```bash
cd /home/venu/Desktop/everactive
uv init --lib --name max --python 3.12
```

- [ ] **Step 2: Replace pyproject.toml with Max configuration**

```toml
[project]
name = "max"
version = "0.1.0"
description = "Max — self-evolving autonomous AI agent system"
requires-python = ">=3.12"
dependencies = [
    "anthropic[aiohttp]>=0.88.0",
    "asyncpg>=0.30.0",
    "redis[hiredis]>=5.2.0",
    "pydantic>=2.10.0",
    "pydantic-settings>=2.7.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.25.0",
    "pytest-cov>=6.0.0",
    "ruff>=0.9.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.backends"

[tool.hatch.build.targets.wheel]
packages = ["src/max"]
```

- [ ] **Step 3: Create .env.example**

```env
# Anthropic
ANTHROPIC_API_KEY=sk-ant-xxxxx

# PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=max
POSTGRES_USER=max
POSTGRES_PASSWORD=max_dev_password

# Redis
REDIS_URL=redis://localhost:6379/0

# Max
MAX_LOG_LEVEL=DEBUG
MAX_OWNER_TELEGRAM_ID=
MAX_OWNER_WHATSAPP_ID=
```

- [ ] **Step 4: Create .gitignore**

```gitignore
__pycache__/
*.py[cod]
*.egg-info/
dist/
.eggs/
.env
.venv/
*.db
*.sqlite3
.pytest_cache/
.ruff_cache/
.coverage
htmlcov/
.superpowers/
```

- [ ] **Step 5: Create src/max/__init__.py**

```python
__version__ = "0.1.0"
```

- [ ] **Step 6: Create directory structure**

Run:
```bash
mkdir -p src/max/{models,llm,bus,db,agents,tools}
mkdir -p tests scripts
touch src/max/models/__init__.py src/max/llm/__init__.py src/max/bus/__init__.py
touch src/max/db/__init__.py src/max/agents/__init__.py src/max/tools/__init__.py
touch tests/__init__.py
```

- [ ] **Step 7: Install dependencies**

Run:
```bash
uv sync --all-extras
```
Expected: dependencies install successfully.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml .env.example .gitignore src/ tests/ scripts/
git commit -m "feat: initialize Max project structure and dependencies"
```

---

### Task 2: Configuration Module

**Files:**
- Create: `src/max/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import os
import pytest
from max.config import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("POSTGRES_HOST", "db.example.com")
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    monkeypatch.setenv("POSTGRES_DB", "max_test")
    monkeypatch.setenv("POSTGRES_USER", "testuser")
    monkeypatch.setenv("POSTGRES_PASSWORD", "testpass")
    monkeypatch.setenv("REDIS_URL", "redis://redis.example.com:6380/1")
    monkeypatch.setenv("MAX_LOG_LEVEL", "WARNING")

    settings = Settings()
    assert settings.anthropic_api_key == "sk-ant-test-key"
    assert settings.postgres_host == "db.example.com"
    assert settings.postgres_port == 5433
    assert settings.postgres_db == "max_test"
    assert settings.redis_url == "redis://redis.example.com:6380/1"
    assert settings.max_log_level == "WARNING"


def test_settings_defaults(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("POSTGRES_PASSWORD", "testpass")
    settings = Settings()
    assert settings.postgres_host == "localhost"
    assert settings.postgres_port == 5432
    assert settings.postgres_db == "max"
    assert settings.max_log_level == "DEBUG"


def test_postgres_dsn(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("POSTGRES_USER", "max")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    monkeypatch.setenv("POSTGRES_HOST", "localhost")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_DB", "max")
    settings = Settings()
    assert settings.postgres_dsn == "postgresql://max:secret@localhost:5432/max"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'max.config'`

- [ ] **Step 3: Write the implementation**

```python
# src/max/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Anthropic
    anthropic_api_key: str

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "max"
    postgres_user: str = "max"
    postgres_password: str

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Max
    max_log_level: str = "DEBUG"
    max_owner_telegram_id: str = ""
    max_owner_whatsapp_id: str = ""

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/max/config.py tests/test_config.py
git commit -m "feat: add configuration module with env var loading"
```

---

### Task 3: Docker Compose for Local Development

**Files:**
- Create: `docker-compose.yml`

- [ ] **Step 1: Create docker-compose.yml**

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_DB: max
      POSTGRES_USER: max
      POSTGRES_PASSWORD: max_dev_password
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U max -d max"]
      interval: 5s
      timeout: 3s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  pgdata:
  redisdata:
```

- [ ] **Step 2: Start services**

Run: `docker compose up -d`
Expected: Both containers start and pass health checks.

- [ ] **Step 3: Verify connectivity**

Run:
```bash
docker compose exec postgres pg_isready -U max -d max && echo "PostgreSQL OK"
docker compose exec redis redis-cli ping && echo "Redis OK"
```
Expected: `PostgreSQL OK` and `PONG` then `Redis OK`

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add Docker Compose for local dev (PostgreSQL + pgvector, Redis)"
```

---

### Task 4: Data Models

**Files:**
- Create: `src/max/models/messages.py`
- Create: `src/max/models/tasks.py`
- Create: `src/max/models/__init__.py` (update)
- Create: `tests/test_models.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_models.py
import uuid
from datetime import datetime, timezone

from max.models.messages import Intent, Result, ClarificationRequest, StatusUpdate, Priority
from max.models.tasks import Task, SubTask, TaskStatus, AuditReport, AuditVerdict


def test_intent_creation():
    intent = Intent(
        user_message="Deploy the app to staging",
        source_platform="telegram",
        goal_anchor="Deploy the app to staging",
    )
    assert intent.user_message == "Deploy the app to staging"
    assert intent.source_platform == "telegram"
    assert intent.goal_anchor == "Deploy the app to staging"
    assert intent.priority == Priority.NORMAL
    assert intent.id is not None


def test_result_creation():
    result = Result(
        task_id=uuid.uuid4(),
        content="Deployment complete. App is live at staging.example.com",
        artifacts=["/logs/deploy.log"],
        confidence=0.95,
    )
    assert result.confidence == 0.95
    assert len(result.artifacts) == 1


def test_clarification_request():
    req = ClarificationRequest(
        task_id=uuid.uuid4(),
        question="Which staging environment — US or EU?",
        options=["US staging", "EU staging"],
    )
    assert len(req.options) == 2


def test_status_update():
    update = StatusUpdate(
        task_id=uuid.uuid4(),
        message="Sub-agent 3/5 completed. Running auditor.",
        progress=0.6,
    )
    assert update.progress == 0.6


def test_task_creation():
    task = Task(
        goal_anchor="Deploy the app to staging",
        source_intent_id=uuid.uuid4(),
    )
    assert task.status == TaskStatus.PENDING
    assert task.subtasks == []
    assert task.created_at is not None


def test_subtask_creation():
    subtask = SubTask(
        parent_task_id=uuid.uuid4(),
        description="Run database migrations",
        assigned_tools=["shell.execute", "git.pull"],
    )
    assert subtask.status == TaskStatus.PENDING
    assert len(subtask.assigned_tools) == 2


def test_audit_report():
    report = AuditReport(
        task_id=uuid.uuid4(),
        subtask_id=uuid.uuid4(),
        verdict=AuditVerdict.PASS,
        score=0.92,
        goal_alignment=0.95,
        confidence=0.88,
        issues=[],
    )
    assert report.verdict == AuditVerdict.PASS
    assert report.issues == []


def test_audit_report_with_issues():
    report = AuditReport(
        task_id=uuid.uuid4(),
        subtask_id=uuid.uuid4(),
        verdict=AuditVerdict.FAIL,
        score=0.4,
        goal_alignment=0.6,
        confidence=0.9,
        issues=[
            {"severity": "critical", "description": "Missing error handling", "suggestion": "Add try/except"}
        ],
    )
    assert report.verdict == AuditVerdict.FAIL
    assert len(report.issues) == 1
    assert report.issues[0]["severity"] == "critical"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL with import errors

- [ ] **Step 3: Write messages.py**

```python
# src/max/models/messages.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


class Priority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class Intent(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    user_message: str
    source_platform: str
    goal_anchor: str
    priority: Priority = Priority.NORMAL
    attachments: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Result(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    task_id: uuid.UUID
    content: str
    artifacts: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ClarificationRequest(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    task_id: uuid.UUID
    question: str
    options: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StatusUpdate(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    task_id: uuid.UUID
    message: str
    progress: float = Field(ge=0.0, le=1.0, default=0.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 4: Write tasks.py**

```python
# src/max/models/tasks.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
    PENDING = "pending"
    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    AUDITING = "auditing"
    FIXING = "fixing"
    COMPLETED = "completed"
    FAILED = "failed"


class AuditVerdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    CONDITIONAL = "conditional"


class SubTask(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    parent_task_id: uuid.UUID
    description: str
    status: TaskStatus = TaskStatus.PENDING
    assigned_tools: list[str] = Field(default_factory=list)
    context_package: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    audit_report: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


class Task(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    goal_anchor: str
    source_intent_id: uuid.UUID
    status: TaskStatus = TaskStatus.PENDING
    subtasks: list[SubTask] = Field(default_factory=list)
    quality_criteria: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


class AuditReport(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    task_id: uuid.UUID
    subtask_id: uuid.UUID
    verdict: AuditVerdict
    score: float = Field(ge=0.0, le=1.0)
    goal_alignment: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    issues: list[dict[str, str]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 5: Update models __init__.py**

```python
# src/max/models/__init__.py
from max.models.messages import (
    ClarificationRequest,
    Intent,
    Priority,
    Result,
    StatusUpdate,
)
from max.models.tasks import (
    AuditReport,
    AuditVerdict,
    SubTask,
    Task,
    TaskStatus,
)

__all__ = [
    "AuditReport",
    "AuditVerdict",
    "ClarificationRequest",
    "Intent",
    "Priority",
    "Result",
    "StatusUpdate",
    "SubTask",
    "Task",
    "TaskStatus",
]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: 8 passed

- [ ] **Step 7: Commit**

```bash
git add src/max/models/ tests/test_models.py
git commit -m "feat: add core data models (Intent, Task, SubTask, AuditReport)"
```

---

### Task 5: LLM Client

**Files:**
- Create: `src/max/llm/client.py`
- Create: `src/max/llm/models.py`
- Create: `src/max/llm/__init__.py` (update)
- Create: `tests/test_llm_client.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_llm_client.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from max.llm.models import ModelType
from max.llm.client import LLMClient


def test_model_type_ids():
    assert ModelType.OPUS.model_id == "claude-opus-4-6"
    assert ModelType.SONNET.model_id == "claude-sonnet-4-6"


@pytest.fixture
def llm_client():
    return LLMClient(api_key="sk-ant-test-key")


def test_client_creation(llm_client):
    assert llm_client is not None
    assert llm_client.default_model == ModelType.OPUS


@pytest.mark.asyncio
async def test_client_complete(llm_client):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text="Hello back!")]
    mock_response.usage = MagicMock(input_tokens=10, output_tokens=5)
    mock_response.model = "claude-opus-4-6"
    mock_response.stop_reason = "end_turn"

    with patch.object(
        llm_client._client.messages, "create", new_callable=AsyncMock, return_value=mock_response
    ):
        response = await llm_client.complete(
            messages=[{"role": "user", "content": "Hello"}],
            system_prompt="You are Max.",
        )
        assert response.text == "Hello back!"
        assert response.input_tokens == 10
        assert response.output_tokens == 5


@pytest.mark.asyncio
async def test_client_complete_with_model_override(llm_client):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text="Routed.")]
    mock_response.usage = MagicMock(input_tokens=8, output_tokens=3)
    mock_response.model = "claude-sonnet-4-6"
    mock_response.stop_reason = "end_turn"

    with patch.object(
        llm_client._client.messages, "create", new_callable=AsyncMock, return_value=mock_response
    ) as mock_create:
        response = await llm_client.complete(
            messages=[{"role": "user", "content": "Route this"}],
            model=ModelType.SONNET,
        )
        assert response.text == "Routed."
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["model"] == "claude-sonnet-4-6"


def test_usage_tracking(llm_client):
    assert llm_client.total_input_tokens == 0
    assert llm_client.total_output_tokens == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_llm_client.py -v`
Expected: FAIL with import errors

- [ ] **Step 3: Write models.py**

```python
# src/max/llm/models.py
from __future__ import annotations

from enum import Enum

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


class LLMResponse(BaseModel):
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    stop_reason: str
    tool_calls: list[dict] | None = None
```

- [ ] **Step 4: Write client.py**

```python
# src/max/llm/client.py
from __future__ import annotations

from typing import Any

from anthropic import AsyncAnthropic

from max.llm.models import LLMResponse, ModelType


class LLMClient:
    def __init__(self, api_key: str, default_model: ModelType = ModelType.OPUS):
        self._client = AsyncAnthropic(api_key=api_key)
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

        response = await self._client.messages.create(**kwargs)

        text_parts = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    {"id": block.id, "name": block.name, "input": block.input}
                )

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

- [ ] **Step 5: Update llm __init__.py**

```python
# src/max/llm/__init__.py
from max.llm.client import LLMClient
from max.llm.models import LLMResponse, ModelType

__all__ = ["LLMClient", "LLMResponse", "ModelType"]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm_client.py -v`
Expected: 5 passed

- [ ] **Step 7: Commit**

```bash
git add src/max/llm/ tests/test_llm_client.py
git commit -m "feat: add async LLM client with model selection and usage tracking"
```

---

### Task 6: Redis Message Bus

**Files:**
- Create: `src/max/bus/message_bus.py`
- Create: `src/max/bus/__init__.py` (update)
- Create: `tests/test_message_bus.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_message_bus.py
import asyncio
import pytest
import redis.asyncio as aioredis

from max.bus.message_bus import MessageBus


@pytest.fixture
async def redis_client():
    client = aioredis.from_url("redis://localhost:6379/15")  # test DB
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def bus(redis_client):
    bus = MessageBus(redis_client)
    yield bus
    await bus.close()


@pytest.mark.asyncio
async def test_publish_and_subscribe(bus):
    received = []

    async def handler(channel: str, data: dict):
        received.append((channel, data))

    await bus.subscribe("test.channel", handler)
    await bus.start_listening()
    await asyncio.sleep(0.1)

    await bus.publish("test.channel", {"type": "greeting", "text": "hello"})
    await asyncio.sleep(0.3)

    await bus.stop_listening()
    assert len(received) == 1
    assert received[0][0] == "test.channel"
    assert received[0][1]["text"] == "hello"


@pytest.mark.asyncio
async def test_multiple_channels(bus):
    received_a = []
    received_b = []

    async def handler_a(channel: str, data: dict):
        received_a.append(data)

    async def handler_b(channel: str, data: dict):
        received_b.append(data)

    await bus.subscribe("channel.a", handler_a)
    await bus.subscribe("channel.b", handler_b)
    await bus.start_listening()
    await asyncio.sleep(0.1)

    await bus.publish("channel.a", {"msg": "for_a"})
    await bus.publish("channel.b", {"msg": "for_b"})
    await asyncio.sleep(0.3)

    await bus.stop_listening()
    assert len(received_a) == 1
    assert received_a[0]["msg"] == "for_a"
    assert len(received_b) == 1
    assert received_b[0]["msg"] == "for_b"


@pytest.mark.asyncio
async def test_unsubscribe(bus):
    received = []

    async def handler(channel: str, data: dict):
        received.append(data)

    await bus.subscribe("test.unsub", handler)
    await bus.start_listening()
    await asyncio.sleep(0.1)

    await bus.publish("test.unsub", {"n": 1})
    await asyncio.sleep(0.2)

    await bus.unsubscribe("test.unsub")
    await bus.publish("test.unsub", {"n": 2})
    await asyncio.sleep(0.2)

    await bus.stop_listening()
    assert len(received) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_message_bus.py -v`
Expected: FAIL with import errors

- [ ] **Step 3: Write the implementation**

```python
# src/max/bus/message_bus.py
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
        self._handlers: dict[str, Handler] = {}
        self._listen_task: asyncio.Task | None = None

    async def subscribe(self, channel: str, handler: Handler) -> None:
        self._handlers[channel] = handler
        await self._pubsub.subscribe(channel)
        logger.debug("Subscribed to %s", channel)

    async def unsubscribe(self, channel: str) -> None:
        self._handlers.pop(channel, None)
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
                handler = self._handlers.get(channel)
                if handler is None:
                    continue
                try:
                    data = json.loads(message["data"])
                    await handler(channel, data)
                except Exception:
                    logger.exception("Error in handler for %s", channel)
        except asyncio.CancelledError:
            raise

    async def close(self) -> None:
        await self.stop_listening()
        await self._pubsub.aclose()
```

- [ ] **Step 4: Update bus __init__.py**

```python
# src/max/bus/__init__.py
from max.bus.message_bus import MessageBus

__all__ = ["MessageBus"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_message_bus.py -v`
Expected: 3 passed (requires Redis running via `docker compose up -d`)

- [ ] **Step 6: Commit**

```bash
git add src/max/bus/ tests/test_message_bus.py
git commit -m "feat: add async Redis pub/sub message bus"
```

---

### Task 7: Database Layer (PostgreSQL)

**Files:**
- Create: `src/max/db/schema.sql`
- Create: `src/max/db/postgres.py`
- Create: `src/max/db/__init__.py` (update)
- Create: `scripts/init_db.py`
- Create: `tests/test_postgres.py`

- [ ] **Step 1: Write the schema**

```sql
-- src/max/db/schema.sql

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Tasks
CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY,
    goal_anchor TEXT NOT NULL,
    source_intent_id UUID NOT NULL,
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
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_postgres.py
import uuid
import pytest

from max.db.postgres import Database


@pytest.fixture
async def db():
    database = Database(dsn="postgresql://max:max_dev_password@localhost:5432/max")
    await database.connect()
    # Clean test data
    await database.execute("DELETE FROM audit_reports")
    await database.execute("DELETE FROM subtasks")
    await database.execute("DELETE FROM tasks")
    yield database
    await database.execute("DELETE FROM audit_reports")
    await database.execute("DELETE FROM subtasks")
    await database.execute("DELETE FROM tasks")
    await database.close()


@pytest.mark.asyncio
async def test_connect_and_ping(db):
    row = await db.fetchone("SELECT 1 AS val")
    assert row["val"] == 1


@pytest.mark.asyncio
async def test_insert_and_fetch_task(db):
    task_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO tasks (id, goal_anchor, source_intent_id, status) VALUES ($1, $2, $3, $4)",
        task_id, "Test goal", intent_id, "pending",
    )
    row = await db.fetchone("SELECT * FROM tasks WHERE id = $1", task_id)
    assert row["goal_anchor"] == "Test goal"
    assert row["status"] == "pending"


@pytest.mark.asyncio
async def test_fetchall(db):
    for i in range(3):
        await db.execute(
            "INSERT INTO tasks (id, goal_anchor, source_intent_id) VALUES ($1, $2, $3)",
            uuid.uuid4(), f"Goal {i}", uuid.uuid4(),
        )
    rows = await db.fetchall("SELECT * FROM tasks ORDER BY created_at")
    assert len(rows) >= 3
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_postgres.py -v`
Expected: FAIL with import errors

- [ ] **Step 4: Write postgres.py**

```python
# src/max/db/postgres.py
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class Database:
    def __init__(self, dsn: str, min_pool_size: int = 2, max_pool_size: int = 10):
        self._dsn = dsn
        self._min_pool_size = min_pool_size
        self._max_pool_size = max_pool_size
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=self._min_pool_size,
            max_size=self._max_pool_size,
        )
        logger.info("Connected to PostgreSQL")

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            logger.info("Disconnected from PostgreSQL")

    async def init_schema(self) -> None:
        schema_sql = SCHEMA_PATH.read_text()
        async with self._pool.acquire() as conn:
            await conn.execute(schema_sql)
        logger.info("Database schema initialized")

    async def execute(self, query: str, *args: Any) -> str:
        async with self._pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def fetchone(self, query: str, *args: Any) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None

    async def fetchall(self, query: str, *args: Any) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]
```

- [ ] **Step 5: Write init_db.py script**

```python
# scripts/init_db.py
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from max.config import Settings
from max.db.postgres import Database


async def main():
    settings = Settings()
    db = Database(dsn=settings.postgres_dsn)
    await db.connect()
    await db.init_schema()
    print("Schema initialized successfully.")
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 6: Initialize the database schema**

Run:
```bash
cp .env.example .env
# Edit .env to set ANTHROPIC_API_KEY (can be placeholder for now)
uv run python scripts/init_db.py
```
Expected: `Schema initialized successfully.`

- [ ] **Step 7: Update db __init__.py**

```python
# src/max/db/__init__.py
from max.db.postgres import Database

__all__ = ["Database"]
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/test_postgres.py -v`
Expected: 3 passed (requires PostgreSQL running via `docker compose up -d` and schema initialized)

- [ ] **Step 9: Commit**

```bash
git add src/max/db/ scripts/init_db.py tests/test_postgres.py
git commit -m "feat: add PostgreSQL database layer with schema and connection pool"
```

---

### Task 8: Redis Warm Memory Store

**Files:**
- Create: `src/max/db/redis_store.py`
- Create: `tests/test_redis_store.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_redis_store.py
import pytest
import redis.asyncio as aioredis

from max.db.redis_store import WarmMemory


@pytest.fixture
async def redis_client():
    client = aioredis.from_url("redis://localhost:6379/14")  # test DB
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def warm(redis_client):
    return WarmMemory(redis_client)


@pytest.mark.asyncio
async def test_set_and_get(warm):
    await warm.set("user:prefs", {"tone": "direct", "detail": "high"})
    result = await warm.get("user:prefs")
    assert result["tone"] == "direct"
    assert result["detail"] == "high"


@pytest.mark.asyncio
async def test_get_missing_key(warm):
    result = await warm.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_set_with_ttl(warm):
    await warm.set("temp:data", {"value": 42}, ttl_seconds=1)
    result = await warm.get("temp:data")
    assert result["value"] == 42


@pytest.mark.asyncio
async def test_delete(warm):
    await warm.set("to:delete", {"data": True})
    await warm.delete("to:delete")
    result = await warm.get("to:delete")
    assert result is None


@pytest.mark.asyncio
async def test_set_state_document(warm):
    state = {
        "active_tasks": [],
        "pending_decisions": [],
        "system_health": "ok",
    }
    await warm.set("coordinator:state", state)
    result = await warm.get("coordinator:state")
    assert result["system_health"] == "ok"


@pytest.mark.asyncio
async def test_list_push_and_range(warm):
    await warm.list_push("events", {"type": "task_started", "id": "1"})
    await warm.list_push("events", {"type": "task_completed", "id": "2"})
    items = await warm.list_range("events", 0, -1)
    assert len(items) == 2
    assert items[0]["type"] == "task_started"
    assert items[1]["type"] == "task_completed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_redis_store.py -v`
Expected: FAIL with import errors

- [ ] **Step 3: Write the implementation**

```python
# src/max/db/redis_store.py
from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

PREFIX = "max:"


class WarmMemory:
    def __init__(self, redis_client: aioredis.Redis):
        self._redis = redis_client

    def _key(self, key: str) -> str:
        return f"{PREFIX}{key}"

    async def set(self, key: str, value: dict[str, Any], ttl_seconds: int | None = None) -> None:
        payload = json.dumps(value)
        if ttl_seconds:
            await self._redis.setex(self._key(key), ttl_seconds, payload)
        else:
            await self._redis.set(self._key(key), payload)

    async def get(self, key: str) -> dict[str, Any] | None:
        raw = await self._redis.get(self._key(key))
        if raw is None:
            return None
        return json.loads(raw)

    async def delete(self, key: str) -> None:
        await self._redis.delete(self._key(key))

    async def list_push(self, key: str, value: dict[str, Any]) -> None:
        payload = json.dumps(value)
        await self._redis.rpush(self._key(key), payload)

    async def list_range(self, key: str, start: int, stop: int) -> list[dict[str, Any]]:
        raw_items = await self._redis.lrange(self._key(key), start, stop)
        return [json.loads(item) for item in raw_items]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_redis_store.py -v`
Expected: 6 passed

- [ ] **Step 5: Update db __init__.py**

```python
# src/max/db/__init__.py
from max.db.postgres import Database
from max.db.redis_store import WarmMemory

__all__ = ["Database", "WarmMemory"]
```

- [ ] **Step 6: Commit**

```bash
git add src/max/db/redis_store.py tests/test_redis_store.py src/max/db/__init__.py
git commit -m "feat: add Redis warm memory store with key-value and list operations"
```

---

### Task 9: Base Agent Class

**Files:**
- Create: `src/max/agents/base.py`
- Create: `src/max/agents/__init__.py` (update)
- Create: `tests/test_base_agent.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_base_agent.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from max.agents.base import BaseAgent, AgentConfig
from max.llm.models import ModelType, LLMResponse


class TestAgent(BaseAgent):
    async def run(self, input_data: dict) -> dict:
        response = await self.think(
            messages=[{"role": "user", "content": input_data["message"]}],
        )
        return {"response": response.text}


@pytest.fixture
def mock_llm():
    client = MagicMock()
    client.complete = AsyncMock(
        return_value=LLMResponse(
            text="I'm a test agent.",
            input_tokens=10,
            output_tokens=5,
            model="claude-opus-4-6",
            stop_reason="end_turn",
        )
    )
    return client


@pytest.fixture
def agent(mock_llm):
    config = AgentConfig(
        name="test-agent",
        model=ModelType.OPUS,
        system_prompt="You are a test agent.",
    )
    return TestAgent(config=config, llm=mock_llm)


def test_agent_creation(agent):
    assert agent.config.name == "test-agent"
    assert agent.config.model == ModelType.OPUS


@pytest.mark.asyncio
async def test_agent_think(agent, mock_llm):
    response = await agent.think(
        messages=[{"role": "user", "content": "hello"}],
    )
    assert response.text == "I'm a test agent."
    mock_llm.complete.assert_called_once()
    call_kwargs = mock_llm.complete.call_args[1]
    assert call_kwargs["system_prompt"] == "You are a test agent."
    assert call_kwargs["model"] == ModelType.OPUS


@pytest.mark.asyncio
async def test_agent_run(agent):
    result = await agent.run({"message": "hello"})
    assert result["response"] == "I'm a test agent."


def test_agent_config_defaults():
    config = AgentConfig(name="minimal", system_prompt="Be helpful.")
    assert config.model == ModelType.OPUS
    assert config.max_turns == 10
    assert config.tools == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_base_agent.py -v`
Expected: FAIL with import errors

- [ ] **Step 3: Write the implementation**

```python
# src/max/agents/base.py
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


class BaseAgent(ABC):
    def __init__(self, config: AgentConfig, llm: LLMClient):
        self.config = config
        self.llm = llm
        self.agent_id = str(uuid.uuid4())
        self._turn_count = 0

    async def think(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        model: ModelType | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self._turn_count += 1
        logger.debug(
            "[%s] Turn %d: sending %d messages",
            self.config.name,
            self._turn_count,
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
    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        ...

    def reset(self) -> None:
        self._turn_count = 0
```

- [ ] **Step 4: Update agents __init__.py**

```python
# src/max/agents/__init__.py
from max.agents.base import AgentConfig, BaseAgent

__all__ = ["AgentConfig", "BaseAgent"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_base_agent.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add src/max/agents/ tests/test_base_agent.py
git commit -m "feat: add base agent class with LLM integration and config"
```

---

### Task 10: Tool Registry

**Files:**
- Create: `src/max/tools/registry.py`
- Create: `src/max/tools/__init__.py` (update)
- Create: `tests/test_tool_registry.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_tool_registry.py
import pytest

from max.tools.registry import ToolRegistry, ToolDefinition


@pytest.fixture
def registry():
    return ToolRegistry()


def test_register_tool(registry):
    tool = ToolDefinition(
        tool_id="shell.execute",
        category="code",
        description="Execute a shell command",
        permissions=["system.shell"],
    )
    registry.register(tool)
    assert registry.get("shell.execute") is not None


def test_get_missing_tool(registry):
    assert registry.get("nonexistent") is None


def test_list_by_category(registry):
    registry.register(ToolDefinition(
        tool_id="file.read", category="code", description="Read a file", permissions=["fs.read"],
    ))
    registry.register(ToolDefinition(
        tool_id="file.write", category="code", description="Write a file", permissions=["fs.write"],
    ))
    registry.register(ToolDefinition(
        tool_id="browser.navigate", category="web", description="Navigate to URL", permissions=["network"],
    ))
    code_tools = registry.list_by_category("code")
    assert len(code_tools) == 2
    web_tools = registry.list_by_category("web")
    assert len(web_tools) == 1


def test_check_permissions(registry):
    registry.register(ToolDefinition(
        tool_id="shell.execute",
        category="code",
        description="Execute a shell command",
        permissions=["system.shell"],
    ))
    assert registry.check_permission("shell.execute", allowed=["system.shell"])
    assert not registry.check_permission("shell.execute", allowed=["fs.read"])


def test_list_all(registry):
    registry.register(ToolDefinition(
        tool_id="a", category="x", description="A", permissions=[],
    ))
    registry.register(ToolDefinition(
        tool_id="b", category="y", description="B", permissions=[],
    ))
    assert len(registry.list_all()) == 2


def test_to_anthropic_tools(registry):
    registry.register(ToolDefinition(
        tool_id="file.read",
        category="code",
        description="Read a file from the filesystem",
        permissions=["fs.read"],
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File path"}},
            "required": ["path"],
        },
    ))
    tools = registry.to_anthropic_tools(["file.read"])
    assert len(tools) == 1
    assert tools[0]["name"] == "file.read"
    assert tools[0]["description"] == "Read a file from the filesystem"
    assert tools[0]["input_schema"]["properties"]["path"]["type"] == "string"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tool_registry.py -v`
Expected: FAIL with import errors

- [ ] **Step 3: Write the implementation**

```python
# src/max/tools/registry.py
from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ToolDefinition(BaseModel):
    tool_id: str
    category: str
    description: str
    permissions: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    cost_tier: str = "low"
    reliability: float = 1.0
    avg_latency_ms: int = 0


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.tool_id] = tool
        logger.debug("Registered tool: %s", tool.tool_id)

    def get(self, tool_id: str) -> ToolDefinition | None:
        return self._tools.get(tool_id)

    def list_all(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def list_by_category(self, category: str) -> list[ToolDefinition]:
        return [t for t in self._tools.values() if t.category == category]

    def check_permission(self, tool_id: str, allowed: list[str]) -> bool:
        tool = self._tools.get(tool_id)
        if tool is None:
            return False
        return all(perm in allowed for perm in tool.permissions)

    def to_anthropic_tools(self, tool_ids: list[str]) -> list[dict[str, Any]]:
        result = []
        for tool_id in tool_ids:
            tool = self._tools.get(tool_id)
            if tool is None:
                continue
            result.append({
                "name": tool.tool_id,
                "description": tool.description,
                "input_schema": tool.input_schema,
            })
        return result
```

- [ ] **Step 4: Update tools __init__.py**

```python
# src/max/tools/__init__.py
from max.tools.registry import ToolDefinition, ToolRegistry

__all__ = ["ToolDefinition", "ToolRegistry"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_tool_registry.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add src/max/tools/ tests/test_tool_registry.py
git commit -m "feat: add tool registry with permissions and Anthropic format conversion"
```

---

### Task 11: Test Fixtures & Integration Smoke Test

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write shared test fixtures**

```python
# tests/conftest.py
import pytest
import redis.asyncio as aioredis

from max.config import Settings
from max.db.postgres import Database
from max.db.redis_store import WarmMemory
from max.bus.message_bus import MessageBus


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("POSTGRES_PASSWORD", "max_dev_password")
    return Settings()


@pytest.fixture
async def db(settings):
    database = Database(dsn=settings.postgres_dsn)
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def redis_client():
    client = aioredis.from_url("redis://localhost:6379/15")
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def warm_memory(redis_client):
    return WarmMemory(redis_client)


@pytest.fixture
async def bus(redis_client):
    b = MessageBus(redis_client)
    yield b
    await b.close()
```

- [ ] **Step 2: Write the integration smoke test**

```python
# tests/test_integration.py
import asyncio
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from max.config import Settings
from max.llm.client import LLMClient
from max.llm.models import ModelType, LLMResponse
from max.bus.message_bus import MessageBus
from max.db.redis_store import WarmMemory
from max.agents.base import BaseAgent, AgentConfig
from max.tools.registry import ToolRegistry, ToolDefinition
from max.models import Intent, Task, TaskStatus, Priority


class EchoAgent(BaseAgent):
    async def run(self, input_data: dict) -> dict:
        response = await self.think(
            messages=[{"role": "user", "content": input_data["message"]}],
        )
        return {"response": response.text}


@pytest.mark.asyncio
async def test_full_pipeline_smoke(db, warm_memory, bus):
    """Smoke test: config → models → bus → warm memory → db → agent → tool registry."""

    # 1. Create an intent (simulating Communicator receiving a message)
    intent = Intent(
        user_message="Write a Python hello world script",
        source_platform="telegram",
        goal_anchor="Write a Python hello world script",
        priority=Priority.NORMAL,
    )
    assert intent.id is not None

    # 2. Create a task from the intent (simulating Coordinator)
    task = Task(
        goal_anchor=intent.goal_anchor,
        source_intent_id=intent.id,
    )

    # 3. Persist task to PostgreSQL
    await db.execute(
        "INSERT INTO tasks (id, goal_anchor, source_intent_id, status) VALUES ($1, $2, $3, $4)",
        task.id, task.goal_anchor, task.source_intent_id, task.status.value,
    )
    row = await db.fetchone("SELECT * FROM tasks WHERE id = $1", task.id)
    assert row["goal_anchor"] == "Write a Python hello world script"

    # 4. Store coordinator state in warm memory
    state = {"active_tasks": [str(task.id)], "system_health": "ok"}
    await warm_memory.set("coordinator:state", state)
    retrieved_state = await warm_memory.get("coordinator:state")
    assert str(task.id) in retrieved_state["active_tasks"]

    # 5. Publish task event on message bus
    received = []

    async def on_task(channel, data):
        received.append(data)

    await bus.subscribe("tasks.new", on_task)
    await bus.start_listening()
    await asyncio.sleep(0.1)
    await bus.publish("tasks.new", {"task_id": str(task.id), "goal": task.goal_anchor})
    await asyncio.sleep(0.3)
    await bus.stop_listening()
    assert len(received) == 1
    assert received[0]["goal"] == "Write a Python hello world script"

    # 6. Create a mock LLM and run an agent
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.complete = AsyncMock(
        return_value=LLMResponse(
            text='print("Hello, World!")',
            input_tokens=50,
            output_tokens=10,
            model="claude-opus-4-6",
            stop_reason="end_turn",
        )
    )
    agent = EchoAgent(
        config=AgentConfig(name="code-writer", system_prompt="Write code."),
        llm=mock_llm,
    )
    result = await agent.run({"message": task.goal_anchor})
    assert "Hello, World!" in result["response"]

    # 7. Register and look up a tool
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        tool_id="file.write",
        category="code",
        description="Write content to a file",
        permissions=["fs.write"],
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    ))
    tools = registry.to_anthropic_tools(["file.write"])
    assert len(tools) == 1
    assert tools[0]["name"] == "file.write"
```

- [ ] **Step 3: Run the full test suite**

Run: `uv run pytest tests/ -v --tb=short`
Expected: All tests pass (requires Docker Compose services running)

- [ ] **Step 4: Run linter**

Run: `uv run ruff check src/ tests/`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/test_integration.py
git commit -m "feat: add test fixtures and integration smoke test for core foundation"
```

---

### Task 12: Final Cleanup & Phase 1 Complete

- [ ] **Step 1: Run full test suite with coverage**

Run: `uv run pytest tests/ -v --cov=max --cov-report=term-missing`
Expected: All tests pass, coverage for core modules visible.

- [ ] **Step 2: Lint and format**

Run:
```bash
uv run ruff check src/ tests/ --fix
uv run ruff format src/ tests/
```
Expected: Clean output.

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "chore: Phase 1 complete — core foundation with all tests passing"
```
