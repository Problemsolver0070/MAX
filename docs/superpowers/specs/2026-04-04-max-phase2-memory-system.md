# Max — Phase 2: Memory System Design Specification

**Date:** 2026-04-04
**Status:** Approved
**Author:** Venu + Claude
**Depends on:** Phase 1: Core Foundation (complete)

---

## 1. Three-Tier Memory Architecture

Max's memory is organized into three tiers with distinct access patterns, storage backends, and lifetimes. Every piece of information exists in exactly one tier at any given time, but can move between tiers based on relevance.

### 1.1 Hot Memory (LLM Context Window)

**Storage:** In-prompt content passed to each LLM call
**Scope:** Single agent, single call
**Lifetime:** Duration of one LLM invocation

Contents:
- Agent's system prompt and identity
- Current task goal + constraints
- Curated context package (assembled by Context Packager)
- Active conversation turns (for Communicator)
- Immediate tool outputs from current execution
- Relevant context anchors

Hot memory is **read-only from the system's perspective** — it's assembled fresh for each LLM call by the Context Packager. The agent cannot directly write to hot memory; it produces outputs that flow into warm or cold storage.

**Budget:** Each agent type has a configurable token budget. The Context Packager ensures the assembled hot memory never exceeds this budget. Default budgets:
- Coordinator: 16,384 tokens
- Planner: 32,768 tokens
- Sub-Agents: 24,576 tokens
- Auditors: 16,384 tokens
- All other agents: 24,576 tokens

### 1.2 Warm Memory (Redis)

**Storage:** Redis via the existing `WarmMemory` class (key-value + lists with TTL)
**Scope:** Cross-agent, cross-call, current operational window
**Lifetime:** Active until demoted by compaction (no hard TTL — relevance-driven)

Contents:
- Coordinator State Document (Section 6)
- Active task trees with full context
- Recent conversation summaries
- Context anchor cache (active anchors for fast access)
- Hot subgraph cache (frequently traversed graph neighborhoods)
- Agent state snapshots
- Pending decisions and follow-ups
- Compaction metadata (relevance scores, tier assignments)

The existing `WarmMemory` class provides the foundation. Phase 2 extends it with:
- Relevance-scored entries (each entry carries a relevance score + metadata)
- Tier-aware storage (full fidelity, summarized, pointer-only)
- Batch operations for compaction sweeps
- Pub/sub integration for cache invalidation

### 1.3 Cold Memory (PostgreSQL + pgvector)

**Storage:** PostgreSQL with pgvector extension via the existing `Database` class
**Scope:** Permanent, system-wide
**Lifetime:** Indefinite — never deleted, only archived

Contents:
- All past task records and outcomes
- Complete conversation history
- User preference profile (evolving)
- Learned patterns and behavioral rules
- Quality Ledger (append-only)
- Graph nodes and edges (persistent storage)
- Memory embeddings for semantic search
- Compacted content (full versions of summarized/pointer items)
- Anchor version history (supersession chains)
- System evolution history
- Audit trail

Cold memory is the source of truth. When warm memory is lost (Redis restart, cache eviction), it's reconstructed from cold storage. Every write to warm memory has a corresponding cold storage record.

---

## 2. Context Anchors

Context anchors are tagged content that resists compaction and maintains high priority across all memory operations. They represent critical context that must never be silently lost.

### 2.1 Anchor Types

| Type | Source | Example | Decay Rate (λ) |
|------|--------|---------|-----------------|
| `user_goal` | User message | "Build me a REST API for..." | 0.0005 (~58 days half-life) |
| `correction` | User correction | "No, I meant PostgreSQL not MySQL" | 0.0003 (~96 days half-life) |
| `decision` | Clarification outcome | "We'll use JWT, not sessions" | 0.001 (~29 days half-life) |
| `quality_standard` | User-confirmed | "Always write tests first" | 0.0002 (~144 days half-life) |
| `system_rule` | Learned behavior | "User prefers terse updates" | 0.0005 (~58 days half-life) |
| `security` | System-level | "Only accept messages from user ID X" | 0.0 (permanent) |

### 2.2 Anchor Lifecycle

Each anchor progresses through a lifecycle with explicit state transitions:

```
Created → Active → Stale → Archived
                ↑          ↓
                ← Restored ←
                
Active → Superseded → Archived (with link to replacement)
```

**States:**
- **Active** — in warm memory cache, included in context packaging by default, relevance score above 0.3
- **Stale** — relevance score dropped below 0.3, flagged for re-evaluation. Not auto-demoted — an Opus re-evaluation call determines: restore (boost relevance), supersede (create replacement), or archive
- **Superseded** — replaced by a newer anchor. Moved to cold storage with a `superseded_by` pointer. The supersession chain is preserved for audit: v1 → v2 → v3
- **Archived** — in cold storage only, retrievable via graph traversal or semantic search, but not in the active anchor set

**State transitions:**
- `Active → Stale`: Triggered when `relevance_score < 0.3` during compaction sweep
- `Stale → Active`: Re-evaluation determines anchor is still valid; relevance boosted
- `Stale → Archived`: Re-evaluation determines anchor is outdated and no replacement needed
- `Active → Superseded`: New information contradicts or refines this anchor
- `Superseded → Archived`: Automatic — superseded anchors always move to cold
- `Archived → Active`: Retrieved and explicitly promoted (user reference or strong semantic match)

### 2.3 Anchor Adaptation Mechanisms

**Relevance Decay (slow):** Anchors have relevance scores that decay, but at much slower rates than regular content (see λ values above). When an anchor's score drops below 0.3, it's flagged for re-evaluation rather than silently dropped.

