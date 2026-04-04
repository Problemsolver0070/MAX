# Max — Project Status

> **Last updated:** 2026-04-04
> **Current phase:** Phase 3 Complete + Merged, Phase 4 not started
> **Branch:** `master` (Phase 1 + Phase 2 + Phase 3 merged)

---

## Quick Resume Guide

**To continue building Max in a new session:**

1. Read this file first
2. Check `docs/superpowers/specs/2026-04-04-max-design.md` for the full design spec
3. Check `docs/superpowers/specs/2026-04-04-max-phase3-communication-layer.md` for Phase 3 design spec
4. Check `docs/superpowers/plans/2026-04-04-max-phase3-communication-layer.md` for Phase 3 plan (completed)
5. **Next step:** Brainstorm + write Phase 4 (Command Chain) spec and plan, then execute

---

## What Exists

### Design Documents
- `docs/superpowers/specs/2026-04-04-max-design.md` — Full approved design spec (10 sections)
- `docs/superpowers/specs/2026-04-04-max-phase2-memory-system.md` — Phase 2 memory system design spec
- `docs/superpowers/specs/2026-04-04-max-phase3-communication-layer.md` — Phase 3 communication layer design spec
- `docs/superpowers/plans/2026-04-04-max-phase1-core-foundation.md` — Phase 1 plan (completed)
- `docs/superpowers/plans/2026-04-04-max-phase1-critical-fixes.md` — Phase 1 fixes plan (completed)
- `docs/superpowers/plans/2026-04-04-max-phase2-memory-system.md` — Phase 2 plan (13 tasks, completed)
- `docs/superpowers/plans/2026-04-04-max-phase3-communication-layer.md` — Phase 3 plan (11 tasks, completed)
- `RESEARCH.md` — OpenClaw research

### Phase 1: Core Foundation (Complete + Merged)

```
src/max/
├── __init__.py               # v0.1.0
├── config.py                 # Settings class (pydantic-settings, env vars)
├── models/
│   ├── messages.py           # Intent, Result, ClarificationRequest, StatusUpdate, Priority
│   └── tasks.py              # Task, SubTask, AuditReport, TaskStatus, AuditVerdict, QualityRule
├── llm/
│   ├── client.py             # Async Anthropic wrapper (complete/close, usage tracking, retries)
│   └── models.py             # ModelType enum, LLMResponse, ToolCall
├── bus/
│   └── message_bus.py        # Redis pub/sub (subscribe/unsubscribe/publish, multi-handler fan-out)
├── db/
│   ├── postgres.py           # Async connection pool (asyncpg), transactions, query helpers
│   ├── redis_store.py        # WarmMemory: key-value with TTL, list operations
│   └── schema.sql            # 11 tables (6 Phase 1 + 5 Phase 2)
├── agents/
│   └── base.py               # Abstract BaseAgent with think(), AgentConfig, lifecycle hooks
└── tools/
    └── registry.py           # Register, get, list, permissions, to_anthropic_tools
```

### Phase 2: Memory System (Complete + Merged)

```
src/max/memory/
├── __init__.py               # Package exports (10 public classes)
├── models.py                 # 4 StrEnum + 28 Pydantic v2 models + GraphHealthStatus alias
├── embeddings.py             # EmbeddingProvider ABC + VoyageEmbeddingProvider (voyage-3, 1024-dim)
├── graph.py                  # MemoryGraph: CRUD, BFS traversal, cycle detection, shortest path, subgraph, decay, merge
├── anchors.py                # AnchorManager: lifecycle (Active→Stale→Superseded→Archived), permanence, supersession
├── compaction.py             # CompactionEngine: relevance scoring, tier determination, soft budget (never hard-cuts)
├── retrieval.py              # HybridRetriever (graph+semantic+keyword) + RRFMerger
├── context_packager.py       # ContextPackager: LLM-curated context packaging (two-call Opus pipeline)
├── coordinator_state.py      # CoordinatorStateManager: warm (Redis) + cold (PostgreSQL) persistence
└── metrics.py                # MetricCollector: recording, baselines (percentiles), blind comparison

src/max/db/migrations/
└── 002_memory_system.sql     # Standalone migration for Phase 2 tables
```

**173 tests passing, 94% coverage, lint clean.**

### Phase 3: Communication Layer (Complete + Merged)

```
src/max/comm/
├── __init__.py               # Package exports (14 public symbols)
├── models.py                 # 3 StrEnum + 6 Pydantic v2 models (InboundMessage, OutboundMessage, etc.)
├── injection_scanner.py      # PromptInjectionScanner: pattern-based trust scoring (0.0-1.0)
├── formatter.py              # OutboundFormatter: 5 static methods (result, status, clarification, batch, error)
├── telegram_adapter.py       # TelegramAdapter + OwnerOnlyMiddleware (aiogram 3.x)
├── communicator.py           # CommunicatorAgent: LLM intent parsing, commands, batching, urgency
└── router.py                 # MessageRouter: lifecycle, persistence, callback routing

src/max/db/migrations/
├── 002_memory_system.sql
└── 003_communication.sql     # conversation_messages table
```

**247 tests passing (74 new), lint/format clean.**

Key features:
- Three-layer adapter pattern: TelegramAdapter → MessageRouter → CommunicatorAgent
- LLM-powered intent parsing with structured JSON output
- Urgency classification: SILENT/NORMAL/IMPORTANT/CRITICAL
- Update batching for SILENT messages with periodic flush
- Prompt injection scanning with pattern-based trust scoring
- OwnerOnlyMiddleware drops all non-owner Telegram users
- Outbound formatter with HTML formatting and inline keyboards
- Conversation persistence in PostgreSQL

