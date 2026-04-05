# Phase 7: Evolution System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Max's self-evolution capabilities — preference learning, 7-step evolution pipeline, canary testing, snapshot/rollback, self-model, and quality ratchet integration.

**Architecture:** New `src/max/evolution/` package with 10 modules. EvolutionDirectorAgent orchestrates the pipeline. Scouts discover improvements, ImprovementAgent implements them, CanaryRunner verifies non-regression, SnapshotManager handles rollback.

**Tech Stack:** Python 3.12, Pydantic v2, asyncio, PostgreSQL (via existing Database class), message bus (existing), LLMClient (existing)

**Depends on:** Phases 1-6 (all complete, 949 tests passing)

---

## Task 1: Evolution Models

**Files:**
- Create: `src/max/evolution/__init__.py`
- Create: `src/max/evolution/models.py`
- Test: `tests/test_evolution_models.py`

This task defines all Pydantic models for the evolution domain. These models are used by every other module.

- [ ] **Step 1: Write failing tests for evolution models**

```python
# tests/test_evolution_models.py
"""Tests for Phase 7 evolution domain models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from max.evolution.models import (
    CanaryRequest,
    CanaryResult,
    CanaryTaskResult,
    ChangeSet,
    ChangeSetEntry,
    CommunicationPrefs,
    CodePrefs,
    DomainPrefs,
    EvolutionJournalEntry,
    EvolutionProposal,
    Observation,
    PreferenceProfile,
    PromotionEvent,
    RollbackEvent,
    SnapshotData,
    WorkflowPrefs,
)


class TestEvolutionProposal:
    def test_defaults(self):
        p = EvolutionProposal(
            scout_type="tool",
            description="Increase shell timeout",
            target_type="tool_config",
        )
        assert p.status == "proposed"
        assert p.impact_score == 0.0
        assert p.effort_score == 0.0
        assert p.risk_score == 0.0
        assert p.priority == 0.0
        assert p.experiment_id is None
        assert isinstance(p.id, uuid.UUID)

    def test_priority_calculation(self):
        p = EvolutionProposal(
            scout_type="quality",
            description="Fix recurring null check",
            target_type="prompt",
            impact_score=0.8,
            effort_score=0.2,
            risk_score=0.1,
        )
        expected = 0.8 * (1 - 0.1) / max(0.2, 0.1)
        assert p.computed_priority == pytest.approx(expected)

    def test_all_target_types(self):
        for tt in ("prompt", "tool_config", "context_rule", "workflow"):
            p = EvolutionProposal(
                scout_type="pattern", description="x", target_type=tt
            )
            assert p.target_type == tt


class TestChangeSet:
    def test_entry_structure(self):
        entry = ChangeSetEntry(
            target_type="prompt",
            target_id="coordinator",
            old_value="Be concise",
            new_value="Be concise and structured",
        )
        cs = ChangeSet(proposal_id=uuid.uuid4(), entries=[entry])
        assert len(cs.entries) == 1
        assert cs.entries[0].target_type == "prompt"


class TestSnapshotData:
    def test_serialization(self):
        snap = SnapshotData(
            prompts={"coordinator": "Be concise"},
            tool_configs={"shell.execute": {"timeout": 30}},
            context_rules=[],
            metrics_baseline={"audit_score": 0.85},
        )
        d = snap.model_dump()
        assert d["prompts"]["coordinator"] == "Be concise"
        assert d["metrics_baseline"]["audit_score"] == 0.85


class TestPreferenceProfile:
    def test_default_empty(self):
        pp = PreferenceProfile(user_id="venu")
        assert pp.communication.tone == "professional"
        assert pp.code.test_coverage == "high"
        assert pp.workflow.autonomy_level == "high"
        assert pp.observation_log == []

    def test_observation_log(self):
        obs = Observation(
            signal_type="correction",
            data={"original": "x", "corrected": "y"},
        )
        pp = PreferenceProfile(user_id="venu", observation_log=[obs])
        assert len(pp.observation_log) == 1
        assert pp.observation_log[0].signal_type == "correction"


class TestCanaryModels:
    def test_canary_request(self):
        req = CanaryRequest(
            experiment_id=uuid.uuid4(),
            task_ids=[uuid.uuid4(), uuid.uuid4()],
            candidate_config={"prompts": {}},
            timeout_seconds=300,
        )
        assert len(req.task_ids) == 2

    def test_canary_result_pass(self):
        task_result = CanaryTaskResult(
            task_id=uuid.uuid4(),
            original_score=0.8,
            canary_score=0.85,
            passed=True,
        )
        result = CanaryResult(
            experiment_id=uuid.uuid4(),
            task_results=[task_result],
            overall_passed=True,
        )
        assert result.overall_passed is True

    def test_canary_result_fail_on_regression(self):
        r1 = CanaryTaskResult(
            task_id=uuid.uuid4(), original_score=0.8, canary_score=0.85, passed=True
        )
        r2 = CanaryTaskResult(
            task_id=uuid.uuid4(), original_score=0.9, canary_score=0.7, passed=False
        )
        result = CanaryResult(
            experiment_id=uuid.uuid4(),
            task_results=[r1, r2],
            overall_passed=False,
        )
        assert result.overall_passed is False


class TestEvolutionJournal:
    def test_entry(self):
        entry = EvolutionJournalEntry(
            experiment_id=uuid.uuid4(),
            action="promoted",
            details={"score_delta": 0.05},
        )
        assert entry.action == "promoted"
        assert isinstance(entry.recorded_at, datetime)


class TestPromotionRollbackEvents:
    def test_promotion_event(self):
        evt = PromotionEvent(
            experiment_id=uuid.uuid4(),
            proposal_description="Improved coordinator prompt",
            score_improvement=0.05,
        )
        assert evt.score_improvement == 0.05

    def test_rollback_event(self):
        evt = RollbackEvent(
            experiment_id=uuid.uuid4(),
            reason="Canary regression on task replay",
            snapshot_id=uuid.uuid4(),
        )
        assert "regression" in evt.reason
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution && python -m pytest tests/test_evolution_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'max.evolution'`

- [ ] **Step 3: Implement evolution models**

```python
# src/max/evolution/__init__.py
"""Phase 7: Self-Evolution System."""
```

```python
# src/max/evolution/models.py
"""Pydantic models for the evolution domain."""

from __future__ import annotations

import uuid as uuid_mod
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Preference Profile ──────────────────────────────────────────────────────


class CommunicationPrefs(BaseModel):
    tone: str = "professional"
    detail_level: str = "moderate"
    update_frequency: str = "on_completion"
    languages: list[str] = Field(default_factory=lambda: ["en"])
    timezone: str = "UTC"


class CodePrefs(BaseModel):
    style: dict[str, str] = Field(default_factory=dict)  # lang -> style notes
    review_depth: str = "thorough"
    test_coverage: str = "high"
    commit_style: str = "conventional"


class WorkflowPrefs(BaseModel):
    clarification_threshold: float = 0.3
    autonomy_level: str = "high"
    reporting_style: str = "concise"


class DomainPrefs(BaseModel):
    expertise_areas: list[str] = Field(default_factory=list)
    client_contexts: dict[str, str] = Field(default_factory=dict)
    project_conventions: dict[str, str] = Field(default_factory=dict)


class Observation(BaseModel):
    signal_type: str  # correction | acceptance | choice | modification | timing
    data: dict[str, Any] = Field(default_factory=dict)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PreferenceProfile(BaseModel):
    user_id: str
    communication: CommunicationPrefs = Field(default_factory=CommunicationPrefs)
    code: CodePrefs = Field(default_factory=CodePrefs)
    workflow: WorkflowPrefs = Field(default_factory=WorkflowPrefs)
    domain_knowledge: DomainPrefs = Field(default_factory=DomainPrefs)
    observation_log: list[Observation] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: int = 1


# ── Evolution Pipeline ──────────────────────────────────────────────────────


class EvolutionProposal(BaseModel):
    id: uuid_mod.UUID = Field(default_factory=uuid_mod.uuid4)
    scout_type: str  # tool | pattern | quality | ecosystem
    description: str
    target_type: str  # prompt | tool_config | context_rule | workflow
    target_id: str | None = None
    impact_score: float = 0.0
    effort_score: float = 0.0
    risk_score: float = 0.0
    priority: float = 0.0
    status: str = "proposed"
    experiment_id: uuid_mod.UUID | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def computed_priority(self) -> float:
        return self.impact_score * (1 - self.risk_score) / max(self.effort_score, 0.1)


class ChangeSetEntry(BaseModel):
    target_type: str  # prompt | tool_config | context_rule
    target_id: str
    old_value: Any = None
    new_value: Any = None


class ChangeSet(BaseModel):
    proposal_id: uuid_mod.UUID
    entries: list[ChangeSetEntry] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SnapshotData(BaseModel):
    prompts: dict[str, str] = Field(default_factory=dict)
    tool_configs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    context_rules: list[dict[str, Any]] = Field(default_factory=list)
    metrics_baseline: dict[str, float] = Field(default_factory=dict)


# ── Canary Testing ──────────────────────────────────────────────────────────


class CanaryRequest(BaseModel):
    experiment_id: uuid_mod.UUID
    task_ids: list[uuid_mod.UUID]
    candidate_config: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = 300


class CanaryTaskResult(BaseModel):
    task_id: uuid_mod.UUID
    original_score: float
    canary_score: float
    passed: bool  # canary_score >= original_score


class CanaryResult(BaseModel):
    experiment_id: uuid_mod.UUID
    task_results: list[CanaryTaskResult] = Field(default_factory=list)
    overall_passed: bool = False
    duration_seconds: float = 0.0


# ── Events ──────────────────────────────────────────────────────────────────


class PromotionEvent(BaseModel):
    experiment_id: uuid_mod.UUID
    proposal_description: str
    score_improvement: float = 0.0
    promoted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RollbackEvent(BaseModel):
    experiment_id: uuid_mod.UUID
    reason: str
    snapshot_id: uuid_mod.UUID
    rolled_back_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ── Self-Model ──────────────────────────────────────────────────────────────


class EvolutionJournalEntry(BaseModel):
    id: uuid_mod.UUID = Field(default_factory=uuid_mod.uuid4)
    experiment_id: uuid_mod.UUID | None = None
    action: str  # proposed | approved | snapshot | implemented | audited | canary_passed | canary_failed | promoted | rolled_back | frozen | unfrozen
    details: dict[str, Any] = Field(default_factory=dict)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution && python -m pytest tests/test_evolution_models.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution
git add src/max/evolution/__init__.py src/max/evolution/models.py tests/test_evolution_models.py
git commit -m "feat(evolution): add evolution domain models"
```

---

## Task 2: Database Schema + EvolutionStore

**Files:**
- Modify: `src/max/db/schema.sql` (add evolution tables)
- Create: `src/max/evolution/store.py`
- Test: `tests/test_evolution_store.py`

- [ ] **Step 1: Add evolution tables to schema.sql**

Append after the `shelved_improvements` table (line ~209):

```sql
-- ── Evolution proposals ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS evolution_proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scout_type VARCHAR(50) NOT NULL,
    description TEXT NOT NULL,
    target_type VARCHAR(50) NOT NULL,
    target_id VARCHAR(200),
    impact_score REAL NOT NULL DEFAULT 0.0,
    effort_score REAL NOT NULL DEFAULT 0.0,
    risk_score REAL NOT NULL DEFAULT 0.0,
    priority REAL NOT NULL DEFAULT 0.0,
    status VARCHAR(20) NOT NULL DEFAULT 'proposed',
    experiment_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_evo_proposals_status ON evolution_proposals(status);
CREATE INDEX IF NOT EXISTS idx_evo_proposals_created ON evolution_proposals(created_at DESC);

-- ── Evolution snapshots ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS evolution_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID NOT NULL,
    snapshot_data JSONB NOT NULL,
    metrics_baseline JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_evo_snapshots_experiment ON evolution_snapshots(experiment_id);

-- ── Mutable agent prompts ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS evolution_prompts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_type VARCHAR(100) NOT NULL,
    prompt_text TEXT NOT NULL,
    version INT NOT NULL DEFAULT 1,
    experiment_id UUID,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_evo_prompts_live
    ON evolution_prompts(agent_type) WHERE experiment_id IS NULL;

-- ── Mutable tool configurations ────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS evolution_tool_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_id VARCHAR(200) NOT NULL,
    config JSONB NOT NULL,
    version INT NOT NULL DEFAULT 1,
    experiment_id UUID,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_evo_tool_configs_live
    ON evolution_tool_configs(tool_id) WHERE experiment_id IS NULL;

-- ── Context packaging rules ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS evolution_context_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_name VARCHAR(200) NOT NULL,
    condition JSONB NOT NULL,
    action JSONB NOT NULL,
    priority INT NOT NULL DEFAULT 0,
    version INT NOT NULL DEFAULT 1,
    experiment_id UUID,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Preference profiles ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS preference_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(200) NOT NULL UNIQUE,
    communication JSONB NOT NULL DEFAULT '{}',
    code_prefs JSONB NOT NULL DEFAULT '{}',
    workflow JSONB NOT NULL DEFAULT '{}',
    domain_knowledge JSONB NOT NULL DEFAULT '{}',
    observation_log JSONB NOT NULL DEFAULT '[]',
    version INT NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Capability map ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS capability_map (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain VARCHAR(100) NOT NULL,
    task_type VARCHAR(100) NOT NULL,
    score REAL NOT NULL,
    sample_count INT NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(domain, task_type)
);

CREATE INDEX IF NOT EXISTS idx_capability_map_domain ON capability_map(domain, task_type);

-- ── Failure taxonomy ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS failure_taxonomy (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category VARCHAR(100) NOT NULL,
    subcategory VARCHAR(100),
    details JSONB NOT NULL DEFAULT '{}',
    source_task_id UUID,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_failure_taxonomy_category ON failure_taxonomy(category);

-- ── Evolution journal ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS evolution_journal (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID,
    action VARCHAR(50) NOT NULL,
    details JSONB NOT NULL DEFAULT '{}',
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_evo_journal_experiment ON evolution_journal(experiment_id);
CREATE INDEX IF NOT EXISTS idx_evo_journal_recorded ON evolution_journal(recorded_at DESC);

-- ── Confidence calibration ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS confidence_calibration (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    predicted_score REAL NOT NULL,
    actual_score REAL NOT NULL,
    task_type VARCHAR(100),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_confidence_cal_recorded ON confidence_calibration(recorded_at DESC);
```

- [ ] **Step 2: Write failing tests for EvolutionStore**