**Supersession Chain:** When new information contradicts or refines an existing anchor, the system creates a new anchor and marks the old one as superseded. Each version is preserved in cold storage:
```
Anchor v1 (superseded_by: v2) → Anchor v2 (superseded_by: v3) → Anchor v3 (active)
```

**Periodic Re-evaluation:** An Opus call reviews stale anchors against recent context every 6 hours (configurable via `memory_anchor_re_evaluation_interval_hours`). The evaluator receives the anchor content, recent relevant context, and asks: "Is this anchor still accurate? Still relevant? Has the user's behavior contradicted it?" This catches drift that no single event would trigger. Re-evaluations are batched — all stale anchors are reviewed in a single Opus call to minimize API usage.

**Usage Tracking:** Every time an anchor is retrieved for context packaging, that access is logged. Anchors that are never retrieved over a sustained period are candidates for staleness review — they're "important" but apparently not useful.

**User-Triggered Cascade:** When the user explicitly changes a preference or goal, all anchors tagged with that domain get flagged for immediate re-evaluation. This is detected by the Communicator when processing user corrections.

### 2.4 Anchor Permanence Classes

| Class | Examples | Can be superseded? | Can be archived? |
|-------|----------|-------------------|------------------|
| **Permanent** | Security rules, user identity | Only by user | Never |
| **Durable** | User goals, quality standards | Yes, with audit trail | Only when superseded |
| **Adaptive** | Preferences, learned patterns | Yes, by stronger evidence | Yes, when stale |
| **Task-scoped** | Task goals, constraints | Yes, within task | When task completes |

### 2.5 Data Model

**Enhanced `context_anchors` table (extends Phase 1):**
```sql
ALTER TABLE context_anchors ADD COLUMN IF NOT EXISTS lifecycle_state VARCHAR(20) NOT NULL DEFAULT 'active';
ALTER TABLE context_anchors ADD COLUMN IF NOT EXISTS relevance_score REAL NOT NULL DEFAULT 1.0;
ALTER TABLE context_anchors ADD COLUMN IF NOT EXISTS last_accessed TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE context_anchors ADD COLUMN IF NOT EXISTS access_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE context_anchors ADD COLUMN IF NOT EXISTS decay_rate REAL NOT NULL DEFAULT 0.001;
ALTER TABLE context_anchors ADD COLUMN IF NOT EXISTS permanence_class VARCHAR(20) NOT NULL DEFAULT 'adaptive';
ALTER TABLE context_anchors ADD COLUMN IF NOT EXISTS superseded_by UUID REFERENCES context_anchors(id);
ALTER TABLE context_anchors ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE context_anchors ADD COLUMN IF NOT EXISTS parent_anchor_id UUID REFERENCES context_anchors(id);
```

**Pydantic model:**
```python
class AnchorLifecycleState(StrEnum):
    ACTIVE = "active"
    STALE = "stale"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"

class AnchorPermanenceClass(StrEnum):
    PERMANENT = "permanent"
    DURABLE = "durable"
    ADAPTIVE = "adaptive"
    TASK_SCOPED = "task_scoped"

class ContextAnchor(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    content: str
    anchor_type: str
    source_task_id: uuid.UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    lifecycle_state: AnchorLifecycleState = AnchorLifecycleState.ACTIVE
    relevance_score: float = Field(default=1.0, ge=0.0, le=1.0)
    last_accessed: datetime = Field(default_factory=lambda: datetime.now(UTC))
    access_count: int = 0
    decay_rate: float = 0.001
    permanence_class: AnchorPermanenceClass = AnchorPermanenceClass.ADAPTIVE
    superseded_by: uuid.UUID | None = None
    version: int = 1
    parent_anchor_id: uuid.UUID | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
```

---

## 3. Full Graph Layer

The graph layer is the relationship backbone of Max's memory. Every significant piece of context exists as a node, and relationships between them are explicit, weighted edges.

### 3.1 Node Types

| Type | Represents | Content Reference |
|------|-----------|-------------------|
| `anchor` | Context anchors | FK → context_anchors.id |
| `memory` | Cold storage entries | FK → memory_embeddings.id |
| `task` | Active and completed tasks | FK → tasks.id |
| `subtask` | Task subdivisions | FK → subtasks.id |
| `agent` | Agent identities | agent_id string |
| `tool` | Tool definitions | FK → tool registry |
| `rule` | Quality/evolution rules | FK → quality_ledger.id |
| `intent` | User messages | FK → intents.id |
| `result` | Task outcomes | FK → results.id |

### 3.2 Edge Properties

```python
class EdgeRelation(StrEnum):
    DERIVED_FROM = "derived_from"      # B was created using A
    DEPENDS_ON = "depends_on"          # B requires A to function
    SUPERSEDES = "supersedes"          # B replaces A
    RELATED_TO = "related_to"         # Semantic relationship
    PRODUCED_BY = "produced_by"       # A created B
    CONSTRAINS = "constrains"         # A limits/shapes B
    PARENT_OF = "parent_of"           # Hierarchical: task → subtask
    TRIGGERED_BY = "triggered_by"     # A caused B to happen
    REFERENCES = "references"         # A mentions/uses B

class GraphEdge(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    source_id: uuid.UUID
    target_id: uuid.UUID
    relation: EdgeRelation
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_traversed: datetime = Field(default_factory=lambda: datetime.now(UTC))
```

### 3.3 Traversal Engine

**Depth-limited BFS** with configurable parameters:
- `max_depth`: Maximum traversal depth (default 3, max 6)
- `min_weight`: Minimum edge weight to follow (default 0.1)
- `direction`: Outbound, inbound, or both
- `relation_filter`: Optional set of relation types to follow
- `max_results`: Maximum nodes to return (default 50)

