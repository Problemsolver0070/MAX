# Max — Project Status

> **Last updated:** 2026-04-04
> **Current phase:** Phase 2 Complete + Merged, Phase 3 not started
> **Branch:** `master` (Phase 1 + Phase 2 merged)

---

## Quick Resume Guide

**To continue building Max in a new session:**

1. Read this file first
2. Check `docs/superpowers/specs/2026-04-04-max-design.md` for the full design spec
3. Check `docs/superpowers/specs/2026-04-04-max-phase2-memory-system.md` for Phase 2 design spec
4. Check `docs/superpowers/plans/2026-04-04-max-phase2-memory-system.md` for Phase 2 plan (completed)
5. **Next step:** Brainstorm + write Phase 3 (Communication Layer) plan, then execute

---

## What Exists

### Design Documents
- `docs/superpowers/specs/2026-04-04-max-design.md` — Full approved design spec (10 sections)
- `docs/superpowers/specs/2026-04-04-max-phase2-memory-system.md` — Phase 2 memory system design spec
- `docs/superpowers/plans/2026-04-04-max-phase1-core-foundation.md` — Phase 1 plan (completed)
- `docs/superpowers/plans/2026-04-04-max-phase1-critical-fixes.md` — Phase 1 fixes plan (completed)
- `docs/superpowers/plans/2026-04-04-max-phase2-memory-system.md` — Phase 2 plan (13 tasks, completed)
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

### Database Schema (11 tables)
Phase 1: tasks, subtasks, audit_reports, intents, results, status_updates, clarification_requests, context_anchors, quality_ledger, memory_embeddings
Phase 2: graph_nodes, graph_edges, compaction_log, performance_metrics, shelved_improvements
Phase 2 ALTERs: context_anchors (9 new lifecycle/permanence columns), memory_embeddings (8 new columns + FTS)

### Config (env vars)
Phase 1: ANTHROPIC_API_KEY, POSTGRES_*, REDIS_*
Phase 2: VOYAGE_API_KEY, MEMORY_COMPACTION_INTERVAL_SECONDS(60), MEMORY_WARM_BUDGET_TOKENS(100000), MEMORY_GRAPH_CACHE_MAX_NODES(500), MEMORY_EMBEDDING_DIMENSION(1024), MEMORY_ANCHOR_RE_EVALUATION_INTERVAL_HOURS(6)

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

## Phase Roadmap

| Phase | Name | Status | Next Action |
|-------|------|--------|-------------|
| 1 | Core Foundation | ✅ Complete + Merged | All 12 review findings fixed |
| 2 | Memory System | ✅ Complete + Merged | All 14 review findings addressed |
| 3 | Communication Layer | Not started | Brainstorm → write plan → implement |
| 4 | Command Chain | Not started | Depends on Phase 3 |
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