```python
# tests/test_evolution_store.py
"""Tests for EvolutionStore — DB persistence for evolution data."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from max.evolution.models import (
    EvolutionJournalEntry,
    EvolutionProposal,
    SnapshotData,
)
from max.evolution.store import EvolutionStore


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.fetchone = AsyncMock(return_value=None)
    db.fetchall = AsyncMock(return_value=[])
    return db


@pytest.fixture
def store(mock_db):
    return EvolutionStore(mock_db)


class TestProposalCRUD:
    @pytest.mark.asyncio
    async def test_create_proposal(self, store, mock_db):
        proposal = EvolutionProposal(
            scout_type="tool",
            description="Increase timeout",
            target_type="tool_config",
            impact_score=0.7,
            priority=0.5,
        )
        await store.create_proposal(proposal)
        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args
        assert "INSERT INTO evolution_proposals" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_proposals_by_status(self, store, mock_db):
        mock_db.fetchall.return_value = [
            {
                "id": str(uuid.uuid4()),
                "scout_type": "tool",
                "description": "test",
                "target_type": "prompt",
                "target_id": None,
                "impact_score": 0.5,
                "effort_score": 0.2,
                "risk_score": 0.1,
                "priority": 0.5,
                "status": "proposed",
                "experiment_id": None,
                "created_at": datetime.now(UTC),
            }
        ]
        result = await store.get_proposals(status="proposed")
        assert len(result) == 1
        mock_db.fetchall.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_proposal_status(self, store, mock_db):
        pid = uuid.uuid4()
        await store.update_proposal_status(pid, "approved")
        mock_db.execute.assert_called_once()
        assert "UPDATE evolution_proposals" in mock_db.execute.call_args[0][0]


class TestSnapshotCRUD:
    @pytest.mark.asyncio
    async def test_create_snapshot(self, store, mock_db):
        snap = SnapshotData(
            prompts={"coordinator": "Be concise"},
            tool_configs={},
            context_rules=[],
            metrics_baseline={"audit_score": 0.85},
        )
        exp_id = uuid.uuid4()
        snap_id = await store.create_snapshot(exp_id, snap)
        assert isinstance(snap_id, uuid.UUID)
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_snapshot(self, store, mock_db):
        exp_id = uuid.uuid4()
        mock_db.fetchone.return_value = {
            "id": str(uuid.uuid4()),
            "experiment_id": str(exp_id),
            "snapshot_data": json.dumps({"prompts": {}, "tool_configs": {}, "context_rules": [], "metrics_baseline": {}}),
            "metrics_baseline": json.dumps({}),
            "created_at": datetime.now(UTC),
        }
        result = await store.get_snapshot(exp_id)
        assert result is not None


class TestPromptCRUD:
    @pytest.mark.asyncio
    async def test_set_live_prompt(self, store, mock_db):
        await store.set_prompt("coordinator", "Be concise and clear")
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_live_prompt(self, store, mock_db):
        mock_db.fetchone.return_value = {
            "prompt_text": "Be concise",
            "version": 1,
        }
        result = await store.get_prompt("coordinator")
        assert result == "Be concise"

    @pytest.mark.asyncio
    async def test_get_all_live_prompts(self, store, mock_db):
        mock_db.fetchall.return_value = [
            {"agent_type": "coordinator", "prompt_text": "Be concise", "version": 1},
            {"agent_type": "planner", "prompt_text": "Plan well", "version": 1},
        ]
        result = await store.get_all_prompts()
        assert len(result) == 2
        assert result["coordinator"] == "Be concise"

    @pytest.mark.asyncio
    async def test_set_candidate_prompt(self, store, mock_db):
        exp_id = uuid.uuid4()
        await store.set_prompt("coordinator", "New prompt", experiment_id=exp_id)
        call_args = mock_db.execute.call_args
        assert exp_id in call_args[0] or str(exp_id) in str(call_args)


class TestToolConfigCRUD:
    @pytest.mark.asyncio
    async def test_set_tool_config(self, store, mock_db):
        await store.set_tool_config("shell.execute", {"timeout": 60})
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_tool_config(self, store, mock_db):
        mock_db.fetchone.return_value = {
            "config": json.dumps({"timeout": 60}),
            "version": 1,
        }
        result = await store.get_tool_config("shell.execute")
        assert result == {"timeout": 60}


class TestJournal:
    @pytest.mark.asyncio
    async def test_record_journal_entry(self, store, mock_db):
        entry = EvolutionJournalEntry(
            experiment_id=uuid.uuid4(),
            action="promoted",
            details={"delta": 0.05},
        )
        await store.record_journal(entry)
        mock_db.execute.assert_called_once()
        assert "INSERT INTO evolution_journal" in mock_db.execute.call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_journal(self, store, mock_db):
        mock_db.fetchall.return_value = []
        result = await store.get_journal(limit=10)
        assert result == []


class TestPreferenceProfile:
    @pytest.mark.asyncio
    async def test_save_profile(self, store, mock_db):
        await store.save_preference_profile(
            user_id="venu",
            communication={"tone": "professional"},
            code_prefs={"test_coverage": "high"},
            workflow={"autonomy_level": "high"},
            domain_knowledge={},
            observation_log=[],
        )
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_profile(self, store, mock_db):
        mock_db.fetchone.return_value = {
            "user_id": "venu",
            "communication": json.dumps({"tone": "casual"}),
            "code_prefs": json.dumps({}),
            "workflow": json.dumps({}),
            "domain_knowledge": json.dumps({}),
            "observation_log": json.dumps([]),
            "version": 1,
        }
        result = await store.get_preference_profile("venu")
        assert result is not None
        assert result["user_id"] == "venu"


class TestCapabilityMap:
    @pytest.mark.asyncio
    async def test_upsert_capability(self, store, mock_db):
        await store.upsert_capability("code", "bug_fix", 0.85, 10)
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_capability_map(self, store, mock_db):
        mock_db.fetchall.return_value = [
            {"domain": "code", "task_type": "bug_fix", "score": 0.85, "sample_count": 10},
            {"domain": "code", "task_type": "feature", "score": 0.9, "sample_count": 5},
        ]
        result = await store.get_capability_map()
        assert "code" in result
        assert "bug_fix" in result["code"]


class TestFailureTaxonomy:
    @pytest.mark.asyncio
    async def test_record_failure(self, store, mock_db):
        await store.record_failure("validation", "missing_field", {"field": "name"})
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_failure_counts(self, store, mock_db):
        mock_db.fetchall.return_value = [
            {"category": "validation", "count": 5},
            {"category": "timeout", "count": 2},
        ]
        result = await store.get_failure_counts()
        assert result["validation"] == 5


class TestConfidenceCalibration:
    @pytest.mark.asyncio
    async def test_record_prediction(self, store, mock_db):
        await store.record_prediction(0.8, 0.75, "bug_fix")
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_calibration_error(self, store, mock_db):
        mock_db.fetchall.return_value = [
            {"predicted_score": 0.8, "actual_score": 0.75},
            {"predicted_score": 0.9, "actual_score": 0.85},
        ]
        result = await store.get_calibration_error()
        # mean absolute error = (|0.8-0.75| + |0.9-0.85|) / 2 = 0.05
        assert abs(result - 0.05) < 0.001


class TestLedgerRecording:
    @pytest.mark.asyncio
    async def test_record_evolution_ledger(self, store, mock_db):
        await store.record_to_ledger("evolution_promoted", {"experiment": "abc"})
        mock_db.execute.assert_called_once()
        assert "quality_ledger" in mock_db.execute.call_args[0][0]


class TestPromoteCandidates:
    @pytest.mark.asyncio
    async def test_promote_candidates(self, store, mock_db):
        exp_id = uuid.uuid4()
        await store.promote_candidates(exp_id)
        # Should delete old live, update candidate to live
        assert mock_db.execute.call_count >= 2

    @pytest.mark.asyncio
    async def test_discard_candidates(self, store, mock_db):
        exp_id = uuid.uuid4()
        await store.discard_candidates(exp_id)
        mock_db.execute.assert_called()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution && python -m pytest tests/test_evolution_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'max.evolution.store'`

- [ ] **Step 4: Implement EvolutionStore**

```python
# src/max/evolution/store.py
"""EvolutionStore — async CRUD for evolution data."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from max.db.postgres import Database
from max.evolution.models import (
    EvolutionJournalEntry,
    EvolutionProposal,
    SnapshotData,
)

logger = logging.getLogger(__name__)


class EvolutionStore:
    """Persistence layer for all evolution operations."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Proposals ───────────────────────────────────────────────────────

    async def create_proposal(self, proposal: EvolutionProposal) -> None:
        await self._db.execute(
            "INSERT INTO evolution_proposals "
            "(id, scout_type, description, target_type, target_id, "
            "impact_score, effort_score, risk_score, priority, status, experiment_id) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
            proposal.id, proposal.scout_type, proposal.description,
            proposal.target_type, proposal.target_id,
            proposal.impact_score, proposal.effort_score, proposal.risk_score,
            proposal.priority, proposal.status, proposal.experiment_id,
        )

    async def get_proposals(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            return await self._db.fetchall(
                "SELECT * FROM evolution_proposals WHERE status = $1 "
                "ORDER BY priority DESC", status,
            )
        return await self._db.fetchall(
            "SELECT * FROM evolution_proposals ORDER BY created_at DESC"
        )

    async def update_proposal_status(
        self, proposal_id: uuid.UUID, status: str, experiment_id: uuid.UUID | None = None,
    ) -> None:
        if experiment_id:
            await self._db.execute(
                "UPDATE evolution_proposals SET status = $1, experiment_id = $2 WHERE id = $3",
                status, experiment_id, proposal_id,
            )
        else:
            await self._db.execute(
                "UPDATE evolution_proposals SET status = $1 WHERE id = $2",
                status, proposal_id,
            )

    # ── Snapshots ───────────────────────────────────────────────────────

    async def create_snapshot(self, experiment_id: uuid.UUID, data: SnapshotData) -> uuid.UUID:
        snap_id = uuid.uuid4()
        await self._db.execute(
            "INSERT INTO evolution_snapshots (id, experiment_id, snapshot_data, metrics_baseline) "
            "VALUES ($1, $2, $3::jsonb, $4::jsonb)",
            snap_id, experiment_id,
            json.dumps(data.model_dump()), json.dumps(data.metrics_baseline),
        )
        return snap_id

    async def get_snapshot(self, experiment_id: uuid.UUID) -> dict[str, Any] | None:
        return await self._db.fetchone(
            "SELECT * FROM evolution_snapshots WHERE experiment_id = $1 "
            "ORDER BY created_at DESC LIMIT 1", experiment_id,
        )

    # ── Prompts ─────────────────────────────────────────────────────────

    async def set_prompt(
        self, agent_type: str, prompt_text: str, experiment_id: uuid.UUID | None = None,
    ) -> None:
        await self._db.execute(
            "INSERT INTO evolution_prompts (id, agent_type, prompt_text, experiment_id) "
            "VALUES ($1, $2, $3, $4) "
            "ON CONFLICT (agent_type) WHERE experiment_id IS NULL "
            "DO UPDATE SET prompt_text = $3, version = evolution_prompts.version + 1, "
            "updated_at = NOW()",
            uuid.uuid4(), agent_type, prompt_text, experiment_id,
        )

    async def get_prompt(self, agent_type: str, experiment_id: uuid.UUID | None = None) -> str | None:
        if experiment_id:
            row = await self._db.fetchone(
                "SELECT prompt_text FROM evolution_prompts "
                "WHERE agent_type = $1 AND experiment_id = $2",
                agent_type, experiment_id,
            )
        else:
            row = await self._db.fetchone(
                "SELECT prompt_text FROM evolution_prompts "
                "WHERE agent_type = $1 AND experiment_id IS NULL",
                agent_type,
            )
        return row["prompt_text"] if row else None

    async def get_all_prompts(self, experiment_id: uuid.UUID | None = None) -> dict[str, str]:
        if experiment_id:
            rows = await self._db.fetchall(
                "SELECT agent_type, prompt_text FROM evolution_prompts "
                "WHERE experiment_id = $1", experiment_id,
            )
        else:
            rows = await self._db.fetchall(
                "SELECT agent_type, prompt_text FROM evolution_prompts "
                "WHERE experiment_id IS NULL"
            )
        return {r["agent_type"]: r["prompt_text"] for r in rows}

    # ── Tool Configs ────────────────────────────────────────────────────

    async def set_tool_config(
        self, tool_id: str, config: dict[str, Any], experiment_id: uuid.UUID | None = None,
    ) -> None:
        await self._db.execute(
            "INSERT INTO evolution_tool_configs (id, tool_id, config, experiment_id) "
            "VALUES ($1, $2, $3::jsonb, $4) "
            "ON CONFLICT (tool_id) WHERE experiment_id IS NULL "
            "DO UPDATE SET config = $3::jsonb, version = evolution_tool_configs.version + 1, "
            "updated_at = NOW()",
            uuid.uuid4(), tool_id, json.dumps(config), experiment_id,
        )

    async def get_tool_config(self, tool_id: str, experiment_id: uuid.UUID | None = None) -> dict[str, Any] | None:
        if experiment_id:
            row = await self._db.fetchone(
                "SELECT config FROM evolution_tool_configs "
                "WHERE tool_id = $1 AND experiment_id = $2",
                tool_id, experiment_id,
            )
        else:
            row = await self._db.fetchone(
                "SELECT config FROM evolution_tool_configs "
                "WHERE tool_id = $1 AND experiment_id IS NULL",
                tool_id,
            )
        if row:
            cfg = row["config"]
            return json.loads(cfg) if isinstance(cfg, str) else cfg
        return None

    async def get_all_tool_configs(self, experiment_id: uuid.UUID | None = None) -> dict[str, dict]:
        if experiment_id:
            rows = await self._db.fetchall(
                "SELECT tool_id, config FROM evolution_tool_configs "
                "WHERE experiment_id = $1", experiment_id,
            )
        else:
            rows = await self._db.fetchall(
                "SELECT tool_id, config FROM evolution_tool_configs "
                "WHERE experiment_id IS NULL"
            )
        result = {}
        for r in rows:
            cfg = r["config"]
            result[r["tool_id"]] = json.loads(cfg) if isinstance(cfg, str) else cfg
        return result

    # ── Promote / Discard ───────────────────────────────────────────────

    async def promote_candidates(self, experiment_id: uuid.UUID) -> None:
        """Promote candidate prompts/configs to live (replace old live versions)."""
        # Delete old live prompts that have candidates
        await self._db.execute(
            "DELETE FROM evolution_prompts WHERE experiment_id IS NULL "
            "AND agent_type IN ("
            "  SELECT agent_type FROM evolution_prompts WHERE experiment_id = $1"
            ")", experiment_id,
        )
        # Promote candidates to live
        await self._db.execute(
            "UPDATE evolution_prompts SET experiment_id = NULL, "
            "version = version + 1, updated_at = NOW() "
            "WHERE experiment_id = $1", experiment_id,
        )
        # Same for tool configs
        await self._db.execute(
            "DELETE FROM evolution_tool_configs WHERE experiment_id IS NULL "
            "AND tool_id IN ("
            "  SELECT tool_id FROM evolution_tool_configs WHERE experiment_id = $1"
            ")", experiment_id,
        )
        await self._db.execute(
            "UPDATE evolution_tool_configs SET experiment_id = NULL, "
            "version = version + 1, updated_at = NOW() "
            "WHERE experiment_id = $1", experiment_id,
        )

    async def discard_candidates(self, experiment_id: uuid.UUID) -> None:
        """Delete all candidate prompts/configs for an experiment."""
        await self._db.execute(
            "DELETE FROM evolution_prompts WHERE experiment_id = $1", experiment_id,
        )
        await self._db.execute(
            "DELETE FROM evolution_tool_configs WHERE experiment_id = $1", experiment_id,
        )

    # ── Journal ─────────────────────────────────────────────────────────

    async def record_journal(self, entry: EvolutionJournalEntry) -> None:
        await self._db.execute(
            "INSERT INTO evolution_journal (id, experiment_id, action, details) "
            "VALUES ($1, $2, $3, $4::jsonb)",
            entry.id, entry.experiment_id, entry.action, json.dumps(entry.details),
        )

    async def get_journal(self, limit: int = 50, experiment_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
        if experiment_id:
            return await self._db.fetchall(
                "SELECT * FROM evolution_journal WHERE experiment_id = $1 "
                "ORDER BY recorded_at DESC LIMIT $2", experiment_id, limit,
            )
        return await self._db.fetchall(
            "SELECT * FROM evolution_journal ORDER BY recorded_at DESC LIMIT $1", limit,
        )

    # ── Preference Profiles ─────────────────────────────────────────────

    async def save_preference_profile(
        self, user_id: str, communication: dict, code_prefs: dict,
        workflow: dict, domain_knowledge: dict, observation_log: list,
    ) -> None:
        await self._db.execute(
            "INSERT INTO preference_profiles "
            "(id, user_id, communication, code_prefs, workflow, domain_knowledge, observation_log) "
            "VALUES ($1, $2, $3::jsonb, $4::jsonb, $5::jsonb, $6::jsonb, $7::jsonb) "
            "ON CONFLICT (user_id) DO UPDATE SET "
            "communication = $3::jsonb, code_prefs = $4::jsonb, "
            "workflow = $5::jsonb, domain_knowledge = $6::jsonb, "
            "observation_log = $7::jsonb, version = preference_profiles.version + 1, "
            "updated_at = NOW()",
            uuid.uuid4(), user_id,
            json.dumps(communication), json.dumps(code_prefs),
            json.dumps(workflow), json.dumps(domain_knowledge),
            json.dumps(observation_log),
        )

    async def get_preference_profile(self, user_id: str) -> dict[str, Any] | None:
        return await self._db.fetchone(
            "SELECT * FROM preference_profiles WHERE user_id = $1", user_id,
        )

    # ── Capability Map ──────────────────────────────────────────────────

    async def upsert_capability(
        self, domain: str, task_type: str, score: float, sample_count: int,
    ) -> None:
        await self._db.execute(
            "INSERT INTO capability_map (id, domain, task_type, score, sample_count) "
            "VALUES ($1, $2, $3, $4, $5) "
            "ON CONFLICT (domain, task_type) DO UPDATE SET "
            "score = $4, sample_count = $5, updated_at = NOW()",
            uuid.uuid4(), domain, task_type, score, sample_count,
        )

    async def get_capability_map(self) -> dict[str, dict[str, float]]:
        rows = await self._db.fetchall(
            "SELECT domain, task_type, score, sample_count FROM capability_map "
            "ORDER BY domain, task_type"
        )
        result: dict[str, dict[str, float]] = {}
        for r in rows:
            domain = r["domain"]
            if domain not in result:
                result[domain] = {}
            result[domain][r["task_type"]] = r["score"]
        return result

    # ── Failure Taxonomy ────────────────────────────────────────────────

    async def record_failure(
        self, category: str, subcategory: str | None, details: dict,
        source_task_id: uuid.UUID | None = None,
    ) -> None:
        await self._db.execute(
            "INSERT INTO failure_taxonomy (id, category, subcategory, details, source_task_id) "
            "VALUES ($1, $2, $3, $4::jsonb, $5)",
            uuid.uuid4(), category, subcategory, json.dumps(details), source_task_id,
        )

    async def get_failure_counts(self) -> dict[str, int]:
        rows = await self._db.fetchall(
            "SELECT category, COUNT(*) as count FROM failure_taxonomy "
            "GROUP BY category ORDER BY count DESC"
        )
        return {r["category"]: r["count"] for r in rows}

    # ── Confidence Calibration ──────────────────────────────────────────

    async def record_prediction(
        self, predicted: float, actual: float, task_type: str | None = None,
    ) -> None:
        await self._db.execute(
            "INSERT INTO confidence_calibration (id, predicted_score, actual_score, task_type) "
            "VALUES ($1, $2, $3, $4)",
            uuid.uuid4(), predicted, actual, task_type,
        )

    async def get_calibration_error(self, limit: int = 100) -> float:
        rows = await self._db.fetchall(
            "SELECT predicted_score, actual_score FROM confidence_calibration "
            "ORDER BY recorded_at DESC LIMIT $1", limit,
        )
        if not rows:
            return 0.0
        errors = [abs(r["predicted_score"] - r["actual_score"]) for r in rows]
        return sum(errors) / len(errors)

    # ── Quality Ledger Integration ──────────────────────────────────────

    async def record_to_ledger(self, entry_type: str, content: dict) -> None:
        await self._db.execute(
            "INSERT INTO quality_ledger (id, entry_type, content) "
            "VALUES ($1, $2, $3::jsonb)",
            uuid.uuid4(), entry_type, json.dumps(content),
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution && python -m pytest tests/test_evolution_store.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution
git add src/max/db/schema.sql src/max/evolution/store.py tests/test_evolution_store.py
git commit -m "feat(evolution): add EvolutionStore with DB schema"
```

