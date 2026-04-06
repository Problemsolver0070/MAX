# MAX

**A self-evolving autonomous AI agent system that thinks, plans, executes, audits its own work, and continuously improves itself — without human intervention.**

MAX is a production-grade multi-agent orchestration platform built on Claude. It accepts natural language requests, decomposes them into phased execution plans, runs them through a command chain of specialized agents, quality-audits every output through a blind audit protocol, and evolves its own prompts, tools, and strategies through a sentinel-guarded evolution pipeline.

Built by **Venu Kumar**.

---

## What Makes MAX Different

Most AI agent systems are glorified prompt chains. MAX is an autonomous system designed to run 24/7, improve itself over time, and never degrade in quality. Here's what sets it apart:

**Self-Evolution with Safety Rails** — MAX doesn't just execute tasks. It analyzes its own performance, proposes improvements to its prompts and tool configurations, tests those changes against 24 fixed benchmarks, and only promotes changes that pass regression testing. If quality starts dropping, evolution automatically freezes.

**Blind Quality Auditing** — Every piece of work MAX produces goes through an independent audit. The auditor never sees the worker's reasoning or confidence scores — only the raw output against the original goal. This eliminates confirmation bias and catches issues that self-review misses.

**Durable Event-Driven Architecture** — All inter-agent communication flows through Redis Streams with consumer groups, acknowledgments, and dead-letter queues. If MAX crashes mid-task, orphaned work is automatically recovered on restart. Nothing is lost.

**Memory That Doesn't Forget** — A hybrid retrieval system combining knowledge graphs, semantic search (pgvector), and full-text search, merged via Reciprocal Rank Fusion. Memory compaction uses continuous relevance scoring with four tiers — content is never deleted, only progressively summarized.

**80 Native Tools** — From code analysis and git operations to AWS management, browser automation, database queries, email, calendar, web scraping, and infrastructure management. Plus MCP server support and auto-generated tools from any OpenAPI spec.

---

## Architecture Overview

```
                        User (Telegram / REST API / Webhook)
                                      |
                                      v
                    +-----------------+-----------------+
                    |          FastAPI Gateway           |
                    |   Auth | Rate Limit | Health      |
                    +-----------------+-----------------+
                                      |
                    +-----------------v-----------------+
                    |        Communicator Agent          |
                    |  Injection scanning, intent parse  |
                    +-----------------+-----------------+
                                      |
                          intents.new (Redis Streams)
                                      |
          +---------------------------v---------------------------+
          |                  Coordinator Agent                     |
          |  Intent classification, task lifecycle, state mgmt    |
          +--+------------------+------------------+--------------+
             |                  |                  |
        tasks.plan        tasks.cancel      status_updates
             |
    +--------v--------+
    |  Planner Agent   |
    |  Goal decompose  |
    |  Phased subtasks |
    +--------+--------+
             |
        tasks.execute
             |
    +--------v-----------+
    | Orchestrator Agent  |     +-------------------+
    | Phase execution     |---->|  Worker Agent(s)   |
    | Retry logic         |     |  LLM + Tools       |
    | Audit orchestration |     +-------------------+
    +--------+-----------+
             |
        audit.request
             |
    +--------v-------------------+
    |  Quality Director Agent     |     +-------------------+
    |  Spawns blind auditors      |---->|  Auditor Agent(s)  |
    |  Rule extraction on fail    |     |  Independent eval  |
    |  Pattern capture on success |     +-------------------+
    +--------+-------------------+
             |
    +--------v---------+       +------------------------+
    | Evolution Director |<---->|   Sentinel System       |
    | Propose, test,     |      |  24 benchmarks          |
    | promote or rollback|      |  Baseline vs candidate  |
    +--------------------+      |  Regression detection   |
                                +------------------------+
```

**7 Phases + Sentinel**, built incrementally:

| Phase | Module | What It Does |
|-------|--------|-------------|
| 1 | Core Foundation | Database, Redis, LLM client, base agent, configuration |
| 2 | Memory System | Knowledge graph, embeddings, compaction, hybrid retrieval, context packaging |
| 3 | Communication | Telegram adapter, message router, injection scanning, command handling |
| 4 | Command Chain | Coordinator, planner, orchestrator, worker, task store |
| 5 | Quality Gate | Blind audit protocol, quality rules, pattern learning |
| 6 | Tool System | 80 native tools, MCP provider, OpenAPI provider, 3-layer architecture |
| 7 | Evolution | Self-model, scouts, canary testing, snapshot/rollback, preference learning |
| S | Sentinel | 24 benchmarks, regression detection, anti-degradation guard |

Plus three Go-Live plans: Infrastructure Hardening (circuit breaker, Redis Streams, scheduler), API & Composition Root (FastAPI, auth, rate limiting, graceful shutdown), and Docker & Azure Deployment.

---

## Key Design Decisions