**Path Scoring:**
```
path_score = product(edge_weights) × depth_penalty(depth)

where:
  depth_penalty(d) = 1.0 / (1.0 + 0.3 × d)
```

Paths are returned sorted by `path_score` descending. Each result includes the full path (list of edges) and the terminal node.

**Cycle Detection:** Standard visited-set approach. Each traversal maintains a `set[UUID]` of visited node IDs. Cycles are logged but not treated as errors — they indicate rich interconnection.

**Direction-Aware Traversal:**
- Outbound: "What did this produce/cause/enable?"
- Inbound: "What led to/caused/produced this?"
- Both: "What is related to this in any direction?"

### 3.4 Graph Operations API

```python
class MemoryGraph:
    async def add_node(self, node_type: str, content_id: uuid.UUID, metadata: dict) -> uuid.UUID
    async def add_edge(self, source: uuid.UUID, target: uuid.UUID, relation: EdgeRelation, weight: float = 1.0, metadata: dict = {}) -> uuid.UUID
    async def remove_node(self, node_id: uuid.UUID) -> None  # cascades edges
    async def remove_edge(self, edge_id: uuid.UUID) -> None
    async def update_edge_weight(self, edge_id: uuid.UUID, weight: float) -> None
    
    # Traversal
    async def traverse(self, start_node: uuid.UUID, direction: str = "outbound", max_depth: int = 3, min_weight: float = 0.1, relation_filter: set[EdgeRelation] | None = None, max_results: int = 50) -> list[TraversalPath]
    async def find_related(self, node_id: uuid.UUID, relation: EdgeRelation, min_weight: float = 0.1) -> list[GraphNode]
    async def shortest_path(self, source: uuid.UUID, target: uuid.UUID) -> TraversalPath | None
    async def subgraph(self, center: uuid.UUID, depth: int = 2) -> SubGraph
    
    # Maintenance
    async def decay_weights(self, cutoff_hours: float = 168.0, decay_factor: float = 0.95) -> int  # returns edges decayed
    async def merge_nodes(self, keep: uuid.UUID, remove: uuid.UUID) -> None  # rewire edges
    async def find_orphans(self) -> list[uuid.UUID]  # nodes with no edges
    async def get_stats(self) -> GraphStats
```

### 3.5 Weight Decay

Edge weights decay based on `last_traversed`:
```
decayed_weight = current_weight × decay_factor ^ (hours_since_last_traversal / cutoff_hours)
```

Edges that are frequently traversed stay strong. Unused edges weaken but are **never auto-deleted**. A weak edge is still a retrievable relationship; it just won't surface in default traversals. Deletion only happens when a node is explicitly removed (cascade) or during supervised cleanup.

### 3.6 Hot Subgraph Cache

Frequently traversed graph neighborhoods (around active tasks) are cached in warm memory for fast traversal. The cache:
- Holds the subgraph within depth-2 of all active task nodes
- Invalidated when edges are added/removed/updated in the cached region
- Rebuilt lazily on next traversal after invalidation
- Bounded to 500 nodes maximum (LRU eviction of least-recent subgraphs)

### 3.7 Data Model

```sql
-- Graph nodes (reference table pointing to typed content)
CREATE TABLE IF NOT EXISTS graph_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_type VARCHAR(20) NOT NULL,
    content_id UUID NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_graph_nodes_type ON graph_nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_content ON graph_nodes(content_id);

-- Graph edges (weighted, typed relationships)
CREATE TABLE IF NOT EXISTS graph_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    target_id UUID NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    relation VARCHAR(30) NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_traversed TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges(source_id, relation);
CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges(target_id, relation);
CREATE INDEX IF NOT EXISTS idx_graph_edges_weight ON graph_edges(weight DESC);
```

---

## 4. Continuous Compaction

Compaction keeps context sharp without ever losing information. Every piece of context has a relevance score that continuously decays, and compaction runs as an always-on background process.

**CRITICAL CONSTRAINT: No hard cuts, ever, under any condition.** Content is never abruptly dropped. Even under maximum memory pressure, the worst case is faster summarization through tiers. Content always exists somewhere in the system — warm, cold, or retrievable via graph/semantic search.

### 4.1 Relevance Score Model

```
relevance(item, t) = base_relevance × recency_factor(t) × usage_factor × anchor_boost

where:
  base_relevance    = initial importance (set when content enters the system, 0.0–1.0)
  recency_factor(t) = e^(-λ × hours_since_last_access)
  usage_factor      = log(1 + access_count) / log(1 + max_access_count_in_window)
  anchor_boost      = 10.0 if anchored, 1.0 otherwise
```

### 4.2 Decay Rates by Content Type

| Content Type | λ (decay rate) | Half-life (~) | Rationale |
|-------------|---------------|---------------|-----------|
| Active task context | 0.005 | ~6 days | Stays relevant while task is open |
| Conversation turns | 0.05 | ~14 hours | Recent conversation matters most |
| Decisions/outcomes | 0.01 | ~3 days | Important but not urgent |
| Anchored content | 0.001 | ~29 days | Resists decay, nearly permanent |
| Agent state | 0.02 | ~35 hours | Current state matters, old state less so |
| Quality rules | 0.002 | ~14.5 days | Learned patterns should persist |

### 4.3 Compaction Tiers

Content moves through tiers as relevance drops. Each tier represents a different fidelity level:

| Tier | Relevance Range | Storage | What's Stored |
|------|----------------|---------|---------------|
| **Full Fidelity** | > 0.7 | Warm (complete) | Full original content |
| **Summarized** | 0.3 – 0.7 | Warm (summary) + Cold (full) | LLM-generated summary in warm, full version preserved in cold |
| **Pointer Only** | 0.1 – 0.3 | Warm (pointer) + Cold (full) | One-line description + UUID reference in warm, full content in cold |
| **Cold Only** | < 0.1 | Cold only | Removed from warm entirely, retrievable via graph traversal or semantic search |

