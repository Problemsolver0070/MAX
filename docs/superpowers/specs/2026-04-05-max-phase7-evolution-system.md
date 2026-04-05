# Phase 7: Self-Evolution System — Design Specification

## 1. Overview

Phase 7 is the final phase of Max. It adds self-improvement capabilities: learning user preferences, discovering optimization opportunities, implementing changes in sandboxed isolation, verifying improvements through canary testing, and promoting or rolling back automatically.

**Goal:** Enable Max to get measurably better over time without human intervention, while guaranteeing it never gets worse (strict non-regression via canary testing and anti-degradation triggers).

**Architecture:** Three pillars — Behavioral Adaptation (learns the user), System Evolution (upgrades itself), Quality Ratchet Integration (only goes up). A Self-Model maintains awareness of capabilities and limitations.

**Builds on:**
- Phase 1 (config, models, LLM, bus, database)
- Phase 2 (memory tiers, context anchors, cold storage)
- Phase 4 (coordinator, orchestrator, workers, task store)
- Phase 5 (quality director, auditors, rule engine, quality store, ledger)
- Phase 6 (tool executor, tool registry)

---

## 2. Architecture

### 2.1 New Package: `src/max/evolution/`

```
src/max/evolution/
  __init__.py          # Exports
  models.py            # Pydantic models for evolution domain
  store.py             # EvolutionStore — DB persistence
  director.py          # EvolutionDirectorAgent — orchestrates pipeline
  scouts.py            # Scout agents (4 types)
  improver.py          # ImprovementAgent — implements changes in sandbox
  canary.py            # CanaryRunner — replays tasks, compares outputs
  snapshot.py          # SnapshotManager — capture/restore system state
  preference.py        # PreferenceProfileManager — behavioral adaptation
  self_model.py        # SelfModel — capability map, baselines, failure taxonomy
```

### 2.2 Agent Architecture

```
EvolutionDirectorAgent (BaseAgent)
  ├── Subscribes to: evolution.trigger, audit.complete, quality.correction
  ├── Manages: EvolutionState on CoordinatorState
  ├── Orchestrates: Scout → Evaluate → Snapshot → Implement → Audit → Canary → Promote
  │
  ├── Scouts (spawned by Director, not persistent)
  │   ├── ToolScout — discovers new tool configs, parameter tuning
  │   ├── PatternScout — finds workflow pattern improvements
  │   ├── QualityScout — root-cause analysis on recurring failures
  │   └── EcosystemScout — monitors external dependencies, API changes
  │
  ├── ImprovementAgent (spawned per proposal)
  │   └── Implements proposed change in isolated sandbox context
  │
  └── CanaryRunner (not an agent — utility class)
      └── Replays recent tasks, compares outputs against baseline
```

### 2.3 Data Flow

```
[Signals] → [Scouts discover] → [Director evaluates] → [Snapshot current] →
[Improver implements] → [Quality Audit] → [Canary Test] → [Promote | Rollback]
```

The entire pipeline is async, event-driven via the message bus. Each step publishes its result to a bus channel, and the director orchestrates transitions.

---

## 3. Pillar 1: Behavioral Adaptation

### 3.1 Observation Signals

The system observes user behavior across multiple signal types:

| Signal | Strength | Source | What It Captures |
|--------|----------|--------|------------------|
| Correction | Strongest | `quality.correction` bus event | User says "no, I meant X" — stored as context anchor |
| Acceptance | Strong | Task marked complete without edits | Positive reinforcement of approach |
| Choice | Medium | User picks from options | Preference pattern emerges over time |
| Modification | Medium | User edits Max's output | Diff reveals style/content preferences |
| Timing | Weak | Message timestamps | Active hours, urgency patterns |

### 3.2 PreferenceProfile Model

Stored as a cold memory JSON document, keyed by user ID. Structure:

```python
class PreferenceProfile(BaseModel):
    user_id: str
    communication: CommunicationPrefs  # tone, detail_level, update_frequency, languages, timezone
    code: CodePrefs                    # style per language, review depth, test coverage, commit style  
    workflow: WorkflowPrefs            # clarification_threshold, autonomy_level, reporting_style
    domain_knowledge: DomainPrefs      # expertise_areas, client_contexts, project_conventions
    observation_log: list[Observation] # raw signal log (last 500, FIFO)
    updated_at: datetime
    version: int
```

### 3.3 PreferenceProfileManager

```python
class PreferenceProfileManager:
    def __init__(self, db: Database, llm: LLMClient)
    
    async def record_signal(self, signal_type: str, data: dict) -> None
    async def get_profile(self, user_id: str) -> PreferenceProfile
    async def refresh_profile(self, user_id: str) -> PreferenceProfile  # LLM analyzes signals, updates profile
    async def get_context_injection(self, user_id: str) -> dict  # Returns formatted prefs for agent context
```

**Refresh cadence:** Profile is refreshed (LLM re-analyzes observation log) after every 10 new signals, or on explicit request.

**Context injection:** `get_context_injection()` returns a dict that gets merged into every agent's context package via the existing `ContextPackager`. Each agent type uses different sections:
- Communicator → `communication` prefs
- Planner → `workflow` prefs
- Workers → `code` prefs
- Auditors → `code.test_coverage`, `code.review_depth`

---

## 4. Pillar 2: System Evolution Pipeline

### 4.1 The 7-Step Pipeline

#### Step 1: Discover

Scouts are spawned periodically by the Evolution Director (configurable interval, default 6 hours). Each scout type looks for specific improvement opportunities:

- **ToolScout:** Analyzes tool usage patterns from `performance_metrics`. Finds tools with high error rates, slow execution, or unused configurations.
- **PatternScout:** Reviews recent task plans from `TaskStore`. Identifies recurring decomposition patterns that could be templated.
- **QualityScout:** Queries `QualityStore` for recurring failure categories. Performs root-cause analysis on audit failures that share a common pattern.
- **EcosystemScout:** Checks for changes in external APIs, new tool capabilities, dependency updates (via tool metadata).

Each scout returns a list of `EvolutionProposal` models.

#### Step 2: Evaluate

The Evolution Director receives proposals and evaluates each:
- **Impact score** (0-1): How much improvement is expected?
- **Effort score** (0-1): How complex is the change?
- **Risk score** (0-1): How likely is regression?
- **Priority** = impact * (1 - risk) / max(effort, 0.1)

Proposals below a configurable threshold (`evolution_min_priority`, default 0.3) are discarded. Top proposal proceeds to implementation.

**Single-flight rule:** Only ONE evolution experiment runs at a time. Concurrent experiments make canary testing unreliable.

#### Step 3: Snapshot

Before any change, `SnapshotManager` captures current system state:
- All mutable agent prompts (stored in `evolution_prompts` table)
- Tool configurations (stored in `evolution_tool_configs` table)
- Context packaging rules (stored in `evolution_context_rules` table)
- Current quality metrics baseline (from `MetricCollector.get_baseline()`)

Snapshots are stored in the `evolution_snapshots` table with a UUID. The snapshot ID is linked to the experiment.

#### Step 4: Implement

An `ImprovementAgent` is spawned with:
- The proposal description
- Current system state from the snapshot
- Constraints (what it can and cannot modify)

The agent produces a `ChangeSet` — a list of specific mutations:
- Prompt modifications (old text → new text for a specific agent type)
- Tool config changes (parameter adjustments)
- New context packaging rules

Changes are written to a "candidate" version in the database (same tables, tagged with `experiment_id`).

#### Step 5: Audit

The existing Quality Director audits the proposed changes:
- Prompt changes are reviewed for quality rule compliance
- The audit uses the blind protocol (auditor doesn't see the improvement agent's reasoning)
- If audit fails, the experiment is shelved immediately