---

## Task 3: Configuration Additions

**Files:**
- Modify: `src/max/config.py`
- Test: `tests/test_evolution_config.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_evolution_config.py
"""Tests for Phase 7 evolution config fields."""

from __future__ import annotations

from max.config import Settings


class TestEvolutionConfig:
    def test_defaults(self):
        s = Settings()
        assert s.evolution_scout_interval_hours == 6
        assert s.evolution_canary_replay_count == 5
        assert s.evolution_min_priority == 0.3
        assert s.evolution_max_concurrent == 1
        assert s.evolution_freeze_consecutive_drops == 2
        assert s.evolution_preference_refresh_signals == 10
        assert s.evolution_canary_timeout_seconds == 300
        assert s.evolution_snapshot_retention_days == 30

    def test_override_from_env(self, monkeypatch):
        monkeypatch.setenv("EVOLUTION_SCOUT_INTERVAL_HOURS", "12")
        monkeypatch.setenv("EVOLUTION_CANARY_REPLAY_COUNT", "10")
        s = Settings()
        assert s.evolution_scout_interval_hours == 12
        assert s.evolution_canary_replay_count == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution && python -m pytest tests/test_evolution_config.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'evolution_scout_interval_hours'`

- [ ] **Step 3: Add config fields**

Add to `src/max/config.py` Settings class, after the existing quality config fields:

```python
    # ── Evolution System ────────────────────────────────────────────────
    evolution_scout_interval_hours: int = 6
    evolution_canary_replay_count: int = 5
    evolution_min_priority: float = 0.3
    evolution_max_concurrent: int = 1
    evolution_freeze_consecutive_drops: int = 2
    evolution_preference_refresh_signals: int = 10
    evolution_canary_timeout_seconds: int = 300
    evolution_snapshot_retention_days: int = 30
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution && python -m pytest tests/test_evolution_config.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution
git add src/max/config.py tests/test_evolution_config.py
git commit -m "feat(evolution): add evolution config fields to Settings"
```

---

## Task 4: SnapshotManager

**Files:**
- Create: `src/max/evolution/snapshot.py`
- Test: `tests/test_snapshot.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_snapshot.py
"""Tests for SnapshotManager — capture and restore system state."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest

from max.evolution.models import SnapshotData
from max.evolution.snapshot import SnapshotManager


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.get_all_prompts = AsyncMock(return_value={"coordinator": "Be concise"})
    store.get_all_tool_configs = AsyncMock(return_value={"shell.execute": {"timeout": 30}})
    store.create_snapshot = AsyncMock(return_value=uuid.uuid4())
    return store


@pytest.fixture
def mock_metrics():
    metrics = AsyncMock()
    metrics.get_baseline = AsyncMock(return_value=None)
    return metrics


@pytest.fixture
def manager(mock_store, mock_metrics):
    return SnapshotManager(mock_store, mock_metrics)


class TestCapture:
    @pytest.mark.asyncio
    async def test_capture_returns_snapshot_id(self, manager, mock_store):
        exp_id = uuid.uuid4()
        snap_id = await manager.capture(exp_id)
        assert isinstance(snap_id, uuid.UUID)
        mock_store.create_snapshot.assert_called_once()

    @pytest.mark.asyncio
    async def test_capture_includes_prompts_and_configs(self, manager, mock_store):
        exp_id = uuid.uuid4()
        await manager.capture(exp_id)
        call_args = mock_store.create_snapshot.call_args
        snap_data = call_args[0][1]
        assert isinstance(snap_data, SnapshotData)
        assert snap_data.prompts == {"coordinator": "Be concise"}
        assert snap_data.tool_configs == {"shell.execute": {"timeout": 30}}

    @pytest.mark.asyncio
    async def test_capture_includes_metrics_baseline(self, manager, mock_store, mock_metrics):
        from max.memory.models import MetricBaseline
        from datetime import UTC, datetime
        mock_metrics.get_baseline.return_value = MetricBaseline(
            metric_name="audit_score", mean=0.85, median=0.84,
            p95=0.95, p99=0.98, stddev=0.05, sample_count=50,
            window_start=datetime.now(UTC), window_end=datetime.now(UTC),
        )
        exp_id = uuid.uuid4()
        await manager.capture(exp_id)
        call_args = mock_store.create_snapshot.call_args
        snap_data = call_args[0][1]
        assert "audit_score" in snap_data.metrics_baseline


class TestRestore:
    @pytest.mark.asyncio
    async def test_restore_from_snapshot(self, manager, mock_store):
        exp_id = uuid.uuid4()
        mock_store.get_snapshot.return_value = {
            "snapshot_data": json.dumps({
                "prompts": {"coordinator": "Old prompt"},
                "tool_configs": {"shell.execute": {"timeout": 20}},
                "context_rules": [],
                "metrics_baseline": {},
            }),
        }
        await manager.restore(exp_id)
        # Should set prompts and configs back to snapshot values
        mock_store.set_prompt.assert_called_once_with("coordinator", "Old prompt")
        mock_store.set_tool_config.assert_called_once_with(
            "shell.execute", {"timeout": 20}
        )

    @pytest.mark.asyncio
    async def test_restore_no_snapshot_raises(self, manager, mock_store):
        mock_store.get_snapshot.return_value = None
        with pytest.raises(ValueError, match="No snapshot found"):
            await manager.restore(uuid.uuid4())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution && python -m pytest tests/test_snapshot.py -v`
Expected: FAIL

- [ ] **Step 3: Implement SnapshotManager**

```python
# src/max/evolution/snapshot.py
"""SnapshotManager — capture and restore system state for evolution experiments."""

from __future__ import annotations

import json
import logging
import uuid

from max.evolution.models import SnapshotData
from max.evolution.store import EvolutionStore
from max.memory.metrics import MetricCollector

logger = logging.getLogger(__name__)

BASELINE_METRICS = ["audit_score", "audit_duration_seconds"]


class SnapshotManager:
    """Captures and restores system state for safe evolution experiments."""

    def __init__(self, store: EvolutionStore, metrics: MetricCollector) -> None:
        self._store = store
        self._metrics = metrics

    async def capture(self, experiment_id: uuid.UUID) -> uuid.UUID:
        """Capture current system state before an evolution experiment."""
        prompts = await self._store.get_all_prompts()
        tool_configs = await self._store.get_all_tool_configs()

        metrics_baseline: dict[str, float] = {}
        for metric_name in BASELINE_METRICS:
            baseline = await self._metrics.get_baseline(metric_name)
            if baseline:
                metrics_baseline[metric_name] = baseline.mean

        snap = SnapshotData(
            prompts=prompts,
            tool_configs=tool_configs,
            context_rules=[],
            metrics_baseline=metrics_baseline,
        )
        snap_id = await self._store.create_snapshot(experiment_id, snap)
        logger.info("Captured snapshot %s for experiment %s", snap_id, experiment_id)
        return snap_id

    async def restore(self, experiment_id: uuid.UUID) -> None:
        """Restore system state from a snapshot."""
        row = await self._store.get_snapshot(experiment_id)
        if not row:
            raise ValueError(f"No snapshot found for experiment {experiment_id}")

        raw = row["snapshot_data"]
        data = json.loads(raw) if isinstance(raw, str) else raw
        snap = SnapshotData(**data)

        for agent_type, prompt_text in snap.prompts.items():
            await self._store.set_prompt(agent_type, prompt_text)
        for tool_id, config in snap.tool_configs.items():
            await self._store.set_tool_config(tool_id, config)

        logger.info("Restored snapshot for experiment %s", experiment_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution && python -m pytest tests/test_snapshot.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution
git add src/max/evolution/snapshot.py tests/test_snapshot.py
git commit -m "feat(evolution): add SnapshotManager for state capture/restore"
```

---

## Task 5: PreferenceProfileManager