### 4.4 Compaction Loop

Runs as a continuous background task (asyncio):

```
every 60 seconds:
    1. Recalculate relevance scores for all warm memory items
    2. For each item where tier has changed:
       a. Demotion (full → summarized):
          - Generate summary via Opus call
          - Store full content in cold (if not already there)
          - Replace warm entry with summary + cold reference
       b. Demotion (summarized → pointer):
          - Collapse to one-line pointer + UUID in warm
       c. Demotion (pointer → cold only):
          - Remove from warm
       d. Promotion (accessed item moved back up):
          - Restore content from cold to appropriate tier
    3. Log every compaction action to quality_ledger for audit
```

### 4.5 Promotion (Retrieval-Triggered)

When a cold or low-tier item is retrieved (via graph traversal, semantic search, or explicit reference), its relevance score gets a boost:
```
boosted_relevance = min(1.0, current_relevance + 0.4)
```

This can promote the item back up through tiers. The system naturally resurfaces old context when it becomes relevant again.

### 4.6 Compaction Safeguards

- **Anchor immunity:** Anchored content never drops below "summarized" tier without explicit user action. Security anchors (permanence_class=permanent) never drop at all.
- **Active task lock:** Content linked to an active task via graph edges cannot be demoted below "full fidelity" while the task is active.
- **Compaction audit log:** Every demotion/promotion is logged with before/after state, tier change, and reasoning.
- **Emergency restore:** If an agent requests context that was compacted, it's restored from cold storage within the same request cycle and its relevance gets boosted.

### 4.7 Soft Context Budget

Each agent has a context budget (in tokens). The compaction system ensures warm memory stays manageable by **gradually increasing decay rates** as the budget fills — never by hard-cutting content.

```
effective_λ = base_λ × pressure_multiplier

where:
  pressure = current_warm_tokens / budget_limit
  pressure_multiplier = 1.0              if pressure < 0.7
                      = 1.0 + (pressure - 0.7) × 3.0   if 0.7 ≤ pressure < 0.9
                      = 1.6 + (pressure - 0.9) × 10.0   if pressure ≥ 0.9
```

This creates smooth pressure: at 70% capacity, decay is normal. At 90%, decay is ~1.6× faster. At 100%, decay is ~2.6× faster. Content transitions through tiers more quickly, but no content is ever hard-cut.

### 4.8 Data Model

```sql
-- Compaction log (audit trail for every tier transition)
CREATE TABLE IF NOT EXISTS compaction_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id UUID NOT NULL,
    item_type VARCHAR(30) NOT NULL,
    from_tier VARCHAR(20) NOT NULL,
    to_tier VARCHAR(20) NOT NULL,
    relevance_before REAL NOT NULL,
    relevance_after REAL NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_compaction_log_item ON compaction_log(item_id);
CREATE INDEX IF NOT EXISTS idx_compaction_log_created ON compaction_log(created_at DESC);
```

**Enhanced `memory_embeddings` table:**
```sql
ALTER TABLE memory_embeddings ADD COLUMN IF NOT EXISTS relevance_score REAL NOT NULL DEFAULT 1.0;
ALTER TABLE memory_embeddings ADD COLUMN IF NOT EXISTS tier VARCHAR(20) NOT NULL DEFAULT 'full';
ALTER TABLE memory_embeddings ADD COLUMN IF NOT EXISTS last_accessed TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE memory_embeddings ADD COLUMN IF NOT EXISTS access_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE memory_embeddings ADD COLUMN IF NOT EXISTS summary TEXT;
ALTER TABLE memory_embeddings ADD COLUMN IF NOT EXISTS base_relevance REAL NOT NULL DEFAULT 0.5;
ALTER TABLE memory_embeddings ADD COLUMN IF NOT EXISTS decay_rate REAL NOT NULL DEFAULT 0.01;
```

---

## 5. LLM-Curated Context Packaging

The intelligence layer that decides what context each agent receives. An Opus call reasons about what context is actually relevant for a specific task, rather than stuffing everything or using naive keyword matching.

### 5.1 Packaging Pipeline

```
1. Agent receives task assignment
2. Context Packager extracts:
   - Task goal + constraints (from task model)
   - Agent's role description + system prompt template
   - Available context budget (in tokens)
3. Opus Call #1 — Relevance Reasoning:
   - Input: task goal, agent role, list of available context items
     (titles + one-line summaries + relevance scores + types)
   - Output: ranked list of context items to include, with reasoning
     for each inclusion/exclusion decision
4. Retrieve full content for selected items (from warm or cold)
5. Opus Call #2 — Context Assembly:
   - Input: selected full content + task goal + budget
   - Output: assembled context package — organized, deduplicated,
     with navigation hints for the sub-agent
6. Deliver package to sub-agent as system prompt / context block
```

### 5.2 Why Two Opus Calls

- **Call #1** works on lightweight summaries to decide *what* to include — fast, operates on small token counts. This is the selection/filtering step.
- **Call #2** works on full content to *assemble* it coherently — ensures no contradictions, removes duplication, adds structure and navigation hints.
- Splitting avoids stuffing massive content into a single call that has to both select and organize simultaneously.

### 5.3 Context Package Structure

