# Phase 5: Quality Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Insert a Quality Gate between subtask execution and result delivery — every output is audited before reaching the user.

**Architecture:** Post-execution audit via QualityDirectorAgent (persistent) that spawns ephemeral AuditorAgents per subtask. Blind audit protocol enforced at the type level. Fix loop re-executes failed subtasks up to `quality_max_fix_attempts` times. Append-only Quality Ledger records all verdicts, rules, and patterns. RuleEngine learns from failures and successes.

**Tech Stack:** Python 3.12+, asyncio, Pydantic v2, asyncpg (PostgreSQL), Redis (bus), pytest-asyncio, ruff

---

## File Structure

```
New files:
  src/max/quality/__init__.py           — package exports
  src/max/quality/models.py             — QualityPattern, AuditRequest, AuditResponse, SubtaskAuditItem, SubtaskVerdict, FixInstruction
  src/max/quality/store.py              — QualityStore (async CRUD for audit reports, ledger, rules, patterns)
  src/max/quality/auditor.py            — AuditorAgent (ephemeral, blind audit)
  src/max/quality/director.py           — QualityDirectorAgent (persistent, audit lifecycle)
  src/max/quality/rules.py              — RuleEngine (rule extraction, supersession, pattern extraction)
  src/max/db/migrations/005_quality_gate.sql — new tables + ALTER

  tests/test_quality_models.py          — model validation tests
  tests/test_quality_store.py           — QualityStore CRUD (mocked DB)
  tests/test_auditor.py                 — AuditorAgent tests
  tests/test_quality_director.py        — QualityDirectorAgent tests
  tests/test_rule_engine.py             — RuleEngine tests
  tests/test_quality_integration.py     — full pipeline with audit

Modified files:
  src/max/config.py                     — add Quality Gate settings
  src/max/db/schema.sql                 — append Phase 5 section
  src/max/command/orchestrator.py       — add audit.request + on_audit_complete + fix loop
  tests/test_config.py                  — add test_quality_settings_defaults
  tests/test_postgres.py                — add Phase 5 table existence tests
```

---

### Task 1: Config settings + DB migration

**Files:**
- Modify: `src/max/config.py:71` (add after command chain block)
- Create: `src/max/db/migrations/005_quality_gate.sql`
- Modify: `src/max/db/schema.sql` (append Phase 5 section)
- Modify: `tests/test_config.py` (add quality settings test)
- Modify: `tests/test_postgres.py` (add Phase 5 table tests)

- [ ] **Step 1: Write failing test for quality config defaults**

In `tests/test_config.py`, add at end of file:

```python
def test_quality_gate_settings_defaults(settings):
    assert settings.quality_director_model == "claude-opus-4-6"
    assert settings.auditor_model == "claude-opus-4-6"
    assert settings.quality_max_fix_attempts == 2
    assert settings.quality_audit_timeout_seconds == 120
    assert settings.quality_pass_threshold == 0.7
    assert settings.quality_high_score_threshold == 0.9
    assert settings.quality_max_rules_per_audit == 5
    assert settings.quality_max_recent_verdicts == 50
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_config.py::test_quality_gate_settings_defaults -v`
Expected: FAIL with AttributeError

- [ ] **Step 3: Add Quality Gate settings to config.py**

In `src/max/config.py`, add after line 71 (after `worker_timeout_seconds`):

```python
    # Quality Gate
    quality_director_model: str = "claude-opus-4-6"
    auditor_model: str = "claude-opus-4-6"
    quality_max_fix_attempts: int = 2
    quality_audit_timeout_seconds: int = 120
    quality_pass_threshold: float = 0.7
    quality_high_score_threshold: float = 0.9
    quality_max_rules_per_audit: int = 5
    quality_max_recent_verdicts: int = 50
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_config.py::test_quality_gate_settings_defaults -v`
Expected: PASS

- [ ] **Step 5: Create DB migration file**

Create `src/max/db/migrations/005_quality_gate.sql`:

```sql
-- Phase 5: Quality Gate
-- New tables: quality_rules, quality_patterns
-- ALTER: audit_reports (fix_instructions, strengths, fix_attempt)

CREATE TABLE IF NOT EXISTS quality_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule TEXT NOT NULL,
    source TEXT NOT NULL,
    category VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL DEFAULT 'normal',
    superseded_by UUID REFERENCES quality_rules(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quality_rules_category ON quality_rules(category);
CREATE INDEX IF NOT EXISTS idx_quality_rules_active
    ON quality_rules(category) WHERE superseded_by IS NULL;

CREATE TABLE IF NOT EXISTS quality_patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pattern TEXT NOT NULL,
    source_task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
    category VARCHAR(50) NOT NULL,
    reinforcement_count INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quality_patterns_category ON quality_patterns(category);
CREATE INDEX IF NOT EXISTS idx_quality_patterns_reinforcement
    ON quality_patterns(reinforcement_count DESC);

ALTER TABLE audit_reports
    ADD COLUMN IF NOT EXISTS fix_instructions TEXT;
ALTER TABLE audit_reports
    ADD COLUMN IF NOT EXISTS strengths JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE audit_reports
    ADD COLUMN IF NOT EXISTS fix_attempt INTEGER NOT NULL DEFAULT 0;
```

- [ ] **Step 6: Append Phase 5 section to schema.sql**

In `src/max/db/schema.sql`, add at the end (after the Phase 4 section):

```sql
-- ═════════════════════════════════════════════════════════════════════════════
-- Phase 5: Quality Gate tables and alterations
-- ═════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS quality_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule TEXT NOT NULL,
    source TEXT NOT NULL,
    category VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL DEFAULT 'normal',
    superseded_by UUID REFERENCES quality_rules(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quality_rules_category ON quality_rules(category);
CREATE INDEX IF NOT EXISTS idx_quality_rules_active
    ON quality_rules(category) WHERE superseded_by IS NULL;

CREATE TABLE IF NOT EXISTS quality_patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pattern TEXT NOT NULL,
    source_task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
    category VARCHAR(50) NOT NULL,
    reinforcement_count INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quality_patterns_category ON quality_patterns(category);
CREATE INDEX IF NOT EXISTS idx_quality_patterns_reinforcement
    ON quality_patterns(reinforcement_count DESC);

ALTER TABLE audit_reports
    ADD COLUMN IF NOT EXISTS fix_instructions TEXT;
ALTER TABLE audit_reports
    ADD COLUMN IF NOT EXISTS strengths JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE audit_reports
    ADD COLUMN IF NOT EXISTS fix_attempt INTEGER NOT NULL DEFAULT 0;
```

- [ ] **Step 7: Write DB table existence tests**

In `tests/test_postgres.py`, add at end:

```python
@pytest.mark.asyncio
async def test_quality_rules_table_exists(db):
    """Verify Phase 5 quality_rules table is created."""
    tables = await db.fetchall("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    table_names = {row["tablename"] for row in tables}
    assert "quality_rules" in table_names


@pytest.mark.asyncio
async def test_quality_patterns_table_exists(db):
    """Verify Phase 5 quality_patterns table is created."""
    tables = await db.fetchall("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    table_names = {row["tablename"] for row in tables}
    assert "quality_patterns" in table_names


@pytest.mark.asyncio
async def test_audit_reports_has_phase5_columns(db):
    """Verify audit_reports has Phase 5 columns."""
    cols = await db.fetchall(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'audit_reports'"
    )
    col_names = {row["column_name"] for row in cols}
    expected = {"fix_instructions", "strengths", "fix_attempt"}
    assert expected.issubset(col_names), f"Missing columns: {expected - col_names}"
```

- [ ] **Step 8: Run all tests to verify everything passes**

Run: `uv run python -m pytest tests/test_config.py tests/test_postgres.py --tb=short -q`
Expected: All pass (existing + 4 new)

- [ ] **Step 9: Commit**

```bash
git add src/max/config.py src/max/db/migrations/005_quality_gate.sql src/max/db/schema.sql tests/test_config.py tests/test_postgres.py
git commit -m "feat(config): add Phase 5 Quality Gate settings and DB migration"
```

---

### Task 2: Quality models

**Files:**
- Create: `src/max/quality/__init__.py`
- Create: `src/max/quality/models.py`
- Create: `tests/test_quality_models.py`

- [ ] **Step 1: Write failing tests for quality models**

Create `tests/test_quality_models.py`:

```python
"""Tests for Phase 5 Quality Gate models."""

import uuid

import pytest
from pydantic import ValidationError

from max.quality.models import (
    AuditRequest,
    AuditResponse,
    FixInstruction,
    QualityPattern,
    SubtaskAuditItem,
    SubtaskVerdict,
)
from max.models.tasks import AuditVerdict


class TestQualityPattern:
    def test_create_with_defaults(self):
        p = QualityPattern(
            pattern="Use structured logging",
            source_task_id=uuid.uuid4(),
            category="code_quality",
        )
        assert p.reinforcement_count == 1
        assert p.id is not None
        assert p.created_at is not None

    def test_create_with_custom_reinforcement(self):
        p = QualityPattern(
            pattern="Test pattern",
            source_task_id=uuid.uuid4(),
            category="research",
            reinforcement_count=5,
        )
        assert p.reinforcement_count == 5


class TestSubtaskAuditItem:
    def test_create_minimal(self):
        item = SubtaskAuditItem(
            subtask_id=uuid.uuid4(),
            description="Write a summary",
            content="Here is my summary...",
        )
        assert item.quality_criteria == {}

    def test_no_reasoning_field(self):
        """SubtaskAuditItem should NOT have reasoning/confidence fields (blind audit)."""
        item = SubtaskAuditItem(
            subtask_id=uuid.uuid4(),
            description="test",
            content="output",
        )
        assert not hasattr(item, "reasoning")
        assert not hasattr(item, "confidence")


class TestAuditRequest:
    def test_create_with_subtasks(self):
        task_id = uuid.uuid4()
        req = AuditRequest(
            task_id=task_id,
            goal_anchor="Deploy the app",
            subtask_results=[
                SubtaskAuditItem(
                    subtask_id=uuid.uuid4(),
                    description="Write deploy script",
                    content="#!/bin/bash\ndeploy.sh",
                ),
            ],
        )
        assert req.task_id == task_id
        assert len(req.subtask_results) == 1

    def test_empty_subtask_results(self):
        req = AuditRequest(
            task_id=uuid.uuid4(),
            goal_anchor="Test",
            subtask_results=[],
        )
        assert req.subtask_results == []


class TestSubtaskVerdict:
    def test_create_pass(self):
        v = SubtaskVerdict(
            subtask_id=uuid.uuid4(),
            verdict=AuditVerdict.PASS,
            score=0.85,
            goal_alignment=0.9,
        )
        assert v.verdict == "pass"
        assert v.issues == []

    def test_create_fail_with_issues(self):
        v = SubtaskVerdict(
            subtask_id=uuid.uuid4(),
            verdict=AuditVerdict.FAIL,
            score=0.3,
            goal_alignment=0.4,
            issues=[{"category": "completeness", "description": "Missing error handling"}],
        )
        assert len(v.issues) == 1


class TestFixInstruction:
    def test_create(self):
        fi = FixInstruction(
            subtask_id=uuid.uuid4(),
            instructions="Add error handling for network failures",
            original_content="def fetch(): return requests.get(url)",
            issues=[{"category": "robustness", "description": "No error handling"}],
        )
        assert "error handling" in fi.instructions


class TestAuditResponse:
    def test_success_response(self):
        resp = AuditResponse(
            task_id=uuid.uuid4(),
            success=True,
            verdicts=[
                SubtaskVerdict(
                    subtask_id=uuid.uuid4(),
                    verdict=AuditVerdict.PASS,
                    score=0.9,
                    goal_alignment=0.95,
                ),
            ],
            overall_score=0.9,
        )
        assert resp.success is True
        assert resp.fix_required == []

    def test_failure_response_with_fixes(self):
        sid = uuid.uuid4()
        resp = AuditResponse(
            task_id=uuid.uuid4(),
            success=False,
            verdicts=[
                SubtaskVerdict(
                    subtask_id=sid,
                    verdict=AuditVerdict.FAIL,
                    score=0.3,
                    goal_alignment=0.4,
                    issues=[{"category": "quality", "description": "Incomplete"}],
                ),
            ],
            overall_score=0.3,
            fix_required=[
                FixInstruction(
                    subtask_id=sid,
                    instructions="Complete the implementation",
                    original_content="partial...",
                    issues=[{"category": "quality", "description": "Incomplete"}],
                ),
            ],
        )
        assert resp.success is False
        assert len(resp.fix_required) == 1

    def test_score_validation(self):
        """Scores must be between 0 and 1."""
        with pytest.raises(ValidationError):
            SubtaskVerdict(
                subtask_id=uuid.uuid4(),
                verdict=AuditVerdict.PASS,
                score=1.5,
                goal_alignment=0.9,
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_quality_models.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Create models.py**

Create `src/max/quality/models.py`:

```python
"""Phase 5 Quality Gate models — audit requests, responses, patterns, verdicts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from max.models.tasks import AuditVerdict


class QualityPattern(BaseModel):
    """A quality pattern learned from high-scoring audits — reinforced over time."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    pattern: str
    source_task_id: uuid.UUID
    category: str
    reinforcement_count: int = 1
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SubtaskAuditItem(BaseModel):
    """One subtask's output for the auditor to evaluate.

    Deliberately excludes reasoning, confidence, and error fields
    from SubtaskResult to enforce the blind audit protocol.
    """

    subtask_id: uuid.UUID
    description: str
    content: str
    quality_criteria: dict[str, Any] = Field(default_factory=dict)