### Why Blind Auditing?
When an auditor can see the worker's reasoning ("I'm 95% confident because..."), it anchors to that confidence and finds fewer issues. MAX's auditor receives only the goal, the description, the raw output, and quality rules. Nothing else. This is the single most important quality mechanism in the system.

### Why Event-Driven?
Agents never call each other directly. Every interaction goes through the message bus. This means:
- Agents can be tested in isolation
- The system can be split into microservices later by just deploying agents as separate processes pointed at the same Redis
- Adding a new agent is just subscribing to channels — zero changes to existing agents

### Why No DI Framework?
The composition root (`app.py`) manually wires ~50 dependencies through constructor injection. At this scale, a DI framework adds complexity without benefit. Every dependency is explicit, traceable, and debuggable.

### Why Sentinel-Guarded Evolution?
Self-improving systems can degrade catastrophically if improvements aren't validated. MAX runs 24 fixed benchmarks before and after every proposed change. Both per-test-case AND per-capability-aggregate regressions must pass. If quality drops for two consecutive checks, evolution automatically freezes.

### Why "No Hard Cuts" in Memory?
Deleting old memories is irreversible. MAX uses four compaction tiers (full -> summarized -> pointer -> cold_only) so information is progressively compressed but never lost. Context anchors get a 10x relevance boost, ensuring important context always surfaces.

---

## Running MAX

### Prerequisites

- Python 3.12+
- PostgreSQL 17 with pgvector extension
- Redis 7+
- Anthropic API key (Claude access)

### Local Development (Docker)

```bash
# Clone the repository
git clone https://github.com/<your-username>/MAX.git
cd MAX

# Create your environment file
cp .env.example .env
# Edit .env — at minimum set ANTHROPIC_API_KEY and POSTGRES_PASSWORD

# Start everything
docker compose up
```

MAX will be available at `http://localhost:8080`. API docs at `http://localhost:8080/docs`.

### Without Docker

```bash
# Install dependencies
pip install uv
uv sync

# Start PostgreSQL and Redis (must be running)
# Initialize the database schema
python scripts/init_db.py

# Run MAX
python -m max
```

### Azure Deployment

```bash
# Provision Azure infrastructure (one-time)
./scripts/azure-provision.sh

# Add secrets to Key Vault
az keyvault secret set --vault-name max-kv --name anthropic-api-key --value <your-key>
az keyvault secret set --vault-name max-kv --name telegram-bot-token --value <your-token>
az keyvault secret set --vault-name max-kv --name max-api-keys --value <comma-separated-keys>

# Build and deploy
./scripts/deploy.sh
```

---

## API

All endpoints except `/health` and `/ready` require `Authorization: Bearer <api-key>`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Liveness — agent status, infrastructure status, uptime |
| GET | `/ready` | Readiness — DB + Redis connectivity check |
| POST | `/api/v1/messages` | Send a message to MAX |
| GET | `/api/v1/messages` | Poll for responses |
| POST | `/api/v1/messages/webhook` | Register webhook for push delivery |
| POST | `/webhook/telegram` | Telegram webhook receiver |
| GET | `/api/v1/tasks` | List active tasks |
| GET | `/api/v1/tasks/{id}` | Task detail with subtasks |
| GET | `/api/v1/evolution` | Evolution state and proposals |
| GET | `/api/v1/sentinel` | Sentinel scores and verdicts |
| GET | `/api/v1/dead-letters` | Dead-lettered messages |
| POST | `/api/v1/admin/evolution/freeze` | Freeze evolution |
| POST | `/api/v1/admin/evolution/unfreeze` | Unfreeze evolution |
| POST | `/api/v1/admin/sentinel/run` | Trigger sentinel run |

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12 |
| LLM | Claude (Opus 4.6 / Sonnet 4.6) via Anthropic API |
| Web Framework | FastAPI + Uvicorn |
| Database | PostgreSQL 17 + pgvector |
| Cache & Bus | Redis 7 (Streams + pub/sub) |
| Embeddings | Voyage AI (voyage-3, 1024 dimensions) |
| Telegram | aiogram 3 |
| Rate Limiting | slowapi |
| Observability | OpenTelemetry + structured JSON logging |
| Containerization | Docker (multi-stage, uv) |
| Cloud | Azure (Container Apps, ACR, Key Vault, Flexible Server, Redis Cache) |
| Testing | pytest + pytest-asyncio (1500+ tests) |
| Linting | ruff |

---

## Project Stats

- **111 source files** across 15 modules
- **36 database tables** with pgvector indexes
- **80 native tools** across 15 categories
- **24 sentinel benchmarks** across 7 capability dimensions
- **26 message bus channels**
- **6 persistent agents** + 4 ephemeral agent types
- **1500+ tests** with comprehensive coverage
- **~80 configuration settings** fully documented

---

## License

This project is proprietary. All rights reserved.

---

*Built with an obsession for quality and a refusal to compromise.*