```python
class ContextPackage(BaseModel):
    task_summary: str                    # one-paragraph task description
    anchors: list[ContextAnchor]         # all relevant anchors (always included)
    graph_context: list[dict[str, Any]]  # nodes retrieved via graph traversal
    semantic_matches: list[dict[str, Any]]  # cold storage items matched by embedding
    agent_state: dict[str, Any]          # agent's own previous state (if any)
    navigation_hints: str                # LLM-generated guide for the sub-agent
    token_count: int                     # actual token count of assembled package
    budget_remaining: int                # remaining budget for agent's reasoning
    packaging_reasoning: str             # why these items were included (for audit)
    created_at: datetime
```

### 5.4 Anchor Bypass

Context anchors bypass the selection process — they're always included in the package. The Opus relevance call only decides on non-anchor content. This guarantees critical context (user preferences, system goals, security rules) is never excluded by an LLM judgment call.

Active anchors relevant to the task domain are automatically included. The packager filters anchors by:
1. All `permanent` and `durable` class anchors
2. `adaptive` anchors whose `anchor_type` matches the task domain
3. `task_scoped` anchors linked to the current task via graph edges

### 5.5 Graph-Informed Retrieval

The packager uses the graph layer to find structural context. Starting from the task node, it traverses outbound edges (depth 2-3) to find:
- Related decisions and their reasoning
- Previous similar task results
- Constraints and quality rules that apply
- Dependencies and prerequisites

This gives structural context that embedding similarity alone would miss.

### 5.6 Hybrid with Semantic Search

After graph retrieval, the packager also runs an embedding similarity search against cold storage using the task goal as the query. This catches relevant context that isn't directly linked via graph edges — like similar past tasks or related conversations that happened before graph edges were created.

Results from graph traversal and semantic search are merged using Reciprocal Rank Fusion (Section 7) before feeding into the Opus selection call.

### 5.7 Feedback Loop

After the sub-agent completes its work, the quality audit captures whether the context was sufficient:
- If the agent had to ask for more context → packager was too conservative
- If the agent made errors due to missing information → specific gaps identified
- If the agent ignored large portions of context → packager was too generous

This feedback adjusts the relevance model for future packaging decisions:
- Items that were needed but missing get a relevance boost for similar future tasks
- Items that were included but unused get a slight relevance penalty for similar contexts

---

## 6. Coordinator State Document

The Coordinator maintains a structured state document in warm memory. This is the persistent "brain state" that survives across LLM calls. Every Coordinator invocation loads this document, acts on it, and writes updates back before the call ends.

### 6.1 Structure (9 Sections)

```python
class CoordinatorState(BaseModel):
    """The Coordinator's persistent state document, stored in warm memory."""
    
    # Section 1: Active Tasks
    active_tasks: list[ActiveTaskSummary]  # current task tree, statuses, assigned agents, progress
    
    # Section 2: Task Queue
    task_queue: list[QueuedTask]  # pending tasks, priority-ordered, estimated complexity
    
    # Section 3: Agent Registry
    agent_registry: list[AgentEntry]  # active agents, health, current assignment, turn count
    
    # Section 4: Context Budget Status
    context_budget: ContextBudgetStatus  # per-agent token usage, warm memory pressure, compaction stats
    
    # Section 5: Communication State
    communication: CommunicationState  # pending user messages, active channels, last interaction
    
    # Section 6: Active Anchors
    active_anchors: AnchorInventory  # current anchor inventory with relevance scores, lifecycle states
    
    # Section 7: Graph Health
    graph_health: GraphHealthStatus  # node/edge counts, orphan detection, cache hit rates
    
    # Section 8: Audit Pipeline
    audit_pipeline: AuditPipelineState  # active audits, queue, recent verdicts, quality pulse
    
    # Section 9: Evolution State
    evolution: EvolutionState  # active experiments, canary status, rollback readiness, shelved items
    
    last_updated: datetime
    version: int  # incremented on every write
```

### 6.2 Section Details

**Section 1 — Active Tasks:**
```python
class ActiveTaskSummary(BaseModel):
    task_id: uuid.UUID
    goal_anchor: str                    # original user intent
    status: TaskStatus
    assigned_agent_ids: list[str]       # agents working on this
    subtask_count: int
    subtasks_completed: int
    priority: Priority
    created_at: datetime
    estimated_completion: datetime | None
```

**Section 2 — Task Queue:**
```python
class QueuedTask(BaseModel):
    task_id: uuid.UUID
    goal_anchor: str
    priority: Priority
    estimated_complexity: str           # "simple", "moderate", "complex"
    dependencies: list[uuid.UUID]       # tasks that must complete first
    queued_at: datetime
```

**Section 3 — Agent Registry:**
```python
class AgentEntry(BaseModel):
    agent_id: str
    agent_type: str                     # "coordinator", "planner", "sub_agent", etc.
    status: str                         # "idle", "active", "error", "terminated"
    current_task_id: uuid.UUID | None
    turn_count: int
    max_turns: int
    started_at: datetime
    last_heartbeat: datetime
```

**Section 4 — Context Budget Status:**
```python
class ContextBudgetStatus(BaseModel):
    total_warm_tokens: int              # current warm memory size in tokens
    warm_capacity_percent: float        # percentage of budget used
    compaction_pressure: float          # current pressure multiplier
    items_per_tier: dict[str, int]      # {"full": 42, "summarized": 15, "pointer": 8}
    last_compaction_run: datetime
    items_compacted_last_hour: int
```

**Section 5 — Communication State:**
```python
class CommunicationState(BaseModel):
    pending_user_messages: int
    active_channels: list[str]          # ["telegram", "whatsapp"]
    last_user_interaction: datetime
    last_outbound_message: datetime
    pending_clarifications: int
    queued_status_updates: int
```