#### Step 6: Canary Test

`CanaryRunner` replays recent completed tasks (configurable count, default 5-10):
1. Fetches recent task + subtask records from `TaskStore`
2. For each task, runs the planning + execution pipeline with the candidate configuration
3. Runs the quality audit on canary output
4. Compares canary audit scores against the original scores

**Strict non-regression rule:** The candidate must score equal or better on EVERY replayed task. A single regression shelves the experiment.

Comparison uses `MetricCollector.compare()` to determine statistical significance.

#### Step 7: Promote or Rollback

- **Promote:** Candidate configuration becomes live. The old snapshot is archived. `EvolutionState.last_promotion` is updated. An `evolution_promoted` entry is appended to the quality ledger.
- **Rollback:** On any failure (audit, canary, or runtime error), the snapshot is restored. The experiment is shelved in `shelved_improvements`. An `evolution_rolled_back` entry is appended to the quality ledger.

### 4.2 What Can Be Evolved

| Target | Storage | How It Changes |
|--------|---------|----------------|
| Agent system prompts | `evolution_prompts` table | Text replacement, section additions |
| Tool configurations | `evolution_tool_configs` table | Parameter adjustments (timeouts, limits) |
| Context packaging rules | `evolution_context_rules` table | New rules for proactive context inclusion |
| Workflow patterns | `evolution_prompts` (planner prompt) | Better decomposition templates |

**What CANNOT be evolved (hard-coded safety rails):**
- Core agent logic (Python code)
- Database schema
- Security controls (injection scanner rules)
- Authentication/authorization
- The evolution pipeline itself (no self-modifying evolution)

---

## 5. Pillar 3: Quality Ratchet Integration

### 5.1 Wiring User Corrections

The existing `QualityStore.record_user_correction()` stub gets wired:
1. CommunicatorAgent detects correction patterns ("no, I meant...", "actually...", explicit negation)
2. Publishes to `quality.correction` bus channel
3. PreferenceProfileManager records the signal
4. QualityStore records to ledger
5. RuleEngine can extract rules from corrections (new method: `extract_rules_from_correction()`)

### 5.2 Anti-Degradation Trigger

The Evolution Director monitors quality metrics via `QualityStore.get_quality_pulse()`:

```python
async def check_anti_degradation(self) -> bool:
    """Returns True if evolution should be frozen."""
    pulse = await self._quality_store.get_quality_pulse(hours=24)
    prev_pulse = await self._quality_store.get_quality_pulse(hours=48)  # previous period
    
    # Freeze if pass rate dropped for 2 consecutive periods
    if pulse["pass_rate"] < prev_pulse["pass_rate"] and self._consecutive_drops >= 1:
        return True
    # Freeze if avg score dropped below threshold
    if pulse["avg_score"] < self._settings.quality_pass_threshold:
        return True
    return False
```

When triggered:
- `EvolutionState.evolution_frozen = True` with reason
- All non-critical evolution experiments are shelved
- Quality Director is notified to increase audit scrutiny
- A QualityScout is dispatched for focused investigation
- Freeze lifts when metrics recover for 2 consecutive periods

### 5.3 Learning from Successes and Failures

Already implemented in Phase 5 (RuleEngine). Phase 7 enhances:
- Quality rules generated from evolution failures get tagged with `source="evolution"`
- Quality patterns from successful evolutions get tagged similarly
- The Self-Model tracks which types of evolution succeed vs fail

---

## 6. Meta-Learning: Self-Model

### 6.1 SelfModel Class

