# Phase 5: Quality Gate — Design Specification

> **Status:** Approved  
> **Date:** 2026-04-05  
> **Depends on:** Phase 4 (Command Chain)  
> **Deferred to Phase 7:** Quality Scout (root-cause analysis), anti-degradation trigger (evolution freeze)

---

## 1. Purpose

Every output Max produces must be audited before delivery. Phase 5 inserts a Quality Gate between subtask execution and task completion. The Quality Director manages the audit lifecycle, spawns blind Auditor agents, collects verdicts, manages a fix loop for failures, maintains an append-only Quality Ledger, and learns Quality Rules from audit outcomes.

**Core invariant:** No result reaches the user without passing audit.

---

## 2. Architecture Overview

### 2.1 Pipeline Position

Phase 4 flow (current):
```
Orchestrator runs subtasks → assembles results → publishes tasks.complete → Coordinator → user
```

Phase 5 flow (new):
```
Orchestrator runs subtasks → publishes audit.request → Quality Director audits → 
  PASS: publishes audit.complete(success) → Orchestrator publishes tasks.complete
  FAIL: publishes audit.complete(fail + fix_instructions) → Orchestrator re-executes → re-audits
```

### 2.2 New Agents

| Agent | Type | Role |
|-------|------|------|
| **QualityDirectorAgent** | Persistent (long-lived) | Manages audit lifecycle, spawns Auditors, collects verdicts, maintains rules, updates ledger |
| **AuditorAgent** | Ephemeral (1 per subtask audit) | Reviews a single subtask's output against goal + criteria. Blind — never sees worker reasoning |

### 2.3 Blind Audit Protocol

The Auditor receives:
- The subtask's **output content** (what the worker produced)
- The **original goal anchor** (what was requested)
- The **quality criteria** (how to judge it)
- **Active quality rules** (learned constraints from past failures)

The Auditor does NOT receive:
- The worker's **reasoning** field
- The worker's **confidence** score
- The worker's **self-assessment**
- Any information about retries or previous attempts

This separation ensures the auditor judges the work product on its own merits.

---

## 3. Components

### 3.1 QualityDirectorAgent

**File:** `src/max/quality/director.py`

Extends `BaseAgent`. Long-lived agent that subscribes to bus channels and manages the audit pipeline.

**Responsibilities:**
1. Receives `audit.request` with task_id + list of subtask results
2. For each subtask, fetches quality_criteria and active quality rules from DB
3. Spawns an `AuditorAgent` per subtask (concurrently via `asyncio.gather`)
4. Collects `AuditReport` from each auditor
5. Decides overall task verdict:
   - All PASS → publish `audit.complete` with `success=True`
   - Any FAIL → publish `audit.complete` with `success=False` + failed subtask IDs + fix instructions
   - CONDITIONAL → treat as PASS with logged warnings
6. Records all verdicts in the Quality Ledger
7. After failures: extracts Quality Rules from audit issues
8. After successes: extracts Quality Patterns from high-scoring work
9. Updates `AuditPipelineState` on coordinator state (active audits, recent verdicts, quality pulse)

**State management:** Uses `CoordinatorStateManager` to update the `audit_pipeline` field on `CoordinatorState`. The Quality Director does not have its own separate state — it piggybacks on the existing coordinator state infrastructure.

**Constructor dependencies:**
```python
def __init__(
    self,
    config: AgentConfig,
    llm: LLMClient,
    bus: MessageBus,
    db: Database,
    warm_memory: WarmMemory,
    settings: Settings,
    task_store: TaskStore,
    quality_store: QualityStore,
    rule_engine: RuleEngine,
    state_manager: CoordinatorStateManager,
) -> None:
```

### 3.2 AuditorAgent

**File:** `src/max/quality/auditor.py`

Extends `BaseAgent`. Ephemeral — created per subtask audit, discarded after producing a report.