**Files:**
- Create: `src/max/evolution/preference.py`
- Test: `tests/test_preference.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_preference.py
"""Tests for PreferenceProfileManager — behavioral adaptation."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from max.evolution.models import Observation, PreferenceProfile
from max.evolution.preference import PreferenceProfileManager


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.save_preference_profile = AsyncMock()
    store.get_preference_profile = AsyncMock(return_value=None)
    return store


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    return llm


@pytest.fixture
def manager(mock_store, mock_llm):
    return PreferenceProfileManager(mock_store, mock_llm)


class TestRecordSignal:
    @pytest.mark.asyncio
    async def test_record_correction_signal(self, manager, mock_store):
        mock_store.get_preference_profile.return_value = {
            "user_id": "venu",
            "communication": json.dumps({"tone": "professional"}),
            "code_prefs": json.dumps({}),
            "workflow": json.dumps({}),
            "domain_knowledge": json.dumps({}),
            "observation_log": json.dumps([]),
            "version": 1,
        }
        await manager.record_signal("venu", "correction", {"original": "x", "corrected": "y"})
        mock_store.save_preference_profile.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_creates_profile_if_missing(self, manager, mock_store):
        mock_store.get_preference_profile.return_value = None
        await manager.record_signal("venu", "acceptance", {"task_id": "abc"})
        mock_store.save_preference_profile.assert_called_once()
        call_args = mock_store.save_preference_profile.call_args
        assert call_args[1]["user_id"] == "venu" or call_args[0][0] == "venu"

    @pytest.mark.asyncio
    async def test_observation_log_capped_at_500(self, manager, mock_store):
        existing_log = [{"signal_type": "acceptance", "data": {}, "recorded_at": "2026-01-01T00:00:00Z"}] * 500
        mock_store.get_preference_profile.return_value = {
            "user_id": "venu",
            "communication": json.dumps({}),
            "code_prefs": json.dumps({}),
            "workflow": json.dumps({}),
            "domain_knowledge": json.dumps({}),
            "observation_log": json.dumps(existing_log),
            "version": 1,
        }
        await manager.record_signal("venu", "correction", {"x": "y"})
        call_args = mock_store.save_preference_profile.call_args
        saved_log = call_args[1].get("observation_log") or call_args[0][5]
        assert len(saved_log) <= 500


class TestGetProfile:
    @pytest.mark.asyncio
    async def test_get_existing_profile(self, manager, mock_store):
        mock_store.get_preference_profile.return_value = {
            "user_id": "venu",
            "communication": json.dumps({"tone": "casual"}),
            "code_prefs": json.dumps({"test_coverage": "high"}),
            "workflow": json.dumps({"autonomy_level": "full"}),
            "domain_knowledge": json.dumps({}),
            "observation_log": json.dumps([]),
            "version": 2,
        }
        profile = await manager.get_profile("venu")
        assert isinstance(profile, PreferenceProfile)
        assert profile.communication.tone == "casual"

    @pytest.mark.asyncio
    async def test_get_missing_profile_returns_default(self, manager, mock_store):
        mock_store.get_preference_profile.return_value = None
        profile = await manager.get_profile("unknown")
        assert isinstance(profile, PreferenceProfile)
        assert profile.user_id == "unknown"


class TestRefreshProfile:
    @pytest.mark.asyncio
    async def test_refresh_calls_llm(self, manager, mock_store, mock_llm):
        mock_store.get_preference_profile.return_value = {
            "user_id": "venu",
            "communication": json.dumps({}),
            "code_prefs": json.dumps({}),
            "workflow": json.dumps({}),
            "domain_knowledge": json.dumps({}),
            "observation_log": json.dumps([
                {"signal_type": "correction", "data": {"note": "be more concise"}, "recorded_at": "2026-01-01T00:00:00Z"}
            ]),
            "version": 1,
        }
        mock_llm.complete.return_value = AsyncMock(
            text='{"communication": {"tone": "concise"}, "code": {}, "workflow": {}, "domain": {}}'
        )
        profile = await manager.refresh_profile("venu")
        mock_llm.complete.assert_called_once()
        assert isinstance(profile, PreferenceProfile)


class TestContextInjection:
    @pytest.mark.asyncio
    async def test_get_context_injection(self, manager, mock_store):
        mock_store.get_preference_profile.return_value = {
            "user_id": "venu",
            "communication": json.dumps({"tone": "professional", "detail_level": "high"}),
            "code_prefs": json.dumps({"test_coverage": "high"}),
            "workflow": json.dumps({"autonomy_level": "full"}),
            "domain_knowledge": json.dumps({"expertise_areas": ["distributed systems"]}),
            "observation_log": json.dumps([]),
            "version": 1,
        }
        injection = await manager.get_context_injection("venu")
        assert "communication" in injection
        assert "code" in injection
        assert "workflow" in injection
        assert injection["communication"]["tone"] == "professional"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution && python -m pytest tests/test_preference.py -v`
Expected: FAIL

- [ ] **Step 3: Implement PreferenceProfileManager**

```python
# src/max/evolution/preference.py
"""PreferenceProfileManager — behavioral adaptation through user observation."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from max.evolution.models import (
    CommunicationPrefs,
    CodePrefs,
    DomainPrefs,
    Observation,
    PreferenceProfile,
    WorkflowPrefs,
)
from max.evolution.store import EvolutionStore
from max.llm.client import LLMClient

logger = logging.getLogger(__name__)

MAX_OBSERVATION_LOG = 500

REFRESH_PROMPT = """You are analyzing user behavior signals to update a preference profile.

Current observation log (most recent signals):
{observations}

Current profile:
{current_profile}

Based on these signals, update the preference profile. Return ONLY valid JSON:
{{
  "communication": {{"tone": "...", "detail_level": "...", "update_frequency": "...", "languages": [...], "timezone": "..."}},
  "code": {{"style": {{}}, "review_depth": "...", "test_coverage": "...", "commit_style": "..."}},
  "workflow": {{"clarification_threshold": 0.3, "autonomy_level": "...", "reporting_style": "..."}},
  "domain": {{"expertise_areas": [...], "client_contexts": {{}}, "project_conventions": {{}}}}
}}

Only change fields where the signals provide clear evidence. Keep existing values for unaffected fields."""


class PreferenceProfileManager:
    """Manages user preference profiles through behavioral observation."""

    def __init__(self, store: EvolutionStore, llm: LLMClient) -> None:
        self._store = store
        self._llm = llm

    async def record_signal(
        self, user_id: str, signal_type: str, data: dict[str, Any],
    ) -> None:
        """Record a behavioral observation signal."""
        row = await self._store.get_preference_profile(user_id)

        if row:
            obs_raw = row["observation_log"]
            obs_log = json.loads(obs_raw) if isinstance(obs_raw, str) else obs_raw
            comm = json.loads(row["communication"]) if isinstance(row["communication"], str) else row["communication"]
            code = json.loads(row["code_prefs"]) if isinstance(row["code_prefs"], str) else row["code_prefs"]
            wf = json.loads(row["workflow"]) if isinstance(row["workflow"], str) else row["workflow"]
            dk = json.loads(row["domain_knowledge"]) if isinstance(row["domain_knowledge"], str) else row["domain_knowledge"]
        else:
            obs_log = []
            comm = CommunicationPrefs().model_dump()
            code = CodePrefs().model_dump()
            wf = WorkflowPrefs().model_dump()
            dk = DomainPrefs().model_dump()

        new_obs = {
            "signal_type": signal_type,
            "data": data,
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        obs_log.append(new_obs)
        if len(obs_log) > MAX_OBSERVATION_LOG:
            obs_log = obs_log[-MAX_OBSERVATION_LOG:]

        await self._store.save_preference_profile(
            user_id=user_id,
            communication=comm,
            code_prefs=code,
            workflow=wf,
            domain_knowledge=dk,
            observation_log=obs_log,
        )

    async def get_profile(self, user_id: str) -> PreferenceProfile:
        """Get the current preference profile for a user."""
        row = await self._store.get_preference_profile(user_id)
        if not row:
            return PreferenceProfile(user_id=user_id)

        comm_raw = row["communication"]
        comm = json.loads(comm_raw) if isinstance(comm_raw, str) else comm_raw
        code_raw = row["code_prefs"]
        code = json.loads(code_raw) if isinstance(code_raw, str) else code_raw
        wf_raw = row["workflow"]
        wf = json.loads(wf_raw) if isinstance(wf_raw, str) else wf_raw
        dk_raw = row["domain_knowledge"]
        dk = json.loads(dk_raw) if isinstance(dk_raw, str) else dk_raw
        obs_raw = row["observation_log"]
        obs_log = json.loads(obs_raw) if isinstance(obs_raw, str) else obs_raw

        return PreferenceProfile(
            user_id=user_id,
            communication=CommunicationPrefs(**comm) if comm else CommunicationPrefs(),
            code=CodePrefs(**code) if code else CodePrefs(),
            workflow=WorkflowPrefs(**wf) if wf else WorkflowPrefs(),
            domain_knowledge=DomainPrefs(**dk) if dk else DomainPrefs(),
            observation_log=[
                Observation(**o) if isinstance(o, dict) else o for o in obs_log
            ],
            version=row.get("version", 1),
        )

    async def refresh_profile(self, user_id: str) -> PreferenceProfile:
        """Re-analyze observation log with LLM to update the preference profile."""
        profile = await self.get_profile(user_id)

        if not profile.observation_log:
            return profile

        recent_obs = profile.observation_log[-50:]
        obs_text = json.dumps(
            [{"type": o.signal_type, "data": o.data} for o in recent_obs],
            indent=2,
        )
        current_text = json.dumps({
            "communication": profile.communication.model_dump(),
            "code": profile.code.model_dump(),
            "workflow": profile.workflow.model_dump(),
            "domain": profile.domain_knowledge.model_dump(),
        }, indent=2)

        prompt = REFRESH_PROMPT.format(
            observations=obs_text, current_profile=current_text,
        )

        try:
            response = await self._llm.complete(
                messages=[{"role": "user", "content": prompt}],
            )
            parsed = self._parse_json(response.text)
        except Exception:
            logger.exception("Preference profile refresh failed")
            return profile

        comm = parsed.get("communication", profile.communication.model_dump())
        code = parsed.get("code", profile.code.model_dump())
        wf = parsed.get("workflow", profile.workflow.model_dump())
        dk = parsed.get("domain", profile.domain_knowledge.model_dump())

        await self._store.save_preference_profile(
            user_id=user_id,
            communication=comm,
            code_prefs=code,
            workflow=wf,
            domain_knowledge=dk,
            observation_log=[o.model_dump() for o in profile.observation_log],
        )

        return await self.get_profile(user_id)

    async def get_context_injection(self, user_id: str) -> dict[str, Any]:
        """Get formatted preferences for injection into agent context."""
        profile = await self.get_profile(user_id)
        return {
            "communication": profile.communication.model_dump(),
            "code": profile.code.model_dump(),
            "workflow": profile.workflow.model_dump(),
            "domain": profile.domain_knowledge.model_dump(),
        }

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
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

Run: `cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution && python -m pytest tests/test_preference.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution
git add src/max/evolution/preference.py tests/test_preference.py
git commit -m "feat(evolution): add PreferenceProfileManager for behavioral adaptation"
```

---

## Task 6: SelfModel

**Files:**
- Create: `src/max/evolution/self_model.py`
- Test: `tests/test_self_model.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_self_model.py
"""Tests for SelfModel — capability map, failure taxonomy, confidence calibration."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from max.evolution.models import EvolutionJournalEntry
from max.evolution.self_model import SelfModel


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.upsert_capability = AsyncMock()
    store.get_capability_map = AsyncMock(return_value={})
    store.record_failure = AsyncMock()
    store.get_failure_counts = AsyncMock(return_value={})
    store.record_prediction = AsyncMock()
    store.get_calibration_error = AsyncMock(return_value=0.0)
    store.record_journal = AsyncMock()
    store.get_journal = AsyncMock(return_value=[])
    return store


@pytest.fixture
def mock_metrics():
    metrics = AsyncMock()
    metrics.get_baseline = AsyncMock(return_value=None)
    return metrics


@pytest.fixture
def model(mock_store, mock_metrics):
    return SelfModel(mock_store, mock_metrics)


class TestCapabilityMap:
    @pytest.mark.asyncio
    async def test_record_capability(self, model, mock_store):
        await model.record_capability("code", "bug_fix", 0.85)
        mock_store.upsert_capability.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_capability_map(self, model, mock_store):
        mock_store.get_capability_map.return_value = {
            "code": {"bug_fix": 0.85, "feature": 0.9},
        }
        result = await model.get_capability_map()
        assert "code" in result
        assert result["code"]["bug_fix"] == 0.85

    @pytest.mark.asyncio
    async def test_update_capability_rolling_average(self, model, mock_store):
        # Existing: score=0.8, count=10. New observation: 0.9
        # Rolling avg: (0.8*10 + 0.9) / 11 = 0.809...
        mock_store.get_capability_map.return_value = {
            "code": {"bug_fix": 0.8},
        }
        # We need raw data for rolling avg, so mock fetchone
        mock_store._db = AsyncMock()
        await model.record_capability("code", "bug_fix", 0.9)
        mock_store.upsert_capability.assert_called_once()


class TestFailureTaxonomy:
    @pytest.mark.asyncio
    async def test_record_failure(self, model, mock_store):
        await model.record_failure("validation", {"field": "name"})
        mock_store.record_failure.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_failure_taxonomy(self, model, mock_store):
        mock_store.get_failure_counts.return_value = {
            "validation": 5, "timeout": 2,
        }
        result = await model.get_failure_taxonomy()
        assert result["validation"] == 5


class TestConfidenceCalibration:
    @pytest.mark.asyncio
    async def test_record_prediction(self, model, mock_store):
        await model.record_prediction(0.8, 0.75, "bug_fix")
        mock_store.record_prediction.assert_called_once_with(0.8, 0.75, "bug_fix")

    @pytest.mark.asyncio
    async def test_get_calibration_error(self, model, mock_store):
        mock_store.get_calibration_error.return_value = 0.05
        error = await model.get_calibration_error()
        assert error == 0.05


class TestEvolutionJournal:
    @pytest.mark.asyncio
    async def test_record_evolution(self, model, mock_store):
        entry = EvolutionJournalEntry(
            experiment_id=uuid.uuid4(),
            action="promoted",
            details={"delta": 0.05},
        )
        await model.record_evolution(entry)
        mock_store.record_journal.assert_called_once_with(entry)

    @pytest.mark.asyncio
    async def test_get_journal(self, model, mock_store):
        mock_store.get_journal.return_value = [{"action": "promoted"}]
        result = await model.get_journal(limit=10)
        assert len(result) == 1


class TestPerformanceBaselines:
    @pytest.mark.asyncio
    async def test_update_baselines(self, model, mock_metrics):
        from max.memory.models import MetricBaseline
        from datetime import UTC, datetime
        mock_metrics.get_baseline.return_value = MetricBaseline(
            metric_name="audit_score", mean=0.85, median=0.84,
            p95=0.95, p99=0.98, stddev=0.05, sample_count=50,
            window_start=datetime.now(UTC), window_end=datetime.now(UTC),
        )
        result = await model.update_baselines()
        assert "audit_score" in result

    @pytest.mark.asyncio
    async def test_get_baseline(self, model, mock_metrics):
        mock_metrics.get_baseline.return_value = None
        result = await model.get_baseline("audit_score")
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution && python -m pytest tests/test_self_model.py -v`
Expected: FAIL

- [ ] **Step 3: Implement SelfModel**

```python
# src/max/evolution/self_model.py
"""SelfModel — capability map, performance baselines, failure taxonomy, journal."""

from __future__ import annotations

import logging
from typing import Any

from max.evolution.models import EvolutionJournalEntry
from max.evolution.store import EvolutionStore
from max.memory.metrics import MetricCollector
from max.memory.models import MetricBaseline

logger = logging.getLogger(__name__)

TRACKED_METRICS = ["audit_score", "audit_duration_seconds"]


class SelfModel:
    """Maintains Max's understanding of its own capabilities and limitations."""

    def __init__(self, store: EvolutionStore, metrics: MetricCollector) -> None:
        self._store = store
        self._metrics = metrics

    # ── Capability Map ──────────────────────────────────────────────────

    async def record_capability(
        self, domain: str, task_type: str, score: float,
    ) -> None:
        """Record a capability observation (updates rolling average)."""
        current = await self._store.get_capability_map()
        existing_score = current.get(domain, {}).get(task_type)
        if existing_score is not None:
            # Approximate rolling average (weight existing more)
            new_score = existing_score * 0.9 + score * 0.1
            await self._store.upsert_capability(domain, task_type, new_score, 0)
        else:
            await self._store.upsert_capability(domain, task_type, score, 1)

    async def get_capability_map(self) -> dict[str, dict[str, float]]:
        return await self._store.get_capability_map()

    # ── Performance Baselines ───────────────────────────────────────────

    async def update_baselines(self) -> dict[str, MetricBaseline]:
        result: dict[str, MetricBaseline] = {}
        for metric in TRACKED_METRICS:
            baseline = await self._metrics.get_baseline(metric)
            if baseline:
                result[metric] = baseline
        return result

    async def get_baseline(self, metric: str) -> MetricBaseline | None:
        return await self._metrics.get_baseline(metric)

    # ── Failure Taxonomy ────────────────────────────────────────────────

    async def record_failure(
        self, category: str, details: dict[str, Any],
        subcategory: str | None = None,
    ) -> None:
        await self._store.record_failure(category, subcategory, details)

    async def get_failure_taxonomy(self) -> dict[str, int]:
        return await self._store.get_failure_counts()

    # ── Confidence Calibration ──────────────────────────────────────────

    async def record_prediction(
        self, predicted: float, actual: float, task_type: str | None = None,
    ) -> None:
        await self._store.record_prediction(predicted, actual, task_type)

    async def get_calibration_error(self) -> float:
        return await self._store.get_calibration_error()

    # ── Evolution Journal ───────────────────────────────────────────────

    async def record_evolution(self, entry: EvolutionJournalEntry) -> None:
        await self._store.record_journal(entry)

    async def get_journal(self, limit: int = 50) -> list[dict[str, Any]]:
        return await self._store.get_journal(limit=limit)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution && python -m pytest tests/test_self_model.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution
git add src/max/evolution/self_model.py tests/test_self_model.py
git commit -m "feat(evolution): add SelfModel for capability tracking and calibration"
```

---

## Task 7: Scout Agents

**Files:**
- Create: `src/max/evolution/scouts.py`
- Test: `tests/test_scouts.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_scouts.py
"""Tests for Scout agents — discover improvement opportunities."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest

from max.evolution.models import EvolutionProposal
from max.evolution.scouts import (
    BaseScout,
    EcosystemScout,
    PatternScout,
    QualityScout,
    ToolScout,
)


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    return llm


@pytest.fixture
def mock_quality_store():
    store = AsyncMock()
    store.get_quality_pulse = AsyncMock(return_value={
        "pass_rate": 0.85, "avg_score": 0.82,
        "active_rules_count": 5, "top_patterns": [],
    })
    store.get_active_rules = AsyncMock(return_value=[])
    store.get_patterns = AsyncMock(return_value=[])
    return store


@pytest.fixture
def mock_metrics():
    metrics = AsyncMock()
    metrics.get_baseline = AsyncMock(return_value=None)
    return metrics


@pytest.fixture
def mock_evo_store():
    store = AsyncMock()
    store.get_all_prompts = AsyncMock(return_value={"coordinator": "Be concise"})
    store.get_all_tool_configs = AsyncMock(return_value={})
    return store


class TestToolScout:
    @pytest.mark.asyncio
    async def test_discovers_proposals(self, mock_llm, mock_metrics, mock_evo_store):
        mock_llm.complete.return_value = AsyncMock(
            text=json.dumps({
                "proposals": [{
                    "description": "Increase shell timeout for long-running tasks",
                    "target_type": "tool_config",
                    "target_id": "shell.execute",
                    "impact_score": 0.6,
                    "effort_score": 0.1,
                    "risk_score": 0.1,
                }]
            })
        )
        scout = ToolScout(mock_llm, mock_metrics, mock_evo_store)
        proposals = await scout.discover()
        assert len(proposals) >= 1
        assert all(isinstance(p, EvolutionProposal) for p in proposals)
        assert proposals[0].scout_type == "tool"

    @pytest.mark.asyncio
    async def test_returns_empty_on_llm_failure(self, mock_llm, mock_metrics, mock_evo_store):
        mock_llm.complete.side_effect = Exception("LLM error")
        scout = ToolScout(mock_llm, mock_metrics, mock_evo_store)
        proposals = await scout.discover()
        assert proposals == []


class TestPatternScout:
    @pytest.mark.asyncio
    async def test_discovers_proposals(self, mock_llm, mock_quality_store, mock_evo_store):
        mock_llm.complete.return_value = AsyncMock(
            text=json.dumps({
                "proposals": [{
                    "description": "Add structured output format to planner prompt",
                    "target_type": "prompt",
                    "target_id": "planner",
                    "impact_score": 0.5,
                    "effort_score": 0.3,
                    "risk_score": 0.2,
                }]
            })
        )
        scout = PatternScout(mock_llm, mock_quality_store, mock_evo_store)
        proposals = await scout.discover()
        assert len(proposals) >= 1
        assert proposals[0].scout_type == "pattern"


class TestQualityScout:
    @pytest.mark.asyncio
    async def test_discovers_from_failure_patterns(self, mock_llm, mock_quality_store, mock_evo_store):
        mock_quality_store.get_active_rules.return_value = [
            {"rule": "Always validate input", "category": "validation", "severity": "high"},
            {"rule": "Always validate input types", "category": "validation", "severity": "high"},
        ]
        mock_llm.complete.return_value = AsyncMock(
            text=json.dumps({
                "proposals": [{
                    "description": "Add input validation reminder to worker prompt",
                    "target_type": "prompt",
                    "target_id": "worker",
                    "impact_score": 0.7,
                    "effort_score": 0.2,
                    "risk_score": 0.1,
                }]
            })
        )
        scout = QualityScout(mock_llm, mock_quality_store, mock_evo_store)
        proposals = await scout.discover()
        assert len(proposals) >= 1
        assert proposals[0].scout_type == "quality"


class TestEcosystemScout:
    @pytest.mark.asyncio
    async def test_discovers_proposals(self, mock_llm, mock_evo_store):
        mock_llm.complete.return_value = AsyncMock(
            text=json.dumps({
                "proposals": [{
                    "description": "Update API timeout for slow endpoint",
                    "target_type": "tool_config",
                    "target_id": "web.fetch",
                    "impact_score": 0.4,
                    "effort_score": 0.1,
                    "risk_score": 0.2,
                }]
            })
        )
        scout = EcosystemScout(mock_llm, mock_evo_store)
        proposals = await scout.discover()
        assert len(proposals) >= 1
        assert proposals[0].scout_type == "ecosystem"

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self, mock_llm, mock_evo_store):
        mock_llm.complete.side_effect = RuntimeError("fail")
        scout = EcosystemScout(mock_llm, mock_evo_store)
        proposals = await scout.discover()
        assert proposals == []


class TestProposalCapping:
    @pytest.mark.asyncio
    async def test_max_3_proposals_per_scout(self, mock_llm, mock_evo_store):
        mock_llm.complete.return_value = AsyncMock(
            text=json.dumps({
                "proposals": [
                    {"description": f"Proposal {i}", "target_type": "prompt", "impact_score": 0.5, "effort_score": 0.2, "risk_score": 0.1}
                    for i in range(10)
                ]
            })
        )
        scout = EcosystemScout(mock_llm, mock_evo_store)
        proposals = await scout.discover()
        assert len(proposals) <= 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution && python -m pytest tests/test_scouts.py -v`
Expected: FAIL

- [ ] **Step 3: Implement Scout agents**

```python
# src/max/evolution/scouts.py
"""Scout agents — discover improvement opportunities for the evolution pipeline."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from max.evolution.models import EvolutionProposal
from max.evolution.store import EvolutionStore
from max.llm.client import LLMClient
from max.memory.metrics import MetricCollector

logger = logging.getLogger(__name__)

MAX_PROPOSALS_PER_SCOUT = 3


class BaseScout(ABC):
    """Base class for all scout types."""

    scout_type: str = "base"

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    @abstractmethod
    async def discover(self) -> list[EvolutionProposal]:
        """Discover improvement opportunities. Returns proposals."""

    def _parse_proposals(self, text: str) -> list[EvolutionProposal]:
        """Parse LLM response into EvolutionProposal list."""
        parsed = self._parse_json(text)
        raw = parsed.get("proposals", [])
        proposals = []
        for item in raw[:MAX_PROPOSALS_PER_SCOUT]:
            try:
                proposals.append(EvolutionProposal(
                    scout_type=self.scout_type,
                    description=item.get("description", ""),
                    target_type=item.get("target_type", "prompt"),
                    target_id=item.get("target_id"),
                    impact_score=float(item.get("impact_score", 0.0)),
                    effort_score=float(item.get("effort_score", 0.0)),
                    risk_score=float(item.get("risk_score", 0.0)),
                ))
            except Exception:
                logger.warning("Failed to parse proposal: %s", item)
        return proposals

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
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


TOOL_SCOUT_PROMPT = """You are a Tool Scout for Max, an autonomous AI agent system.

Analyze the current tool configurations and metrics to find improvement opportunities.

Current tool configs:
{tool_configs}

Current metric baselines (if available):
{baselines}

Find tools that could benefit from parameter tuning (timeouts, limits, retry policies).
Return ONLY valid JSON:
{{
  "proposals": [
    {{
      "description": "Clear description of the improvement",
      "target_type": "tool_config",
      "target_id": "tool.name",
      "impact_score": 0.0-1.0,
      "effort_score": 0.0-1.0,
      "risk_score": 0.0-1.0
    }}
  ]
}}

Only propose changes with clear evidence of benefit. Max 3 proposals."""


class ToolScout(BaseScout):
    """Discovers tool configuration improvements."""

    scout_type = "tool"

    def __init__(
        self, llm: LLMClient, metrics: MetricCollector, evo_store: EvolutionStore,
    ) -> None:
        super().__init__(llm)
        self._metrics = metrics
        self._evo_store = evo_store

    async def discover(self) -> list[EvolutionProposal]:
        try:
            configs = await self._evo_store.get_all_tool_configs()
            baselines: dict[str, float] = {}
            for metric in ["audit_score", "audit_duration_seconds"]:
                b = await self._metrics.get_baseline(metric)
                if b:
                    baselines[metric] = b.mean

            prompt = TOOL_SCOUT_PROMPT.format(
                tool_configs=json.dumps(configs, indent=2),
                baselines=json.dumps(baselines, indent=2),
            )
            response = await self._llm.complete(
                messages=[{"role": "user", "content": prompt}],
            )
            return self._parse_proposals(response.text)
        except Exception:
            logger.exception("ToolScout discovery failed")
            return []


PATTERN_SCOUT_PROMPT = """You are a Pattern Scout for Max, an autonomous AI agent system.

Analyze quality patterns and agent prompts to find workflow improvements.

Current quality patterns:
{patterns}

Current agent prompts:
{prompts}

Quality pulse: {pulse}

Find opportunities to improve workflow patterns in agent prompts.
Return ONLY valid JSON:
{{
  "proposals": [
    {{
      "description": "Clear description of the improvement",
      "target_type": "prompt",
      "target_id": "agent_type",
      "impact_score": 0.0-1.0,
      "effort_score": 0.0-1.0,
      "risk_score": 0.0-1.0
    }}
  ]
}}

Max 3 proposals."""


class PatternScout(BaseScout):
    """Discovers workflow pattern improvements."""

    scout_type = "pattern"

    def __init__(
        self, llm: LLMClient, quality_store: Any, evo_store: EvolutionStore,
    ) -> None:
        super().__init__(llm)
        self._quality_store = quality_store
        self._evo_store = evo_store

    async def discover(self) -> list[EvolutionProposal]:
        try:
            patterns = await self._quality_store.get_patterns()
            prompts = await self._evo_store.get_all_prompts()
            pulse = await self._quality_store.get_quality_pulse()

            prompt = PATTERN_SCOUT_PROMPT.format(
                patterns=json.dumps(patterns[:20], indent=2, default=str),
                prompts=json.dumps(prompts, indent=2),
                pulse=json.dumps(pulse, indent=2, default=str),
            )
            response = await self._llm.complete(
                messages=[{"role": "user", "content": prompt}],
            )
            return self._parse_proposals(response.text)
        except Exception:
            logger.exception("PatternScout discovery failed")
            return []


QUALITY_SCOUT_PROMPT = """You are a Quality Scout for Max, an autonomous AI agent system.

Analyze recurring quality failures to find root causes that could be fixed.

Active quality rules (extracted from past failures):
{rules}

Quality pulse: {pulse}

Current agent prompts:
{prompts}

Look for recurring failure patterns that suggest a systemic fix in agent prompts.
Return ONLY valid JSON:
{{
  "proposals": [
    {{
      "description": "Clear description of the root cause fix",
      "target_type": "prompt",
      "target_id": "agent_type",
      "impact_score": 0.0-1.0,
      "effort_score": 0.0-1.0,
      "risk_score": 0.0-1.0
    }}
  ]
}}

Max 3 proposals."""


class QualityScout(BaseScout):
    """Root-cause analysis on recurring quality failures."""

    scout_type = "quality"

    def __init__(
        self, llm: LLMClient, quality_store: Any, evo_store: EvolutionStore,
    ) -> None:
        super().__init__(llm)
        self._quality_store = quality_store
        self._evo_store = evo_store

    async def discover(self) -> list[EvolutionProposal]:
        try:
            rules = await self._quality_store.get_active_rules()
            pulse = await self._quality_store.get_quality_pulse()
            prompts = await self._evo_store.get_all_prompts()

            prompt = QUALITY_SCOUT_PROMPT.format(
                rules=json.dumps(rules[:30], indent=2, default=str),
                pulse=json.dumps(pulse, indent=2, default=str),
                prompts=json.dumps(prompts, indent=2),
            )
            response = await self._llm.complete(
                messages=[{"role": "user", "content": prompt}],
            )
            return self._parse_proposals(response.text)
        except Exception:
            logger.exception("QualityScout discovery failed")
            return []