```python
class SelfModel:
    def __init__(self, db: Database, metrics: MetricCollector)
    
    # Capability Map
    async def record_capability(self, domain: str, task_type: str, score: float) -> None
    async def get_capability_map(self) -> dict[str, dict[str, float]]
    
    # Performance Baselines
    async def update_baselines(self) -> dict[str, MetricBaseline]
    async def get_baseline(self, metric: str) -> MetricBaseline | None
    
    # Failure Taxonomy
    async def record_failure(self, category: str, details: dict) -> None
    async def get_failure_taxonomy(self) -> dict[str, int]  # category -> count
    
    # Evolution Journal
    async def record_evolution(self, entry: EvolutionJournalEntry) -> None
    async def get_journal(self, limit: int = 50) -> list[EvolutionJournalEntry]
    
    # Confidence Calibration
    async def record_prediction(self, predicted_score: float, actual_score: float) -> None
    async def get_calibration_error(self) -> float  # mean absolute error
```

### 6.2 Capability Map

Built from audit scores grouped by task domain and type:
- Domain: "code", "research", "communication", "data_analysis"
- Type: "bug_fix", "feature", "refactor", "explanation", "summary"
- Score: Rolling average of audit scores for that domain+type pair

Used by: Planner (to set realistic expectations), Evolution Director (to prioritize improvements in weak areas).

### 6.3 Confidence Calibration

Tracks predicted confidence vs actual audit score over time. If Max consistently over-estimates (confident but wrong) or under-estimates (uncertain but correct), the calibration adjusts. This feeds back into worker confidence scores.

---

## 7. Database Schema Additions