### Database Schema (12 tables)
Phase 1: tasks, subtasks, audit_reports, intents, results, status_updates, clarification_requests, context_anchors, quality_ledger, memory_embeddings
Phase 2: graph_nodes, graph_edges, compaction_log, performance_metrics, shelved_improvements
Phase 2 ALTERs: context_anchors (9 new lifecycle/permanence columns), memory_embeddings (8 new columns + FTS)
Phase 3: conversation_messages

### Config (env vars)
Phase 1: ANTHROPIC_API_KEY, POSTGRES_*, REDIS_*
Phase 2: VOYAGE_API_KEY, MEMORY_COMPACTION_INTERVAL_SECONDS(60), MEMORY_WARM_BUDGET_TOKENS(100000), MEMORY_GRAPH_CACHE_MAX_NODES(500), MEMORY_EMBEDDING_DIMENSION(1024), MEMORY_ANCHOR_RE_EVALUATION_INTERVAL_HOURS(6)
Phase 3: TELEGRAM_BOT_TOKEN, COMM_BATCH_INTERVAL_SECONDS(30), COMM_MAX_BATCH_SIZE(10), COMM_CONTEXT_WINDOW_SIZE(20), COMM_MEDIA_DIR, COMM_WEBHOOK_ENABLED(False), COMM_WEBHOOK_HOST/PORT/PATH/URL/SECRET

---

## Phase 2 Code Review — ALL RESOLVED

14 findings from final code review, all fixed in commit `93cf966`:

### Critical (2/2 fixed):
1. ~~relevance_score le=10.0~~ — ✅ Changed to le=1.0 + cap calculate_relevance at min(1.0, ...)
2. ~~decay_weights fragile string parsing~~ — ✅ Added try/except for ValueError/IndexError

### Should-Fix (6/6 fixed):
3. ~~metrics window_start/end both now()~~ — ✅ window_start = now - timedelta(hours=window_hours)
4. ~~compare() sync vs spec async~~ — ✅ Made async
5. ~~shortest_path outbound-only~~ — ✅ Now uses "both" direction
6. ~~backup_to_cold unclear serialization~~ — ✅ Clarifying docstring
7. ~~p95/p99 index overflow~~ — ✅ min(int(n*0.95), n-1)
8. ~~Missing GraphHealthStatus model~~ — ✅ Added alias for GraphStats

### Nice-to-Have (1/6 fixed):
9. ~~merge_nodes self-loops~~ — ✅ DELETE self-loops after merge

---

## Phase 3 Code Review — Key Fixes Applied

4 findings fixed from final code review (commit `895b45f`):

### Critical (2/2 fixed):
1. ~~Unbounded retry recursion in send()~~ — ✅ Added `_retries` counter with max 3
2. ~~Webhook URL built from bind address 0.0.0.0~~ — ✅ Added explicit `webhook_url` parameter

### Should-Fix (2/2 fixed):
3. ~~No periodic flush for batched SILENT messages~~ — ✅ Added `_periodic_flush()` asyncio task
4. ~~Injection warning in user prompt (attackable)~~ — ✅ Moved to system prompt

### Deferred to Phase 4+:
- S2: Callback missing option text + edit_message
- S3: scan_result not persisted to DB
- S4: CommunicationState enum for connection lifecycle
- S6: _get_task_goal DB coupling in CommunicatorAgent

---

## Phase Roadmap

| Phase | Name | Status | Next Action |
|-------|------|--------|-------------|
| 1 | Core Foundation | ✅ Complete + Merged | All 12 review findings fixed |
| 2 | Memory System | ✅ Complete + Merged | All 14 review findings addressed |
| 3 | Communication Layer | ✅ Complete + Merged | 247 tests, 7 modules, 4 review fixes |
| 4 | Command Chain | Not started | Brainstorm → write plan → implement |
| 5 | Quality Gate | Not started | Depends on Phase 4 |
| 6 | Tool Arsenal | Not started | Depends on Phase 4 |
| 7 | Evolution System | Not started | Depends on all above |

**Post-build:** Anti-degradation strategy (Venu has ideas, wants system built first)

---

## Architecture Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Architecture | Modular Monolith | Clean boundaries + subprocess isolation |
| AI Provider | Anthropic only | Claude Opus for reasoning, quality focus |
| Supervisor | Distributed 5-agent leadership | Avoids single-supervisor bottleneck |
| Communication | Mirror mode (Telegram + WhatsApp) | Same conversation on both platforms |
| Memory | Three-tier (Hot/Warm/Cold) | Context anchors never dropped |
| Embeddings | Voyage AI (voyage-3, 1024-dim) | High quality, cost-effective |
| Tool protocol | MCP | Standardized, hot-pluggable, auditable |
| Self-evolution | Full autonomy | Scout→Evaluate→Sandbox→Audit→Canary→Promote |
| Package manager | uv | Fast, modern Python |
| Database | PostgreSQL + pgvector | Relational + vector + FTS in one |

---

## Development Workflow

- **Skills:** superpowers:brainstorming → writing-plans → subagent-driven-development
- **Git:** Worktrees for isolation, one commit per task, conventional commits
- **TDD:** Tests first, verify fail, implement, verify pass, commit
- **Review:** Spec compliance + code quality after each task, final full review after all tasks
- **Permissions:** All tools allowed globally