**Section 6 — Active Anchors:**
```python
class AnchorInventory(BaseModel):
    total_active: int
    total_stale: int
    total_superseded: int
    anchors_by_type: dict[str, int]     # {"user_goal": 3, "correction": 5, ...}
    anchors_by_permanence: dict[str, int]  # {"permanent": 2, "durable": 8, ...}
    last_re_evaluation: datetime
    pending_re_evaluations: int
```

**Section 7 — Graph Health:**
```python
class GraphHealthStatus(BaseModel):
    total_nodes: int
    total_edges: int
    orphan_nodes: int                   # nodes with no edges
    avg_edge_weight: float
    cache_hit_rate: float               # subgraph cache effectiveness
    last_decay_run: datetime
    edges_decayed_last_run: int
```

**Section 8 — Audit Pipeline:**
```python
class AuditPipelineState(BaseModel):
    active_audits: list[ActiveAudit]    # currently running audits
    audit_queue_depth: int              # waiting for auditor
    recent_verdicts: list[RecentVerdict]  # last 10 verdicts
    quality_pulse: QualityPulse         # rolling quality metrics

class ActiveAudit(BaseModel):
    audit_id: uuid.UUID
    task_id: uuid.UUID
    subtask_id: uuid.UUID
    auditor_agent_id: str
    started_at: datetime

class RecentVerdict(BaseModel):
    task_id: uuid.UUID
    verdict: str                        # "pass", "fail", "conditional"
    score: float
    timestamp: datetime

class QualityPulse(BaseModel):
    avg_score_last_24h: float
    pass_rate_last_24h: float
    trend: str                          # "improving", "stable", "declining"
    consecutive_failures: int
```

**Section 9 — Evolution State:**
```python
class EvolutionState(BaseModel):
    active_experiments: list[ActiveExperiment]
    canary_status: str                  # "idle", "testing", "promoting", "rolling_back"
    last_promotion: datetime | None
    last_rollback: datetime | None
    shelved_improvements: int           # failed improvements waiting for new approach
    evolution_frozen: bool              # true if anti-degradation trigger fired
    freeze_reason: str | None

class ActiveExperiment(BaseModel):
    experiment_id: uuid.UUID
    description: str
    status: str                         # "sandbox", "canary", "evaluating"
    started_at: datetime
    metrics_before: dict[str, float]
    metrics_current: dict[str, float] | None
```

### 6.3 Storage and Access

The State Document is stored as a single JSON blob in warm memory under key `coordinator:state`. Every Coordinator LLM call:
1. Loads the full State Document at call start
2. Acts on the current state
3. Writes the updated State Document back before the call ends
4. Increments the version counter

A cold backup is written to PostgreSQL every 5 minutes and on every significant state change (task completion, audit verdict, agent spawn/kill).

---

## 7. Hybrid Retrieval

Combines three retrieval strategies with fusion scoring to find the most relevant context for any query.

### 7.1 Retrieval Strategies

**Strategy 1 — Graph Traversal:**
Starting from a seed node (task, anchor, or intent), traverse the graph following weighted edges. Returns structurally related content — things connected by explicit relationships like "derived_from", "depends_on", "constrains".

- Seed selection: The current task node, plus any directly referenced entities
- Traversal depth: 2-3 (configurable per query)
- Edge filtering: Optionally restrict to specific relation types
- Returns: list of (node, path_score) tuples

**Strategy 2 — Semantic Search (pgvector):**
Embed the query text and find nearest neighbors in the `memory_embeddings` table using the HNSW index. Returns semantically similar content regardless of explicit graph relationships.

- Embedding model: Voyage AI (voyage-3) — Anthropic's recommended embedding partner
- Vector dimension: 1024 (matching voyage-3 output)
- Distance metric: Cosine similarity
- Top-k: Configurable (default 20)
- Pre-filter: Optional metadata filters (memory_type, date range)

**Strategy 3 — Keyword/Tag Search (PostgreSQL FTS):**
Full-text search using PostgreSQL's built-in `tsvector`/`tsquery` for exact keyword matches. Catches content that shares specific terms but may not be semantically similar in embedding space.

- Uses `ts_rank` for relevance scoring
- Supports prefix matching, phrase matching, boolean operators
- Searches across content fields in memory_embeddings, context_anchors, and task goal_anchors

### 7.2 Reciprocal Rank Fusion (RRF)

Results from all three strategies are merged using RRF:

```
RRF_score(item) = Σ_strategy [ 1 / (k + rank_in_strategy) ]

where k = 60 (standard RRF constant)
```

If an item appears in multiple strategies' result lists, its RRF score reflects all of them. Items that appear in only one strategy still get scored but with lower fusion confidence.

**Weighted RRF variant:** Each strategy gets a configurable weight:
```
weighted_RRF_score(item) = Σ_strategy [ weight_strategy / (k + rank_in_strategy) ]

Default weights:
  graph_weight     = 1.0   (structural relationships are highly reliable)
  semantic_weight  = 0.8   (good for discovery, but can have false positives)
  keyword_weight   = 0.6   (precise but narrow)
```

### 7.3 Retrieval Pipeline

```
1. Query arrives (task goal, user question, or packager request)
2. In parallel:
   a. Graph traversal from seed nodes → ranked results
   b. Embed query → pgvector kNN search → ranked results
   c. Parse query → PostgreSQL FTS → ranked results
3. Merge via weighted RRF
4. Deduplicate (same content_id from multiple strategies)
5. Apply tier awareness (prefer full-fidelity items; promote cold items if selected)
6. Return top-k results with fusion scores and strategy attribution
```

### 7.4 Retrieval Result