class AuditRequest(BaseModel):
    """Published on audit.request by the Orchestrator."""

    task_id: uuid.UUID
    goal_anchor: str
    subtask_results: list[SubtaskAuditItem]
    quality_criteria: dict[str, Any] = Field(default_factory=dict)


class SubtaskVerdict(BaseModel):
    """Audit verdict for a single subtask."""

    subtask_id: uuid.UUID
    verdict: AuditVerdict
    score: float = Field(ge=0.0, le=1.0)
    goal_alignment: float = Field(ge=0.0, le=1.0)
    issues: list[dict[str, str]] = Field(default_factory=list)


class FixInstruction(BaseModel):
    """Instructions for fixing a failed subtask."""

    subtask_id: uuid.UUID
    instructions: str
    original_content: str
    issues: list[dict[str, str]] = Field(default_factory=list)


class AuditResponse(BaseModel):
    """Published on audit.complete by the Quality Director."""

    task_id: uuid.UUID
    success: bool
    verdicts: list[SubtaskVerdict]
    overall_score: float = Field(ge=0.0, le=1.0)
    fix_required: list[FixInstruction] = Field(default_factory=list)
```

- [ ] **Step 4: Create __init__.py**

Create `src/max/quality/__init__.py`:

```python
"""Phase 5: Quality Gate — audit pipeline, rules engine, quality ledger."""

from max.quality.models import (
    AuditRequest,
    AuditResponse,
    FixInstruction,
    QualityPattern,
    SubtaskAuditItem,
    SubtaskVerdict,
)

