# Max — Project Status

> **Last updated:** 2026-04-04
> **Current phase:** Phase 1 Complete, Phase 2 not started
> **Branch:** `phase1/core-foundation` (not yet merged to master)

---

## Quick Resume Guide

**To continue building Max in a new session:**

1. Read this file first
2. Check `docs/superpowers/specs/2026-04-04-max-design.md` for the full design spec
3. Check `docs/superpowers/plans/2026-04-04-max-phase1-core-foundation.md` for the Phase 1 plan (completed)
4. The Phase 1 code is on branch `phase1/core-foundation` in worktree `.worktrees/phase1-core-foundation/`
5. **Next step:** Merge Phase 1 to master, then brainstorm + write Phase 2 (Memory System) plan

---

## What Exists

### Design Documents
- `docs/superpowers/specs/2026-04-04-max-design.md` — Full approved design spec (10 sections: architecture, context management, tool system, self-evolution, communication, infrastructure, security, tech stack)
- `docs/superpowers/plans/2026-04-04-max-phase1-core-foundation.md` — Phase 1 implementation plan (12 tasks, all completed)
- `RESEARCH.md` — OpenClaw research (features, architecture, security failures, alternatives landscape)

### Phase 1 Implementation (branch: `phase1/core-foundation`)

```
src/max/
├── __init__.py               # v0.1.0
├── config.py                 # Settings class (pydantic-settings, env vars, postgres_dsn with URL encoding)
├── models/
│   ├── __init__.py           # Re-exports all models
│   ├── messages.py           # Intent, Result, ClarificationRequest, StatusUpdate, Priority
│   └── tasks.py              # Task, SubTask, AuditReport, TaskStatus, AuditVerdict
├── llm/
│   ├── __init__.py           # Re-exports LLMClient, LLMResponse, ModelType
│   ├── client.py             # Async Anthropic wrapper (complete/close, usage tracking)
│   └── models.py             # ModelType enum (OPUS/SONNET), LLMResponse
├── bus/
│   ├── __init__.py           # Re-exports MessageBus
│   └── message_bus.py        # Redis pub/sub (subscribe/unsubscribe/publish, async listener)
├── db/
│   ├── __init__.py           # Re-exports Database, WarmMemory
│   ├── postgres.py           # Async connection pool (asyncpg), query helpers, pool guard
│   ├── redis_store.py        # WarmMemory: key-value with TTL, list operations, max: prefix
│   └── schema.sql            # 6 tables: tasks, subtasks, audit_reports, context_anchors, quality_ledger, memory_embeddings
├── agents/
│   ├── __init__.py           # Re-exports BaseAgent, AgentConfig
│   └── base.py               # Abstract BaseAgent with think() → LLM, AgentConfig
└── tools/
    ├── __init__.py           # Re-exports ToolRegistry, ToolDefinition
    └── registry.py           # Register, get, list, permissions, to_anthropic_tools

tests/
├── conftest.py               # Shared fixtures (settings, db, redis_client, warm_memory, bus)
├── test_config.py            # 4 tests (env loading, defaults, DSN, special chars)
├── test_models.py            # 8 tests (all model types)
├── test_llm_client.py        # 5 tests (model IDs, creation, complete, model override, usage)
├── test_message_bus.py       # 3 tests (pub/sub, multi-channel, unsubscribe)
├── test_postgres.py          # 3 tests (ping, insert/fetch, fetchall)
├── test_redis_store.py       # 6 tests (set/get, missing key, TTL, delete, state doc, list ops)
├── test_base_agent.py        # 4 tests (creation, think, run, config defaults)
├── test_tool_registry.py     # 6 tests (register, missing, category, permissions, list_all, anthropic format)
└── test_integration.py       # 1 smoke test (full pipeline end-to-end)

docker-compose.yml            # PostgreSQL+pgvector:pg17, Redis 7-alpine
scripts/init_db.py            # Database schema initialization script
```

**40 tests passing, 96% coverage, lint clean.**

### Database Schema (6 tables)
1. `tasks` — id, goal_anchor, source_intent_id, status, quality_criteria, timestamps
2. `subtasks` — id, parent_task_id (FK→tasks), description, status, assigned_tools, context_package, result, timestamps
3. `audit_reports` — id, task_id (FK→tasks), subtask_id (FK→subtasks), verdict, score, goal_alignment, confidence, issues
4. `context_anchors` — id, content, anchor_type, source_task_id, metadata, created_at
5. `quality_ledger` — id, entry_type, content (JSONB), created_at (append-only)
6. `memory_embeddings` — id, content, embedding (vector 1536), memory_type, metadata, created_at