**System prompt template:**
```
You are a Quality Auditor for Max, an autonomous AI agent system.

Your job: evaluate work output against the stated goal and quality criteria.
You must be objective, thorough, and fair.

Goal: {goal_anchor}
Subtask: {subtask_description}
Quality Criteria: {quality_criteria}

Active Quality Rules (learned from past audits):
{quality_rules}

Evaluate the following work output and return ONLY valid JSON:
{
  "verdict": "pass | fail | conditional",
  "score": 0.0 to 1.0,
  "goal_alignment": 0.0 to 1.0,
  "confidence": 0.0 to 1.0,
  "issues": [{"category": "...", "description": "...", "severity": "low|normal|high|critical"}],
  "fix_instructions": "Specific instructions for fixing issues (only if verdict is fail)",
  "strengths": ["What was done well"],
  "reasoning": "Your evaluation reasoning"
}

Scoring guidelines:
- score: overall quality (0.0 = terrible, 1.0 = perfect)
- goal_alignment: how well the output achieves the stated goal
- confidence: how confident you are in your assessment
- verdict: "pass" if score >= 0.7 and no critical issues, "fail" if score < 0.5 or any critical issue, "conditional" otherwise
```

**Key design decisions:**
- The auditor gets a fresh LLM call with only the blind context (no worker reasoning)
- Response parsing handles JSON, markdown-fenced JSON, and plain text fallback (same pattern as worker/coordinator/planner)
- On parse failure: returns a CONDITIONAL verdict with confidence=0.3 to flag for human review

### 3.3 QualityStore

**File:** `src/max/quality/store.py`

Async CRUD layer for quality-specific database operations. Wraps the shared `Database` instance.

**Methods:**
```python
class QualityStore:
    def __init__(self, db: Database) -> None: ...
    
    # Audit reports
    async def create_audit_report(self, report: AuditReport) -> dict[str, Any]: ...
    async def get_audit_reports(self, task_id: UUID) -> list[dict[str, Any]]: ...
    async def get_audit_report_for_subtask(self, subtask_id: UUID) -> dict[str, Any] | None: ...
    
    # Quality Ledger (append-only)
    async def record_verdict(self, task_id: UUID, subtask_id: UUID, verdict: AuditVerdict, score: float, metadata: dict) -> None: ...
    async def record_rule(self, rule: QualityRule) -> None: ...
    async def record_pattern(self, pattern: QualityPattern) -> None: ...
    async def record_user_correction(self, task_id: UUID, correction: str) -> None: ...
    async def get_ledger_entries(self, entry_type: str, limit: int = 100) -> list[dict[str, Any]]: ...
    
    # Quality Rules
    async def create_rule(self, rule: QualityRule) -> None: ...
    async def get_active_rules(self, category: str | None = None) -> list[dict[str, Any]]: ...
    async def supersede_rule(self, old_rule_id: UUID, new_rule_id: UUID) -> None: ...
    
    # Quality Patterns
    async def create_pattern(self, pattern: QualityPattern) -> None: ...
    async def get_patterns(self, category: str | None = None, min_reinforcement: int = 1) -> list[dict[str, Any]]: ...
    async def reinforce_pattern(self, pattern_id: UUID) -> None: ...
    
    # Metrics
    async def get_quality_pulse(self, hours: int = 24) -> dict[str, Any]: ...
    async def get_pass_rate(self, hours: int = 24) -> float: ...
    async def get_avg_score(self, hours: int = 24) -> float: ...
```

### 3.4 RuleEngine

**File:** `src/max/quality/rules.py`

Manages quality rule lifecycle — extraction, storage, retrieval, supersession.

**Responsibilities:**
1. **Extract rules from failures:** When an audit fails, the Quality Director calls `extract_rules()` with the audit report. The RuleEngine uses the LLM to generate a `QualityRule` from the failure pattern.
2. **Retrieve active rules:** Returns all non-superseded rules, optionally filtered by category. These are injected into auditor prompts.
3. **Supersede rules:** When a new rule covers the same ground as an existing one, the old rule is marked superseded (never deleted — append-only ledger).
4. **Extract patterns from successes:** When audit passes with high scores (>= 0.9), extracts a `QualityPattern` capturing what made it good.
5. **Reinforce patterns:** When a pattern is seen again, increment its reinforcement count.