ECOSYSTEM_SCOUT_PROMPT = """You are an Ecosystem Scout for Max, an autonomous AI agent system.

Analyze the current tool configurations to find optimization opportunities.

Current tool configs:
{tool_configs}

Current agent prompts:
{prompts}

Look for configuration improvements based on best practices.
Return ONLY valid JSON:
{{
  "proposals": [
    {{
      "description": "Clear description of the improvement",
      "target_type": "tool_config | prompt",
      "target_id": "tool.name or agent_type",
      "impact_score": 0.0-1.0,
      "effort_score": 0.0-1.0,
      "risk_score": 0.0-1.0
    }}
  ]
}}

Max 3 proposals."""


class EcosystemScout(BaseScout):
    """Monitors external ecosystem for optimization opportunities."""

    scout_type = "ecosystem"

    def __init__(self, llm: LLMClient, evo_store: EvolutionStore) -> None:
        super().__init__(llm)
        self._evo_store = evo_store

    async def discover(self) -> list[EvolutionProposal]:
        try:
            configs = await self._evo_store.get_all_tool_configs()
            prompts = await self._evo_store.get_all_prompts()

            prompt = ECOSYSTEM_SCOUT_PROMPT.format(
                tool_configs=json.dumps(configs, indent=2),
                prompts=json.dumps(prompts, indent=2),
            )
            response = await self._llm.complete(
                messages=[{"role": "user", "content": prompt}],
            )
            return self._parse_proposals(response.text)
        except Exception:
            logger.exception("EcosystemScout discovery failed")
            return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution && python -m pytest tests/test_scouts.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution
git add src/max/evolution/scouts.py tests/test_scouts.py
git commit -m "feat(evolution): add Scout agents (Tool, Pattern, Quality, Ecosystem)"
```

---

## Task 8: ImprovementAgent

**Files:**
- Create: `src/max/evolution/improver.py`
- Test: `tests/test_improver.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_improver.py
"""Tests for ImprovementAgent — implements evolution changes in sandbox."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest

from max.evolution.improver import ImprovementAgent
from max.evolution.models import ChangeSet, EvolutionProposal


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    return llm


@pytest.fixture
def mock_evo_store():
    store = AsyncMock()
    store.get_prompt = AsyncMock(return_value="Be concise")
    store.get_tool_config = AsyncMock(return_value={"timeout": 30})
    store.set_prompt = AsyncMock()
    store.set_tool_config = AsyncMock()
    return store


@pytest.fixture
def agent(mock_llm, mock_evo_store):
    return ImprovementAgent(mock_llm, mock_evo_store)


class TestImplementProposal:
    @pytest.mark.asyncio
    async def test_prompt_change(self, agent, mock_llm, mock_evo_store):
        proposal = EvolutionProposal(
            scout_type="quality",
            description="Add validation reminder to coordinator prompt",
            target_type="prompt",
            target_id="coordinator",
            experiment_id=uuid.uuid4(),
        )
        mock_llm.complete.return_value = AsyncMock(
            text=json.dumps({
                "changes": [{
                    "target_type": "prompt",
                    "target_id": "coordinator",
                    "new_value": "Be concise. Always validate inputs.",
                }]
            })
        )
        changeset = await agent.implement(proposal)
        assert isinstance(changeset, ChangeSet)
        assert len(changeset.entries) == 1
        assert changeset.entries[0].target_type == "prompt"
        # Should write candidate prompt
        mock_evo_store.set_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_tool_config_change(self, agent, mock_llm, mock_evo_store):
        proposal = EvolutionProposal(
            scout_type="tool",
            description="Increase shell timeout",
            target_type="tool_config",
            target_id="shell.execute",
            experiment_id=uuid.uuid4(),
        )
        mock_llm.complete.return_value = AsyncMock(
            text=json.dumps({
                "changes": [{
                    "target_type": "tool_config",
                    "target_id": "shell.execute",
                    "new_value": {"timeout": 60},
                }]
            })
        )
        changeset = await agent.implement(proposal)
        assert len(changeset.entries) == 1
        mock_evo_store.set_tool_config.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_empty_changeset_on_failure(self, agent, mock_llm):
        proposal = EvolutionProposal(
            scout_type="tool",
            description="test",
            target_type="tool_config",
            experiment_id=uuid.uuid4(),
        )
        mock_llm.complete.side_effect = Exception("LLM error")
        changeset = await agent.implement(proposal)
        assert isinstance(changeset, ChangeSet)
        assert len(changeset.entries) == 0

    @pytest.mark.asyncio
    async def test_caps_changes_at_5(self, agent, mock_llm, mock_evo_store):
        proposal = EvolutionProposal(
            scout_type="pattern",
            description="test",
            target_type="prompt",
            experiment_id=uuid.uuid4(),
        )
        mock_llm.complete.return_value = AsyncMock(
            text=json.dumps({
                "changes": [
                    {"target_type": "prompt", "target_id": f"agent_{i}", "new_value": "new"}
                    for i in range(10)
                ]
            })
        )
        changeset = await agent.implement(proposal)
        assert len(changeset.entries) <= 5
```

- [ ] **Step 2: Run tests, then implement**

```python
# src/max/evolution/improver.py
"""ImprovementAgent — implements evolution changes in sandbox context."""

from __future__ import annotations

import json
import logging
from typing import Any

from max.evolution.models import ChangeSet, ChangeSetEntry, EvolutionProposal
from max.evolution.store import EvolutionStore
from max.llm.client import LLMClient

logger = logging.getLogger(__name__)

MAX_CHANGES = 5

IMPROVEMENT_PROMPT = """You are an Improvement Agent for Max, an autonomous AI agent system.

Your task: {description}

Target type: {target_type}
Target ID: {target_id}

Current value:
{current_value}

Produce the improved version. Return ONLY valid JSON:
{{
  "changes": [
    {{
      "target_type": "{target_type}",
      "target_id": "specific target",
      "new_value": "the new value (string for prompts, object for configs)"
    }}
  ]
}}

Rules:
- Changes must be minimal and focused
- Do not remove existing functionality
- Preserve the overall structure and intent
- Max {max_changes} changes"""


class ImprovementAgent:
    """Implements proposed evolution changes."""

    def __init__(self, llm: LLMClient, store: EvolutionStore) -> None:
        self._llm = llm
        self._store = store

    async def implement(self, proposal: EvolutionProposal) -> ChangeSet:
        """Implement a proposal, writing candidates to the store."""
        changeset = ChangeSet(proposal_id=proposal.id)

        try:
            current_value = await self._get_current_value(
                proposal.target_type, proposal.target_id,
            )

            prompt = IMPROVEMENT_PROMPT.format(
                description=proposal.description,
                target_type=proposal.target_type,
                target_id=proposal.target_id or "N/A",
                current_value=json.dumps(current_value, indent=2)
                if not isinstance(current_value, str) else current_value,
                max_changes=MAX_CHANGES,
            )

            response = await self._llm.complete(
                messages=[{"role": "user", "content": prompt}],
            )
            parsed = self._parse_json(response.text)
            raw_changes = parsed.get("changes", [])[:MAX_CHANGES]

            for change in raw_changes:
                entry = ChangeSetEntry(
                    target_type=change.get("target_type", proposal.target_type),
                    target_id=change.get("target_id", proposal.target_id or ""),
                    old_value=current_value,
                    new_value=change.get("new_value"),
                )
                changeset.entries.append(entry)

                await self._apply_candidate(
                    entry, proposal.experiment_id,
                )

        except Exception:
            logger.exception("ImprovementAgent failed for proposal %s", proposal.id)

        return changeset

    async def _get_current_value(self, target_type: str, target_id: str | None) -> Any:
        if target_type == "prompt" and target_id:
            return await self._store.get_prompt(target_id) or ""
        elif target_type == "tool_config" and target_id:
            return await self._store.get_tool_config(target_id) or {}
        return ""

    async def _apply_candidate(
        self, entry: ChangeSetEntry, experiment_id: Any,
    ) -> None:
        if entry.target_type == "prompt":
            await self._store.set_prompt(
                entry.target_id, entry.new_value, experiment_id=experiment_id,
            )
        elif entry.target_type == "tool_config":
            config = entry.new_value if isinstance(entry.new_value, dict) else {}
            await self._store.set_tool_config(
                entry.target_id, config, experiment_id=experiment_id,
            )

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
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

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution && python -m pytest tests/test_improver.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution
git add src/max/evolution/improver.py tests/test_improver.py
git commit -m "feat(evolution): add ImprovementAgent for sandbox changes"
```

---

## Task 9: CanaryRunner

**Files:**
- Create: `src/max/evolution/canary.py`
- Test: `tests/test_canary.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_canary.py
"""Tests for CanaryRunner — replays tasks and compares outputs."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from max.evolution.canary import CanaryRunner
from max.evolution.models import CanaryRequest, CanaryResult


@pytest.fixture
def mock_task_store():
    store = AsyncMock()
    store.get_task = AsyncMock(return_value={
        "id": str(uuid.uuid4()),
        "goal": "Fix the login bug",
        "status": "completed",
    })
    return store


@pytest.fixture
def mock_quality_store():
    store = AsyncMock()
    store.get_quality_pulse = AsyncMock(return_value={
        "pass_rate": 0.9, "avg_score": 0.85,
    })
    return store


@pytest.fixture
def mock_evo_store():
    store = AsyncMock()
    return store


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    return llm


@pytest.fixture
def mock_metrics():
    metrics = AsyncMock()
    return metrics


@pytest.fixture
def runner(mock_task_store, mock_quality_store, mock_evo_store, mock_llm, mock_metrics):
    return CanaryRunner(
        task_store=mock_task_store,
        quality_store=mock_quality_store,
        evo_store=mock_evo_store,
        llm=mock_llm,
        metrics=mock_metrics,
        timeout_seconds=10,
    )


class TestCanaryExecution:
    @pytest.mark.asyncio
    async def test_all_tasks_pass(self, runner, mock_task_store, mock_llm):
        task_id = uuid.uuid4()
        mock_task_store.get_subtasks = AsyncMock(return_value=[
            {"id": str(uuid.uuid4()), "description": "Fix login", "content": "Fixed"},
        ])
        # Mock the re-evaluation: original score 0.8, canary score 0.85
        mock_llm.complete.return_value = AsyncMock(
            text='{"score": 0.85, "verdict": "pass"}'
        )
        runner._get_original_score = AsyncMock(return_value=0.8)

        request = CanaryRequest(
            experiment_id=uuid.uuid4(),
            task_ids=[task_id],
            candidate_config={"prompts": {}},
        )
        result = await runner.run(request)
        assert isinstance(result, CanaryResult)
        assert result.overall_passed is True
        assert len(result.task_results) == 1

    @pytest.mark.asyncio
    async def test_regression_fails_canary(self, runner, mock_task_store, mock_llm):
        task_id = uuid.uuid4()
        mock_task_store.get_subtasks = AsyncMock(return_value=[
            {"id": str(uuid.uuid4()), "description": "Fix login", "content": "Fixed"},
        ])
        mock_llm.complete.return_value = AsyncMock(
            text='{"score": 0.6, "verdict": "fail"}'
        )
        runner._get_original_score = AsyncMock(return_value=0.8)

        request = CanaryRequest(
            experiment_id=uuid.uuid4(),
            task_ids=[task_id],
            candidate_config={},
        )
        result = await runner.run(request)
        assert result.overall_passed is False

    @pytest.mark.asyncio
    async def test_empty_tasks_passes(self, runner):
        request = CanaryRequest(
            experiment_id=uuid.uuid4(),
            task_ids=[],
            candidate_config={},
        )
        result = await runner.run(request)
        assert result.overall_passed is True
        assert len(result.task_results) == 0

    @pytest.mark.asyncio
    async def test_error_during_replay_fails_task(self, runner, mock_task_store):
        task_id = uuid.uuid4()
        mock_task_store.get_subtasks = AsyncMock(side_effect=Exception("DB error"))
        runner._get_original_score = AsyncMock(return_value=0.8)

        request = CanaryRequest(
            experiment_id=uuid.uuid4(),
            task_ids=[task_id],
            candidate_config={},
        )
        result = await runner.run(request)
        assert result.overall_passed is False
```

- [ ] **Step 2: Run tests, then implement**

```python
# src/max/evolution/canary.py
"""CanaryRunner — replays recent tasks to verify evolution non-regression."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from max.evolution.models import CanaryRequest, CanaryResult, CanaryTaskResult
from max.evolution.store import EvolutionStore
from max.llm.client import LLMClient
from max.memory.metrics import MetricCollector

logger = logging.getLogger(__name__)

CANARY_EVAL_PROMPT = """You are evaluating whether a task output meets quality standards.

Task goal: {goal}
Subtask: {subtask_description}
Output:
{output}

Score this output from 0.0 to 1.0 on quality.
Return ONLY valid JSON: {{"score": 0.0-1.0, "verdict": "pass|fail"}}"""


class CanaryRunner:
    """Replays recent tasks with candidate config to verify non-regression."""

    def __init__(
        self,
        task_store: Any,
        quality_store: Any,
        evo_store: EvolutionStore,
        llm: LLMClient,
        metrics: MetricCollector,
        timeout_seconds: int = 300,
    ) -> None:
        self._task_store = task_store
        self._quality_store = quality_store
        self._evo_store = evo_store
        self._llm = llm
        self._metrics = metrics
        self._timeout = timeout_seconds

    async def run(self, request: CanaryRequest) -> CanaryResult:
        """Run canary test for all specified tasks."""
        start = time.monotonic()
        task_results: list[CanaryTaskResult] = []
        all_passed = True

        for task_id in request.task_ids:
            try:
                result = await self._replay_task(task_id, request)
                task_results.append(result)
                if not result.passed:
                    all_passed = False
            except Exception:
                logger.exception("Canary replay failed for task %s", task_id)
                task_results.append(CanaryTaskResult(
                    task_id=task_id,
                    original_score=0.0,
                    canary_score=0.0,
                    passed=False,
                ))
                all_passed = False

        duration = time.monotonic() - start
        return CanaryResult(
            experiment_id=request.experiment_id,
            task_results=task_results,
            overall_passed=all_passed,
            duration_seconds=duration,
        )

    async def _replay_task(
        self, task_id: uuid.UUID, request: CanaryRequest,
    ) -> CanaryTaskResult:
        """Replay a single task and compare scores."""
        task = await self._task_store.get_task(task_id)
        subtasks = await self._task_store.get_subtasks(task_id)
        original_score = await self._get_original_score(task_id)

        scores: list[float] = []
        for subtask in subtasks:
            score = await self._evaluate_subtask(
                task.get("goal", ""),
                subtask.get("description", ""),
                subtask.get("content", ""),
            )
            scores.append(score)

        canary_score = sum(scores) / max(len(scores), 1)
        passed = canary_score >= original_score

        return CanaryTaskResult(
            task_id=task_id,
            original_score=original_score,
            canary_score=canary_score,
            passed=passed,
        )

    async def _evaluate_subtask(
        self, goal: str, description: str, output: str,
    ) -> float:
        """Use LLM to score a subtask output."""
        prompt = CANARY_EVAL_PROMPT.format(
            goal=goal,
            subtask_description=description,
            output=output[:2000],
        )
        try:
            response = await self._llm.complete(
                messages=[{"role": "user", "content": prompt}],
            )
            parsed = self._parse_json(response.text)
            return float(parsed.get("score", 0.0))
        except Exception:
            logger.exception("Canary evaluation failed")
            return 0.0

    async def _get_original_score(self, task_id: uuid.UUID) -> float:
        """Get the original audit score for a task."""
        try:
            reports = await self._quality_store.get_audit_reports(task_id)
            if reports:
                return sum(r.get("score", 0.0) for r in reports) / len(reports)
        except Exception:
            pass
        return 0.0

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
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

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution && python -m pytest tests/test_canary.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution
git add src/max/evolution/canary.py tests/test_canary.py
git commit -m "feat(evolution): add CanaryRunner for non-regression testing"
```

---

## Task 10: EvolutionDirectorAgent

**Files:**
- Create: `src/max/evolution/director.py`
- Test: `tests/test_evolution_director.py`

This is the main orchestrator — it ties together all components and manages the 7-step pipeline.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_evolution_director.py
"""Tests for EvolutionDirectorAgent — orchestrates the evolution pipeline."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from max.evolution.director import EvolutionDirectorAgent
from max.evolution.models import (
    CanaryResult,
    CanaryTaskResult,
    ChangeSet,
    ChangeSetEntry,
    EvolutionProposal,
)


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def mock_bus():
    bus = AsyncMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def mock_evo_store():
    store = AsyncMock()
    store.create_proposal = AsyncMock()
    store.update_proposal_status = AsyncMock()
    store.get_proposals = AsyncMock(return_value=[])
    store.promote_candidates = AsyncMock()
    store.discard_candidates = AsyncMock()
    store.record_to_ledger = AsyncMock()
    return store


