# MAX

A multi-agent system that decomposes natural-language requests into phased plans, executes them with worker agents and tools, and runs quality audits on every output. Designed to run continuously, recover from interruption, and improve through controlled self-modification.

Built by Venu Kumar.

## Architecture

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

The system is organized into eight modules:

| Module | Responsibility |
|--------|----------------|
| Core | Database, Redis, LLM client, base agent, settings |
| Memory | Knowledge graph, embeddings, compaction, hybrid retrieval, context packaging |
| Communication | Telegram adapter, message router, injection scanning, command handling |
| Command Chain | Coordinator, planner, orchestrator, worker, task store |
| Quality Gate | Blind audit protocol, quality rules, pattern learning |
| Tools | Native tools, MCP provider, OpenAPI provider |
| Evolution | Self-model, scouts, canary testing, snapshot/rollback, preference learning |
| Sentinel | Benchmark-driven regression detection, anti-degradation guard |

Plus three deployment plans: infrastructure hardening (circuit breaker, Redis Streams, scheduler), API and composition root (FastAPI, auth, rate limiting, graceful shutdown), and Docker + Azure deployment.

## Key design decisions

### Blind auditing
When an auditor sees the worker's reasoning ("I'm 95% confident because..."), it anchors to that confidence and finds fewer issues. The auditor in MAX receives only the goal, the description, the raw output, and quality rules. Nothing else. This is the most important quality mechanism in the system.

### Event-driven
Agents never call each other directly. Every interaction goes through the message bus. Agents can be tested in isolation, deployed as separate processes against the same Redis, and added without changing existing agents.

### No DI framework
The composition root (`app.py`) manually wires roughly 50 dependencies through constructor injection. At this scale a DI framework adds complexity without benefit. Every dependency is explicit and traceable.

### Sentinel-guarded evolution
Self-improving systems can degrade catastrophically if changes aren't validated. MAX runs 24 fixed benchmarks before and after every proposed change. Per-test-case and per-capability regressions both must pass. If quality drops for two consecutive checks, evolution freezes automatically.

### No hard cuts in memory
Deleting old memories is irreversible. MAX uses four compaction tiers (full → summarized → pointer → cold_only) so information is progressively compressed but never lost. Context anchors get a 10x relevance boost.

## Running it

### Prerequisites

- Python 3.12+
- PostgreSQL 17 with pgvector extension
- Redis 7+
- Anthropic API key

### Local development (Docker)

```bash
git clone https://github.com/<your-username>/MAX.git
cd MAX

cp .env.example .env
# Edit .env, set ANTHROPIC_API_KEY and POSTGRES_PASSWORD

docker compose up
```

API at `http://localhost:8080`. Docs at `http://localhost:8080/docs`.

### Without Docker

```bash
pip install uv
uv sync

python scripts/init_db.py
python -m max
```

### Azure deployment

```bash
./scripts/azure-provision.sh

az keyvault secret set --vault-name max-kv --name anthropic-api-key --value <your-key>
az keyvault secret set --vault-name max-kv --name telegram-bot-token --value <your-token>
az keyvault secret set --vault-name max-kv --name max-api-keys --value <comma-separated-keys>

./scripts/deploy.sh
```

## API

All endpoints except `/health` and `/ready` require `Authorization: Bearer <api-key>`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Liveness: agent status, infrastructure status, uptime |
| GET | `/ready` | Readiness: DB and Redis connectivity check |
| POST | `/api/v1/messages` | Send a message |
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
| POST | `/api/v1/admin/sentinel/run` | Trigger a sentinel run |

## Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.12 |
| LLM provider | Anthropic Claude (Opus 4.6 / Sonnet 4.6) |
| Web framework | FastAPI + Uvicorn |
| Database | PostgreSQL 17 + pgvector |
| Cache and bus | Redis 7 (Streams + pub/sub) |
| Embeddings | Voyage AI (voyage-3, 1024 dimensions) |
| Telegram | aiogram 3 |
| Rate limiting | slowapi |
| Observability | OpenTelemetry + structured JSON logging |
| Containerization | Docker, uv-based multi-stage build |
| Cloud | Azure (Container Apps, ACR, Key Vault, Flexible Server, Redis Cache) |
| Testing | pytest + pytest-asyncio |
| Linting | ruff |

## Stats

- 111 source files across 15 modules
- 36 database tables with pgvector indexes
- 80 native tools across 15 categories
- 24 sentinel benchmarks across 7 capability dimensions
- 26 message bus channels
- 6 persistent agents and 4 ephemeral agent types
- ~80 configuration settings
- 1500+ tests

## License

Proprietary. All rights reserved.