```python
class RuleEngine:
    def __init__(self, db: Database, llm: LLMClient, quality_store: QualityStore) -> None: ...
    
    async def extract_rules(self, report: AuditReport, subtask_description: str, output_content: str) -> list[QualityRule]: ...
    async def extract_patterns(self, report: AuditReport, subtask_description: str, output_content: str) -> list[QualityPattern]: ...
    async def get_rules_for_audit(self, category: str | None = None) -> list[QualityRule]: ...
    async def supersede_rule(self, old_rule_id: UUID, new_rule: QualityRule) -> None: ...
```

---

## 4. New Models

### 4.1 QualityPattern

**File:** `src/max/quality/models.py`

```python
class QualityPattern(BaseModel):
    """A quality pattern learned from high-scoring audits — reinforced over time."""
    id: UUID = Field(default_factory=uuid4)
    pattern: str                              # Description of what was done well
    source_task_id: UUID                      # Which task it was extracted from
    category: str                             # e.g., "code_quality", "research", "communication"
    reinforcement_count: int = 1              # How many times this pattern has been seen
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
```

### 4.2 AuditRequest

```python
class AuditRequest(BaseModel):
    """Published on audit.request by the Orchestrator."""
    task_id: UUID
    goal_anchor: str
    subtask_results: list[SubtaskAuditItem]
    quality_criteria: dict[str, Any] = Field(default_factory=dict)
```

### 4.3 SubtaskAuditItem

```python
class SubtaskAuditItem(BaseModel):
    """One subtask's output for the auditor to evaluate."""
    subtask_id: UUID
    description: str                          # What the subtask was supposed to do
    content: str                              # The actual output (worker's content)
    quality_criteria: dict[str, Any] = Field(default_factory=dict)
```

Note: `SubtaskAuditItem` deliberately excludes `reasoning`, `confidence`, and `error` fields from `SubtaskResult`. This enforces the blind audit protocol at the type level.

### 4.4 AuditResponse

```python
class AuditResponse(BaseModel):
    """Published on audit.complete by the Quality Director."""
    task_id: UUID
    success: bool                             # True if all subtasks passed
    verdicts: list[SubtaskVerdict]
    overall_score: float                      # Average across subtask scores
    fix_required: list[FixInstruction] = Field(default_factory=list)
```

### 4.5 SubtaskVerdict

```python
class SubtaskVerdict(BaseModel):
    subtask_id: UUID
    verdict: AuditVerdict
    score: float
    goal_alignment: float
    issues: list[dict[str, str]] = Field(default_factory=list)
```

### 4.6 FixInstruction

```python
class FixInstruction(BaseModel):
    subtask_id: UUID
    instructions: str                         # What needs to be fixed
    original_content: str                     # What the worker produced (for context)
    issues: list[dict[str, str]]              # The specific issues found
```

---

## 5. Bus Channel Topology

### 5.1 New Channels

| Channel | Publisher | Subscriber | Payload |
|---------|-----------|------------|---------|
| `audit.request` | Orchestrator | Quality Director | `AuditRequest` |
| `audit.complete` | Quality Director | Orchestrator | `AuditResponse` |

### 5.2 Modified Flow

**Before (Phase 4):**
```
Orchestrator → tasks.complete → Coordinator
```

**After (Phase 5):**
```
Orchestrator → audit.request → Quality Director → audit.complete → Orchestrator → tasks.complete → Coordinator
```

The Orchestrator's `on_execute` method changes:
1. After all phases complete successfully, instead of publishing `tasks.complete`, publish `audit.request`
2. New handler `on_audit_complete` receives audit results
3. If all pass: publish `tasks.complete` (same as before)
4. If any fail: re-execute only the failed subtasks with fix instructions appended to their prompts, then re-audit
5. Fix loop limit: `quality_max_fix_attempts` (default 2). After exhausting, publish `tasks.complete` with `success=False` and the audit report as the error

