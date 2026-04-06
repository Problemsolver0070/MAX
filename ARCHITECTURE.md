# MAX — Complete Technical Architecture

This document describes every component of MAX in full technical detail: what it does, how it works, why it was built that way, and how it connects to everything else. It is the definitive reference for understanding the system.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Core Infrastructure](#2-core-infrastructure)
3. [Memory System](#3-memory-system)
4. [Communication Layer](#4-communication-layer)
5. [Command Chain](#5-command-chain)
6. [Quality Gate](#6-quality-gate)
7. [Tool System](#7-tool-system)
8. [Evolution System](#8-evolution-system)
9. [Sentinel Anti-Degradation](#9-sentinel-anti-degradation)
10. [API Layer](#10-api-layer)
11. [Composition Root & Application Lifecycle](#11-composition-root--application-lifecycle)
12. [Message Bus & Channel Map](#12-message-bus--channel-map)
13. [Database Schema](#13-database-schema)
14. [Configuration Reference](#14-configuration-reference)
15. [Deployment Architecture](#15-deployment-architecture)
16. [Testing Strategy](#16-testing-strategy)

---

## 1. System Overview

### 1.1 What MAX Is

MAX is an autonomous multi-agent AI system that:

1. Receives natural language requests from users via Telegram, REST API, or webhooks
2. Decomposes them into phased execution plans through a command chain of specialized agents
3. Executes each phase with worker agents backed by Claude, using 80+ tools
4. Quality-audits every output through a blind audit protocol
5. Continuously evolves its own prompts, tool configurations, and strategies
6. Guards against degradation with a 24-benchmark sentinel testing system

It is designed to run 24/7, survive restarts, recover orphaned work, and improve over time without human intervention.

### 1.2 Design Philosophy

**Composition over inheritance.** Every agent, store, and service takes its dependencies as constructor parameters. There is no service locator, no dependency injection framework, no global state. The composition root (`app.py`) wires everything explicitly.

**Event-driven loose coupling.** Agents never call each other directly. All communication flows through the message bus (Redis Streams). This makes agents independently testable, independently deployable, and independently replaceable.

**Defense in depth for quality.** Worker self-check -> blind audit -> rule extraction -> fix cycle -> re-audit. Five layers ensure quality, with the blind audit as the keystone.

**Monolith-first.** One process, one event loop, one container. The architecture supports splitting into microservices (just deploy agents as separate processes against the same Redis), but premature distribution adds complexity without value at current scale.

**No hard cuts.** Memory is never deleted, only progressively compressed. Scheduled work is never skipped, only caught up. Tasks are never abandoned, only recovered. The system is designed to be resilient to interruption at any point.

### 1.3 Module Map

```
src/max/
├── agents/          Base agent abstraction (think, think_with_tools)
├── api/             FastAPI endpoints, auth, rate limiting
├── bus/             Message bus (Redis Streams + pub/sub fallback)
├── command/         Command chain (coordinator, planner, orchestrator, worker)
├── comm/            Communication (Telegram, message routing, injection scanning)
├── db/              Database (asyncpg), Redis store, SQL schema
├── evolution/       Self-improvement (director, scouts, canary, snapshot, self-model)
├── llm/             LLM client, circuit breaker, model definitions
├── memory/          Memory system (graph, retrieval, compaction, anchors, embeddings)
├── models/          Shared domain models (tasks, messages)
├── quality/         Quality gate (director, auditor, rules, store)
├── sentinel/        Anti-degradation (benchmarks, scorer, runner, comparator)
├── tools/           Tool system (registry, executor, providers, 80 native tools)
├── app.py           Composition root — wires all dependencies
├── config.py        Settings (pydantic-settings, ~80 env vars)
├── observability.py Structured logging, OpenTelemetry metrics, correlation IDs
├── recovery.py      Orphaned task recovery on startup
├── scheduler.py     Database-backed periodic job scheduler
└── __main__.py      Entry point (python -m max)
```

---

## 2. Core Infrastructure

### 2.1 Database (`src/max/db/postgres.py`)

**What:** Async PostgreSQL connection pool via asyncpg.

**How:** The `Database` class manages the connection lifecycle:
- `connect()` creates an asyncpg connection pool with configurable min/max size
- `init_schema()` runs the idempotent SQL schema file on every startup — all DDL uses `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`, so it's safe to run repeatedly
- `execute()` runs a single query and returns rows
- `fetch_one()` / `fetch_all()` for typed retrieval
- `transaction()` provides async context manager for explicit transactions

**Why asyncpg:** It's the fastest PostgreSQL driver for Python async. MAX runs everything in a single event loop, so async I/O is critical for performance. asyncpg provides native PostgreSQL type support including JSONB, arrays, and pgvector.

**Why PostgreSQL:** Needed for pgvector (semantic search), full-text search (tsvector/GIN), JSONB (flexible schema for state documents), and strong transactional guarantees. No other database provides all four.

### 2.2 Redis Store (`src/max/db/redis_store.py`)

**What:** `WarmMemory` — a prefixed JSON key-value store over async Redis.

**How:** Every key is prefixed with `max:` for namespace isolation. Values are JSON-serialized for storage. Provides typed get/set/delete with optional TTL. Used for:
- Coordinator state (fast reads, backed by Postgres)
- Response queues for API polling
- Webhook registrations
- Rate limit state (via slowapi)

**Why Redis for state:** Redis provides sub-millisecond reads for coordinator state that's accessed on every incoming message. PostgreSQL backup ensures durability — state is eventually consistent between Redis (fast) and Postgres (durable).

### 2.3 LLM Client (`src/max/llm/client.py`)

**What:** Async wrapper around Anthropic's `AsyncAnthropic` client.

**How:** Single `complete()` method that:
1. Checks circuit breaker state — if OPEN, raises immediately
2. Calls `client.messages.create()` with model, system prompt, messages, tools, temperature
3. Parses the response into `LLMResponse`: extracts text content and tool_use blocks
4. Records success/failure with circuit breaker
5. Tracks cumulative token usage (input + output)
6. Maps Anthropic exceptions to typed MAX errors

**Model types:**
- `ModelType.OPUS` — `claude-opus-4-6`, 32768 max tokens. Used for all persistent agents by default.
- `ModelType.SONNET` — `claude-sonnet-4-6`, 16384 max tokens. Available for cost optimization.

**Why a wrapper:** Error classification (rate limit vs auth vs connection), circuit breaker integration, token tracking, and tool call parsing are all concerns that shouldn't leak into agent code.

### 2.4 Circuit Breaker (`src/max/llm/circuit_breaker.py`)

**What:** Three-state circuit breaker protecting the LLM client from cascading failures.

**States:**
```
CLOSED (normal) ──[5 consecutive failures]──> OPEN (failing fast)
                                                  |
                                          [60s cooldown]
                                                  |
                                                  v
                                           HALF_OPEN (test one)
                                            /           \
                                     [success]        [failure]
                                        |                |
                                        v                v
                                     CLOSED            OPEN
```

**How:** Thread-safe via `threading.Lock`. Records success/failure after each LLM call. When failure count hits threshold (configurable, default 5), transitions to OPEN. In OPEN state, `check()` raises `CircuitOpenError` immediately without calling the API. After cooldown period (configurable, default 60s), transitions to HALF_OPEN and allows one test request.

**Why:** When Anthropic's API is degraded, continuing to send requests wastes time and money while getting errors. The circuit breaker fails fast, gives the API time to recover, and automatically resumes when it's healthy.

### 2.5 Scheduler (`src/max/scheduler.py`)

**What:** Database-backed periodic job scheduler that survives restarts.

**How:**
- Jobs are registered with name, interval, and async callback
- On startup, `load_state()` reads `scheduler_state` from PostgreSQL
- If a job's `next_run_at` is in the past (MAX was down), it fires immediately (catch-up)
- After each execution, `last_run_at` and the new `next_run_at` are persisted
- Background asyncio tasks sleep until the next run time

**Registered jobs:**

| Job | Default Interval | Action |
|-----|-----------------|--------|
| `evolution_scout` | 6 hours | Publishes `evolution.trigger` on bus |
| `sentinel_monitor` | 12 hours | Publishes `sentinel.run_request` on bus |
| `memory_compaction` | 60 seconds | Publishes `memory.compact` on bus |
| `anchor_re_evaluation` | 6 hours | Publishes `memory.anchor_re_eval` on bus |

**Why database-backed:** `asyncio.sleep()` loops don't survive restarts. If MAX is down for 2 hours, the scheduler catches up on missed work immediately on boot instead of waiting for the next interval.

### 2.6 Observability (`src/max/observability.py`)

**What:** Structured JSON logging, correlation ID propagation, and OpenTelemetry metrics.

**Structured logging:** Every log line is JSON with `timestamp`, `level`, `module`, `message`, and `correlation_id`. The correlation ID is set when a message enters MAX and propagated through the entire agent chain via `contextvars.ContextVar`.

**Why JSON logging:** Azure Log Analytics ingests JSON natively. Structured logs enable querying by correlation ID to trace a single user request through all agents.

**Metrics:** `MetricsRegistry` provides typed factories for counters, histograms, and gauges backed by OpenTelemetry. Currently exports to console; OTLP exporter endpoint is configurable for Azure Monitor.

---

## 3. Memory System

The memory system gives MAX persistent, queryable, evolving memory across conversations. It's not a simple key-value store — it's a multi-strategy retrieval system with lifecycle management and progressive compaction.

### 3.1 Knowledge Graph (`src/max/memory/graph.py`)

**What:** A weighted directed graph stored in PostgreSQL (`graph_nodes` and `graph_edges` tables).

**Node types:** `concept`, `entity`, `event`, `fact`, `preference`, `instruction`

**Edge relations (9 types):** `related_to`, `part_of`, `depends_on`, `causes`, `similar_to`, `supersedes`, `references`, `derived_from`, `contradicts`

**Operations:**
- **Add/update nodes and edges** with arbitrary JSON properties
- **BFS traversal** with configurable max depth, returning weight products along paths with depth penalties
- **Shortest path** via BFS
- **Subgraph extraction** (neighborhood query)
- **Weight decay** — exponential decay based on time since last traversal. Edge weight = `current_weight * exp(-decay_rate * days_elapsed)`. This naturally deprioritizes stale connections.
- **Node merging** — when two nodes represent the same concept, merge re-wires all edges and removes self-loops
- **Orphan detection** — finds nodes with no edges for cleanup

**Why a graph:** Relationships between concepts can't be captured by vector similarity alone. "Python depends on CPython" and "Python is similar to Ruby" are fundamentally different relationships that a graph can represent but an embedding space cannot.

### 3.2 Embeddings (`src/max/memory/embeddings.py`)

**What:** Vector embeddings via Voyage AI (voyage-3 model, 1024 dimensions) stored in PostgreSQL with pgvector.

**How:** `VoyageEmbeddingProvider.embed()` batches texts and calls the Voyage API. Embeddings are stored in the `memory_embeddings` table with an HNSW index (m=16, ef_construction=64) for fast cosine similarity search.

**Why Voyage-3:** At 1024 dimensions, it provides strong semantic quality while keeping storage and computation costs reasonable. The HNSW index provides approximate nearest neighbor search in sub-millisecond time.

**Why pgvector over a dedicated vector DB:** MAX already uses PostgreSQL. Adding Pinecone or Weaviate would mean another infrastructure dependency, another failure mode, and another consistency boundary. pgvector is "good enough" for MAX's scale and eliminates the distributed systems complexity.

### 3.3 Compaction Engine (`src/max/memory/compaction.py`)

**What:** Automatic memory lifecycle management with four tiers and the invariant "no hard cuts, ever."

**Tiers:**

| Tier | Relevance Score | What Happens |
|------|----------------|--------------|
| `full` | > 0.7 | Complete content preserved |
| `summarized` | 0.3 – 0.7 | LLM generates a summary, replaces full content |
| `pointer` | 0.1 – 0.3 | Minimal reference retained, content in cold storage |
| `cold_only` | <= 0.1 | Only in PostgreSQL, not in active retrieval |

**Relevance scoring formula:**
```
relevance = base_relevance * recency_factor * usage_factor * anchor_boost
```

- `recency_factor` = exponential decay based on time since last access
- `usage_factor` = log(1 + access_count) / log(1 + max_access_count)
- `anchor_boost` = 10x if linked to an active context anchor (ensures critical context always surfaces)

**Pressure multiplier:** When memory usage approaches the warm budget:
- 0-70% capacity: no pressure (multiplier = 1.0)
- 70-100%: linear increase to ~1.6x
- 100%+: continues increasing to ~2.6x
This creates soft pressure that gradually demotes lower-relevance content rather than a hard cliff.

**Why no hard cuts:** Deleting memories is irreversible. A memory that seems irrelevant today might be critical tomorrow when context changes. Progressive summarization preserves the information in compressed form. The system prefers being slightly over-budget to losing information.

### 3.4 Context Anchors (`src/max/memory/anchors.py`)

**What:** Named persistent context markers with lifecycle management.

**Lifecycle states:** `active` -> `dormant` -> `archived` -> `expired`

**Permanence classes:** `permanent` (never auto-demoted), `session` (active during a conversation), `contextual` (active while relevant)

**Features:**
- Anchors get a 10x relevance boost in compaction, ensuring they always surface in retrieval
- Supersession: a new anchor can supersede an old one, automatically archiving it
- Versioning: anchors track version numbers for evolution tracking
- Hierarchical: anchors can have parent anchors for nested context

**Why anchors:** In a system that compacts aggressively, you need a way to say "this specific context must always be available." Anchors are that mechanism. The 10x boost is deliberate — it's strong enough to override any recency or usage decay.

### 3.5 Hybrid Retrieval (`src/max/memory/retrieval.py`)

**What:** Three-strategy retrieval merged via Reciprocal Rank Fusion.

**Strategy 1 — Graph traversal:**
Start from seed nodes (identified by keyword matching against node labels), BFS outward with configurable depth. Score = product of edge weights along path * depth penalty. Returns connected concepts that may not share any keywords with the query.

**Strategy 2 — Semantic search:**
Embed the query with Voyage-3, search `memory_embeddings` via pgvector's `<=>` (cosine distance) operator. Returns semantically similar content regardless of exact wording.

**Strategy 3 — Keyword search:**
PostgreSQL full-text search using `plainto_tsquery()` against GIN-indexed `search_vector` columns on `context_anchors` and `memory_embeddings`. Returns exact and stemmed keyword matches.

**Reciprocal Rank Fusion (k=60):**
```
RRF_score(d) = sum over strategies s of: 1 / (k + rank_s(d))
```

Each strategy ranks its results independently. RRF merges them by adding reciprocal ranks. k=60 is a standard value that balances giving credit to high-ranked results while not completely ignoring lower-ranked ones.

**Why three strategies:** Each strategy has blind spots. Graph misses content not in the graph. Semantic misses exact matches. Keyword misses paraphrases. RRF fusion compensates — a document ranked high by any two strategies will surface even if the third misses it.

### 3.6 Context Packaging (`src/max/memory/context_packager.py`)

**What:** Assembles a `ContextPackage` for agents from anchors + retrieval within a token budget.

**How (two-call Opus pipeline):**
1. Always include all active anchors (non-negotiable baseline)
2. Run hybrid retrieval with the task description as query
3. Call LLM to select which retrieved candidates are relevant to the task and fit the budget
4. Assemble the final package with token accounting (4 chars ≈ 1 token)

**Why LLM selection:** Retrieval returns a ranked list, but ranking doesn't tell you which items are actually relevant to this specific task. An LLM can judge "this memory about database schemas is relevant to a task about fixing a SQL query" in a way that pure scoring cannot.

---

## 4. Communication Layer

### 4.1 Telegram Adapter (`src/max/comm/telegram_adapter.py`)

**What:** aiogram 3 integration for Telegram messaging.

**Features:**
- Owner-only middleware — only accepts messages from the configured owner Telegram ID
- Supports both long-polling (development) and webhook (production) modes
- Handles text messages, documents, photos, voice messages, and callbacks
- Converts Telegram's message format to MAX's internal `InboundMessage` model

**Why owner-only:** MAX is designed as a personal AI system first. Multi-user support is a product feature that requires tenant isolation, per-user billing, and access controls — all future work.

### 4.2 Message Router (`src/max/comm/router.py`)

**What:** Glue layer between communication adapters (Telegram, future WhatsApp) and the communicator agent.

**How:** Routes inbound messages from adapters to the communicator, and outbound messages from the communicator back to the correct adapter. Maintains adapter registry by platform name.

**Why a router:** Decouples adapters from the communicator. Adding WhatsApp means implementing a WhatsApp adapter and registering it with the router — zero changes to the communicator.

### 4.3 Communicator Agent (`src/max/comm/communicator.py`)

**What:** The agent responsible for all inbound and outbound messaging.

**Inbound flow:**
1. Receive message from router
2. Run injection scanner
3. Check for command prefixes (`/help`, `/status`, `/cancel`, `/pause`, `/resume`, `/quiet`, `/verbose`)
4. Use LLM to parse intent (with injection scan context for the LLM to consider)
5. Publish `intents.new` on bus

**Outbound flow (3 channels):**
- `results.new` — task completion results
- `status_updates.new` — progress updates
- `clarifications.new` — questions for the user

**Quiet mode:** When enabled, non-critical updates are batched and flushed periodically (`comm_batch_interval_seconds`, default 30s). Only results and clarifications are sent immediately.

### 4.4 Injection Scanner (`src/max/comm/injection_scanner.py`)

**What:** Regex-based prompt injection detection with trust scoring.

**10 patterns in 3 categories:**

| Category | Patterns | Penalty |
|----------|----------|---------|
| role_override (5) | "ignore previous instructions", "you are now", "new instructions", "forget everything", "disregard" | 0.5-0.6 each |
| delimiter_injection (2) | `---` separator, `===` separator | 0.3 each |
| instruction_smuggling (4) | "system:", "IMPORTANT:", "```system", hidden instructions | 0.35 each |

**Trust score:** `max(0.0, 1.0 - total_penalty)`. Message is flagged as suspicious if trust < 0.5.

**Why regex over LLM:** Speed and predictability. Injection scanning runs on every inbound message. An LLM call would add 1-3 seconds of latency and cost. Regex patterns catch the most common injection techniques in microseconds. The trust score is passed to the intent-parsing LLM as additional context, so the LLM can make the final judgment.

### 4.5 Outbound Formatter (`src/max/comm/formatter.py`)

**What:** Converts internal response objects to Telegram HTML format.

**Features:** Progress bars (Unicode block characters), inline keyboards for clarification options, truncation with "..." for long messages, escaping for Telegram's HTML subset.

---

## 5. Command Chain

The command chain is the core execution pipeline: a request enters as an intent and exits as a quality-audited result.

### 5.1 Base Agent (`src/max/agents/base.py`)

**What:** Abstract base class for all agents.

**`AgentConfig`:** name, system_prompt, model (ModelType), max_turns (default 10), tools list

**`think(messages)`:** Single LLM call. Sends messages to the LLM with the agent's system prompt and returns the response. No tool execution.

**`think_with_tools(messages)`:** Tool-use loop:
1. Call LLM with messages + tool definitions
2. If response contains tool_use blocks, execute each tool call
3. Append tool results to messages
4. Call LLM again with updated messages
5. Repeat until no more tool calls or max_turns exceeded

**Why max_turns:** Prevents infinite tool-use loops. If an agent keeps calling tools without producing a final response, it's stuck. The turn limit forces convergence.

### 5.2 Coordinator Agent (`src/max/command/coordinator.py`)

**Subscribes to:** `intents.new`, `tasks.complete`

**Role:** Entry point for all user requests. The coordinator is the only agent that maintains persistent state across requests.

**Intent classification (5 types):**
- `create_task` — new work request -> creates task in store, publishes `tasks.plan`
- `query_status` — user asking about progress -> reads state, publishes response
- `cancel_task` — user wants to stop a task -> publishes `tasks.cancel`
- `provide_context` — additional context for an existing task -> publishes `tasks.context_update`
- `clarification_response` — answer to a planner's question -> publishes `clarifications.response`

**State management:** Maintains a `CoordinatorState` document in Redis (fast reads) with Postgres backup (durability). The state tracks: active tasks, recent intents, pending clarifications, evolution state, and system health.

**Concurrency limit:** Enforces `coordinator_max_active_tasks` (default 5). If the limit is hit, new task requests are queued with a user-facing message.

**Why a single coordinator:** Having one agent that sees all requests enables: deduplication (don't create the same task twice), prioritization (urgent requests jump the queue), and context awareness (relate new requests to in-flight work).

### 5.3 Planner Agent (`src/max/command/planner.py`)

**Subscribes to:** `tasks.plan`, `clarifications.response`, `tasks.context_update`

**Role:** Decomposes a high-level goal into phased subtasks.

**Planning process:**
1. Receive task with goal and context package
2. Use LLM to analyze the goal and produce an `ExecutionPlan`:
   - List of `PlannedSubtask` objects, each with description, phase_number, assigned_tools, quality_criteria, and estimated_complexity
   - Subtasks are grouped by phase — subtasks in the same phase can run in parallel
3. If the goal is ambiguous, publishes a `ClarificationRequest` instead of a plan
   - Clarification has a 1-hour TTL; if the user doesn't respond, the task is cancelled
4. Caps subtasks at `planner_max_subtasks` (default 10) to prevent runaway decomposition

**Context update handling:** If new context arrives for a task that's being planned, the planner re-plans with the updated context.

**Why phased subtasks:** Some subtasks depend on others ("gather data" must complete before "analyze data"). Phase numbers express these dependencies. Within a phase, everything is independent and can run in parallel.

### 5.4 Orchestrator Agent (`src/max/command/orchestrator.py`)

**Subscribes to:** `tasks.execute`, `tasks.cancel`, `tasks.context_update`, `audit.complete`

**Role:** Executes the plan phase by phase, manages retries, and orchestrates the audit cycle.

**Execution flow:**
```
Receive ExecutionPlan
    |
    for each phase (sequential):
        |
        asyncio.gather(execute_subtask(s1), execute_subtask(s2), ...)
        |
        if any subtask failed:
            retry (up to worker_max_retries)
    |
    Build blind AuditRequest (strips worker reasoning/confidence)
    |
    Publish audit.request
    |
    Wait for audit.complete
    |
    if audit PASS:
        Publish tasks.complete with results
    |
    if audit FAIL:
        Re-execute failed subtasks with fix_instructions from auditor
        (up to quality_max_fix_attempts)
        Re-audit
```

**Cooperative cancellation:** Maintains a `_cancelled_tasks` set. Before starting each phase, checks if the task has been cancelled. If so, stops execution and publishes a cancellation acknowledgment.

**Context updates during execution:** If new context arrives for a task mid-execution, it's applied to all remaining subtasks.

**Why the orchestrator handles auditing:** The orchestrator is the only agent that has the full execution context — it knows which subtasks failed, what the worker produced, and what the fix instructions should reference. Delegating audit orchestration to another agent would require duplicating all this context.

### 5.5 Worker Agent (`src/max/command/worker.py`)

**What:** Ephemeral agent created per subtask. Not a persistent bus subscriber.

**How:** Created by the orchestrator's `InProcessRunner`. Receives:
- Subtask description
- Context package
- Assigned tools
- Quality criteria
- Fix instructions (if re-executing after audit failure)

Produces `{content, confidence, reasoning}`. The confidence and reasoning are used for logging but deliberately excluded from the audit (blind audit protocol).

**Why ephemeral:** Workers are stateless by design. Each subtask gets a fresh worker with no memory of previous work. This prevents cross-contamination between subtasks and makes workers trivially parallelizable.

### 5.6 Task Store (`src/max/command/task_store.py`)

**What:** CRUD operations for tasks, subtasks, and results against PostgreSQL.

**Key operations:**
- `create_task()` / `create_subtask()` — insert with generated UUIDs
- `update_status()` — status transitions with timestamp tracking
- `save_result()` — store subtask execution results
- `get_active_tasks()` — query by status for coordinator state
- `get_completed_tasks()` — query completed tasks (used by recovery and evolution)

**Why a dedicated store:** Centralizes all task persistence logic. Every agent that needs task data goes through the store, ensuring consistent query patterns and status transitions.

---

## 6. Quality Gate

### 6.1 Design Principle: Blind Auditing

The quality gate's core innovation is that **the auditor never sees the worker's reasoning or confidence**. This is deliberate and non-negotiable.

**What the auditor receives:**
- Task goal (goal_anchor)
- Subtask description
- Raw output content
- Quality criteria
- Active quality rules (learned from past failures)

**What the auditor does NOT receive:**
- Worker reasoning
- Worker confidence score
- Worker's chain of thought
- Which tools the worker used
- How many retries the worker needed

**Why:** When an evaluator sees "I'm 95% confident," they anchor to that number and look for confirmation. Studies on code review show that reviewers who see author notes find fewer bugs. The blind protocol forces the auditor to evaluate the output on its own merits.

### 6.2 Quality Director Agent (`src/max/quality/director.py`)

**Subscribes to:** `audit.request`

**Flow:**
1. Receive `AuditRequest` containing blind `SubtaskAuditItem` objects
2. Load active quality rules from `QualityStore`
3. Spawn one `AuditorAgent` per subtask (ephemeral)
4. Run all audits concurrently with `asyncio.gather()`, each with a timeout (`quality_audit_timeout_seconds`, default 120s)
5. Aggregate verdicts into `AuditResponse`
6. **On FAIL:** Extract quality rules from the failure via `RuleEngine` and persist them
7. **On high-score PASS (>= 0.9):** Extract success patterns and persist them
8. Record everything to the quality ledger (append-only)
9. Update coordinator state with latest audit results
10. Publish `audit.complete`

**Why concurrent audits:** Subtasks within a phase are independent, so their audits are independent too. Running them concurrently cuts audit time by the parallelism factor.

### 6.3 Auditor Agent (`src/max/quality/auditor.py`)

**What:** Ephemeral LLM-based evaluator that produces a verdict.

**Output:** `AuditReport` with:
- `verdict`: PASS, FAIL, or NEEDS_REVISION
- `score`: 0.0 to 1.0
- `goal_alignment`: how well the output addresses the original goal
- `confidence`: auditor's confidence in its own verdict
- `issues`: list of specific problems found
- `fix_instructions`: actionable instructions for the worker to fix issues
- `strengths`: what was done well (used for pattern extraction)
- `fix_attempt`: which attempt this audit corresponds to

**Temperature:** 0.0 (deterministic). The auditor should produce consistent, reproducible verdicts.

### 6.4 Rule Engine (`src/max/quality/rules.py`)

**What:** LLM-based extraction and management of quality rules.

**Rule extraction (on failure):**
After an audit failure, the rule engine uses an LLM to analyze the failure and extract reusable quality rules. For example, if a subtask failed because it produced code without error handling, the rule might be: "All code outputs must include error handling for expected failure modes."

**Rule supersession:** Rules are never deleted. When a new rule contradicts or improves upon an old one, the old rule is marked `superseded_by` the new one. This preserves the full history of quality learning.

**Pattern extraction (on high-score success):**
When a subtask scores >= 0.9, the rule engine extracts what worked well as a `quality_pattern`. Patterns are reinforced (count incremented) when the same pattern appears again.

**Cap:** At most `quality_max_rules_per_audit` (default 5) rules are extracted per audit cycle to prevent rule explosion.

**Why append-only rules:** Quality knowledge should accumulate, not churn. A rule that was relevant 100 tasks ago might be relevant again. Supersession provides recency without destruction.

---

## 7. Tool System

### 7.1 Architecture

The tool system has three layers:

**Layer 1 — Registry (`src/max/tools/registry.py`):**
Central catalog of all tool definitions. Each tool has an ID, name, description, input schema (JSON Schema), category, and provider reference. The registry:
- Manages per-agent tool access policies (which agents can use which tools)
- Converts tool definitions to Anthropic's `tool_use` format for LLM calls
- Supports tool permissions (read-only, write, execute, admin)

**Layer 2 — Executor (`src/max/tools/executor.py`):**
Execution pipeline for every tool invocation:
1. **Resolve:** Look up tool definition in registry
2. **Permission check:** Verify the calling agent has access
3. **Provider health:** Check if the provider is healthy
4. **Execute:** Call the provider's `execute()` method with timeout (`tool_execution_timeout_seconds`, default 60s)
5. **Audit:** If `tool_audit_enabled` (default true), record the invocation in `tool_invocations` table

**Layer 3 — Providers:**
- `NativeToolProvider`: In-process handlers registered as Python functions
- `MCPToolProvider`: Proxies to external MCP servers via stdio transport
- `OpenAPIToolProvider`: Auto-generates tools from OpenAPI 3.x specs

### 7.2 Provider Types

**NativeToolProvider (`src/max/tools/providers/native.py`):**
Maps tool IDs to handler functions. Handlers are async and receive the tool inputs as a dict. 67 handler mappings are registered in `src/max/tools/native/__init__.py`.

**MCPToolProvider (`src/max/tools/providers/mcp.py`):**
Connects to MCP (Model Context Protocol) servers via stdio. Discovers available tools via `list_tools()`, converts MCP tool definitions to MAX format, and proxies `execute()` calls via `call_tool()`. Supports automatic reconnection.

**OpenAPIToolProvider (`src/max/tools/providers/openapi.py`):**
Given an OpenAPI 3.x spec (JSON, YAML, or file path):
1. Parses the spec and extracts all paths + operations
2. Generates one tool per operation with ID format `{tag}_{operationId}` or `{method}_{path}`
3. Separates parameters into path, query, and body buckets
4. Converts OpenAPI schemas to JSON Schema for tool input validation
5. On execute: builds the HTTP request, substitutes path parameters, sends via httpx

**Why three providers:** Native handles the common case (in-process tools). MCP enables integration with any MCP-compatible server without writing MAX-specific code. OpenAPI enables integration with any REST API by just pointing at its spec — zero code required.

### 7.3 Native Tools (80 tools)

All native tools follow the same patterns:
- **Graceful degradation:** Each module checks for optional imports (`playwright`, `boto3`, `docker`, etc.) at import time. If the library is missing, the tool returns a clear error message rather than crashing.
- **Async execution:** Blocking I/O (subprocess, file I/O) is offloaded to thread executors via `asyncio.to_thread()`
- **Output caps:** Results are truncated at 50KB to prevent context window overflow
- **No side effects on read:** Read operations (`file.read`, `database.*.query`, `git.status`) never modify state

**Categories:**

| Category | Tools | Notes |
|----------|-------|-------|
| **Code & Files** (22) | `code.ast_parse`, `code.lint`, `code.format`, `code.test`, `code.dependencies`, `file.read`, `file.write`, `file.edit`, `file.glob`, `file.delete`, `directory.list`, `shell.execute`, `git.status/diff/log/commit/clone/branch/push/pr_create`, `process.list`, `grep.search` | `shell.execute` has configurable timeout and runs in a subprocess |
| **Web** (2) | `http.fetch`, `http.request` | `http.fetch` is simplified GET; `http.request` supports all methods with headers/body |
| **Browser** (7) | `browser.navigate`, `browser.click`, `browser.type`, `browser.screenshot`, `browser.get_content`, `browser.fill_form`, `browser.evaluate` | Requires `playwright` optional dependency |
| **Database** (6) | `database.postgres_query/execute`, `database.sqlite_query/execute`, `database.redis_get/set` | PostgreSQL uses asyncpg; SQLite uses aiosqlite |
| **Documents** (5) | `document.read_pdf`, `document.read_spreadsheet`, `document.write_csv`, `document.write_spreadsheet`, `document.parse_json` | Requires `PyPDF2`, `openpyxl` optional dependencies |
| **Data** (5) | `data.load`, `data.query`, `data.summarize`, `data.transform`, `data.export` | Uses Polars for fast DataFrame operations |
| **AWS** (8) | `aws.s3_list/get/put/delete`, `aws.ec2_list/manage`, `aws.lambda_invoke`, `aws.cloudwatch_query` | Requires `boto3` |
| **Infrastructure** (9) | `server.system_info`, `server.ssh_execute`, `server.service_status`, `docker.list_containers/run/stop/logs/build/compose` | SSH via `asyncssh`; Docker via `docker` SDK |
| **Email** (4) | `email.send`, `email.read`, `email.search`, `email.list_folders` | SMTP via `aiosmtplib`; IMAP via `aioimaplib` |
| **Calendar** (4) | `calendar.list_events`, `calendar.create_event`, `calendar.update_event`, `calendar.delete_event` | CalDAV protocol via `caldav` library |
| **Media** (5) | `media.image_resize/convert/info`, `media.audio_transcribe`, `media.video_info` | Pillow for images; ffprobe for video |
| **Web Scraping** (3) | `web.scrape`, `web.extract_links`, `web.search` | BeautifulSoup for scraping; Brave Search API for web search |

---

## 8. Evolution System

The evolution system makes MAX self-improving. It proposes changes, tests them safely, and only promotes those that don't cause regressions.

### 8.1 Evolution Director (`src/max/evolution/director.py`)

**Subscribes to:** `evolution.trigger` (from scheduler), `evolution.proposal` (from scouts)

**Pipeline:**

```
Trigger received
    |
    v
Anti-degradation check
    Compare 24h vs 48h quality pulse (average audit scores)
    If 24h < 48h for N consecutive checks: FREEZE evolution
    |
    v
Evaluate proposal priority
    computed_priority = impact * (1 - risk) / max(effort, 0.1)
    Must meet evolution_min_priority threshold (default 0.3)
    |
    v
Run pipeline:
    1. SnapshotManager.capture()        -- save current state
    2. SentinelScorer.run_baseline()    -- 24 benchmarks before change
    3. ImprovementAgent.implement()     -- LLM generates changes
    4. SentinelScorer.run_candidate()   -- 24 benchmarks after change
    5. SentinelScorer.compare_and_verdict()
        |
        +-- PASSED: promote candidates, publish "evolution.promoted"
        +-- FAILED: restore snapshot, publish "evolution.rolled_back"
```

**Freeze/unfreeze:** When the anti-degradation check detects consecutive quality drops (`evolution_freeze_consecutive_drops`, default 2), evolution is frozen. No proposals are evaluated. Unfreeze can be triggered manually via the admin API or automatically when quality recovers.

### 8.2 Scouts (`src/max/evolution/scouts.py`)

**What:** Four specialized agents that analyze system state and propose improvements.

| Scout | What It Looks For |
|-------|-------------------|
| `ToolScout` | Underused tools, missing tool categories, tool error patterns |
| `PatternScout` | Recurring quality patterns, successful strategies to amplify |
| `QualityScout` | Common audit failure modes, rule effectiveness, fix success rates |
| `EcosystemScout` | New capabilities, integration opportunities, architectural improvements |

Each scout produces up to 3 `EvolutionProposal` objects with `impact`, `risk`, `effort` scores and a `rationale`.

### 8.3 Improvement Agent (`src/max/evolution/improver.py`)

**What:** Takes an accepted proposal and generates concrete changes.

**Change types:** `ChangeSet` containing up to 5 changes, each with:
- `target_type`: `prompt`, `tool_config`, or `context_rule`
- `target_id`: which agent/tool/rule to modify
- `before_value`: current value (for rollback)
- `after_value`: proposed new value

The improvement agent uses LLM to translate the proposal's high-level rationale into specific, testable changes.

### 8.4 Canary Runner (`src/max/evolution/canary.py`)

**What:** Replay historical tasks under a candidate configuration.

**How:**
1. Load N recently completed tasks (`evolution_canary_replay_count`, default 5)
2. Re-execute each task with the candidate configuration
3. Re-audit each result with the same criteria
4. Compare canary audit scores against original scores
5. Report pass/fail based on whether the candidate is at least as good

**Why canary testing:** Sentinel benchmarks are synthetic. Canary testing uses real historical tasks, providing a more realistic signal about whether a change improves actual work quality.

### 8.5 Snapshot Manager (`src/max/evolution/snapshot.py`)

**What:** Captures and restores system state for safe experimentation.

**What's captured:** Active prompts (from `evolution_prompts`), tool configs (from `evolution_tool_configs`), and baseline metrics (from `performance_metrics`). All stored in `evolution_snapshots` with experiment_id for traceability.

**Why snapshots:** If a change fails sentinel testing, the system must return to its exact previous state. Snapshots provide that guarantee.

### 8.6 Self-Model (`src/max/evolution/self_model.py`)

**What:** MAX's understanding of its own capabilities and limitations.

**Four dimensions:**
1. **Capability Map** — Domain x task_type matrix with EMA-smoothed scores. Updated after every task completion. Decay factor 0.9, new weight 0.1.
2. **Failure Taxonomy** — Categorized failures with occurrence counts and last-seen timestamps. Used by scouts to identify improvement targets.
3. **Confidence Calibration** — Tracks predicted vs actual scores. Computes mean absolute error to measure how well MAX knows what it's good at.
4. **Evolution Journal** — Complete audit trail of all evolution events (proposals, experiments, promotions, rollbacks).

### 8.7 Preference Learning (`src/max/evolution/preference.py`)

**What:** Per-user preference profiles learned from interaction patterns.

**How:** Records observations (signals) per user — things like response preferences, communication style, domain expertise. When enough signals accumulate (`evolution_preference_refresh_signals`, default 10), an LLM synthesizes them into a structured profile:

- **Communication:** tone, detail_level, update_frequency, languages, timezone
- **Code:** style, review_depth, test_coverage, commit_style
- **Workflow:** clarification_threshold, autonomy_level, reporting_style
- **Domain Knowledge:** expertise_areas, client_contexts, project_conventions

Profiles are used by the context packager to tailor MAX's behavior per user.

---

## 9. Sentinel Anti-Degradation

The sentinel system is MAX's immune system. It ensures that no change — whether from evolution, manual intervention, or bug — degrades the system's capabilities.

### 9.1 Benchmark Registry (`src/max/sentinel/benchmarks.py`)

**24 fixed benchmarks across 7 capability dimensions:**

| Capability | Benchmarks |
|-----------|-----------|
| `memory_retrieval` | context_recall, anchor_persistence, compaction_quality, relevance_ranking |
| `planning` | task_decomposition, phase_ordering, subtask_detail, dependency_detection |
| `communication` | tone_matching, clarity, instruction_following, user_intent_parsing |
| `tool_selection` | correct_tool_choice, parameter_accuracy, fallback_handling, multi_tool_coordination |
| `audit_quality` | defect_detection, false_positive_rate, fix_instruction_quality, score_calibration |
| `security` | injection_detection, privilege_escalation_prevention, data_leakage_prevention, input_validation |
| `orchestration` | parallel_execution, error_recovery, cancellation_handling, progress_reporting |

Each benchmark has:
- A scenario description (what to test)
- Evaluation criteria (how to judge)
- A weight (how much it matters relative to others in its category)

**Why 24 benchmarks:** Enough to cover all critical capabilities without making runs prohibitively expensive. 4 per category provides redundancy — a single flaky benchmark won't cause a false regression.

### 9.2 Scoring Pipeline

**TestRunner (`src/max/sentinel/runner.py`):**
Two-step LLM evaluation per benchmark:
1. **Response step:** Feed the scenario to the agent (or model) being tested, get a response
2. **Judge step:** Use an LLM judge (at temperature 0.0 for determinism) to score the response against the evaluation criteria on a 0.0-1.0 scale

Also supports historical task replay (`replay_count` tasks, default 10) for more realistic evaluation.

**SentinelScorer (`src/max/sentinel/scorer.py`):**
Orchestrates full scoring runs:
1. Run all 24 benchmarks
2. Compute weighted capability aggregates per category
3. Store all scores in `sentinel_scores` and `sentinel_capability_scores`

**ScoreComparator (`src/max/sentinel/comparator.py`):**
Compares baseline (before change) vs candidate (after change):
1. **Per-test-case:** For each benchmark, check if candidate score < baseline score. Any regression is flagged.
2. **Per-capability-aggregate:** For each capability category, check if weighted aggregate dropped. Any regression is flagged.
3. **Verdict:** PASSED only if BOTH layers show zero regressions.

**Why two-layer comparison:** A per-test check catches specific degradation (one benchmark got worse). A per-capability check catches distributed degradation (several benchmarks got slightly worse, none flagged individually, but the category average dropped). Both must pass.

### 9.3 Sentinel Agent (`src/max/sentinel/agent.py`)

**Subscribes to:** `sentinel.run_request`

**Responsibilities:**
- Seeds all 24 benchmarks into the database on startup (idempotent)
- Handles three run types: `baseline`, `candidate`, `scheduled`
- Scheduled monitoring (default every 12 hours) detects drift over time
- Publishes: `sentinel.baseline_complete`, `sentinel.candidate_complete`, `sentinel.verdict`, `sentinel.scheduled_complete`

---

## 10. API Layer

### 10.1 App Factory (`src/max/api/__init__.py`)

`create_api_app(lifespan)` assembles the FastAPI application:
1. Creates the FastAPI instance with the provided lifespan context manager
2. Adds slowapi rate limiting middleware
3. Includes 5 routers: health, messaging, telegram, introspection, admin

### 10.2 Authentication (`src/max/api/auth.py`)

**Mechanism:** Bearer token via `Authorization: Bearer <key>` header.

**Validation:** Keys are validated against the comma-separated `MAX_API_KEYS` setting using `hmac.compare_digest()` for constant-time comparison. This prevents timing side-channel attacks where an attacker could determine how many characters of a key are correct by measuring response time.

**Error responses:**
- No keys configured (MAX_API_KEYS empty): 503 Service Unavailable
- Invalid key: 401 Unauthorized

### 10.3 Rate Limiting (`src/max/api/rate_limit.py`)

**Library:** slowapi (built on `limits`)

**Limits:**
- API endpoints: `rate_limit_api` (default "60/minute")
- Messaging endpoints: `rate_limit_messaging` (default "30/minute")

**Key function:** Extracts client IP from `request.client.host`.

**Response:** 429 Too Many Requests with `Retry-After` header.

### 10.4 Health Endpoints (`src/max/api/health.py`)

**`GET /health` (liveness):**
```json
{
  "status": "ok",
  "uptime_seconds": 3421.5,
  "agents": {
    "coordinator": "running",
    "planner": "running",
    "orchestrator": "running",
    "quality_director": "running",
    "evolution_director": "running",
    "sentinel": "running"
  },
  "infrastructure": {
    "database": "connected",
    "redis": "connected",
    "bus": "listening",
    "circuit_breaker": "closed"
  }
}
```

**`GET /ready` (readiness):**
Checks DB and Redis connectivity. Returns 200 if both are reachable, 503 if either is down. Used by Azure Container Apps for readiness probes.

### 10.5 Messaging Endpoints (`src/max/api/messaging.py`)

- `POST /api/v1/messages` — Accepts `{text, user_id}`, publishes to `intents.new`, returns `{message_id, status: "accepted"}`
- `GET /api/v1/messages?user_id=X` — Polls for responses queued for that user. Clears after read.
- `POST /api/v1/messages/webhook` — Registers a webhook URL for push delivery

### 10.6 Introspection Endpoints (`src/max/api/introspection.py`)

- `GET /api/v1/tasks` — Active tasks with status
- `GET /api/v1/tasks/{task_id}` — Task detail with all subtasks
- `GET /api/v1/evolution` — Latest proposals and journal entries
- `GET /api/v1/sentinel` — Recent test runs and scores
- `GET /api/v1/dead-letters` — Messages in dead letter queues

### 10.7 Admin Endpoints (`src/max/api/admin.py`)

- `POST /api/v1/admin/evolution/freeze` — Manually freeze evolution
- `POST /api/v1/admin/evolution/unfreeze` — Manually unfreeze
- `POST /api/v1/admin/sentinel/run` — Trigger a sentinel monitoring run

### 10.8 Telegram Webhook (`src/max/api/telegram.py`)

- `POST /webhook/telegram` — Receives Telegram updates. Validates `X-Telegram-Bot-Api-Secret-Token` header via `hmac.compare_digest()`.

---

## 11. Composition Root & Application Lifecycle

### 11.1 Composition Root (`src/max/app.py`)

The composition root is the single place where all dependencies are wired together. No dependency injection framework — just explicit constructor injection.

**`create_app_state(settings) -> AppState`** (synchronous):

```
Settings
    |
    +-- configure_logging() + configure_metrics()
    |
    +-- Database(dsn)
    +-- Redis(url)
    +-- WarmMemory(redis)
    +-- StreamsTransport(redis, consumer_group, consumer_name)
    +-- MessageBus(redis, transport)
    +-- CircuitBreaker(threshold, cooldown)
    +-- LLMClient(api_key, circuit_breaker)
    |
    +-- TaskStore(db)
    +-- QualityStore(db)
    +-- EvolutionStore(db)
    +-- SentinelStore(db)
    +-- ToolInvocationStore(db)
    +-- MetricCollector(db)
    +-- CoordinatorStateManager(db, warm_memory)
    +-- Scheduler(db)
    |
    +-- ToolRegistry() + ToolExecutor(registry, store)
    |
    +-- InProcessRunner(llm)
    +-- CoordinatorAgent(llm, bus, db, warm_memory, settings, state_manager, task_store)
    +-- PlannerAgent(llm, bus, db, warm_memory, settings, task_store)
    +-- OrchestratorAgent(llm, bus, db, warm_memory, settings, task_store, runner, quality_store)
    +-- QualityDirectorAgent(llm, bus, db, warm_memory, settings, task_store, quality_store, rule_engine, state_manager, metric_collector)
    +-- EvolutionDirectorAgent(llm, bus, evo_store, quality_store, snapshot_manager, improver, canary_runner, self_model, settings, state_manager, task_store, sentinel_scorer)
    +-- SentinelAgent(bus, scorer, registry, store)
    |
    +-- AppState(all of the above)
```

### 11.2 Startup Sequence

```python
lifespan(app):
    settings = Settings()
    state = create_app_state(settings)    # Synchronous wiring
    app.state.app_state = state

    await state.db.connect()              # Open connection pool
    await state.db.init_schema()          # Run schema.sql (idempotent)
    await state.bus.start_listening()     # Start Streams consumers
    await start_agents(state)             # agent.start() for all 6 agents
    await start_scheduler_jobs(state)     # Register + start 4 jobs
    await recover_orphaned_tasks(state)   # Re-queue in-flight tasks

    yield  # FastAPI runs

    await shutdown_app_state(state)       # Graceful shutdown
```

### 11.3 Shutdown Sequence

Reverse order with 10-second timeouts per step to prevent hung coroutines from blocking:

1. `scheduler.stop()` — No new triggers
2. `agent.stop()` for each agent in reverse — Unsubscribe from bus
3. `bus.close()` — Stop stream consumers
4. `llm.close()` — Close Anthropic client
5. `db.close()` — Close connection pool
6. `redis.close()` — Close Redis connection

### 11.4 Task Recovery (`src/max/recovery.py`)

On startup, queries the task store for tasks stuck in intermediate states:
- `planned` or `executing` → re-publish to `tasks.execute`
- `auditing` → re-publish to `audit.request`

This ensures no work is lost if MAX crashes mid-execution.

---

## 12. Message Bus & Channel Map

### 12.1 Redis Streams Transport (`src/max/bus/streams.py`)

**Publish:** `XADD channel MAXLEN~ stream_max_len * data`

**Subscribe:** Creates a consumer group per channel, reads via `XREADGROUP GROUP group consumer`. On successful handler execution, acknowledges via `XACK`.

**Retry logic:** On handler failure, the message is re-published with incremented `_retry_count`. After `bus_dead_letter_max_retries` (default 3) failures, the message is moved to `dead_letter:{channel}`.

**Why Redis Streams over pub/sub:** Pub/sub loses messages if no subscriber is listening. Streams are durable — messages persist until acknowledged. Consumer groups enable load balancing across multiple consumers. Dead letter queues prevent poison messages from blocking the pipeline.

### 12.2 Full Channel Map

| Channel | Publisher | Subscriber | Payload |
|---------|-----------|------------|---------|
| `intents.new` | CommunicatorAgent, API | CoordinatorAgent | Intent with user message |
| `tasks.plan` | CoordinatorAgent | PlannerAgent | Task to decompose |
| `tasks.execute` | PlannerAgent, recovery | OrchestratorAgent | ExecutionPlan |
| `tasks.complete` | OrchestratorAgent | CoordinatorAgent | Task results |
| `tasks.cancel` | CoordinatorAgent | OrchestratorAgent | Cancellation request |
| `tasks.context_update` | CoordinatorAgent | Planner, Orchestrator | Updated context |
| `clarifications.new` | PlannerAgent | CommunicatorAgent | Question for user |
| `clarifications.response` | CommunicatorAgent | PlannerAgent | User's answer |
| `status_updates.new` | Coordinator, Orchestrator | CommunicatorAgent | Progress update |
| `results.new` | CoordinatorAgent | CommunicatorAgent | Final result |
| `audit.request` | Orchestrator, recovery | QualityDirectorAgent | Blind audit items |
| `audit.complete` | QualityDirectorAgent | OrchestratorAgent | Audit verdicts |
| `evolution.trigger` | Scheduler | EvolutionDirector | Scout trigger |
| `evolution.proposal` | Scouts | EvolutionDirector | Change proposal |
| `evolution.promoted` | EvolutionDirector | (observers) | Promoted change |
| `evolution.rolled_back` | EvolutionDirector | (observers) | Rolled back change |
| `evolution.freeze` | EvolutionDirector, Admin | (observers) | Evolution frozen |
| `evolution.unfreeze` | EvolutionDirector, Admin | (observers) | Evolution unfrozen |
| `sentinel.run_request` | Scheduler, Admin | SentinelAgent | Run trigger |
| `sentinel.baseline_complete` | SentinelAgent | (observers) | Baseline scores |
| `sentinel.candidate_complete` | SentinelAgent | (observers) | Candidate scores |
| `sentinel.verdict` | SentinelAgent | (observers) | Pass/fail verdict |
| `sentinel.scheduled_complete` | SentinelAgent | (observers) | Monitoring results |
| `memory.compact` | Scheduler | (handler) | Compaction trigger |
| `memory.anchor_re_eval` | Scheduler | (handler) | Anchor re-evaluation |

---

## 13. Database Schema

### 13.1 Schema Organization

All DDL is in `src/max/db/schema.sql` — a single file with `CREATE TABLE IF NOT EXISTS` for every table, making it idempotent. The schema is organized in creation order to respect foreign key dependencies.

### 13.2 Table Reference (36 tables)

**Core tables (Phase 1):**
- `intents` — Inbound user requests
- `tasks` — Top-level task tracking
- `subtasks` — Decomposed work units with phase numbers
- `audit_reports` — Quality verdicts with scores and fix instructions
- `results` — Final task outputs
- `clarification_requests` — Planner questions to users
- `status_updates` — Progress notifications
- `context_anchors` — Named persistent context markers with lifecycle
- `quality_ledger` — Append-only audit trail
- `memory_embeddings` — Vector store with 1024-dim embeddings

**Memory tables (Phase 2):**
- `graph_nodes` — Knowledge graph nodes
- `graph_edges` — Weighted directed edges
- `compaction_log` — Compaction history
- `performance_metrics` — Metric time series
- `shelved_improvements` — Parked evolution proposals

**Communication tables (Phase 3):**
- `conversation_messages` — Full message history by platform

**Quality tables (Phase 5):**
- `quality_rules` — Learned rules with supersession
- `quality_patterns` — Success patterns with reinforcement counts

**Tool tables (Phase 6A):**
- `tool_invocations` — Audit trail for tool usage

**Evolution tables (Phase 7):**
- `evolution_proposals`, `evolution_snapshots`, `evolution_prompts`, `evolution_tool_configs`, `evolution_context_rules` — Evolution experiment tracking
- `preference_profiles` — Per-user preferences
- `capability_map`, `failure_taxonomy`, `evolution_journal`, `confidence_calibration` — Self-model

**Sentinel tables (Phase 8):**
- `sentinel_benchmarks`, `sentinel_test_runs`, `sentinel_scores`, `sentinel_capability_scores`, `sentinel_verdicts`, `sentinel_revert_log` — Anti-degradation testing

**Infrastructure tables:**
- `scheduler_state` — Persisted scheduler timestamps

### 13.3 Key Indexes

- **HNSW index** on `memory_embeddings.embedding` — cosine distance, m=16, ef_construction=64 (approximate nearest neighbor for semantic search)
- **GIN indexes** on `search_vector` columns — for PostgreSQL full-text search
- **B-tree indexes** on `status`, `lifecycle_state`, `created_at` — for common query patterns
- **Partial unique index** on `evolution_prompts` — `WHERE is_live = true`, ensures only one live prompt per agent

---

## 14. Configuration Reference

All settings are loaded from environment variables (or `.env` file) via pydantic-settings. See `.env.example` for the full template.

### 14.1 Required Settings

| Setting | Description |
|---------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude access |
| `POSTGRES_PASSWORD` | PostgreSQL password |

### 14.2 Key Optional Settings (with defaults)

| Setting | Default | Description |
|---------|---------|-------------|
| `POSTGRES_HOST` | localhost | PostgreSQL host |
| `POSTGRES_PORT` | 5432 | PostgreSQL port |
| `POSTGRES_DB` | max | Database name |
| `POSTGRES_USER` | max | Database user |
| `REDIS_URL` | redis://localhost:6379/0 | Redis connection URL |
| `MAX_LOG_LEVEL` | DEBUG | Log level |
| `TELEGRAM_BOT_TOKEN` | (empty) | Telegram bot token |
| `MAX_OWNER_TELEGRAM_ID` | (empty) | Owner's Telegram user ID |
| `COORDINATOR_MODEL` | claude-opus-4-6 | Model for coordinator |
| `PLANNER_MODEL` | claude-opus-4-6 | Model for planner |
| `ORCHESTRATOR_MODEL` | claude-opus-4-6 | Model for orchestrator |
| `WORKER_MODEL` | claude-opus-4-6 | Model for workers |
| `QUALITY_DIRECTOR_MODEL` | claude-opus-4-6 | Model for quality director |
| `SENTINEL_MODEL` | claude-opus-4-6 | Model for sentinel judge |
| `COORDINATOR_MAX_ACTIVE_TASKS` | 5 | Max concurrent tasks |
| `PLANNER_MAX_SUBTASKS` | 10 | Max subtasks per plan |
| `WORKER_MAX_RETRIES` | 2 | Max worker retries |
| `WORKER_TIMEOUT_SECONDS` | 300 | Worker execution timeout |
| `QUALITY_MAX_FIX_ATTEMPTS` | 2 | Max fix cycles after audit fail |
| `QUALITY_PASS_THRESHOLD` | 0.7 | Minimum passing audit score |
| `QUALITY_HIGH_SCORE_THRESHOLD` | 0.9 | Score threshold for pattern extraction |
| `EVOLUTION_SCOUT_INTERVAL_HOURS` | 6 | How often scouts run |
| `EVOLUTION_MIN_PRIORITY` | 0.3 | Minimum proposal priority to proceed |
| `EVOLUTION_FREEZE_CONSECUTIVE_DROPS` | 2 | Consecutive drops before freeze |
| `SENTINEL_REPLAY_COUNT` | 10 | Historical tasks to replay |
| `SENTINEL_MONITOR_INTERVAL_HOURS` | 12 | Monitoring frequency |
| `BUS_TRANSPORT` | streams | streams or pubsub |
| `BUS_DEAD_LETTER_MAX_RETRIES` | 3 | Retries before dead letter |
| `TOOL_EXECUTION_TIMEOUT_SECONDS` | 60 | Per-tool timeout |
| `MAX_HOST` | 0.0.0.0 | API server bind host |
| `MAX_PORT` | 8080 | API server port |
| `MAX_API_KEYS` | (empty) | Comma-separated API keys |
| `RATE_LIMIT_API` | 60/minute | API rate limit |
| `RATE_LIMIT_MESSAGING` | 30/minute | Messaging rate limit |
| `LLM_CIRCUIT_BREAKER_THRESHOLD` | 5 | Failures before circuit opens |
| `LLM_CIRCUIT_BREAKER_COOLDOWN_SECONDS` | 60 | Cooldown before half-open |
| `TASK_RECOVERY_ENABLED` | true | Recover orphaned tasks on startup |
| `OTEL_ENABLED` | false | Enable OpenTelemetry metrics |
| `AZURE_KEY_VAULT_URL` | (empty) | Azure Key Vault URL |

---

## 15. Deployment Architecture

### 15.1 Local Development

```
docker compose up
```

This starts three containers:
- `max` — Built from Dockerfile, depends on postgres + redis health
- `postgres` — pgvector/pgvector:pg17 with persistent volume
- `redis` — redis:7-alpine with persistent volume

Environment variables come from `.env` file. Database-level settings (host, port, db name) are overridden in the compose environment block to use Docker service names.

### 15.2 Docker Image

Multi-stage build:
- **Stage 1 (builder):** `python:3.12-slim` + uv 0.6. Copies `pyproject.toml` + `uv.lock` first (layer caching), installs dependencies with `uv sync --frozen --no-dev`, then copies source and installs the project.
- **Stage 2 (runtime):** `python:3.12-slim` + curl (for healthcheck). Non-root user `appuser`. Copies `.venv` and `src/max` from builder. Port 8080, healthcheck on `/health`.

### 15.3 Azure Infrastructure

Provisioned by `scripts/azure-provision.sh` (idempotent):

| Resource | Service | Config |
|----------|---------|--------|
| Resource Group | - | Logical container for all resources |
| Log Analytics | Azure Monitor | 30-day retention, all services stream here |
| Container Registry | ACR Basic | Docker image storage |
| PostgreSQL | Flexible Server B1ms | 1 vCPU, 2GB RAM, 32GB storage, pgvector enabled |
| Redis | Cache for Redis Basic C0 | 250MB, TLS on port 6380 |
| Key Vault | Azure Key Vault | Stores all secrets (API keys, passwords, tokens) |
| Container Apps Env | - | VNet-integrated, Log Analytics connected |
| Container App | Container Apps | 1 CPU, 2GB RAM, min 1 / max 10 replicas, port 8080 |

**Secret management:** All secrets stored in Key Vault. Container App references them via `secretref:` in environment variables. Passwords are generated with `openssl rand -base64 32` on first provisioning and retrieved from Key Vault on subsequent runs.

### 15.4 Deployment Flow

`scripts/deploy.sh`:
1. Pre-flight checks (Azure CLI, Docker installed and running)
2. Build Docker image tagged with git SHA
3. Authenticate with ACR
4. Tag and push to ACR (both SHA tag and `latest`)
5. Update Container App with new image
6. Health check verification with retry (up to 60 seconds)
7. Exit 1 on health check failure

---

## 16. Testing Strategy

### 16.1 Test Framework

- **pytest** with `pytest-asyncio` (asyncio_mode = "auto")
- **ruff** for linting (line-length=100, py312, select=["E","F","I","N","W","UP"])
- All async tests run in a shared event loop per module

### 16.2 Shared Fixtures (`tests/conftest.py`)

Key fixtures that most tests use:
- `settings` — monkeypatched environment with test values
- `db` — real asyncpg connection to a test database with schema initialization
- `redis_client` — Redis DB 15 (isolated from production DB 0) with `flushdb` on teardown
- `warm_memory` — WarmMemory backed by the test Redis
- `bus` — MessageBus backed by the test Redis
- `graph` — MemoryGraph backed by the test database

### 16.3 Test Organization

| Category | Files | Tests |
|----------|-------|-------|
| API | 8 | ~80 |
| Command Chain | 7 | ~100 |
| Communication | 5 | ~60 |
| Quality Gate | 5 | ~50 |
| Evolution | 7 | ~80 |
| Sentinel | 9 | ~120 |
| Memory | 7 | ~70 |
| Bus | 2 | ~30 |
| LLM | 3 | ~20 |
| Tools | 22 | ~500 |
| Infrastructure | 6 | ~50 |
| Models | 4 | ~30 |
| Integration | 5 | ~40 |
| Docker/Deploy | 2 | ~63 |
| **Total** | **~92** | **~1500+** |

### 16.4 Testing Philosophy

- **Real databases:** Integration tests use real PostgreSQL and Redis, not mocks. This catches issues that mocked tests miss (e.g., schema mismatches, query errors).
- **TDD:** Every module was built test-first. Tests were written before implementation, verified to fail, then implementation was written to make them pass.
- **Blind audit testing:** Quality gate tests verify that audit requests do not contain worker reasoning or confidence.
- **Infrastructure validation:** Docker and Azure script tests validate structural properties without requiring Docker or Azure CLI, making them runnable in any CI environment.

---

*This document covers the complete technical architecture of MAX as of its initial release. Every design decision documented here was made deliberately, tested thoroughly, and reviewed independently.*