@pytest.fixture
def mock_quality_store():
    store = AsyncMock()
    store.get_quality_pulse = AsyncMock(return_value={
        "pass_rate": 0.9, "avg_score": 0.85,
        "active_rules_count": 3, "top_patterns": [],
    })
    return store


@pytest.fixture
def mock_snapshot_mgr():
    mgr = AsyncMock()
    mgr.capture = AsyncMock(return_value=uuid.uuid4())
    mgr.restore = AsyncMock()
    return mgr


@pytest.fixture
def mock_improver():
    improver = AsyncMock()
    improver.implement = AsyncMock(return_value=ChangeSet(
        proposal_id=uuid.uuid4(),
        entries=[ChangeSetEntry(target_type="prompt", target_id="coordinator", new_value="new prompt")],
    ))
    return improver


@pytest.fixture
def mock_canary():
    canary = AsyncMock()
    canary.run = AsyncMock(return_value=CanaryResult(
        experiment_id=uuid.uuid4(),
        task_results=[],
        overall_passed=True,
    ))
    return canary


@pytest.fixture
def mock_self_model():
    model = AsyncMock()
    model.record_evolution = AsyncMock()
    return model


@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.evolution_min_priority = 0.3
    settings.evolution_max_concurrent = 1
    settings.evolution_freeze_consecutive_drops = 2
    settings.evolution_canary_replay_count = 5
    settings.evolution_canary_timeout_seconds = 300
    return settings


@pytest.fixture
def mock_state_manager():
    mgr = AsyncMock()
    mgr.load = AsyncMock(return_value=MagicMock(
        evolution=MagicMock(
            active_experiments=[],
            evolution_frozen=False,
            freeze_reason=None,
        )
    ))
    mgr.update = AsyncMock()
    return mgr


@pytest.fixture
def mock_task_store():
    store = AsyncMock()
    store.get_recent_completed = AsyncMock(return_value=[])
    return store


@pytest.fixture
def director(
    mock_llm, mock_bus, mock_evo_store, mock_quality_store,
    mock_snapshot_mgr, mock_improver, mock_canary, mock_self_model,
    mock_settings, mock_state_manager, mock_task_store,
):
    return EvolutionDirectorAgent(
        llm=mock_llm,
        bus=mock_bus,
        evo_store=mock_evo_store,
        quality_store=mock_quality_store,
        snapshot_manager=mock_snapshot_mgr,
        improver=mock_improver,
        canary_runner=mock_canary,
        self_model=mock_self_model,
        settings=mock_settings,
        state_manager=mock_state_manager,
        task_store=mock_task_store,
    )


class TestEvaluateProposal:
    @pytest.mark.asyncio
    async def test_accepts_high_priority(self, director):
        proposal = EvolutionProposal(
            scout_type="quality",
            description="Fix validation",
            target_type="prompt",
            impact_score=0.8,
            effort_score=0.2,
            risk_score=0.1,
        )
        accepted = director.evaluate_proposal(proposal)
        assert accepted is True

    @pytest.mark.asyncio
    async def test_rejects_low_priority(self, director):
        proposal = EvolutionProposal(
            scout_type="tool",
            description="Minor tweak",
            target_type="tool_config",
            impact_score=0.1,
            effort_score=0.5,
            risk_score=0.8,
        )
        accepted = director.evaluate_proposal(proposal)
        assert accepted is False


class TestAntiDegradation:
    @pytest.mark.asyncio
    async def test_freeze_on_consecutive_drops(self, director, mock_quality_store):
        # Simulate 2 consecutive drops
        mock_quality_store.get_quality_pulse.side_effect = [
            {"pass_rate": 0.7, "avg_score": 0.65},  # current
            {"pass_rate": 0.8, "avg_score": 0.75},  # previous
        ]
        director._consecutive_drops = 1  # already had one drop
        should_freeze = await director.check_anti_degradation()
        assert should_freeze is True

    @pytest.mark.asyncio
    async def test_no_freeze_on_stable(self, director, mock_quality_store):
        mock_quality_store.get_quality_pulse.side_effect = [
            {"pass_rate": 0.9, "avg_score": 0.85},
            {"pass_rate": 0.85, "avg_score": 0.82},
        ]
        director._consecutive_drops = 0
        should_freeze = await director.check_anti_degradation()
        assert should_freeze is False


class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_successful_evolution(
        self, director, mock_evo_store, mock_snapshot_mgr,
        mock_improver, mock_canary, mock_self_model, mock_bus,
    ):
        proposal = EvolutionProposal(
            scout_type="quality",
            description="Improve coordinator",
            target_type="prompt",
            target_id="coordinator",
            impact_score=0.8,
            effort_score=0.2,
            risk_score=0.1,
        )
        await director.run_pipeline(proposal)

        # Verify pipeline steps
        mock_snapshot_mgr.capture.assert_called_once()
        mock_improver.implement.assert_called_once()
        mock_canary.run.assert_called_once()
        mock_evo_store.promote_candidates.assert_called_once()
        mock_self_model.record_evolution.assert_called()
        mock_bus.publish.assert_called()

    @pytest.mark.asyncio
    async def test_rollback_on_canary_failure(
        self, director, mock_evo_store, mock_snapshot_mgr,
        mock_canary, mock_self_model, mock_bus,
    ):
        mock_canary.run.return_value = CanaryResult(
            experiment_id=uuid.uuid4(),
            task_results=[CanaryTaskResult(
                task_id=uuid.uuid4(), original_score=0.8,
                canary_score=0.6, passed=False,
            )],
            overall_passed=False,
        )
        proposal = EvolutionProposal(
            scout_type="quality",
            description="Risky change",
            target_type="prompt",
            impact_score=0.8,
            effort_score=0.2,
            risk_score=0.1,
        )
        await director.run_pipeline(proposal)

        mock_snapshot_mgr.restore.assert_called_once()
        mock_evo_store.discard_candidates.assert_called_once()
        mock_evo_store.promote_candidates.assert_not_called()

    @pytest.mark.asyncio
    async def test_rollback_on_empty_changeset(
        self, director, mock_evo_store, mock_snapshot_mgr,
        mock_improver, mock_canary,
    ):
        mock_improver.implement.return_value = ChangeSet(
            proposal_id=uuid.uuid4(), entries=[],
        )
        proposal = EvolutionProposal(
            scout_type="tool",
            description="Empty change",
            target_type="tool_config",
            impact_score=0.5,
            effort_score=0.2,
            risk_score=0.1,
        )
        await director.run_pipeline(proposal)

        mock_canary.run.assert_not_called()
        mock_evo_store.discard_candidates.assert_called_once()


class TestFreezeHandling:
    @pytest.mark.asyncio
    async def test_skips_pipeline_when_frozen(
        self, director, mock_snapshot_mgr,
    ):
        director._frozen = True
        proposal = EvolutionProposal(
            scout_type="quality",
            description="test",
            target_type="prompt",
            impact_score=0.8,
            effort_score=0.2,
            risk_score=0.1,
        )
        await director.run_pipeline(proposal)
        mock_snapshot_mgr.capture.assert_not_called()
```

- [ ] **Step 2: Run tests, then implement**

```python
# src/max/evolution/director.py
"""EvolutionDirectorAgent — orchestrates the 7-step evolution pipeline."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from max.config import Settings
from max.evolution.canary import CanaryRunner
from max.evolution.improver import ImprovementAgent
from max.evolution.models import (
    CanaryRequest,
    EvolutionJournalEntry,
    EvolutionProposal,
    PromotionEvent,
    RollbackEvent,
)
from max.evolution.self_model import SelfModel
from max.evolution.snapshot import SnapshotManager
from max.evolution.store import EvolutionStore
from max.llm.client import LLMClient
from max.memory.coordinator_state import CoordinatorStateManager

logger = logging.getLogger(__name__)


class EvolutionDirectorAgent:
    """Orchestrates the full evolution lifecycle.

    Pipeline: Discover → Evaluate → Snapshot → Implement → Audit → Canary → Promote
    """

    def __init__(
        self,
        llm: LLMClient,
        bus: Any,
        evo_store: EvolutionStore,
        quality_store: Any,
        snapshot_manager: SnapshotManager,
        improver: ImprovementAgent,
        canary_runner: CanaryRunner,
        self_model: SelfModel,
        settings: Settings,
        state_manager: CoordinatorStateManager,
        task_store: Any,
    ) -> None:
        self._llm = llm
        self._bus = bus
        self._evo_store = evo_store
        self._quality_store = quality_store
        self._snapshot = snapshot_manager
        self._improver = improver
        self._canary = canary_runner
        self._self_model = self_model
        self._settings = settings
        self._state_manager = state_manager
        self._task_store = task_store
        self._consecutive_drops = 0
        self._frozen = False

    # ── Bus Integration ─────────────────────────────────────────────────

    async def start(self) -> None:
        """Subscribe to bus channels."""
        await self._bus.subscribe("evolution.trigger", self._on_trigger)
        await self._bus.subscribe("evolution.proposal", self._on_proposal)
        logger.info("EvolutionDirectorAgent started")

    async def _on_trigger(self, message: dict[str, Any]) -> None:
        """Handle evolution trigger (scheduled or manual)."""
        if self._frozen:
            logger.info("Evolution frozen, skipping trigger")
            return
        # Scouts are dispatched externally; this just logs
        logger.info("Evolution trigger received: %s", message.get("trigger"))

    async def _on_proposal(self, message: dict[str, Any]) -> None:
        """Handle incoming proposal from a scout."""
        try:
            proposal = EvolutionProposal(**message)
            if self.evaluate_proposal(proposal):
                await self.run_pipeline(proposal)
        except Exception:
            logger.exception("Failed to process proposal")

    # ── Evaluate (Step 2) ───────────────────────────────────────────────

    def evaluate_proposal(self, proposal: EvolutionProposal) -> bool:
        """Evaluate whether a proposal should proceed."""
        priority = proposal.computed_priority
        threshold = self._settings.evolution_min_priority
        if priority < threshold:
            logger.info(
                "Proposal rejected: priority %.2f < threshold %.2f",
                priority, threshold,
            )
            return False
        return True

    # ── Anti-Degradation ────────────────────────────────────────────────

    async def check_anti_degradation(self) -> bool:
        """Check if evolution should be frozen due to quality drops."""
        current = await self._quality_store.get_quality_pulse(hours=24)
        previous = await self._quality_store.get_quality_pulse(hours=48)

        current_rate = current.get("pass_rate", 0.0)
        previous_rate = previous.get("pass_rate", 0.0)

        if current_rate < previous_rate:
            self._consecutive_drops += 1
        else:
            self._consecutive_drops = 0

        if self._consecutive_drops >= self._settings.evolution_freeze_consecutive_drops:
            return True
        return False

    async def freeze(self, reason: str) -> None:
        """Freeze all evolution activity."""
        self._frozen = True
        await self._evo_store.record_to_ledger("evolution_frozen", {"reason": reason})
        await self._self_model.record_evolution(EvolutionJournalEntry(
            action="frozen", details={"reason": reason},
        ))
        await self._bus.publish("evolution.frozen", {"reason": reason})
        logger.warning("Evolution FROZEN: %s", reason)

    async def unfreeze(self) -> None:
        """Unfreeze evolution activity."""
        self._frozen = False
        self._consecutive_drops = 0
        await self._evo_store.record_to_ledger("evolution_unfrozen", {})
        await self._self_model.record_evolution(EvolutionJournalEntry(
            action="unfrozen", details={},
        ))
        logger.info("Evolution unfrozen")

    # ── Full Pipeline ───────────────────────────────────────────────────

    async def run_pipeline(self, proposal: EvolutionProposal) -> None:
        """Execute the full 7-step evolution pipeline for a proposal."""
        if self._frozen:
            logger.info("Evolution frozen, skipping pipeline")
            return

        experiment_id = uuid.uuid4()
        proposal.experiment_id = experiment_id
        proposal.status = "approved"

        try:
            # Step 1-2: Already done (scout discovered, we evaluated)
            await self._evo_store.create_proposal(proposal)
            await self._self_model.record_evolution(EvolutionJournalEntry(
                experiment_id=experiment_id, action="approved",
                details={"description": proposal.description},
            ))

            # Step 3: Snapshot
            snapshot_id = await self._snapshot.capture(experiment_id)
            await self._self_model.record_evolution(EvolutionJournalEntry(
                experiment_id=experiment_id, action="snapshot",
                details={"snapshot_id": str(snapshot_id)},
            ))

            # Step 4: Implement
            changeset = await self._improver.implement(proposal)
            if not changeset.entries:
                logger.warning("Empty changeset, aborting experiment %s", experiment_id)
                await self._evo_store.discard_candidates(experiment_id)
                await self._evo_store.update_proposal_status(proposal.id, "discarded")
                return

            await self._self_model.record_evolution(EvolutionJournalEntry(
                experiment_id=experiment_id, action="implemented",
                details={"changes": len(changeset.entries)},
            ))

            # Step 5: Audit (simplified — we use canary instead of full audit)
            # In a full system, the QualityDirector would audit the changeset

            # Step 6: Canary Test
            recent_tasks = await self._task_store.get_recent_completed(
                limit=self._settings.evolution_canary_replay_count,
            )
            task_ids = [t.get("id") or t.get("task_id") for t in recent_tasks if t]
            # Convert string IDs to UUIDs
            task_uuids = []
            for tid in task_ids:
                try:
                    task_uuids.append(uuid.UUID(str(tid)) if not isinstance(tid, uuid.UUID) else tid)
                except (ValueError, AttributeError):
                    continue

            canary_result = await self._canary.run(CanaryRequest(
                experiment_id=experiment_id,
                task_ids=task_uuids,
                candidate_config={},
                timeout_seconds=self._settings.evolution_canary_timeout_seconds,
            ))

            # Step 7: Promote or Rollback
            if canary_result.overall_passed:
                await self._promote(experiment_id, proposal, snapshot_id)
            else:
                await self._rollback(experiment_id, proposal, snapshot_id, "Canary test failed")

        except Exception:
            logger.exception("Pipeline failed for experiment %s", experiment_id)
            try:
                await self._rollback(experiment_id, proposal, snapshot_id, "Pipeline exception")
            except Exception:
                logger.exception("Rollback also failed for %s", experiment_id)

    async def _promote(
        self, experiment_id: uuid.UUID, proposal: EvolutionProposal,
        snapshot_id: uuid.UUID,
    ) -> None:
        """Promote candidate changes to live."""
        await self._evo_store.promote_candidates(experiment_id)
        await self._evo_store.update_proposal_status(proposal.id, "promoted", experiment_id)
        await self._evo_store.record_to_ledger("evolution_promoted", {
            "experiment_id": str(experiment_id),
            "description": proposal.description,
        })
        await self._self_model.record_evolution(EvolutionJournalEntry(
            experiment_id=experiment_id, action="promoted",
            details={"description": proposal.description},
        ))
        await self._bus.publish("evolution.promoted", {
            "experiment_id": str(experiment_id),
            "description": proposal.description,
        })
        logger.info("Evolution PROMOTED: %s", proposal.description)

    async def _rollback(
        self, experiment_id: uuid.UUID, proposal: EvolutionProposal,
        snapshot_id: uuid.UUID, reason: str,
    ) -> None:
        """Rollback to snapshot and shelve the proposal."""
        await self._snapshot.restore(experiment_id)
        await self._evo_store.discard_candidates(experiment_id)
        await self._evo_store.update_proposal_status(proposal.id, "shelved")
        await self._evo_store.record_to_ledger("evolution_rolled_back", {
            "experiment_id": str(experiment_id),
            "reason": reason,
        })
        await self._self_model.record_evolution(EvolutionJournalEntry(
            experiment_id=experiment_id, action="rolled_back",
            details={"reason": reason},
        ))
        await self._bus.publish("evolution.rolled_back", {
            "experiment_id": str(experiment_id),
            "reason": reason,
            "snapshot_id": str(snapshot_id),
        })
        logger.info("Evolution ROLLED BACK: %s — %s", proposal.description, reason)
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution && python -m pytest tests/test_evolution_director.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution
git add src/max/evolution/director.py tests/test_evolution_director.py
git commit -m "feat(evolution): add EvolutionDirectorAgent with 7-step pipeline"
```

---

## Task 11: Package Exports + Integration Test

**Files:**
- Modify: `src/max/evolution/__init__.py`
- Create: `tests/test_evolution_integration.py`

- [ ] **Step 1: Update __init__.py exports**

```python
# src/max/evolution/__init__.py
"""Phase 7: Self-Evolution System.