---

## Code Review Findings (MUST address in Phase 2)

### Critical (fix at start of Phase 2)
1. **LLM Client needs error handling** — No try/except around API calls. Add custom `LLMError`, retry with exponential backoff for rate limits and connection errors
2. **MessageBus needs multi-handler support** — Currently `dict[str, Handler]` (one per channel). Change to `dict[str, list[Handler]]` for fan-out. Both Coordinator and Quality Director need the same events
3. **Database needs transaction support** — No way to run atomic multi-query operations. Add `async with db.transaction()` context manager
4. **Missing database tables** — No `intents`, `results`, `status_updates` tables. Need them for Communicator/Coordinator. Add FK from `tasks.source_intent_id → intents.id`
5. **BaseAgent needs lifecycle hooks** — Add `on_start()`, `on_stop()`, and access to bus/db/warm_memory. Consider `AgentContext` object bundling all dependencies

### Important (weave into Phase 2 tasks)
- `WarmMemory.set` with `ttl_seconds=0` — falsy check bug. Change `if ttl_seconds:` to `if ttl_seconds is not None:`
- `BaseAgent.max_turns` not enforced — think() never checks turn count
- `ModelType` fragile dict lookup — use tuple enum values instead
- `LLMResponse.tool_calls` untyped (`list[dict]`) — create `ToolCall` model
- `SubTask.audit_report` is `dict` not `AuditReport` model
- Missing HNSW vector index on `memory_embeddings`
- Missing `QualityRule` model (referenced in plan, not implemented)

---

## Phase Roadmap

| Phase | Name | Status | Next Action |
|-------|------|--------|-------------|
| 1 | Core Foundation | ✅ Complete | Merge branch to master |
| 2 | Memory System | Not started | Brainstorm → write plan → implement |
| 3 | Communication Layer | Not started | Depends on Phase 2 |
| 4 | Command Chain | Not started | Depends on Phase 3 |
| 5 | Quality Gate | Not started | Depends on Phase 4 |
| 6 | Tool Arsenal | Not started | Depends on Phase 4 |
| 7 | Evolution System | Not started | Depends on all above |

**Post-build:** Anti-degradation strategy (Venu has ideas, wants system built first)

---

## Architecture Decisions Log

| Decision | Choice | Rationale | Alternatives Considered |
|----------|--------|-----------|------------------------|
| Architecture | Modular Monolith | Clean boundaries + subprocess isolation without microservice complexity | Microservices (too complex day 1), Pure monolith (no isolation) |
| AI Provider | Anthropic only | Quality focus, Claude Opus for reasoning, Sonnet for routing | Multi-provider (unnecessary complexity) |
| Supervisor design | Distributed 5-agent leadership | Single supervisor = bottleneck risk. Split into Coordinator, Planner, Orchestrator, Quality Director, Evolution Director | Single supervisor (Venu identified the bottleneck) |
| Communication | Mirror mode (Telegram + WhatsApp) | Same conversation on both platforms, seamlessly synced | Telegram-only, WhatsApp-only, Bridge mode |
| Memory | Three-tier (Hot/Warm/Cold) | Different access patterns need different storage. Context anchors never dropped | Single-tier (context degradation), Two-tier (missing semantic search) |
| Tool protocol | MCP | Standardized, hot-pluggable, permissioned, auditable | Custom protocol (non-standard), Direct SDK calls (not extensible) |
| Self-evolution | Full autonomy | Scout→Evaluate→Snapshot→Sandbox→Audit→Canary→Promote pipeline with rollback | Human-gated (too slow), No evolution (static) |
| Package manager | uv | Fast, modern Python package management | pip (slower), poetry (heavier) |
| Database | PostgreSQL + pgvector | Relational + vector search in one. RDS-compatible for AWS | Separate vector DB (more infra), SQLite (no vector, no concurrency) |

---

## Development Workflow

- **Skills used:** superpowers:brainstorming → superpowers:writing-plans → superpowers:subagent-driven-development
- **Git:** Worktrees for isolation (`.worktrees/`), one commit per task, conventional commits
- **TDD:** Tests first, verify fail, implement, verify pass, commit
- **Review:** Spec compliance review + code quality review after each task, final full review after all tasks
- **Permissions:** All tools allowed globally (project settings configured)