```python
class RetrievalResult(BaseModel):
    content_id: uuid.UUID
    content_type: str                   # "anchor", "memory", "task", etc.
    content: str                        # actual content (or summary if compacted)
    rrf_score: float                    # fused relevance score
    strategies: list[str]               # which strategies found this ["graph", "semantic"]
    graph_path: list[uuid.UUID] | None  # if found via graph, the traversal path
    similarity_score: float | None      # if found via semantic, the cosine similarity
    tier: str                           # current compaction tier
    metadata: dict[str, Any]
```

### 7.5 Embedding Provider

Abstract interface with Voyage AI implementation:

```python
class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    
    @abstractmethod
    def dimension(self) -> int: ...

class VoyageEmbeddingProvider(EmbeddingProvider):
    """Voyage AI embedding provider (Anthropic's recommended partner)."""
    
    def __init__(self, api_key: str, model: str = "voyage-3"):
        self._client = voyageai.AsyncClient(api_key=api_key)
        self._model = model
    
    async def embed(self, texts: list[str]) -> list[list[float]]:
        result = await self._client.embed(texts, model=self._model)
        return result.embeddings
    
    def dimension(self) -> int:
        return 1024  # voyage-3 output dimension
```

### 7.6 Schema Changes

```sql
-- Add full-text search support to existing tables
ALTER TABLE memory_embeddings ADD COLUMN IF NOT EXISTS search_vector tsvector;
CREATE INDEX IF NOT EXISTS idx_memory_fts ON memory_embeddings USING gin(search_vector);

ALTER TABLE context_anchors ADD COLUMN IF NOT EXISTS search_vector tsvector;
CREATE INDEX IF NOT EXISTS idx_anchor_fts ON context_anchors USING gin(search_vector);

-- Function to auto-update tsvector on insert/update
CREATE OR REPLACE FUNCTION update_search_vector() RETURNS trigger AS $$
BEGIN
    NEW.search_vector := to_tsvector('english', NEW.content);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_memory_search_vector
    BEFORE INSERT OR UPDATE OF content ON memory_embeddings
    FOR EACH ROW EXECUTE FUNCTION update_search_vector();

CREATE TRIGGER trg_anchor_search_vector
    BEFORE INSERT OR UPDATE OF content ON context_anchors
    FOR EACH ROW EXECUTE FUNCTION update_search_vector();
```

**Update vector dimension:** The existing schema uses `vector(1536)`. Since we're using Voyage AI (1024-dim), the migration will:
```sql
-- Migration: change embedding dimension from 1536 to 1024
ALTER TABLE memory_embeddings ALTER COLUMN embedding TYPE vector(1024);
```
Note: This migration is safe because Phase 1 created the table but no real embeddings have been stored yet. If embeddings existed, they would need to be re-embedded with the new model.

---

## 8. Performance Baselines & Blind Evaluation

Every self-improvement must prove it's actually an improvement through rigorous, unbiased evaluation.

### 8.1 Baseline Metrics

Established during Phase 2 implementation and continuously updated:

| Metric | What It Measures | How It's Collected |
|--------|-----------------|-------------------|
| Context Retrieval Precision | % of retrieved items that were actually used by the agent | Post-task audit: compare retrieved context vs. what was referenced |
| Context Retrieval Recall | % of needed items that were retrieved | Post-task audit: did the agent request additional context? |
| Compaction Quality | Information preservation through tier transitions | Compare pre/post summaries: key facts retained? |
| Graph Traversal Latency | Time for depth-3 traversal (p50, p95, p99) | Instrumented timing on every traversal call |
| Semantic Search Latency | Time for kNN query (p50, p95, p99) | Instrumented timing on every search call |
| Context Package Assembly Time | End-to-end time from task assignment to package delivery | Timer around full packaging pipeline |
| Anchor Accuracy | % of anchors that are still valid at re-evaluation time | Re-evaluation verdicts: valid vs. stale vs. superseded |
| Warm Memory Utilization | Average % of warm memory budget used | Periodic sampling from context_budget status |

### 8.2 Blind Evaluation Protocol

When the Evolution Director evaluates a potential improvement:

1. **Snapshot** current system state (pre-improvement baseline)
2. **Implement** improvement in sandbox
3. **Replay** 5-10 recent tasks through both systems (original + improved)
4. **Collect** metrics from both runs
5. **Evaluate** — the evaluator receives ONLY:
   - Before metrics (labeled "System A")
   - After metrics (labeled "System B")
   - The metric definitions
   - **Zero context** about what changed, who proposed it, or what it's supposed to improve
6. **Verdict:** "A is better", "B is better", or "no significant difference"

The evaluator literally cannot be biased toward the improvement because it doesn't know which system is which.

### 8.3 Auto-Rollback

**Any regression triggers automatic rollback.** The rule is strict:

- If System B is worse than System A on ANY metric → rollback
- "Worse" means statistically significant decline (not noise)
- No exceptions for "but it improved other metrics" — strictly non-regressive
- Rollback happens automatically, then logs the failure for analysis

The rollback restores from the pre-modification snapshot. The failed improvement is logged as a shelved improvement.

### 8.4 Shelved Improvements

Failed improvements are not retried blindly:

```python
class ShelvedImprovement(BaseModel):
    id: uuid.UUID
    description: str
    proposed_by: str                    # which scout/agent proposed it
    failure_reason: str                 # why it regressed
    metrics_before: dict[str, float]
    metrics_after: dict[str, float]
    regressed_metrics: list[str]        # which specific metrics got worse
    shelved_at: datetime
    retry_allowed: bool = False         # only true if user approves or new approach proposed
    retry_approach: str | None = None   # what's different this time
```

A shelved improvement can only be retried when:
1. The user explicitly approves a retry, OR
2. A scout proposes a fundamentally different approach (not a tweak of the same idea)

### 8.5 Metric Collection Infrastructure