---

## 6. Orchestrator Modifications

### 6.1 New State

The Orchestrator needs to track pending audit state:

```python
# Pending audit callbacks — maps task_id to the data needed to resume
_pending_audits: dict[UUID, PendingAuditContext]
```

Where `PendingAuditContext` holds:
- `prior_results: list[SubtaskResult]` — the successful results
- `db_subtasks: list[dict]` — the original subtask definitions
- `fix_attempt: int` — current fix attempt count (0 = first audit)
- `goal_anchor: str`
- `quality_criteria: dict` — task-level quality criteria for re-audits

### 6.2 Modified `on_execute`

After all phases succeed:
1. Set task status to `AUDITING`
2. Build `AuditRequest` from successful subtask results (stripping reasoning/confidence for blind audit)
3. Store `PendingAuditContext` keyed by task_id
4. Publish to `audit.request`
5. Return (await audit response asynchronously)

### 6.3 New `on_audit_complete`

Handler for `audit.complete`:
1. Pop `PendingAuditContext` for the task_id
2. If `success=True`: assemble final result, publish `tasks.complete` (same logic as current success path)
3. If `success=False` and `fix_attempt < quality_max_fix_attempts`:
   - Re-execute only the failed subtasks with fix instructions in the worker prompt
   - Increment fix_attempt
   - Re-audit the new results
4. If `success=False` and fix limit exhausted:
   - Publish `tasks.complete` with `success=False` and audit issues as error

---

## 7. Database Migration

**File:** `src/max/db/migrations/005_quality_gate.sql`

### 7.1 New Table: quality_rules

```sql
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
CREATE INDEX IF NOT EXISTS idx_quality_rules_active ON quality_rules(category) WHERE superseded_by IS NULL;
```

### 7.2 New Table: quality_patterns

```sql
CREATE TABLE IF NOT EXISTS quality_patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pattern TEXT NOT NULL,
    source_task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
    category VARCHAR(50) NOT NULL,
    reinforcement_count INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quality_patterns_category ON quality_patterns(category);
CREATE INDEX IF NOT EXISTS idx_quality_patterns_reinforcement ON quality_patterns(reinforcement_count DESC);
```

### 7.3 ALTER audit_reports

Add columns for Phase 5:

```sql
ALTER TABLE audit_reports ADD COLUMN IF NOT EXISTS fix_instructions TEXT;
ALTER TABLE audit_reports ADD COLUMN IF NOT EXISTS strengths JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE audit_reports ADD COLUMN IF NOT EXISTS fix_attempt INTEGER NOT NULL DEFAULT 0;
```

### 7.4 Schema.sql Updates

Append the new tables and ALTER statements to the Phase 5 section of `schema.sql`.

---

## 8. Config Additions

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

---

## 9. Package Structure

```
src/max/quality/
├── __init__.py           # Package exports
├── models.py             # QualityPattern, AuditRequest, AuditResponse, SubtaskAuditItem, SubtaskVerdict, FixInstruction
├── auditor.py            # AuditorAgent (ephemeral, blind audit)
├── director.py           # QualityDirectorAgent (persistent, manages audit lifecycle)
├── store.py              # QualityStore (async CRUD for audit reports, ledger, rules, patterns)
└── rules.py              # RuleEngine (rule extraction, supersession, pattern extraction)
```

---

## 10. Quality Ledger Entry Types

The quality_ledger table uses `entry_type` to categorize entries. Phase 5 adds these types:

| entry_type | When recorded | Content fields |
|-----------|---------------|----------------|
| `audit_verdict` | After every audit | `{task_id, subtask_id, verdict, score, goal_alignment, fix_attempt}` |
| `quality_rule_created` | When a rule is extracted from a failure | `{rule_id, rule, category, severity, source_audit_id}` |
| `quality_rule_superseded` | When a rule is replaced | `{old_rule_id, new_rule_id, reason}` |
| `quality_pattern_created` | When a pattern is extracted from a success | `{pattern_id, pattern, category, source_task_id}` |
| `quality_pattern_reinforced` | When a pattern is seen again | `{pattern_id, new_reinforcement_count}` |
| `fix_attempt` | When a subtask is re-executed after audit failure | `{task_id, subtask_id, fix_attempt, fix_instructions}` |

All entries are append-only. Nothing is ever deleted from the ledger.

---

## 11. Fix Loop Flow

```
1. Orchestrator completes all subtask phases
2. Orchestrator publishes audit.request
3. Quality Director spawns Auditors (one per subtask, concurrent)
4. Each Auditor returns AuditReport
5. Quality Director aggregates verdicts:
   a. All PASS → publish audit.complete(success=True)
   b. Any FAIL → extract rules from failures → publish audit.complete(success=False, fix_instructions)
6. Orchestrator receives audit.complete:
   a. success=True → publish tasks.complete (deliver to user)
   b. success=False, fix_attempt < max → re-execute failed subtasks with fix_instructions in prompt → goto step 2
   c. success=False, fix_attempt >= max → publish tasks.complete(success=False, error=audit_issues)
```

### Fix Worker Prompt Augmentation

When re-executing a failed subtask, the worker's system prompt is augmented:

```
[Original system prompt]

IMPORTANT: Your previous output was audited and found these issues:
{fix_instructions}

The specific problems were:
{issues_list}

Please fix these issues in your new output. Focus on addressing the audit feedback.
```

---

## 12. Integration with Existing Infrastructure

### 12.1 CoordinatorState

The existing `AuditPipelineState` model (already in `src/max/memory/models.py`) is used by the Quality Director to track active audits, recent verdicts, and quality pulse. The Quality Director updates this via `CoordinatorStateManager` after each audit cycle.

### 12.2 MetricCollector

The Quality Director uses the existing `MetricCollector` (from Phase 2) to record quality metrics:
- `quality.audit_score` — individual audit scores
- `quality.pass_rate` — rolling pass rate
- `quality.fix_rate` — percentage of tasks requiring fixes
- `quality.avg_fix_attempts` — average fix attempts before passing

This enables baseline tracking and trend analysis using the existing `get_baseline()` and `compare()` methods.

### 12.3 TaskStore

Phase 5 uses the existing `TaskStore` for:
- `update_task_status(task_id, TaskStatus.AUDITING)` — when audit starts
- `update_task_status(task_id, TaskStatus.FIXING)` — when fix loop triggers
- `update_subtask_status(subtask_id, TaskStatus.AUDITING)` — per-subtask
- `get_subtasks(task_id)` — to fetch subtask details for audit

---

## 13. Deferred to Phase 7 (Evolution)

The following are explicitly out of scope for Phase 5:

1. **Quality Scout** — root-cause analysis agent spawned on audit failures. Requires Evolution Director to act on findings.
2. **Anti-degradation trigger** — "If any quality metric drops for 2 consecutive measurement periods, Evolution Director freezes all non-critical evolution." Requires Evolution Director.
3. **Confidence calibration** — tracking how well confidence scores predict actual quality. Can be added to MetricCollector later.
4. **User correction loop** — `record_user_correction()` is defined in QualityStore but the UI flow (user rejects a delivered result) depends on Phase 3's Communicator integration which is not wired yet.

---

## 14. Testing Strategy

- **Unit tests:** Each component (AuditorAgent, QualityDirectorAgent, QualityStore, RuleEngine) tested in isolation with mocked dependencies
- **Integration tests:** Full audit pipeline flow — Orchestrator → Quality Director → Auditor → fix loop → completion
- **DB tests:** QualityStore CRUD operations against real PostgreSQL (same pattern as test_postgres.py)
- **Target:** 50+ new tests, maintaining the existing 316 passing