__all__ = [
    "AuditRequest",
    "AuditResponse",
    "FixInstruction",
    "QualityPattern",
    "SubtaskAuditItem",
    "SubtaskVerdict",
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_quality_models.py -v`
Expected: 13 PASS

- [ ] **Step 6: Commit**

```bash
git add src/max/quality/__init__.py src/max/quality/models.py tests/test_quality_models.py
git commit -m "feat(quality): add Phase 5 Quality Gate models"
```

---

### Task 3: QualityStore

**Files:**
- Create: `src/max/quality/store.py`
- Create: `tests/test_quality_store.py`

- [ ] **Step 1: Write failing tests for QualityStore**

Create `tests/test_quality_store.py`:

```python
"""Tests for QualityStore — async CRUD for audit reports, ledger, rules, patterns."""

import json
import uuid
from unittest.mock import AsyncMock

import pytest

from max.models.tasks import AuditVerdict
from max.quality.store import QualityStore


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.fetchone = AsyncMock(return_value=None)
    db.fetchall = AsyncMock(return_value=[])
    return db


@pytest.fixture
def store(mock_db):
    return QualityStore(mock_db)


class TestCreateAuditReport:
    @pytest.mark.asyncio
    async def test_inserts_report(self, store, mock_db):
        report_id = uuid.uuid4()
        task_id = uuid.uuid4()
        subtask_id = uuid.uuid4()
        await store.create_audit_report(
            report_id=report_id,
            task_id=task_id,
            subtask_id=subtask_id,
            verdict=AuditVerdict.PASS,
            score=0.85,
            goal_alignment=0.9,
            confidence=0.95,
            issues=[],
            fix_instructions=None,
            strengths=["Good structure"],
            fix_attempt=0,
        )
        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args
        assert "INSERT INTO audit_reports" in call_args[0][0]


class TestGetAuditReports:
    @pytest.mark.asyncio
    async def test_fetches_by_task_id(self, store, mock_db):
        task_id = uuid.uuid4()
        mock_db.fetchall.return_value = [
            {"id": uuid.uuid4(), "task_id": task_id, "verdict": "pass", "score": 0.9}
        ]
        rows = await store.get_audit_reports(task_id)
        assert len(rows) == 1
        mock_db.fetchall.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_empty_list(self, store, mock_db):
        rows = await store.get_audit_reports(uuid.uuid4())
        assert rows == []


class TestGetAuditReportForSubtask:
    @pytest.mark.asyncio
    async def test_fetches_by_subtask_id(self, store, mock_db):
        subtask_id = uuid.uuid4()
        mock_db.fetchone.return_value = {"id": uuid.uuid4(), "subtask_id": subtask_id}
        row = await store.get_audit_report_for_subtask(subtask_id)
        assert row is not None


class TestRecordVerdict:
    @pytest.mark.asyncio
    async def test_inserts_ledger_entry(self, store, mock_db):
        await store.record_verdict(
            task_id=uuid.uuid4(),
            subtask_id=uuid.uuid4(),
            verdict=AuditVerdict.PASS,
            score=0.85,
            metadata={"fix_attempt": 0},
        )
        call_args = mock_db.execute.call_args
        assert "INSERT INTO quality_ledger" in call_args[0][0]
        assert call_args[0][2] == "audit_verdict"


class TestQualityRules:
    @pytest.mark.asyncio
    async def test_create_rule(self, store, mock_db):
        rule_id = uuid.uuid4()
        await store.create_rule(
            rule_id=rule_id,
            rule="Always validate input",
            source="audit-123",
            category="validation",
            severity="normal",
        )
        call_args = mock_db.execute.call_args
        assert "INSERT INTO quality_rules" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_active_rules(self, store, mock_db):
        mock_db.fetchall.return_value = [
            {"id": uuid.uuid4(), "rule": "Validate input", "category": "validation"}
        ]
        rules = await store.get_active_rules()
        assert len(rules) == 1

    @pytest.mark.asyncio
    async def test_get_active_rules_by_category(self, store, mock_db):
        await store.get_active_rules(category="validation")
        call_args = mock_db.fetchall.call_args
        assert "category = $1" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_supersede_rule(self, store, mock_db):
        old_id = uuid.uuid4()
        new_id = uuid.uuid4()
        await store.supersede_rule(old_id, new_id)
        mock_db.execute.assert_called()
        # Should update old rule AND record in ledger
        assert mock_db.execute.call_count == 2


class TestQualityPatterns:
    @pytest.mark.asyncio
    async def test_create_pattern(self, store, mock_db):
        await store.create_pattern(
            pattern_id=uuid.uuid4(),
            pattern="Use structured logging",
            source_task_id=uuid.uuid4(),
            category="code_quality",
        )
        call_args = mock_db.execute.call_args
        assert "INSERT INTO quality_patterns" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_patterns(self, store, mock_db):
        mock_db.fetchall.return_value = [
            {"id": uuid.uuid4(), "pattern": "test", "reinforcement_count": 3}
        ]
        patterns = await store.get_patterns(min_reinforcement=2)
        assert len(patterns) == 1

    @pytest.mark.asyncio
    async def test_reinforce_pattern(self, store, mock_db):
        pattern_id = uuid.uuid4()
        await store.reinforce_pattern(pattern_id)
        # Should update count AND record in ledger
        assert mock_db.execute.call_count == 2


class TestRecordLedgerEntries:
    @pytest.mark.asyncio
    async def test_record_rule_to_ledger(self, store, mock_db):
        await store.record_rule_to_ledger(
            rule_id=uuid.uuid4(),
            rule="Test rule",
            category="test",
            severity="normal",
            source_audit_id=uuid.uuid4(),
        )
        call_args = mock_db.execute.call_args
        assert call_args[0][2] == "quality_rule_created"

    @pytest.mark.asyncio
    async def test_record_pattern_to_ledger(self, store, mock_db):
        await store.record_pattern_to_ledger(
            pattern_id=uuid.uuid4(),
            pattern="Good pattern",
            category="test",
            source_task_id=uuid.uuid4(),
        )
        call_args = mock_db.execute.call_args
        assert call_args[0][2] == "quality_pattern_created"

    @pytest.mark.asyncio
    async def test_get_ledger_entries(self, store, mock_db):
        mock_db.fetchall.return_value = [
            {"id": uuid.uuid4(), "entry_type": "audit_verdict", "content": "{}"}
        ]
        entries = await store.get_ledger_entries("audit_verdict", limit=50)
        assert len(entries) == 1


class TestQualityMetrics:
    @pytest.mark.asyncio
    async def test_get_pass_rate(self, store, mock_db):
        mock_db.fetchone.return_value = {"pass_rate": 0.85}
        rate = await store.get_pass_rate(hours=24)
        assert rate == 0.85

    @pytest.mark.asyncio
    async def test_get_pass_rate_no_data(self, store, mock_db):
        mock_db.fetchone.return_value = {"pass_rate": None}
        rate = await store.get_pass_rate(hours=24)
        assert rate == 0.0

    @pytest.mark.asyncio
    async def test_get_avg_score(self, store, mock_db):
        mock_db.fetchone.return_value = {"avg_score": 0.78}
        score = await store.get_avg_score(hours=24)
        assert score == 0.78
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_quality_store.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement QualityStore**

Create `src/max/quality/store.py`:

```python
"""QualityStore -- async CRUD for audit reports, quality ledger, rules, patterns."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from max.db.postgres import Database
from max.models.tasks import AuditVerdict

logger = logging.getLogger(__name__)


class QualityStore:
    """Persistence layer for Quality Gate operations."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Audit Reports ───────────────────────────────────────────────────

    async def create_audit_report(
        self,
        report_id: uuid.UUID,
        task_id: uuid.UUID,
        subtask_id: uuid.UUID,
        verdict: AuditVerdict,
        score: float,
        goal_alignment: float,
        confidence: float,
        issues: list[dict[str, str]],
        fix_instructions: str | None = None,
        strengths: list[str] | None = None,
        fix_attempt: int = 0,
    ) -> None:
        """Insert an audit report."""
        await self._db.execute(
            "INSERT INTO audit_reports "
            "(id, task_id, subtask_id, verdict, score, goal_alignment, confidence, "
            "issues, fix_instructions, strengths, fix_attempt) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10::jsonb, $11)",
            report_id,
            task_id,
            subtask_id,
            verdict.value,
            score,
            goal_alignment,
            confidence,
            json.dumps(issues),
            fix_instructions,
            json.dumps(strengths or []),
            fix_attempt,
        )

    async def get_audit_reports(self, task_id: uuid.UUID) -> list[dict[str, Any]]:
        """Get all audit reports for a task."""
        return await self._db.fetchall(
            "SELECT * FROM audit_reports WHERE task_id = $1 ORDER BY created_at DESC",
            task_id,
        )

    async def get_audit_report_for_subtask(
        self, subtask_id: uuid.UUID
    ) -> dict[str, Any] | None:
        """Get the most recent audit report for a subtask."""
        return await self._db.fetchone(
            "SELECT * FROM audit_reports WHERE subtask_id = $1 ORDER BY created_at DESC LIMIT 1",
            subtask_id,
        )

    # ── Quality Ledger (append-only) ────────────────────────────────────

    async def record_verdict(
        self,
        task_id: uuid.UUID,
        subtask_id: uuid.UUID,
        verdict: AuditVerdict,
        score: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record an audit verdict in the quality ledger."""
        content = {
            "task_id": str(task_id),
            "subtask_id": str(subtask_id),
            "verdict": verdict.value,
            "score": score,
            **(metadata or {}),
        }
        await self._db.execute(
            "INSERT INTO quality_ledger (id, entry_type, content) VALUES ($1, $2, $3::jsonb)",
            uuid.uuid4(),
            "audit_verdict",
            json.dumps(content),
        )

    async def record_rule_to_ledger(
        self,
        rule_id: uuid.UUID,
        rule: str,
        category: str,
        severity: str,
        source_audit_id: uuid.UUID,
    ) -> None:
        """Record a quality rule creation in the ledger."""
        content = {
            "rule_id": str(rule_id),
            "rule": rule,
            "category": category,
            "severity": severity,
            "source_audit_id": str(source_audit_id),
        }
        await self._db.execute(
            "INSERT INTO quality_ledger (id, entry_type, content) VALUES ($1, $2, $3::jsonb)",
            uuid.uuid4(),
            "quality_rule_created",
            json.dumps(content),
        )

    async def record_pattern_to_ledger(
        self,
        pattern_id: uuid.UUID,
        pattern: str,
        category: str,
        source_task_id: uuid.UUID,
    ) -> None:
        """Record a quality pattern creation in the ledger."""
        content = {
            "pattern_id": str(pattern_id),
            "pattern": pattern,
            "category": category,
            "source_task_id": str(source_task_id),
        }
        await self._db.execute(
            "INSERT INTO quality_ledger (id, entry_type, content) VALUES ($1, $2, $3::jsonb)",
            uuid.uuid4(),
            "quality_pattern_created",
            json.dumps(content),
        )

    async def get_ledger_entries(
        self, entry_type: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get ledger entries by type."""
        return await self._db.fetchall(
            "SELECT * FROM quality_ledger WHERE entry_type = $1 "
            "ORDER BY created_at DESC LIMIT $2",
            entry_type,
            limit,
        )

    # ── Quality Rules ───────────────────────────────────────────────────

    async def create_rule(
        self,
        rule_id: uuid.UUID,
        rule: str,
        source: str,
        category: str,
        severity: str = "normal",
    ) -> None:
        """Insert a quality rule."""
        await self._db.execute(
            "INSERT INTO quality_rules (id, rule, source, category, severity) "
            "VALUES ($1, $2, $3, $4, $5)",
            rule_id,
            rule,
            source,
            category,
            severity,
        )

    async def get_active_rules(
        self, category: str | None = None
    ) -> list[dict[str, Any]]:
        """Get all non-superseded quality rules."""
        if category:
            return await self._db.fetchall(
                "SELECT * FROM quality_rules WHERE superseded_by IS NULL "
                "AND category = $1 ORDER BY created_at DESC",
                category,
            )
        return await self._db.fetchall(
            "SELECT * FROM quality_rules WHERE superseded_by IS NULL "
            "ORDER BY created_at DESC"
        )

    async def supersede_rule(
        self, old_rule_id: uuid.UUID, new_rule_id: uuid.UUID
    ) -> None:
        """Mark an old rule as superseded by a new one."""
        await self._db.execute(
            "UPDATE quality_rules SET superseded_by = $1 WHERE id = $2",
            new_rule_id,
            old_rule_id,
        )
        # Record in ledger
        content = {
            "old_rule_id": str(old_rule_id),
            "new_rule_id": str(new_rule_id),
        }
        await self._db.execute(
            "INSERT INTO quality_ledger (id, entry_type, content) VALUES ($1, $2, $3::jsonb)",
            uuid.uuid4(),
            "quality_rule_superseded",
            json.dumps(content),
        )

    # ── Quality Patterns ────────────────────────────────────────────────

    async def create_pattern(
        self,
        pattern_id: uuid.UUID,
        pattern: str,
        source_task_id: uuid.UUID,
        category: str,
    ) -> None:
        """Insert a quality pattern."""
        await self._db.execute(
            "INSERT INTO quality_patterns (id, pattern, source_task_id, category) "
            "VALUES ($1, $2, $3, $4)",
            pattern_id,
            pattern,
            source_task_id,
            category,
        )

    async def get_patterns(
        self, category: str | None = None, min_reinforcement: int = 1
    ) -> list[dict[str, Any]]:
        """Get quality patterns filtered by category and minimum reinforcement."""
        if category:
            return await self._db.fetchall(
                "SELECT * FROM quality_patterns "
                "WHERE category = $1 AND reinforcement_count >= $2 "
                "ORDER BY reinforcement_count DESC",
                category,
                min_reinforcement,
            )
        return await self._db.fetchall(
            "SELECT * FROM quality_patterns WHERE reinforcement_count >= $1 "
            "ORDER BY reinforcement_count DESC",
            min_reinforcement,
        )

    async def reinforce_pattern(self, pattern_id: uuid.UUID) -> None:
        """Increment a pattern's reinforcement count."""
        await self._db.execute(
            "UPDATE quality_patterns SET reinforcement_count = reinforcement_count + 1 "
            "WHERE id = $1",
            pattern_id,
        )
        # Record in ledger
        await self._db.execute(
            "INSERT INTO quality_ledger (id, entry_type, content) VALUES ($1, $2, $3::jsonb)",
            uuid.uuid4(),
            "quality_pattern_reinforced",
            json.dumps({"pattern_id": str(pattern_id)}),
        )

    # ── Metrics ─────────────────────────────────────────────────────────

    async def get_pass_rate(self, hours: int = 24) -> float:
        """Get the audit pass rate over the given window."""
        row = await self._db.fetchone(
            "SELECT AVG(CASE WHEN verdict = 'pass' THEN 1.0 ELSE 0.0 END) AS pass_rate "
            "FROM audit_reports WHERE created_at > NOW() - INTERVAL '1 hour' * $1",
            hours,
        )
        return float(row["pass_rate"]) if row and row["pass_rate"] is not None else 0.0

    async def get_avg_score(self, hours: int = 24) -> float:
        """Get the average audit score over the given window."""
        row = await self._db.fetchone(
            "SELECT AVG(score) AS avg_score FROM audit_reports "
            "WHERE created_at > NOW() - INTERVAL '1 hour' * $1",
            hours,
        )
        return float(row["avg_score"]) if row and row["avg_score"] is not None else 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_quality_store.py -v`
Expected: 17 PASS

- [ ] **Step 5: Commit**

```bash
git add src/max/quality/store.py tests/test_quality_store.py
git commit -m "feat(quality): add QualityStore for audit reports, ledger, rules, patterns"
```

---

### Task 4: AuditorAgent

**Files:**
- Create: `src/max/quality/auditor.py`
- Create: `tests/test_auditor.py`

- [ ] **Step 1: Write failing tests for AuditorAgent**

Create `tests/test_auditor.py`:

```python
"""Tests for AuditorAgent — blind audit of subtask outputs."""

import json
import uuid
from unittest.mock import AsyncMock

import pytest

from max.llm.models import LLMResponse
from max.quality.auditor import AUDITOR_SYSTEM_PROMPT_TEMPLATE, AuditorAgent


def _make_llm_response(data: dict | str) -> LLMResponse:
    text = json.dumps(data) if isinstance(data, dict) else data
    return LLMResponse(
        text=text,
        input_tokens=100,
        output_tokens=50,
        model="claude-opus-4-6",
        stop_reason="end_turn",
    )


class TestAuditorRun:
    @pytest.mark.asyncio
    async def test_pass_verdict(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(
            return_value=_make_llm_response(
                {
                    "verdict": "pass",
                    "score": 0.85,
                    "goal_alignment": 0.9,
                    "confidence": 0.95,
                    "issues": [],
                    "fix_instructions": None,
                    "strengths": ["Clear structure"],
                    "reasoning": "Good work",
                }
            )
        )
        auditor = AuditorAgent(llm=llm)
        result = await auditor.run(
            {
                "goal_anchor": "Deploy the app",
                "subtask_description": "Write deploy script",
                "content": "#!/bin/bash\nset -e\ndeploy.sh",
                "quality_criteria": {},
                "quality_rules": [],
            }
        )
        assert result["verdict"] == "pass"
        assert result["score"] == 0.85

    @pytest.mark.asyncio
    async def test_fail_verdict(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(
            return_value=_make_llm_response(
                {
                    "verdict": "fail",
                    "score": 0.3,
                    "goal_alignment": 0.4,
                    "confidence": 0.9,
                    "issues": [
                        {"category": "completeness", "description": "Missing error handling"}
                    ],
                    "fix_instructions": "Add try/except blocks",
                    "strengths": [],
                    "reasoning": "Incomplete",
                }
            )
        )
        auditor = AuditorAgent(llm=llm)
        result = await auditor.run(
            {
                "goal_anchor": "Build API",
                "subtask_description": "Write endpoints",
                "content": "def get(): pass",
                "quality_criteria": {"completeness": "Must handle errors"},
                "quality_rules": [{"rule": "Always handle exceptions"}],
            }
        )
        assert result["verdict"] == "fail"
        assert result["fix_instructions"] == "Add try/except blocks"

    @pytest.mark.asyncio
    async def test_markdown_json_response(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(
            return_value=_make_llm_response(
                '```json\n{"verdict": "pass", "score": 0.8, "goal_alignment": 0.85, '
                '"confidence": 0.9, "issues": [], "fix_instructions": null, '
                '"strengths": [], "reasoning": "ok"}\n```'
            )
        )
        auditor = AuditorAgent(llm=llm)
        result = await auditor.run(
            {
                "goal_anchor": "Test",
                "subtask_description": "Test",
                "content": "output",
                "quality_criteria": {},
                "quality_rules": [],
            }
        )
        assert result["verdict"] == "pass"

    @pytest.mark.asyncio
    async def test_unparseable_response_returns_conditional(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(
            return_value=_make_llm_response("I cannot parse this as JSON at all")
        )
        auditor = AuditorAgent(llm=llm)
        result = await auditor.run(
            {
                "goal_anchor": "Test",
                "subtask_description": "Test",
                "content": "output",
                "quality_criteria": {},
                "quality_rules": [],
            }
        )
        assert result["verdict"] == "conditional"
        assert result["confidence"] == 0.3

    @pytest.mark.asyncio
    async def test_exception_returns_conditional(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=RuntimeError("LLM down"))
        auditor = AuditorAgent(llm=llm)
        result = await auditor.run(
            {
                "goal_anchor": "Test",
                "subtask_description": "Test",
                "content": "output",
                "quality_criteria": {},
                "quality_rules": [],
            }
        )
        assert result["verdict"] == "conditional"
        assert "LLM down" in result.get("error", "")


class TestAuditorPrompt:
    def test_prompt_template_has_required_placeholders(self):
        assert "{goal_anchor}" in AUDITOR_SYSTEM_PROMPT_TEMPLATE
        assert "{subtask_description}" in AUDITOR_SYSTEM_PROMPT_TEMPLATE
        assert "{quality_criteria}" in AUDITOR_SYSTEM_PROMPT_TEMPLATE
        assert "{quality_rules}" in AUDITOR_SYSTEM_PROMPT_TEMPLATE

    def test_prompt_does_not_contain_reasoning(self):
        """The auditor prompt must not ask for the worker's reasoning (blind audit)."""
        assert "worker reasoning" not in AUDITOR_SYSTEM_PROMPT_TEMPLATE.lower()
        assert "worker confidence" not in AUDITOR_SYSTEM_PROMPT_TEMPLATE.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_auditor.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement AuditorAgent**

Create `src/max/quality/auditor.py`:

```python
"""AuditorAgent -- blind audit of subtask outputs."""

from __future__ import annotations

import json
import logging
from typing import Any

from max.agents.base import AgentConfig, BaseAgent
from max.llm.client import LLMClient
from max.llm.models import ModelType

logger = logging.getLogger(__name__)

AUDITOR_SYSTEM_PROMPT_TEMPLATE = """You are a Quality Auditor for Max, an autonomous AI agent system.

Your job: evaluate work output against the stated goal and quality criteria.
You must be objective, thorough, and fair.

Goal: {goal_anchor}
Subtask: {subtask_description}
Quality Criteria: {quality_criteria}

Active Quality Rules (learned from past audits):
{quality_rules}

Evaluate the following work output and return ONLY valid JSON:
{{
  "verdict": "pass | fail | conditional",
  "score": 0.0 to 1.0,
  "goal_alignment": 0.0 to 1.0,
  "confidence": 0.0 to 1.0,
  "issues": [{{"category": "...", "description": "...", "severity": "low|normal|high|critical"}}],
  "fix_instructions": "Specific instructions for fixing issues (only if verdict is fail)",
  "strengths": ["What was done well"],
  "reasoning": "Your evaluation reasoning"
}}

Scoring guidelines:
- score: overall quality (0.0 = terrible, 1.0 = perfect)
- goal_alignment: how well the output achieves the stated goal
- confidence: how confident you are in your assessment
- verdict: "pass" if score >= 0.7 and no critical issues, "fail" if score < 0.5 or any critical issue, "conditional" otherwise"""


class AuditorAgent(BaseAgent):
    """Ephemeral agent that audits a single subtask's output.

    Receives only the work product, goal, and criteria — never the
    worker's reasoning or confidence (blind audit protocol).
    """

    def __init__(
        self,
        llm: LLMClient,
        model: ModelType = ModelType.OPUS,
    ) -> None:
        config = AgentConfig(
            name="auditor",
            system_prompt="",
            model=model,
            max_turns=3,
        )
        super().__init__(config=config, llm=llm)

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Audit a subtask output and return a verdict dict."""
        goal_anchor = input_data.get("goal_anchor", "")
        subtask_description = input_data.get("subtask_description", "")
        content = input_data.get("content", "")
        quality_criteria = input_data.get("quality_criteria", {})
        quality_rules = input_data.get("quality_rules", [])

        criteria_str = (
            json.dumps(quality_criteria, indent=2) if quality_criteria else "None specified"
        )
        rules_str = (
            "\n".join(f"- {r['rule']}" for r in quality_rules) if quality_rules else "None"
        )

        prompt = AUDITOR_SYSTEM_PROMPT_TEMPLATE.format(
            goal_anchor=goal_anchor,
            subtask_description=subtask_description,
            quality_criteria=criteria_str,
            quality_rules=rules_str,
        )

        self.reset()
        try:
            response = await self.think(
                messages=[
                    {
                        "role": "user",
                        "content": f"Evaluate this work output:\n\n{content}",
                    }
                ],
                system_prompt=prompt,
            )
            parsed = self._parse_response(response.text)
            return {
                "verdict": parsed.get("verdict", "conditional"),
                "score": parsed.get("score", 0.5),
                "goal_alignment": parsed.get("goal_alignment", 0.5),
                "confidence": parsed.get("confidence", 0.5),
                "issues": parsed.get("issues", []),
                "fix_instructions": parsed.get("fix_instructions"),
                "strengths": parsed.get("strengths", []),
                "reasoning": parsed.get("reasoning", ""),
            }
        except Exception as exc:
            logger.exception("Auditor failed")
            return {
                "verdict": "conditional",
                "score": 0.5,
                "goal_alignment": 0.5,
                "confidence": 0.3,
                "issues": [],
                "fix_instructions": None,
                "strengths": [],
                "reasoning": "Audit failed due to error",
                "error": str(exc),
            }

    @staticmethod
    def _parse_response(text: str) -> dict[str, Any]:
        """Parse JSON from LLM response, handling markdown code blocks."""
        text = text.strip()
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                try:
                    return json.loads(part)
                except (json.JSONDecodeError, ValueError):
                    continue
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return {
                "verdict": "conditional",
                "score": 0.5,
                "goal_alignment": 0.5,
                "confidence": 0.3,
                "issues": [],
                "reasoning": "Failed to parse auditor response",
            }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_auditor.py -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add src/max/quality/auditor.py tests/test_auditor.py
git commit -m "feat(quality): add AuditorAgent with blind audit protocol"
```

---

### Task 5: RuleEngine

**Files:**
- Create: `src/max/quality/rules.py`
- Create: `tests/test_rule_engine.py`

- [ ] **Step 1: Write failing tests for RuleEngine**

Create `tests/test_rule_engine.py`:

```python
"""Tests for RuleEngine — rule extraction, supersession, pattern extraction."""

import json
import uuid
from unittest.mock import AsyncMock

import pytest

from max.llm.models import LLMResponse
from max.models.tasks import AuditVerdict
from max.quality.rules import RuleEngine


def _make_llm_response(data: dict | str) -> LLMResponse:
    text = json.dumps(data) if isinstance(data, dict) else data
    return LLMResponse(
        text=text,
        input_tokens=100,
        output_tokens=50,
        model="claude-opus-4-6",
        stop_reason="end_turn",
    )


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.create_rule = AsyncMock()
    store.record_rule_to_ledger = AsyncMock()
    store.get_active_rules = AsyncMock(return_value=[])
    store.supersede_rule = AsyncMock()
    store.create_pattern = AsyncMock()
    store.record_pattern_to_ledger = AsyncMock()
    return store


class TestExtractRules:
    @pytest.mark.asyncio
    async def test_extracts_rules_from_failure(self, mock_store):
        llm = AsyncMock()
        llm.complete = AsyncMock(
            return_value=_make_llm_response(
                {
                    "rules": [
                        {
                            "rule": "Always validate user input",
                            "category": "validation",
                            "severity": "high",
                        }
                    ]
                }
            )
        )
        engine = RuleEngine(llm=llm, quality_store=mock_store)
        rules = await engine.extract_rules(
            audit_id=uuid.uuid4(),
            issues=[{"category": "validation", "description": "No input validation"}],
            subtask_description="Build user form",
            output_content="def form(): pass",
        )
        assert len(rules) == 1
        assert rules[0]["rule"] == "Always validate user input"
        mock_store.create_rule.assert_called_once()
        mock_store.record_rule_to_ledger.assert_called_once()

    @pytest.mark.asyncio
    async def test_caps_rules_at_max(self, mock_store):
        llm = AsyncMock()
        many_rules = [{"rule": f"Rule {i}", "category": "test", "severity": "normal"} for i in range(10)]
        llm.complete = AsyncMock(
            return_value=_make_llm_response({"rules": many_rules})
        )
        engine = RuleEngine(llm=llm, quality_store=mock_store, max_rules_per_audit=3)
        rules = await engine.extract_rules(
            audit_id=uuid.uuid4(),
            issues=[{"category": "test", "description": "test"}],
            subtask_description="test",
            output_content="test",
        )
        assert len(rules) == 3

    @pytest.mark.asyncio
    async def test_handles_llm_failure(self, mock_store):
        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=RuntimeError("LLM error"))
        engine = RuleEngine(llm=llm, quality_store=mock_store)
        rules = await engine.extract_rules(
            audit_id=uuid.uuid4(),
            issues=[],
            subtask_description="test",
            output_content="test",
        )
        assert rules == []


class TestExtractPatterns:
    @pytest.mark.asyncio
    async def test_extracts_pattern_from_success(self, mock_store):
        llm = AsyncMock()
        llm.complete = AsyncMock(
            return_value=_make_llm_response(
                {
                    "patterns": [
                        {
                            "pattern": "Uses structured error handling",
                            "category": "code_quality",
                        }
                    ]
                }
            )
        )
        engine = RuleEngine(llm=llm, quality_store=mock_store)
        patterns = await engine.extract_patterns(
            task_id=uuid.uuid4(),
            strengths=["Good error handling"],
            subtask_description="Build API",
            output_content="def api(): try: ... except: ...",
        )
        assert len(patterns) == 1
        mock_store.create_pattern.assert_called_once()
        mock_store.record_pattern_to_ledger.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_llm_failure(self, mock_store):
        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=RuntimeError("fail"))
        engine = RuleEngine(llm=llm, quality_store=mock_store)
        patterns = await engine.extract_patterns(
            task_id=uuid.uuid4(),
            strengths=[],
            subtask_description="test",
            output_content="test",
        )
        assert patterns == []


class TestGetRulesForAudit:
    @pytest.mark.asyncio
    async def test_returns_active_rules(self, mock_store):
        mock_store.get_active_rules.return_value = [
            {"id": str(uuid.uuid4()), "rule": "Validate input", "category": "validation"}
        ]
        engine = RuleEngine(llm=AsyncMock(), quality_store=mock_store)
        rules = await engine.get_rules_for_audit()
        assert len(rules) == 1

    @pytest.mark.asyncio
    async def test_filters_by_category(self, mock_store):
        engine = RuleEngine(llm=AsyncMock(), quality_store=mock_store)
        await engine.get_rules_for_audit(category="validation")
        mock_store.get_active_rules.assert_called_with(category="validation")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_rule_engine.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement RuleEngine**

Create `src/max/quality/rules.py`:

```python
"""RuleEngine -- quality rule extraction, supersession, pattern extraction."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from max.llm.client import LLMClient
from max.quality.store import QualityStore

logger = logging.getLogger(__name__)

RULE_EXTRACTION_PROMPT = """You are a Quality Rule Extractor for Max.

Given an audit failure, extract reusable quality rules that should be checked in future audits.

Audit issues found:
{issues}

Subtask: {subtask_description}
Output that failed:
{output_content}

Return ONLY valid JSON:
{{
  "rules": [
    {{
      "rule": "Clear, actionable quality rule",
      "category": "validation | completeness | robustness | clarity | correctness",
      "severity": "low | normal | high | critical"
    }}
  ]
}}

Rules should be:
- General enough to apply to future tasks (not specific to this task)
- Actionable and clear
- Not redundant with common sense"""

PATTERN_EXTRACTION_PROMPT = """You are a Quality Pattern Extractor for Max.

Given high-quality work, extract reusable patterns that should be encouraged in future work.

Strengths identified:
{strengths}

Subtask: {subtask_description}
High-quality output:
{output_content}

Return ONLY valid JSON:
{{
  "patterns": [
    {{
      "pattern": "Clear description of what was done well",
      "category": "code_quality | research | communication | structure | thoroughness"
    }}
  ]
}}

Patterns should be general enough to apply to future tasks."""


class RuleEngine:
    """Manages quality rule lifecycle — extraction, retrieval, pattern extraction."""

    def __init__(
        self,
        llm: LLMClient,
        quality_store: QualityStore,
        max_rules_per_audit: int = 5,
    ) -> None:
        self._llm = llm
        self._store = quality_store
        self._max_rules = max_rules_per_audit

    async def extract_rules(
        self,
        audit_id: uuid.UUID,
        issues: list[dict[str, str]],
        subtask_description: str,
        output_content: str,
    ) -> list[dict[str, Any]]:
        """Extract quality rules from audit failure issues."""
        if not issues:
            return []

        prompt = RULE_EXTRACTION_PROMPT.format(
            issues=json.dumps(issues, indent=2),
            subtask_description=subtask_description,
            output_content=output_content[:2000],
        )

        try:
            response = await self._llm.complete(
                messages=[{"role": "user", "content": prompt}],
            )
            parsed = self._parse_json(response.text)
            raw_rules = parsed.get("rules", [])
        except Exception:
            logger.exception("Rule extraction failed")
            return []

        capped = raw_rules[: self._max_rules]
        result: list[dict[str, Any]] = []
        for r in capped:
            rule_id = uuid.uuid4()
            rule_text = r.get("rule", "")
            category = r.get("category", "general")
            severity = r.get("severity", "normal")
            await self._store.create_rule(
                rule_id=rule_id,
                rule=rule_text,
                source=str(audit_id),
                category=category,
                severity=severity,
            )
            await self._store.record_rule_to_ledger(
                rule_id=rule_id,
                rule=rule_text,
                category=category,
                severity=severity,
                source_audit_id=audit_id,
            )
            result.append({"rule_id": str(rule_id), "rule": rule_text, "category": category})

        return result

    async def extract_patterns(
        self,
        task_id: uuid.UUID,
        strengths: list[str],
        subtask_description: str,
        output_content: str,
    ) -> list[dict[str, Any]]:
        """Extract quality patterns from high-scoring audit successes."""
        if not strengths:
            return []

        prompt = PATTERN_EXTRACTION_PROMPT.format(
            strengths="\n".join(f"- {s}" for s in strengths),
            subtask_description=subtask_description,
            output_content=output_content[:2000],
        )

        try:
            response = await self._llm.complete(
                messages=[{"role": "user", "content": prompt}],
            )
            parsed = self._parse_json(response.text)
            raw_patterns = parsed.get("patterns", [])
        except Exception:
            logger.exception("Pattern extraction failed")
            return []

        result: list[dict[str, Any]] = []
        for p in raw_patterns[:3]:
            pattern_id = uuid.uuid4()
            pattern_text = p.get("pattern", "")
            category = p.get("category", "general")
            await self._store.create_pattern(
                pattern_id=pattern_id,
                pattern=pattern_text,
                source_task_id=task_id,
                category=category,
            )
            await self._store.record_pattern_to_ledger(
                pattern_id=pattern_id,
                pattern=pattern_text,
                category=category,
                source_task_id=task_id,
            )
            result.append({"pattern_id": str(pattern_id), "pattern": pattern_text})

        return result

    async def get_rules_for_audit(
        self, category: str | None = None
    ) -> list[dict[str, Any]]:
        """Get active quality rules for inclusion in auditor prompts."""
        return await self._store.get_active_rules(category=category)

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        """Parse JSON from LLM response, handling markdown fences."""
        text = text.strip()
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                try:
                    return json.loads(part)
                except (json.JSONDecodeError, ValueError):
                    continue
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return {}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_rule_engine.py -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add src/max/quality/rules.py tests/test_rule_engine.py
git commit -m "feat(quality): add RuleEngine for rule and pattern extraction"
```

---

### Task 6: QualityDirectorAgent

**Files:**
- Create: `src/max/quality/director.py`
- Create: `tests/test_quality_director.py`

- [ ] **Step 1: Write failing tests for QualityDirectorAgent**

Create `tests/test_quality_director.py`:

```python
"""Tests for QualityDirectorAgent — audit lifecycle management."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from max.agents.base import AgentConfig
from max.llm.models import LLMResponse
from max.models.tasks import AuditVerdict
from max.quality.director import QualityDirectorAgent
from max.quality.models import AuditRequest, SubtaskAuditItem


def _make_settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    from max.config import Settings

    return Settings()


def _make_llm_response(data: dict | str) -> LLMResponse:
    text = json.dumps(data) if isinstance(data, dict) else data
    return LLMResponse(
        text=text, input_tokens=100, output_tokens=50,
        model="claude-opus-4-6", stop_reason="end_turn",
    )


def _make_director(monkeypatch):
    settings = _make_settings(monkeypatch)
    llm = AsyncMock()
    bus = AsyncMock()
    bus.subscribe = AsyncMock()
    bus.unsubscribe = AsyncMock()
    bus.publish = AsyncMock()
    db = AsyncMock()
    warm = AsyncMock()
    task_store = AsyncMock()
    quality_store = AsyncMock()
    quality_store.get_active_rules = AsyncMock(return_value=[])
    quality_store.create_audit_report = AsyncMock()
    quality_store.record_verdict = AsyncMock()
    quality_store.get_pass_rate = AsyncMock(return_value=0.85)
    quality_store.get_avg_score = AsyncMock(return_value=0.80)
    rule_engine = AsyncMock()
    rule_engine.get_rules_for_audit = AsyncMock(return_value=[])
    rule_engine.extract_rules = AsyncMock(return_value=[])
    rule_engine.extract_patterns = AsyncMock(return_value=[])
    state_manager = AsyncMock()

    from max.memory.models import AuditPipelineState, CoordinatorState

    state_manager.load = AsyncMock(return_value=CoordinatorState())
    state_manager.save = AsyncMock()

    config = AgentConfig(name="quality_director", system_prompt="")
    director = QualityDirectorAgent(
        config=config,
        llm=llm,
        bus=bus,
        db=db,
        warm_memory=warm,
        settings=settings,
        task_store=task_store,
        quality_store=quality_store,
        rule_engine=rule_engine,
        state_manager=state_manager,
    )
    return director, bus, llm, quality_store, rule_engine, task_store, state_manager


class TestAuditAllPass:
    @pytest.mark.asyncio
    async def test_all_pass_publishes_success(self, monkeypatch):
        director, bus, llm, qstore, rengine, tstore, smgr = _make_director(monkeypatch)

        task_id = uuid.uuid4()
        subtask_id = uuid.uuid4()

        # Mock auditor to return pass
        with patch("max.quality.director.AuditorAgent") as MockAuditor:
            mock_auditor = AsyncMock()
            mock_auditor.run = AsyncMock(
                return_value={
                    "verdict": "pass",
                    "score": 0.85,
                    "goal_alignment": 0.9,
                    "confidence": 0.95,
                    "issues": [],
                    "fix_instructions": None,
                    "strengths": ["Good"],
                    "reasoning": "Well done",
                }
            )
            MockAuditor.return_value = mock_auditor

            request = AuditRequest(
                task_id=task_id,
                goal_anchor="Test goal",
                subtask_results=[
                    SubtaskAuditItem(
                        subtask_id=subtask_id,
                        description="Write code",
                        content="def hello(): pass",
                    ),
                ],
            )
            await director.on_audit_request("audit.request", request.model_dump(mode="json"))

        # Should publish audit.complete with success=True
        publish_calls = [
            c for c in bus.publish.call_args_list if c[0][0] == "audit.complete"
        ]
        assert len(publish_calls) == 1
        payload = publish_calls[0][0][1]
        assert payload["success"] is True
        assert payload["overall_score"] == pytest.approx(0.85)


class TestAuditWithFailure:
    @pytest.mark.asyncio
    async def test_failure_publishes_fix_instructions(self, monkeypatch):
        director, bus, llm, qstore, rengine, tstore, smgr = _make_director(monkeypatch)

        task_id = uuid.uuid4()
        subtask_id = uuid.uuid4()

        with patch("max.quality.director.AuditorAgent") as MockAuditor:
            mock_auditor = AsyncMock()
            mock_auditor.run = AsyncMock(
                return_value={
                    "verdict": "fail",
                    "score": 0.3,
                    "goal_alignment": 0.4,
                    "confidence": 0.9,
                    "issues": [{"category": "quality", "description": "Incomplete"}],
                    "fix_instructions": "Add more detail",
                    "strengths": [],
                    "reasoning": "Needs work",
                }
            )
            MockAuditor.return_value = mock_auditor

            request = AuditRequest(
                task_id=task_id,
                goal_anchor="Test goal",
                subtask_results=[
                    SubtaskAuditItem(
                        subtask_id=subtask_id,
                        description="Write code",
                        content="incomplete",
                    ),
                ],
            )
            await director.on_audit_request("audit.request", request.model_dump(mode="json"))

        publish_calls = [
            c for c in bus.publish.call_args_list if c[0][0] == "audit.complete"
        ]
        assert len(publish_calls) == 1
        payload = publish_calls[0][0][1]
        assert payload["success"] is False
        assert len(payload["fix_required"]) == 1


class TestConditionalVerdict:
    @pytest.mark.asyncio
    async def test_conditional_treated_as_pass(self, monkeypatch):
        director, bus, llm, qstore, rengine, tstore, smgr = _make_director(monkeypatch)

        task_id = uuid.uuid4()

        with patch("max.quality.director.AuditorAgent") as MockAuditor:
            mock_auditor = AsyncMock()
            mock_auditor.run = AsyncMock(
                return_value={
                    "verdict": "conditional",
                    "score": 0.65,
                    "goal_alignment": 0.7,
                    "confidence": 0.5,
                    "issues": [{"category": "minor", "description": "Small issue"}],
                    "fix_instructions": None,
                    "strengths": [],
                    "reasoning": "Mostly ok",
                }
            )
            MockAuditor.return_value = mock_auditor

            request = AuditRequest(
                task_id=task_id,
                goal_anchor="Test",
                subtask_results=[
                    SubtaskAuditItem(
                        subtask_id=uuid.uuid4(),
                        description="test",
                        content="output",
                    ),
                ],
            )
            await director.on_audit_request("audit.request", request.model_dump(mode="json"))

        publish_calls = [
            c for c in bus.publish.call_args_list if c[0][0] == "audit.complete"
        ]
        assert len(publish_calls) == 1
        assert publish_calls[0][0][1]["success"] is True


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_subscribes(self, monkeypatch):
        director, bus, *_ = _make_director(monkeypatch)
        await director.start()
        channels = [c[0][0] for c in bus.subscribe.call_args_list]
        assert "audit.request" in channels

    @pytest.mark.asyncio
    async def test_stop_unsubscribes(self, monkeypatch):
        director, bus, *_ = _make_director(monkeypatch)
        await director.stop()
        channels = [c[0][0] for c in bus.unsubscribe.call_args_list]
        assert "audit.request" in channels


class TestRuleExtraction:
    @pytest.mark.asyncio
    async def test_extracts_rules_on_failure(self, monkeypatch):
        director, bus, llm, qstore, rengine, tstore, smgr = _make_director(monkeypatch)

        with patch("max.quality.director.AuditorAgent") as MockAuditor:
            mock_auditor = AsyncMock()
            mock_auditor.run = AsyncMock(
                return_value={
                    "verdict": "fail",
                    "score": 0.2,
                    "goal_alignment": 0.3,
                    "confidence": 0.9,
                    "issues": [{"category": "validation", "description": "No validation"}],
                    "fix_instructions": "Add validation",
                    "strengths": [],
                    "reasoning": "Missing validation",
                }
            )
            MockAuditor.return_value = mock_auditor

            request = AuditRequest(
                task_id=uuid.uuid4(),
                goal_anchor="Test",
                subtask_results=[
                    SubtaskAuditItem(
                        subtask_id=uuid.uuid4(),
                        description="test",
                        content="output",
                    ),
                ],
            )
            await director.on_audit_request("audit.request", request.model_dump(mode="json"))

        rengine.extract_rules.assert_called_once()

    @pytest.mark.asyncio
    async def test_extracts_patterns_on_high_score(self, monkeypatch):
        director, bus, llm, qstore, rengine, tstore, smgr = _make_director(monkeypatch)

        with patch("max.quality.director.AuditorAgent") as MockAuditor:
            mock_auditor = AsyncMock()
            mock_auditor.run = AsyncMock(
                return_value={
                    "verdict": "pass",
                    "score": 0.95,
                    "goal_alignment": 0.98,
                    "confidence": 0.95,
                    "issues": [],
                    "fix_instructions": None,
                    "strengths": ["Excellent error handling"],
                    "reasoning": "Outstanding",
                }
            )
            MockAuditor.return_value = mock_auditor

            request = AuditRequest(
                task_id=uuid.uuid4(),
                goal_anchor="Test",
                subtask_results=[
                    SubtaskAuditItem(
                        subtask_id=uuid.uuid4(),
                        description="test",
                        content="output",
                    ),
                ],
            )
            await director.on_audit_request("audit.request", request.model_dump(mode="json"))

        rengine.extract_patterns.assert_called_once()


class TestLedgerRecording:
    @pytest.mark.asyncio
    async def test_records_verdict_to_ledger(self, monkeypatch):
        director, bus, llm, qstore, rengine, tstore, smgr = _make_director(monkeypatch)

        with patch("max.quality.director.AuditorAgent") as MockAuditor:
            mock_auditor = AsyncMock()
            mock_auditor.run = AsyncMock(
                return_value={
                    "verdict": "pass", "score": 0.8, "goal_alignment": 0.85,
                    "confidence": 0.9, "issues": [], "fix_instructions": None,
                    "strengths": [], "reasoning": "ok",
                }
            )
            MockAuditor.return_value = mock_auditor

            request = AuditRequest(
                task_id=uuid.uuid4(),
                goal_anchor="Test",
                subtask_results=[
                    SubtaskAuditItem(subtask_id=uuid.uuid4(), description="t", content="c"),
                ],
            )
            await director.on_audit_request("audit.request", request.model_dump(mode="json"))

        qstore.record_verdict.assert_called_once()
        qstore.create_audit_report.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_quality_director.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement QualityDirectorAgent**

Create `src/max/quality/director.py`:

```python
"""QualityDirectorAgent -- audit lifecycle, verdict aggregation, learning."""

from __future__ import annotations

import asyncio
import logging
import uuid as uuid_mod
from typing import Any

from max.agents.base import AgentConfig, AgentContext, BaseAgent
from max.command.task_store import TaskStore
from max.config import Settings
from max.llm.client import LLMClient
from max.memory.coordinator_state import CoordinatorStateManager
from max.memory.models import ActiveAudit, RecentVerdict
from max.models.tasks import AuditVerdict
from max.quality.auditor import AuditorAgent
from max.quality.models import (
    AuditRequest,
    AuditResponse,
    FixInstruction,
    SubtaskAuditItem,
    SubtaskVerdict,
)
from max.quality.rules import RuleEngine
from max.quality.store import QualityStore

logger = logging.getLogger(__name__)


class QualityDirectorAgent(BaseAgent):
    """Manages the audit lifecycle — spawns auditors, aggregates verdicts, learns."""

    def __init__(
        self,
        config: AgentConfig,
        llm: LLMClient,
        bus: Any,
        db: Any,
        warm_memory: Any,
        settings: Settings,
        task_store: TaskStore,
        quality_store: QualityStore,
        rule_engine: RuleEngine,
        state_manager: CoordinatorStateManager,
    ) -> None:
        context = AgentContext(bus=bus, db=db, warm_memory=warm_memory)
        super().__init__(config=config, llm=llm, context=context)
        self._bus = bus
        self._db = db
        self._warm = warm_memory
        self._settings = settings
        self._task_store = task_store
        self._quality_store = quality_store
        self._rule_engine = rule_engine
        self._state_manager = state_manager

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """BaseAgent abstract method — not used directly."""
        return {}

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        await self._bus.subscribe("audit.request", self.on_audit_request)
        await self.on_start()
        logger.info("QualityDirectorAgent started")

    async def stop(self) -> None:
        await self._bus.unsubscribe("audit.request", self.on_audit_request)
        await self.on_stop()
        logger.info("QualityDirectorAgent stopped")

    # ── Event handler ───────────────────────────────────────────────────

    async def on_audit_request(self, channel: str, data: dict[str, Any]) -> None:
        """Handle an audit request: spawn auditors, aggregate, publish response."""
        raw_id = data.get("task_id")
        if raw_id is None:
            logger.error("on_audit_request received data without task_id: %s", data)
            return

        request = AuditRequest.model_validate(data)
        task_id = request.task_id
        goal_anchor = request.goal_anchor

        # Get active quality rules for auditors
        active_rules = await self._rule_engine.get_rules_for_audit()

        # Spawn auditors concurrently
        audit_tasks = []
        for item in request.subtask_results:
            audit_tasks.append(self._audit_subtask(item, goal_anchor, active_rules))

        results = await asyncio.gather(*audit_tasks, return_exceptions=True)

        # Aggregate verdicts
        verdicts: list[SubtaskVerdict] = []
        fix_required: list[FixInstruction] = []
        all_pass = True

        for i, result in enumerate(results):
            item = request.subtask_results[i]

            if isinstance(result, BaseException):
                logger.error("Auditor raised exception for subtask %s: %s", item.subtask_id, result)
                # Treat exception as conditional (pass with warning)
                verdict_data = {
                    "verdict": "conditional",
                    "score": 0.5,
                    "goal_alignment": 0.5,
                    "confidence": 0.3,
                    "issues": [],
                    "fix_instructions": None,
                    "strengths": [],
                    "reasoning": f"Audit error: {result}",
                }
            else:
                verdict_data = result

            verdict_str = verdict_data.get("verdict", "conditional")
            score = verdict_data.get("score", 0.5)
            goal_alignment = verdict_data.get("goal_alignment", 0.5)
            confidence = verdict_data.get("confidence", 0.5)
            issues = verdict_data.get("issues", [])
            fix_instructions = verdict_data.get("fix_instructions")
            strengths = verdict_data.get("strengths", [])

            # Map verdict string to enum
            try:
                verdict_enum = AuditVerdict(verdict_str)
            except ValueError:
                verdict_enum = AuditVerdict.CONDITIONAL

            # Store audit report
            report_id = uuid_mod.uuid4()
            await self._quality_store.create_audit_report(
                report_id=report_id,
                task_id=task_id,
                subtask_id=item.subtask_id,
                verdict=verdict_enum,
                score=score,
                goal_alignment=goal_alignment,
                confidence=confidence,
                issues=issues,
                fix_instructions=fix_instructions,
                strengths=strengths,
            )

            # Record verdict in ledger
            await self._quality_store.record_verdict(
                task_id=task_id,
                subtask_id=item.subtask_id,
                verdict=verdict_enum,
                score=score,
                metadata={"goal_alignment": goal_alignment, "confidence": confidence},
            )

            verdicts.append(
                SubtaskVerdict(
                    subtask_id=item.subtask_id,
                    verdict=verdict_enum,
                    score=score,
                    goal_alignment=goal_alignment,
                    issues=issues,
                )
            )

            if verdict_enum == AuditVerdict.FAIL:
                all_pass = False
                fix_required.append(
                    FixInstruction(
                        subtask_id=item.subtask_id,
                        instructions=fix_instructions or "Fix the identified issues",
                        original_content=item.content,
                        issues=issues,
                    )
                )

                # Extract rules from failure
                await self._rule_engine.extract_rules(
                    audit_id=report_id,
                    issues=issues,
                    subtask_description=item.description,
                    output_content=item.content,
                )

            elif verdict_enum == AuditVerdict.PASS and score >= self._settings.quality_high_score_threshold:
                # Extract patterns from high-scoring success
                await self._rule_engine.extract_patterns(
                    task_id=task_id,
                    strengths=strengths,
                    subtask_description=item.description,
                    output_content=item.content,
                )

        # Compute overall score
        overall_score = (
            sum(v.score for v in verdicts) / len(verdicts) if verdicts else 0.0
        )

        # Build and publish response
        response = AuditResponse(
            task_id=task_id,
            success=all_pass,
            verdicts=verdicts,
            overall_score=overall_score,
            fix_required=fix_required,
        )
        await self._bus.publish("audit.complete", response.model_dump(mode="json"))

        # Update coordinator state
        await self._update_audit_state(task_id, verdicts, overall_score)

    # ── Internal helpers ────────────────────────────────────────────────

    async def _audit_subtask(
        self,
        item: SubtaskAuditItem,
        goal_anchor: str,
        active_rules: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Spawn a single auditor for one subtask."""
        auditor = AuditorAgent(llm=self.llm)
        return await auditor.run(
            {
                "goal_anchor": goal_anchor,
                "subtask_description": item.description,
                "content": item.content,
                "quality_criteria": item.quality_criteria,
                "quality_rules": active_rules,
            }
        )

    async def _update_audit_state(
        self,
        task_id: uuid_mod.UUID,
        verdicts: list[SubtaskVerdict],
        overall_score: float,
    ) -> None:
        """Update audit pipeline state on coordinator state."""
        try:
            state = await self._state_manager.load()
            pipeline = state.audit_pipeline

            # Add recent verdict
            avg_verdict = "pass" if all(v.verdict != AuditVerdict.FAIL for v in verdicts) else "fail"
            pipeline.recent_verdicts.append(
                RecentVerdict(task_id=task_id, verdict=avg_verdict, score=overall_score)
            )
            # Cap recent verdicts
            max_recent = self._settings.quality_max_recent_verdicts
            if len(pipeline.recent_verdicts) > max_recent:
                pipeline.recent_verdicts = pipeline.recent_verdicts[-max_recent:]

            # Update quality pulse
            pass_rate = await self._quality_store.get_pass_rate(hours=24)
            avg_score = await self._quality_store.get_avg_score(hours=24)
            pipeline.quality_pulse.avg_score_last_24h = avg_score
            pipeline.quality_pulse.pass_rate_last_24h = pass_rate

            if avg_verdict == "fail":
                pipeline.quality_pulse.consecutive_failures += 1
            else:
                pipeline.quality_pulse.consecutive_failures = 0

            # Determine trend
            if len(pipeline.recent_verdicts) >= 5:
                recent_scores = [v.score for v in pipeline.recent_verdicts[-5:]]
                older_scores = [v.score for v in pipeline.recent_verdicts[-10:-5]] if len(pipeline.recent_verdicts) >= 10 else []
                if older_scores:
                    recent_avg = sum(recent_scores) / len(recent_scores)
                    older_avg = sum(older_scores) / len(older_scores)
                    if recent_avg > older_avg + 0.05:
                        pipeline.quality_pulse.trend = "improving"
                    elif recent_avg < older_avg - 0.05:
                        pipeline.quality_pulse.trend = "declining"
                    else:
                        pipeline.quality_pulse.trend = "stable"

            await self._state_manager.save(state)
        except Exception:
            logger.exception("Failed to update audit state")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_quality_director.py -v`
Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add src/max/quality/director.py tests/test_quality_director.py
git commit -m "feat(quality): add QualityDirectorAgent with audit lifecycle management"
```

---

### Task 7: Orchestrator modifications (audit integration + fix loop)

**Files:**
- Modify: `src/max/command/orchestrator.py`
- Create: `tests/test_orchestrator_audit.py`

- [ ] **Step 1: Write failing tests for Orchestrator audit integration**

Create `tests/test_orchestrator_audit.py`:

```python
"""Tests for Orchestrator audit integration and fix loop."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from max.agents.base import AgentConfig
from max.command.models import ExecutionPlan, PlannedSubtask, SubtaskResult
from max.command.orchestrator import OrchestratorAgent
from max.config import Settings
from max.llm.models import LLMResponse


def _make_settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    return Settings()


def _make_orchestrator(monkeypatch):
    settings = _make_settings(monkeypatch)
    llm = AsyncMock()
    bus = AsyncMock()
    bus.subscribe = AsyncMock()
    bus.unsubscribe = AsyncMock()
    bus.publish = AsyncMock()
    db = AsyncMock()
    warm = AsyncMock()
    task_store = AsyncMock()
    runner = AsyncMock()

    config = AgentConfig(name="orchestrator", system_prompt="")
    orch = OrchestratorAgent(
        config=config, llm=llm, bus=bus, db=db,
        warm_memory=warm, settings=settings,
        task_store=task_store, runner=runner,
    )
    return orch, bus, task_store, runner


class TestAuditRequestPublished:
    @pytest.mark.asyncio
    async def test_publishes_audit_request_on_success(self, monkeypatch):
        orch, bus, task_store, runner = _make_orchestrator(monkeypatch)

        task_id = uuid.uuid4()
        subtask_id = uuid.uuid4()

        task_store.get_subtasks.return_value = [
            {
                "id": subtask_id,
                "description": "Write code",
                "phase_number": 1,
                "quality_criteria": {},
                "status": "pending",
            }
        ]
        runner.run.return_value = SubtaskResult(
            subtask_id=subtask_id, task_id=task_id,
            success=True, content="Hello world", confidence=0.9,
        )

        plan = ExecutionPlan(
            task_id=task_id, goal_anchor="Test",
            subtasks=[PlannedSubtask(description="Write code", phase_number=1)],
            total_phases=1, reasoning="test",
        )
        await orch.on_execute("tasks.execute", plan.model_dump(mode="json"))

        # Should publish audit.request instead of tasks.complete
        channels = [c[0][0] for c in bus.publish.call_args_list]
        assert "audit.request" in channels
        assert "tasks.complete" not in channels


class TestAuditCompleteSuccess:
    @pytest.mark.asyncio
    async def test_publishes_tasks_complete_on_audit_pass(self, monkeypatch):
        orch, bus, task_store, runner = _make_orchestrator(monkeypatch)

        task_id = uuid.uuid4()
        subtask_id = uuid.uuid4()

        # Pre-populate pending audit
        orch._pending_audits[task_id] = {
            "prior_results": [
                SubtaskResult(
                    subtask_id=subtask_id, task_id=task_id,
                    success=True, content="Hello world", confidence=0.9,
                ),
            ],
            "db_subtasks": [{"id": subtask_id, "description": "test", "quality_criteria": {}}],
            "fix_attempt": 0,
            "goal_anchor": "Test",
            "quality_criteria": {},
        }

        task_store.create_result = AsyncMock(return_value=uuid.uuid4())

        audit_response = {
            "task_id": str(task_id),
            "success": True,
            "verdicts": [
                {
                    "subtask_id": str(subtask_id),
                    "verdict": "pass",
                    "score": 0.85,
                    "goal_alignment": 0.9,
                    "issues": [],
                }
            ],
            "overall_score": 0.85,
            "fix_required": [],
        }
        await orch.on_audit_complete("audit.complete", audit_response)

        channels = [c[0][0] for c in bus.publish.call_args_list]
        assert "tasks.complete" in channels
        complete_payload = next(
            c[0][1] for c in bus.publish.call_args_list if c[0][0] == "tasks.complete"
        )
        assert complete_payload["success"] is True


class TestFixLoop:
    @pytest.mark.asyncio
    async def test_reexecutes_failed_subtasks(self, monkeypatch):
        orch, bus, task_store, runner = _make_orchestrator(monkeypatch)

        task_id = uuid.uuid4()
        failed_id = uuid.uuid4()
        pass_id = uuid.uuid4()

        orch._pending_audits[task_id] = {
            "prior_results": [
                SubtaskResult(subtask_id=pass_id, task_id=task_id, success=True, content="good", confidence=0.9),
                SubtaskResult(subtask_id=failed_id, task_id=task_id, success=True, content="bad", confidence=0.8),
            ],
            "db_subtasks": [
                {"id": pass_id, "description": "passed task", "quality_criteria": {}, "phase_number": 1},
                {"id": failed_id, "description": "failed task", "quality_criteria": {}, "phase_number": 1},
            ],
            "fix_attempt": 0,
            "goal_anchor": "Test",
            "quality_criteria": {},
        }

        runner.run.return_value = SubtaskResult(
            subtask_id=failed_id, task_id=task_id,
            success=True, content="fixed output", confidence=0.9,
        )

        audit_response = {
            "task_id": str(task_id),
            "success": False,
            "verdicts": [
                {"subtask_id": str(pass_id), "verdict": "pass", "score": 0.9, "goal_alignment": 0.9, "issues": []},
                {"subtask_id": str(failed_id), "verdict": "fail", "score": 0.3, "goal_alignment": 0.4, "issues": [{"category": "q", "description": "bad"}]},
            ],
            "overall_score": 0.6,
            "fix_required": [
                {
                    "subtask_id": str(failed_id),
                    "instructions": "Fix the issues",
                    "original_content": "bad",
                    "issues": [{"category": "q", "description": "bad"}],
                }
            ],
        }
        await orch.on_audit_complete("audit.complete", audit_response)

        # Should re-execute only the failed subtask
        runner.run.assert_called_once()
        # Should publish audit.request again (for re-audit)
        audit_req_calls = [c for c in bus.publish.call_args_list if c[0][0] == "audit.request"]
        assert len(audit_req_calls) == 1

    @pytest.mark.asyncio
    async def test_fails_after_max_fix_attempts(self, monkeypatch):
        orch, bus, task_store, runner = _make_orchestrator(monkeypatch)

        task_id = uuid.uuid4()
        subtask_id = uuid.uuid4()

        orch._pending_audits[task_id] = {
            "prior_results": [
                SubtaskResult(subtask_id=subtask_id, task_id=task_id, success=True, content="bad", confidence=0.8),
            ],
            "db_subtasks": [{"id": subtask_id, "description": "test", "quality_criteria": {}, "phase_number": 1}],
            "fix_attempt": 2,  # Already at max
            "goal_anchor": "Test",
            "quality_criteria": {},
        }

        audit_response = {
            "task_id": str(task_id),
            "success": False,
            "verdicts": [
                {"subtask_id": str(subtask_id), "verdict": "fail", "score": 0.3, "goal_alignment": 0.4, "issues": [{"category": "q", "description": "bad"}]},
            ],
            "overall_score": 0.3,
            "fix_required": [
                {"subtask_id": str(subtask_id), "instructions": "Fix it", "original_content": "bad", "issues": []},
            ],
        }
        await orch.on_audit_complete("audit.complete", audit_response)

        # Should publish tasks.complete with failure (not re-execute)
        channels = [c[0][0] for c in bus.publish.call_args_list]
        assert "tasks.complete" in channels
        complete = next(c[0][1] for c in bus.publish.call_args_list if c[0][0] == "tasks.complete")
        assert complete["success"] is False


class TestAuditSubscription:
    @pytest.mark.asyncio
    async def test_start_subscribes_to_audit_complete(self, monkeypatch):
        orch, bus, *_ = _make_orchestrator(monkeypatch)
        await orch.start()
        channels = [c[0][0] for c in bus.subscribe.call_args_list]
        assert "audit.complete" in channels
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_orchestrator_audit.py -v`
Expected: FAIL (missing `on_audit_complete`, `_pending_audits`, etc.)

- [ ] **Step 3: Modify Orchestrator to add audit integration**

In `src/max/command/orchestrator.py`, make these changes:

First, add imports at the top (after existing imports):

```python
from max.quality.models import AuditRequest, AuditResponse, SubtaskAuditItem
```

In `__init__`, add after `self._cancelled_tasks`:

```python
        self._pending_audits: dict[uuid_mod.UUID, dict[str, Any]] = {}
```

In `start()`, add a subscription:

```python
        await self._bus.subscribe("audit.complete", self.on_audit_complete)
```

In `stop()`, add an unsubscription:

```python
        await self._bus.unsubscribe("audit.complete", self.on_audit_complete)
```

Replace the "Assemble final result" block in `on_execute` (lines 170–204, starting with `# Assemble final result.`) with:

```python
        # Route to audit or fail.
        if all_succeeded and prior_results:
            # Build audit request (blind — no reasoning/confidence)
            audit_items = []
            for r in prior_results:
                st_info = next((s for s in db_subtasks if s["id"] == r.subtask_id), None)
                audit_items.append(
                    SubtaskAuditItem(
                        subtask_id=r.subtask_id,
                        description=st_info["description"] if st_info else "",
                        content=r.content,
                        quality_criteria=st_info.get("quality_criteria", {}) if st_info else {},
                    )
                )

            task_data = await self._task_store.get_task(task_id)
            goal_anchor = task_data["goal_anchor"] if task_data else plan.goal_anchor

            self._pending_audits[task_id] = {
                "prior_results": prior_results,
                "db_subtasks": db_subtasks,
                "fix_attempt": 0,
                "goal_anchor": goal_anchor,
                "quality_criteria": task_data.get("quality_criteria", {}) if task_data else {},
            }

            await self._task_store.update_task_status(task_id, TaskStatus.AUDITING)

            audit_req = AuditRequest(
                task_id=task_id,
                goal_anchor=goal_anchor,
                subtask_results=audit_items,
                quality_criteria=task_data.get("quality_criteria", {}) if task_data else {},
            )
            await self._bus.publish("audit.request", audit_req.model_dump(mode="json"))
        else:
            error_msgs = [r.error for r in failed_results if r.error]
            if not error_msgs:
                error_msgs = ["All subtasks failed"]

            await self._bus.publish(
                "tasks.complete",
                {
                    "task_id": str(task_id),
                    "success": False,
                    "error": "; ".join(error_msgs),
                },
            )

        # Clean up cancellation tracking to prevent unbounded growth.
        self._cancelled_tasks.discard(task_id)
```

Add `on_audit_complete` method after `on_context_update`:

```python
    async def on_audit_complete(self, channel: str, data: dict[str, Any]) -> None:
        """Handle audit results — complete task or trigger fix loop."""
        raw_id = data.get("task_id")
        if raw_id is None:
            logger.error("on_audit_complete received data without task_id: %s", data)
            return
        task_id = uuid_mod.UUID(raw_id)
        response = AuditResponse.model_validate(data)

        pending = self._pending_audits.pop(task_id, None)
        if pending is None:
            logger.error("on_audit_complete: no pending audit for task %s", task_id)
            return

        if response.success:
            # All subtasks passed audit — assemble final result
            prior_results = pending["prior_results"]
            combined_content = "\n\n".join(r.content for r in prior_results if r.content)
            avg_confidence = (
                sum(r.confidence for r in prior_results) / len(prior_results)
                if prior_results
                else 0.0
            )

            await self._task_store.create_result(
                task_id=task_id,
                content=combined_content,
                confidence=avg_confidence,
            )
            await self._bus.publish(
                "tasks.complete",
                {
                    "task_id": str(task_id),
                    "success": True,
                    "result_content": combined_content,
                    "confidence": avg_confidence,
                },
            )
        else:
            fix_attempt = pending["fix_attempt"]
            max_attempts = self._settings.quality_max_fix_attempts

            if fix_attempt >= max_attempts:
                # Exhausted fix attempts — fail the task
                issue_summary = "; ".join(
                    f.instructions for f in response.fix_required
                )
                await self._bus.publish(
                    "tasks.complete",
                    {
                        "task_id": str(task_id),
                        "success": False,
                        "error": f"Audit failed after {max_attempts} fix attempts: {issue_summary}",
                    },
                )
                return

            # Re-execute failed subtasks with fix instructions
            await self._task_store.update_task_status(task_id, TaskStatus.FIXING)

            failed_ids = {f.subtask_id for f in response.fix_required}
            fix_map = {f.subtask_id: f for f in response.fix_required}
            prior_results = pending["prior_results"]
            db_subtasks = pending["db_subtasks"]

            new_results: list[SubtaskResult] = []
            for r in prior_results:
                if r.subtask_id not in failed_ids:
                    new_results.append(r)

            for fix in response.fix_required:
                st_info = next((s for s in db_subtasks if s["id"] == fix.subtask_id), None)
                if st_info is None:
                    continue

                # Build augmented worker prompt with fix instructions
                description = st_info["description"]
                fix_prompt = (
                    f"{description}\n\n"
                    f"IMPORTANT: Your previous output was audited and found these issues:\n"
                    f"{fix.instructions}\n\n"
                    f"The specific problems were:\n"
                    + "\n".join(f"- [{iss.get('category', 'issue')}] {iss.get('description', '')}" for iss in fix.issues)
                )

                config = WorkerConfig(
                    subtask_id=fix.subtask_id,
                    task_id=task_id,
                    system_prompt=WORKER_BASE_PROMPT.format(
                        description=fix_prompt,
                        prior_results="(fix attempt — see audit feedback above)",
                    ),
                    quality_criteria=st_info.get("quality_criteria", {}),
                )
                context = AgentContext(bus=self._bus, db=self._db, warm_memory=self._warm)

                try:
                    result = await asyncio.wait_for(
                        self._runner.run(config, context),
                        timeout=self._settings.worker_timeout_seconds,
                    )
                except TimeoutError:
                    result = SubtaskResult(
                        subtask_id=fix.subtask_id,
                        task_id=task_id,
                        success=False,
                        error=f"Worker timed out during fix attempt",
                    )

                if result.success:
                    new_results.append(result)
                    await self._task_store.update_subtask_result(
                        result.subtask_id,
                        {"content": result.content, "confidence": result.confidence, "reasoning": result.reasoning},
                    )
                else:
                    # Fix attempt itself failed — mark task as failed
                    await self._bus.publish(
                        "tasks.complete",
                        {"task_id": str(task_id), "success": False, "error": result.error or "Fix attempt failed"},
                    )
                    return

            # Re-audit with new results
            audit_items = []
            for r in new_results:
                st_info = next((s for s in db_subtasks if s["id"] == r.subtask_id), None)
                audit_items.append(
                    SubtaskAuditItem(
                        subtask_id=r.subtask_id,
                        description=st_info["description"] if st_info else "",
                        content=r.content,
                        quality_criteria=st_info.get("quality_criteria", {}) if st_info else {},
                    )
                )

            self._pending_audits[task_id] = {
                "prior_results": new_results,
                "db_subtasks": db_subtasks,
                "fix_attempt": fix_attempt + 1,
                "goal_anchor": pending["goal_anchor"],
                "quality_criteria": pending["quality_criteria"],
            }

            await self._task_store.update_task_status(task_id, TaskStatus.AUDITING)

            audit_req = AuditRequest(
                task_id=task_id,
                goal_anchor=pending["goal_anchor"],
                subtask_results=audit_items,
                quality_criteria=pending["quality_criteria"],
            )
            await self._bus.publish("audit.request", audit_req.model_dump(mode="json"))
```

Also add the import for `WorkerConfig` at the top if not already there (it should already be imported).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_orchestrator_audit.py -v`
Expected: 5 PASS

- [ ] **Step 5: Run existing orchestrator tests to verify no regressions**

Run: `uv run python -m pytest tests/test_orchestrator.py --tb=short -q`
Expected: All existing tests still pass (the audit.request publish replaces tasks.complete in the success path, but existing tests that mock the bus will still work since they check bus.publish calls)

Note: Some existing orchestrator tests may need adjustment since `on_execute` now publishes `audit.request` instead of `tasks.complete` in the success path. If any tests fail because they expect `tasks.complete` after successful execution, update them to expect `audit.request` instead. The `tasks.complete` logic has moved to `on_audit_complete`.

- [ ] **Step 6: Commit**

```bash
git add src/max/command/orchestrator.py tests/test_orchestrator_audit.py
git commit -m "feat(command): integrate audit pipeline into Orchestrator with fix loop"
```

---

### Task 8: Package exports + __init__.py update

**Files:**
- Modify: `src/max/quality/__init__.py`

- [ ] **Step 1: Update __init__.py with all public exports**

Update `src/max/quality/__init__.py`:

```python
"""Phase 5: Quality Gate — audit pipeline, rules engine, quality ledger."""

from max.quality.auditor import AuditorAgent
from max.quality.director import QualityDirectorAgent
from max.quality.models import (
    AuditRequest,
    AuditResponse,
    FixInstruction,
    QualityPattern,
    SubtaskAuditItem,
    SubtaskVerdict,
)
from max.quality.rules import RuleEngine
from max.quality.store import QualityStore

__all__ = [
    "AuditorAgent",
    "AuditRequest",
    "AuditResponse",
    "FixInstruction",
    "QualityDirectorAgent",
    "QualityPattern",
    "QualityStore",
    "RuleEngine",
    "SubtaskAuditItem",
    "SubtaskVerdict",
]
```

- [ ] **Step 2: Verify imports work**

Run: `uv run python -c "from max.quality import QualityDirectorAgent, AuditorAgent, QualityStore, RuleEngine; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/max/quality/__init__.py
git commit -m "feat(quality): add package exports for quality gate"
```

---

### Task 9: Integration tests

**Files:**
- Create: `tests/test_quality_integration.py`

- [ ] **Step 1: Write integration tests for full audit pipeline**

Create `tests/test_quality_integration.py`:

```python
"""End-to-end integration tests for the Quality Gate pipeline.

Tests the full flow: Orchestrator → audit.request → Quality Director → audit.complete → Orchestrator → tasks.complete.
All LLM calls are mocked. Bus publications are tracked and manually routed.
"""

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from max.agents.base import AgentConfig
from max.command.models import ExecutionPlan, PlannedSubtask, SubtaskResult
from max.command.orchestrator import OrchestratorAgent
from max.config import Settings
from max.llm.models import LLMResponse
from max.quality.director import QualityDirectorAgent
from max.quality.models import AuditRequest


def _make_settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    return Settings()


def _make_llm_response(data: dict | str) -> LLMResponse:
    text = json.dumps(data) if isinstance(data, dict) else data
    return LLMResponse(
        text=text, input_tokens=100, output_tokens=50,
        model="claude-opus-4-6", stop_reason="end_turn",
    )


class TestFullAuditPipeline:
    @pytest.mark.asyncio
    async def test_happy_path_with_audit(self, monkeypatch):
        """Orchestrator → audit.request → Director → audit.complete → tasks.complete."""
        settings = _make_settings(monkeypatch)
        publications: list[tuple[str, dict]] = []

        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.unsubscribe = AsyncMock()

        async def capture_publish(channel, data):
            publications.append((channel, data))

        bus.publish = AsyncMock(side_effect=capture_publish)

        llm = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()
        task_store = AsyncMock()
        runner = AsyncMock()
        quality_store = AsyncMock()
        quality_store.get_active_rules = AsyncMock(return_value=[])
        quality_store.create_audit_report = AsyncMock()
        quality_store.record_verdict = AsyncMock()
        quality_store.get_pass_rate = AsyncMock(return_value=0.85)
        quality_store.get_avg_score = AsyncMock(return_value=0.80)
        rule_engine = AsyncMock()
        rule_engine.get_rules_for_audit = AsyncMock(return_value=[])
        rule_engine.extract_rules = AsyncMock(return_value=[])
        rule_engine.extract_patterns = AsyncMock(return_value=[])
        state_manager = AsyncMock()

        from max.memory.models import CoordinatorState

        state_manager.load = AsyncMock(return_value=CoordinatorState())
        state_manager.save = AsyncMock()

        # Create orchestrator
        orch_config = AgentConfig(name="orchestrator", system_prompt="")
        orch = OrchestratorAgent(
            config=orch_config, llm=llm, bus=bus, db=db,
            warm_memory=warm, settings=settings,
            task_store=task_store, runner=runner,
        )

        # Create director
        dir_config = AgentConfig(name="quality_director", system_prompt="")
        director = QualityDirectorAgent(
            config=dir_config, llm=llm, bus=bus, db=db,
            warm_memory=warm, settings=settings,
            task_store=task_store, quality_store=quality_store,
            rule_engine=rule_engine, state_manager=state_manager,
        )

        task_id = uuid.uuid4()
        subtask_id = uuid.uuid4()

        # Setup: task_store returns subtasks
        task_store.get_subtasks.return_value = [
            {"id": subtask_id, "description": "Write code", "phase_number": 1,
             "quality_criteria": {}, "status": "pending"},
        ]
        task_store.get_task.return_value = {
            "id": task_id, "goal_anchor": "Build feature",
            "quality_criteria": {}, "status": "in_progress",
        }
        task_store.create_result = AsyncMock(return_value=uuid.uuid4())
        task_store.update_task_status = AsyncMock()
        task_store.update_subtask_status = AsyncMock()
        task_store.update_subtask_result = AsyncMock()

        # Setup: worker returns success
        runner.run.return_value = SubtaskResult(
            subtask_id=subtask_id, task_id=task_id,
            success=True, content="Hello world", confidence=0.9,
        )

        # Step 1: Orchestrator receives execution plan
        plan = ExecutionPlan(
            task_id=task_id, goal_anchor="Build feature",
            subtasks=[PlannedSubtask(description="Write code", phase_number=1)],
            total_phases=1, reasoning="test",
        )
        await orch.on_execute("tasks.execute", plan.model_dump(mode="json"))

        # Verify audit.request was published
        audit_reqs = [(ch, d) for ch, d in publications if ch == "audit.request"]
        assert len(audit_reqs) == 1

        # Step 2: Route audit.request to Director
        with patch("max.quality.director.AuditorAgent") as MockAuditor:
            mock_auditor = AsyncMock()
            mock_auditor.run = AsyncMock(return_value={
                "verdict": "pass", "score": 0.85, "goal_alignment": 0.9,
                "confidence": 0.95, "issues": [], "fix_instructions": None,
                "strengths": ["Clean code"], "reasoning": "Good",
            })
            MockAuditor.return_value = mock_auditor
            await director.on_audit_request("audit.request", audit_reqs[0][1])

        # Verify audit.complete was published
        audit_completes = [(ch, d) for ch, d in publications if ch == "audit.complete"]
        assert len(audit_completes) == 1
        assert audit_completes[0][1]["success"] is True

        # Step 3: Route audit.complete back to Orchestrator
        await orch.on_audit_complete("audit.complete", audit_completes[0][1])

        # Verify tasks.complete was published
        task_completes = [(ch, d) for ch, d in publications if ch == "tasks.complete"]
        assert len(task_completes) == 1
        assert task_completes[0][1]["success"] is True
        assert "Hello world" in task_completes[0][1]["result_content"]


class TestFixLoopPipeline:
    @pytest.mark.asyncio
    async def test_fix_and_reaudit(self, monkeypatch):
        """Test that a failed audit triggers a fix loop and re-audit."""
        settings = _make_settings(monkeypatch)
        publications: list[tuple[str, dict]] = []

        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.unsubscribe = AsyncMock()

        async def capture_publish(channel, data):
            publications.append((channel, data))

        bus.publish = AsyncMock(side_effect=capture_publish)

        llm = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()
        task_store = AsyncMock()
        runner = AsyncMock()
        quality_store = AsyncMock()
        quality_store.get_active_rules = AsyncMock(return_value=[])
        quality_store.create_audit_report = AsyncMock()
        quality_store.record_verdict = AsyncMock()
        quality_store.get_pass_rate = AsyncMock(return_value=0.85)
        quality_store.get_avg_score = AsyncMock(return_value=0.80)
        rule_engine = AsyncMock()
        rule_engine.get_rules_for_audit = AsyncMock(return_value=[])
        rule_engine.extract_rules = AsyncMock(return_value=[])
        rule_engine.extract_patterns = AsyncMock(return_value=[])
        state_manager = AsyncMock()

        from max.memory.models import CoordinatorState

        state_manager.load = AsyncMock(return_value=CoordinatorState())
        state_manager.save = AsyncMock()

        dir_config = AgentConfig(name="quality_director", system_prompt="")
        director = QualityDirectorAgent(
            config=dir_config, llm=llm, bus=bus, db=db,
            warm_memory=warm, settings=settings,
            task_store=task_store, quality_store=quality_store,
            rule_engine=rule_engine, state_manager=state_manager,
        )

        orch_config = AgentConfig(name="orchestrator", system_prompt="")
        orch = OrchestratorAgent(
            config=orch_config, llm=llm, bus=bus, db=db,
            warm_memory=warm, settings=settings,
            task_store=task_store, runner=runner,
        )

        task_id = uuid.uuid4()
        subtask_id = uuid.uuid4()

        task_store.get_task.return_value = {
            "id": task_id, "goal_anchor": "Build feature",
            "quality_criteria": {}, "status": "in_progress",
        }
        task_store.get_subtasks.return_value = [
            {"id": subtask_id, "description": "Write code", "phase_number": 1,
             "quality_criteria": {}, "status": "pending"},
        ]
        task_store.create_result = AsyncMock(return_value=uuid.uuid4())
        task_store.update_task_status = AsyncMock()
        task_store.update_subtask_status = AsyncMock()
        task_store.update_subtask_result = AsyncMock()

        # Worker initially returns "bad" content
        runner.run.return_value = SubtaskResult(
            subtask_id=subtask_id, task_id=task_id,
            success=True, content="bad output", confidence=0.8,
        )

        # Step 1: Orchestrator executes plan
        plan = ExecutionPlan(
            task_id=task_id, goal_anchor="Build feature",
            subtasks=[PlannedSubtask(description="Write code", phase_number=1)],
            total_phases=1, reasoning="test",
        )
        await orch.on_execute("tasks.execute", plan.model_dump(mode="json"))

        # Step 2: Director audits — FAIL
        audit_reqs = [(ch, d) for ch, d in publications if ch == "audit.request"]
        with patch("max.quality.director.AuditorAgent") as MockAuditor:
            mock_auditor = AsyncMock()
            mock_auditor.run = AsyncMock(return_value={
                "verdict": "fail", "score": 0.3, "goal_alignment": 0.4,
                "confidence": 0.9, "issues": [{"category": "quality", "description": "Bad"}],
                "fix_instructions": "Make it better", "strengths": [], "reasoning": "Needs work",
            })
            MockAuditor.return_value = mock_auditor
            await director.on_audit_request("audit.request", audit_reqs[0][1])

        # Step 3: Orchestrator receives fail → triggers fix loop
        audit_completes = [(ch, d) for ch, d in publications if ch == "audit.complete"]
        assert audit_completes[0][1]["success"] is False

        # Worker returns "fixed" content on second attempt
        runner.run.return_value = SubtaskResult(
            subtask_id=subtask_id, task_id=task_id,
            success=True, content="fixed output", confidence=0.9,
        )
        await orch.on_audit_complete("audit.complete", audit_completes[0][1])

        # Should have published a second audit.request
        all_audit_reqs = [(ch, d) for ch, d in publications if ch == "audit.request"]
        assert len(all_audit_reqs) == 2
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_quality_integration.py -v`
Expected: 2 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_quality_integration.py
git commit -m "test(quality): add end-to-end quality gate integration tests"
```

---

### Task 10: Lint, format, final test run

**Files:**
- All Phase 5 source and test files

- [ ] **Step 1: Run ruff format on all Phase 5 files**

```bash
uv run ruff format src/max/quality/ tests/test_quality_models.py tests/test_quality_store.py tests/test_auditor.py tests/test_quality_director.py tests/test_rule_engine.py tests/test_orchestrator_audit.py tests/test_quality_integration.py src/max/command/orchestrator.py src/max/config.py src/max/db/schema.sql tests/test_config.py tests/test_postgres.py
```

- [ ] **Step 2: Run ruff check --fix on all Phase 5 files**

```bash
uv run ruff check --fix src/max/quality/ tests/test_quality_models.py tests/test_quality_store.py tests/test_auditor.py tests/test_quality_director.py tests/test_rule_engine.py tests/test_orchestrator_audit.py tests/test_quality_integration.py src/max/command/orchestrator.py src/max/config.py
```

- [ ] **Step 3: Run full test suite**

```bash
uv run python -m pytest --tb=short -q
```

Expected: 370+ tests passing (316 existing + ~55 new)

- [ ] **Step 4: Commit any formatting changes**

```bash
git add -A
git commit -m "style: format and lint Phase 5 quality gate files"
```