```python
class MetricCollector:
    """Collects and stores performance metrics for baseline tracking."""
    
    async def record(self, metric_name: str, value: float, metadata: dict = {}) -> None
    async def get_baseline(self, metric_name: str, window_hours: int = 168) -> MetricBaseline
    async def compare(self, metric_name: str, system_a: list[float], system_b: list[float]) -> ComparisonResult

class MetricBaseline(BaseModel):
    metric_name: str
    mean: float
    median: float
    p95: float
    p99: float
    stddev: float
    sample_count: int
    window_start: datetime
    window_end: datetime

class ComparisonResult(BaseModel):
    metric_name: str
    system_a_mean: float
    system_b_mean: float
    difference_percent: float
    is_significant: bool               # statistical significance test
    verdict: str                       # "a_better", "b_better", "no_difference"
```

### 8.6 Data Model

```sql
-- Performance metrics (time-series)
CREATE TABLE IF NOT EXISTS performance_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    metric_name VARCHAR(100) NOT NULL,
    value REAL NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_metrics_name_time ON performance_metrics(metric_name, recorded_at DESC);

-- Shelved improvements
CREATE TABLE IF NOT EXISTS shelved_improvements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    description TEXT NOT NULL,
    proposed_by VARCHAR(100) NOT NULL,
    failure_reason TEXT NOT NULL,
    metrics_before JSONB NOT NULL,
    metrics_after JSONB NOT NULL,
    regressed_metrics JSONB NOT NULL,
    shelved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    retry_allowed BOOLEAN NOT NULL DEFAULT FALSE,
    retry_approach TEXT
);
```

---

## 9. File Structure

```
src/max/memory/
├── __init__.py              # Re-exports: MemoryGraph, AnchorManager, CompactionEngine,
│                            #   HybridRetriever, ContextPackager, CoordinatorStateManager,
│                            #   EmbeddingProvider, VoyageEmbeddingProvider, MetricCollector
├── models.py                # All Phase 2 Pydantic models: ContextAnchor, GraphNode, GraphEdge,
│                            #   TraversalPath, ContextPackage, CoordinatorState, RetrievalResult,
│                            #   MetricBaseline, ComparisonResult, ShelvedImprovement, enums
├── anchors.py               # AnchorManager: CRUD, lifecycle transitions, re-evaluation,
│                            #   supersession chains, usage tracking, periodic review
├── graph.py                 # MemoryGraph: node/edge CRUD, traversal engine (BFS),
│                            #   path scoring, weight decay, subgraph extraction, merge, orphan detection
├── compaction.py            # CompactionEngine: relevance scoring, tier transitions,
│                            #   background compaction loop, soft budget enforcement, safeguards
├── retrieval.py             # HybridRetriever: graph + semantic + keyword retrieval,
│                            #   RRF fusion, result ranking, tier-aware promotion
├── embeddings.py            # EmbeddingProvider ABC + VoyageEmbeddingProvider implementation
├── context_packager.py      # ContextPackager: two-call Opus pipeline, anchor bypass,
│                            #   package assembly, feedback loop integration
├── coordinator_state.py     # CoordinatorStateManager: load/save state document,
│                            #   section-level updates, cold backup, version tracking
└── metrics.py               # MetricCollector: record, baseline calculation, comparison,
                             #   blind evaluation support

src/max/db/
├── schema.sql               # Updated: new tables (graph_nodes, graph_edges, compaction_log,
│                            #   performance_metrics, shelved_improvements) + ALTER existing tables
└── migrations/
    └── 002_memory_system.sql  # Phase 2 migration: all new tables + column additions

tests/
├── test_anchors.py          # Anchor lifecycle, supersession, re-evaluation, usage tracking
├── test_graph.py            # Node/edge CRUD, traversal, path scoring, weight decay, merge
├── test_compaction.py       # Relevance scoring, tier transitions, safeguards, soft budget
├── test_retrieval.py        # Each strategy, RRF fusion, dedup, tier-aware promotion
├── test_embeddings.py       # Embedding provider (mocked API calls)
├── test_context_packager.py # Package assembly, anchor bypass, budget enforcement
├── test_coordinator_state.py # State load/save, versioning, cold backup
├── test_metrics.py          # Metric recording, baseline calculation, comparison
└── test_memory_integration.py  # End-to-end: anchor → graph → compaction → retrieval → packaging
```

---

## 10. Dependencies

**New packages required:**

| Package | Purpose | Version |
|---------|---------|---------|
| `voyageai` | Embedding API client (Voyage AI) | >=0.3.0 |

**Configuration additions (`Settings` class):**
```python
# Voyage AI (embeddings)
voyage_api_key: str

# Memory system
memory_compaction_interval_seconds: int = 60
memory_warm_budget_tokens: int = 100_000
memory_graph_cache_max_nodes: int = 500
memory_embedding_dimension: int = 1024
memory_anchor_re_evaluation_interval_hours: int = 6
```

---

## 11. Design Principles Summary

1. **No hard cuts, ever** — Content transitions through tiers smoothly. Even under maximum pressure, the system summarizes faster but never drops content.
2. **Anchors are sacred** — Critical context bypasses selection, resists compaction, and is always included in context packages.
3. **Graph gives structure, embeddings give discovery** — Use both together via fusion for maximum retrieval quality.
4. **Every action is auditable** — Compaction, retrieval, packaging, and evaluation all produce audit trails.
5. **Blind evaluation prevents bias** — The evaluator never knows which system is the improvement.
6. **All agents use Opus 4.6** — No cost compromises on model selection. Every LLM call (relevance reasoning, context assembly, anchor re-evaluation, compaction summarization) uses Opus.
7. **Build for the real thing** — Full graph layer, continuous compaction, LLM-curated packaging. No shortcuts.