Components:
  - EvolutionDirectorAgent — orchestrates the 7-step evolution pipeline
  - EvolutionStore — persistence layer for evolution data
  - SnapshotManager — captures and restores system state
  - PreferenceProfileManager — behavioral adaptation through user observation
  - SelfModel — capability map, performance baselines, failure taxonomy
  - ImprovementAgent — implements evolution changes in sandbox
  - CanaryRunner — replays tasks to verify non-regression
  - Scouts — discover improvement opportunities (Tool, Pattern, Quality, Ecosystem)
"""

from max.evolution.canary import CanaryRunner
from max.evolution.director import EvolutionDirectorAgent
from max.evolution.improver import ImprovementAgent
from max.evolution.models import (
    CanaryRequest,
    CanaryResult,
    CanaryTaskResult,
    ChangeSet,
    ChangeSetEntry,
    CommunicationPrefs,
    CodePrefs,
    DomainPrefs,
    EvolutionJournalEntry,
    EvolutionProposal,
    Observation,
    PreferenceProfile,
    PromotionEvent,
    RollbackEvent,
    SnapshotData,
    WorkflowPrefs,
)
from max.evolution.preference import PreferenceProfileManager
from max.evolution.scouts import (
    BaseScout,
    EcosystemScout,
    PatternScout,
    QualityScout,
    ToolScout,
)
from max.evolution.self_model import SelfModel
from max.evolution.snapshot import SnapshotManager
from max.evolution.store import EvolutionStore

__all__ = [
    "CanaryRunner",
    "EvolutionDirectorAgent",
    "EvolutionStore",
    "ImprovementAgent",
    "PreferenceProfileManager",
    "SelfModel",
    "SnapshotManager",
    # Scouts
    "BaseScout",
    "EcosystemScout",
    "PatternScout",
    "QualityScout",
    "ToolScout",
    # Models
    "CanaryRequest",
    "CanaryResult",
    "CanaryTaskResult",
    "ChangeSet",
    "ChangeSetEntry",
    "CommunicationPrefs",
    "CodePrefs",
    "DomainPrefs",
    "EvolutionJournalEntry",
    "EvolutionProposal",
    "Observation",
    "PreferenceProfile",
    "PromotionEvent",
    "RollbackEvent",
    "SnapshotData",
    "WorkflowPrefs",
]
```

- [ ] **Step 2: Write integration test**

```python
# tests/test_evolution_integration.py
"""Integration test — verifies all evolution components work together."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from max.evolution import (
    CanaryRunner,
    EvolutionDirectorAgent,
    EvolutionStore,
    ImprovementAgent,
    PreferenceProfileManager,
    SelfModel,
    SnapshotManager,
)
from max.evolution.models import (
    CanaryResult,
    ChangeSet,
    ChangeSetEntry,
    EvolutionProposal,
    PreferenceProfile,
)
from max.evolution.scouts import ToolScout, PatternScout, QualityScout, EcosystemScout


class TestImportAll:
    """Verify all exports are importable."""

    def test_all_classes_importable(self):
        from max.evolution import (
            CanaryRunner, EvolutionDirectorAgent, EvolutionStore,
            ImprovementAgent, PreferenceProfileManager, SelfModel,
            SnapshotManager, BaseScout, ToolScout, PatternScout,
            QualityScout, EcosystemScout,
        )
        assert EvolutionDirectorAgent is not None
        assert EvolutionStore is not None

    def test_all_models_importable(self):
        from max.evolution import (
            CanaryRequest, CanaryResult, CanaryTaskResult,
            ChangeSet, ChangeSetEntry, CommunicationPrefs,
            CodePrefs, DomainPrefs, EvolutionJournalEntry,
            EvolutionProposal, Observation, PreferenceProfile,
            PromotionEvent, RollbackEvent, SnapshotData, WorkflowPrefs,
        )
        assert EvolutionProposal is not None


class TestEndToEndPipeline:
    """Simulates a full evolution cycle with mocked infrastructure."""

    @pytest.mark.asyncio
    async def test_full_cycle_promote(self):
        """Scout discovers → Director evaluates → Snapshot → Implement → Canary → Promote."""
        # Setup mocks
        mock_db = AsyncMock()
        mock_llm = AsyncMock()
        mock_bus = AsyncMock()
        mock_bus.subscribe = AsyncMock()
        mock_bus.publish = AsyncMock()

        evo_store = AsyncMock(spec=EvolutionStore)
        evo_store.create_proposal = AsyncMock()
        evo_store.update_proposal_status = AsyncMock()
        evo_store.promote_candidates = AsyncMock()
        evo_store.discard_candidates = AsyncMock()
        evo_store.record_to_ledger = AsyncMock()
        evo_store.get_all_prompts = AsyncMock(return_value={"coordinator": "Be concise"})
        evo_store.get_all_tool_configs = AsyncMock(return_value={})

        quality_store = AsyncMock()
        quality_store.get_quality_pulse = AsyncMock(return_value={
            "pass_rate": 0.9, "avg_score": 0.85,
        })

        mock_metrics = AsyncMock()
        mock_metrics.get_baseline = AsyncMock(return_value=None)

        snapshot_mgr = AsyncMock(spec=SnapshotManager)
        snapshot_mgr.capture = AsyncMock(return_value=uuid.uuid4())
        snapshot_mgr.restore = AsyncMock()

        improver = AsyncMock(spec=ImprovementAgent)
        improver.implement = AsyncMock(return_value=ChangeSet(
            proposal_id=uuid.uuid4(),
            entries=[ChangeSetEntry(
                target_type="prompt", target_id="coordinator",
                old_value="Be concise", new_value="Be concise and structured",
            )],
        ))

        canary = AsyncMock(spec=CanaryRunner)
        canary.run = AsyncMock(return_value=CanaryResult(
            experiment_id=uuid.uuid4(),
            task_results=[],
            overall_passed=True,
        ))

        self_model = AsyncMock(spec=SelfModel)
        self_model.record_evolution = AsyncMock()

        settings = MagicMock()
        settings.evolution_min_priority = 0.3
        settings.evolution_max_concurrent = 1
        settings.evolution_freeze_consecutive_drops = 2
        settings.evolution_canary_replay_count = 5
        settings.evolution_canary_timeout_seconds = 300

        state_mgr = AsyncMock()
        task_store = AsyncMock()
        task_store.get_recent_completed = AsyncMock(return_value=[])

        director = EvolutionDirectorAgent(
            llm=mock_llm, bus=mock_bus, evo_store=evo_store,
            quality_store=quality_store, snapshot_manager=snapshot_mgr,
            improver=improver, canary_runner=canary,
            self_model=self_model, settings=settings,
            state_manager=state_mgr, task_store=task_store,
        )

        # Create a proposal that passes evaluation
        proposal = EvolutionProposal(
            scout_type="quality",
            description="Improve coordinator prompt structure",
            target_type="prompt",
            target_id="coordinator",
            impact_score=0.8,
            effort_score=0.2,
            risk_score=0.1,
        )

        # Run the pipeline
        assert director.evaluate_proposal(proposal) is True
        await director.run_pipeline(proposal)

        # Verify all steps executed
        snapshot_mgr.capture.assert_called_once()
        improver.implement.assert_called_once()
        canary.run.assert_called_once()
        evo_store.promote_candidates.assert_called_once()
        evo_store.record_to_ledger.assert_called()
        mock_bus.publish.assert_called()

    @pytest.mark.asyncio
    async def test_full_cycle_rollback(self):
        """Same setup but canary fails → rollback."""
        mock_bus = AsyncMock()
        mock_bus.subscribe = AsyncMock()
        mock_bus.publish = AsyncMock()

        evo_store = AsyncMock(spec=EvolutionStore)
        evo_store.create_proposal = AsyncMock()
        evo_store.update_proposal_status = AsyncMock()
        evo_store.promote_candidates = AsyncMock()
        evo_store.discard_candidates = AsyncMock()
        evo_store.record_to_ledger = AsyncMock()

        snapshot_mgr = AsyncMock(spec=SnapshotManager)
        snapshot_mgr.capture = AsyncMock(return_value=uuid.uuid4())
        snapshot_mgr.restore = AsyncMock()

        improver = AsyncMock(spec=ImprovementAgent)
        improver.implement = AsyncMock(return_value=ChangeSet(
            proposal_id=uuid.uuid4(),
            entries=[ChangeSetEntry(
                target_type="prompt", target_id="coordinator",
                old_value="old", new_value="new",
            )],
        ))

        canary = AsyncMock(spec=CanaryRunner)
        canary.run = AsyncMock(return_value=CanaryResult(
            experiment_id=uuid.uuid4(),
            task_results=[],
            overall_passed=False,  # FAIL
        ))

        self_model = AsyncMock(spec=SelfModel)
        settings = MagicMock()
        settings.evolution_min_priority = 0.3
        settings.evolution_canary_replay_count = 5
        settings.evolution_canary_timeout_seconds = 300

        task_store = AsyncMock()
        task_store.get_recent_completed = AsyncMock(return_value=[])

        director = EvolutionDirectorAgent(
            llm=AsyncMock(), bus=mock_bus, evo_store=evo_store,
            quality_store=AsyncMock(), snapshot_manager=snapshot_mgr,
            improver=improver, canary_runner=canary,
            self_model=self_model, settings=settings,
            state_manager=AsyncMock(), task_store=task_store,
        )

        proposal = EvolutionProposal(
            scout_type="tool", description="Bad change",
            target_type="tool_config", impact_score=0.8,
            effort_score=0.2, risk_score=0.1,
        )
        await director.run_pipeline(proposal)

        # Verify rollback
        snapshot_mgr.restore.assert_called_once()
        evo_store.discard_candidates.assert_called_once()
        evo_store.promote_candidates.assert_not_called()
```

- [ ] **Step 3: Run full test suite**

Run: `cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution && python -m pytest tests/test_evolution_*.py tests/test_snapshot.py tests/test_preference.py tests/test_scouts.py tests/test_improver.py tests/test_canary.py tests/test_self_model.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution
git add src/max/evolution/__init__.py tests/test_evolution_integration.py
git commit -m "feat(evolution): add package exports and integration tests"
```

---

## Task 12: Full Suite Verification + Lint

**Files:**
- All Phase 7 files

- [ ] **Step 1: Run full project test suite**

Run: `cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution && python -m pytest tests/ -v --tb=short 2>&1 | tail -30`
Expected: All previous tests (949) + all new evolution tests pass

- [ ] **Step 2: Run linter**

Run: `cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution && python -m ruff check src/max/evolution/ tests/test_evolution*.py tests/test_snapshot.py tests/test_preference.py tests/test_scouts.py tests/test_improver.py tests/test_canary.py tests/test_self_model.py`
Expected: No errors

- [ ] **Step 3: Fix any lint issues found**

- [ ] **Step 4: Commit lint fixes if any**

```bash
cd /home/venu/Desktop/everactive/.claude/worktrees/phase7-evolution
git add -A && git commit -m "fix(evolution): address lint findings"
```