```sql
-- Evolution proposals from scouts
CREATE TABLE IF NOT EXISTS evolution_proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scout_type VARCHAR(50) NOT NULL,
    description TEXT NOT NULL,
    target_type VARCHAR(50) NOT NULL,  -- prompt | tool_config | context_rule | workflow
    target_id VARCHAR(200),            -- specific prompt/tool/rule being changed
    impact_score REAL NOT NULL DEFAULT 0.0,
    effort_score REAL NOT NULL DEFAULT 0.0,
    risk_score REAL NOT NULL DEFAULT 0.0,
    priority REAL NOT NULL DEFAULT 0.0,
    status VARCHAR(20) NOT NULL DEFAULT 'proposed',  -- proposed | approved | implementing | testing | promoted | shelved | discarded
    experiment_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- System state snapshots before evolution changes
CREATE TABLE IF NOT EXISTS evolution_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID NOT NULL,
    snapshot_data JSONB NOT NULL,  -- full system state (prompts, configs, rules)
    metrics_baseline JSONB NOT NULL,  -- performance metrics at time of snapshot
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Mutable agent prompts (evolved over time)
CREATE TABLE IF NOT EXISTS evolution_prompts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_type VARCHAR(100) NOT NULL UNIQUE,
    prompt_text TEXT NOT NULL,
    version INT NOT NULL DEFAULT 1,
    experiment_id UUID,  -- NULL = live, non-NULL = candidate
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Mutable tool configurations
CREATE TABLE IF NOT EXISTS evolution_tool_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_id VARCHAR(200) NOT NULL,
    config JSONB NOT NULL,
    version INT NOT NULL DEFAULT 1,
    experiment_id UUID,  -- NULL = live, non-NULL = candidate
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Context packaging rules (evolved)
CREATE TABLE IF NOT EXISTS evolution_context_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_name VARCHAR(200) NOT NULL,
    condition JSONB NOT NULL,  -- when to apply
    action JSONB NOT NULL,     -- what context to include
    priority INT NOT NULL DEFAULT 0,
    version INT NOT NULL DEFAULT 1,
    experiment_id UUID,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Preference profiles for behavioral adaptation
CREATE TABLE IF NOT EXISTS preference_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(200) NOT NULL UNIQUE,
    communication JSONB NOT NULL DEFAULT '{}',
    code JSONB NOT NULL DEFAULT '{}',
    workflow JSONB NOT NULL DEFAULT '{}',
    domain_knowledge JSONB NOT NULL DEFAULT '{}',
    observation_log JSONB NOT NULL DEFAULT '[]',
    version INT NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Self-model capability entries
CREATE TABLE IF NOT EXISTS capability_map (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain VARCHAR(100) NOT NULL,
    task_type VARCHAR(100) NOT NULL,
    score REAL NOT NULL,
    sample_count INT NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(domain, task_type)
);

-- Failure taxonomy
CREATE TABLE IF NOT EXISTS failure_taxonomy (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category VARCHAR(100) NOT NULL,
    subcategory VARCHAR(100),
    details JSONB NOT NULL DEFAULT '{}',
    source_task_id UUID,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Evolution journal
CREATE TABLE IF NOT EXISTS evolution_journal (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID,
    action VARCHAR(50) NOT NULL,  -- proposed | approved | snapshot | implemented | audited | canary_passed | canary_failed | promoted | rolled_back | frozen | unfrozen
    details JSONB NOT NULL DEFAULT '{}',
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Confidence calibration tracking
CREATE TABLE IF NOT EXISTS confidence_calibration (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    predicted_score REAL NOT NULL,
    actual_score REAL NOT NULL,
    task_type VARCHAR(100),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Indexes:
```sql
CREATE INDEX IF NOT EXISTS idx_evo_proposals_status ON evolution_proposals(status);
CREATE INDEX IF NOT EXISTS idx_evo_proposals_created ON evolution_proposals(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_evo_snapshots_experiment ON evolution_snapshots(experiment_id);
CREATE INDEX IF NOT EXISTS idx_evo_prompts_agent_type ON evolution_prompts(agent_type) WHERE experiment_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_evo_tool_configs_tool ON evolution_tool_configs(tool_id) WHERE experiment_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_evo_journal_experiment ON evolution_journal(experiment_id);
CREATE INDEX IF NOT EXISTS idx_evo_journal_recorded ON evolution_journal(recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_capability_map_domain ON capability_map(domain, task_type);
CREATE INDEX IF NOT EXISTS idx_failure_taxonomy_category ON failure_taxonomy(category);
CREATE INDEX IF NOT EXISTS idx_confidence_calibration_recorded ON confidence_calibration(recorded_at DESC);
```

---

## 8. Configuration Additions

New fields in `Settings` (src/max/config.py):

```python
# Evolution System
evolution_scout_interval_hours: int = 6        # How often scouts run
evolution_canary_replay_count: int = 5         # Tasks to replay in canary
evolution_min_priority: float = 0.3            # Minimum proposal priority
evolution_max_concurrent: int = 1              # Max concurrent experiments (always 1)
evolution_freeze_consecutive_drops: int = 2    # Drops before freeze
evolution_preference_refresh_signals: int = 10 # Signals before profile refresh
evolution_canary_timeout_seconds: int = 300    # Per-task canary timeout
evolution_snapshot_retention_days: int = 30    # How long to keep snapshots
```

---

## 9. Bus Channels

New message bus channels for evolution events:

| Channel | Publisher | Subscriber | Payload |
|---------|-----------|------------|---------|
| `evolution.trigger` | Scheduler/Manual | EvolutionDirector | `{"trigger": "scheduled\|manual"}` |
| `evolution.proposal` | Scouts | EvolutionDirector | `EvolutionProposal` |
| `evolution.approved` | EvolutionDirector | ImprovementAgent | `ApprovedProposal` |
| `evolution.implemented` | ImprovementAgent | EvolutionDirector | `ChangeSet` |
| `evolution.canary.start` | EvolutionDirector | CanaryRunner | `CanaryRequest` |
| `evolution.canary.result` | CanaryRunner | EvolutionDirector | `CanaryResult` |
| `evolution.promoted` | EvolutionDirector | All agents | `PromotionEvent` |
| `evolution.rolled_back` | EvolutionDirector | All agents | `RollbackEvent` |
| `evolution.frozen` | EvolutionDirector | All agents | `FreezeEvent` |
| `quality.correction` | CommunicatorAgent | PreferenceProfileManager, QualityStore | `UserCorrection` |

---

## 10. Integration Points

### 10.1 With CoordinatorState (Phase 4)

`CoordinatorState.evolution` (EvolutionState) is already defined. Phase 7 populates it:
- `active_experiments` — updated when experiment starts/ends
- `canary_status` — updated during canary phase
- `last_promotion` / `last_rollback` — timestamps
- `evolution_frozen` / `freeze_reason` — anti-degradation state

### 10.2 With QualityStore (Phase 5)

- Reads `get_quality_pulse()` for anti-degradation monitoring
- Reads `get_active_rules()` for scout analysis
- Reads `get_patterns()` for pattern scout
- Writes to quality ledger via new entry types: `evolution_proposed`, `evolution_promoted`, `evolution_rolled_back`, `evolution_frozen`
- Calls `record_user_correction()` (wires existing stub)

### 10.3 With MetricCollector (Phase 2)

- Records evolution-specific metrics: `evolution_duration`, `canary_score_delta`, `preference_profile_updates`
- Uses `get_baseline()` for canary comparison
- Uses `compare()` for statistical significance testing

### 10.4 With ContextPackager (Phase 2)

- `PreferenceProfileManager.get_context_injection()` is called by `ContextPackager` when building agent context
- Adds preference data to the context package under a `user_preferences` key

### 10.5 With TaskStore (Phase 4)

- `CanaryRunner` reads recent completed tasks for replay
- Uses `get_tasks()` filtered by status=completed, ordered by completion date

### 10.6 With RuleEngine (Phase 5)

- New method `extract_rules_from_correction()` for user correction signals
- Evolution-sourced rules tagged with `source="evolution"`

---

## 11. Testing Strategy

### 11.1 Unit Tests

Each module gets comprehensive unit tests:
- `tests/test_evolution_models.py` — Model validation
- `tests/test_evolution_store.py` — DB operations (real SQLite)
- `tests/test_evolution_director.py` — Pipeline orchestration (mocked deps)
- `tests/test_scouts.py` — Scout logic (mocked quality store + metrics)
- `tests/test_improver.py` — Improvement agent (mocked LLM)
- `tests/test_canary.py` — Canary runner (mocked task replay)
- `tests/test_snapshot.py` — Snapshot capture/restore
- `tests/test_preference.py` — Preference profile lifecycle
- `tests/test_self_model.py` — Capability map, calibration
- `tests/test_evolution_integration.py` — End-to-end pipeline

### 11.2 Testing Approach

- All external deps (LLM, bus, DB) mocked in unit tests
- Real SQLite for store tests (same pattern as Phase 5)
- Pipeline tests verify state transitions: proposed → approved → snapshot → implemented → audited → canary → promoted/rolled_back
- Anti-degradation tests verify freeze/unfreeze logic
- Canary tests verify strict non-regression enforcement

---

## 12. Error Handling

- All evolution operations are wrapped in try/except. Failures shelve the experiment, never crash.
- Canary timeout (default 300s per task) prevents stuck experiments from blocking the pipeline.
- If snapshot restore fails, the system logs a critical error and freezes evolution permanently until manual intervention.
- Scout failures are logged but never block the system — a failed scout simply produces no proposals.

---

## 13. Deferred / Out of Scope

- **Automated code changes:** Max cannot modify its own Python source code. Evolution is limited to prompts, configs, and rules.
- **Multi-user preference profiles:** V1 supports a single user profile. Multi-user can be added later.
- **External tool discovery:** EcosystemScout in V1 only analyzes existing tools, not external package discovery.
- **A/B testing:** V1 uses sequential experiments only (single-flight). A/B testing with traffic splitting is future work.
- **S3 snapshot storage:** V1 stores snapshots in PostgreSQL JSONB. S3 archival is future optimization.
