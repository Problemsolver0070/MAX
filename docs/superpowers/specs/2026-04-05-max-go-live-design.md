# Max Go-Live: Production Deployment Design

## 1. Purpose

Take Max from tested modules to a running, deployable product on Azure. This design covers the composition root that wires all 7 phases + Sentinel together, the REST API layer, durable messaging, scheduling, containerization, Azure infrastructure, observability, and reliability features. Every decision is made with Max's future as a multi-user product/SaaS in mind — no single-user shortcuts.

## 2. Architecture Overview

**Approach:** Monolith-first. One container runs all agents, the API, Telegram adapter, and schedulers inside a single async event loop. The MessageBus uses Redis Streams (durable, with consumer groups), so splitting into microservices later requires zero application code changes — just deploy agents into separate processes pointed at the same Redis.

```
┌──────────────────────────────────────────────────────────┐
│                    Azure API Management                   │
│          (auth, rate limiting, routing, logging)          │
└──────────────────────┬───────────────────────────────────┘
                       │ HTTPS
┌──────────────────────▼───────────────────────────────────┐
│              Max Container (Azure Container Apps)         │
│                                                          │
│  Composition Root (src/max/app.py)                       │
│  ├── FastAPI (health + REST API + Telegram webhook)      │
│  ├── Auth Middleware (API key → JWT/OAuth later)          │
│  ├── Rate Limiting Middleware (slowapi)                   │
│  ├── All Agents (bus subscribers via Redis Streams)       │
│  ├── Scheduler (DB-backed, survives restarts)            │
│  ├── Circuit Breaker (LLM client)                        │
│  ├── OpenTelemetry (metrics → Azure Monitor)             │
│  └── Graceful Shutdown (signal handlers, drain timeouts) │
│                                                          │
│  Connects to:                                            │
│  ├── Azure Database for PostgreSQL (pgvector)            │
│  ├── Azure Cache for Redis (Streams + pub/sub)           │
│  ├── Azure Key Vault (secrets)                           │
│  └── Anthropic API (Claude)                              │
└──────────────────────────────────────────────────────────┘
```

## 3. Composition Root & Application Lifecycle

**File:** `src/max/app.py`

**`create_app()` async function — the single wiring point:**

1. Load `Settings` from environment variables / Azure Key Vault
2. Infrastructure layer:
   - `Database` → `connect()` → `init_schema()` (idempotent, runs every boot)
   - Redis client → `WarmMemory` → `MessageBus` (Redis Streams transport)
   - `LLMClient` (with circuit breaker wrapping)
3. Store layer:
   - `TaskStore`, `QualityStore`, `EvolutionStore`, `SentinelStore`, `CoordinatorStateManager`
4. Agent layer:
   - `ToolRegistry` → `ToolExecutor` → `InProcessRunner`
   - `CoordinatorAgent`, `PlannerAgent`, `OrchestratorAgent`
   - `QualityDirectorAgent`, `AuditorAgent`
   - `EvolutionDirectorAgent` (scouts, improver, canary, snapshot, self-model, preference profile)
   - `SentinelScorer` → `SentinelAgent`
   - `CommunicatorAgent` → `TelegramAdapter` → `MessageRouter`
5. Call `start()` on every agent (subscribes to bus channels)
6. Seed Sentinel benchmarks
7. Recover orphaned in-flight tasks from previous run
8. Start scheduler
9. Start FastAPI server (uvicorn, serves all endpoints)

**Entry point:** `src/max/__main__.py`
- `asyncio.run(main())` which calls `create_app()` and starts uvicorn
- Runnable as `python -m max` or `max` CLI command (via pyproject.toml `[project.scripts]`)
- Registers SIGINT/SIGTERM handlers for graceful shutdown

**No DI framework.** Manual constructor injection. Every class already takes dependencies as constructor params. A DI framework adds complexity with no benefit at this scale.

## 4. REST API Layer

**Framework:** FastAPI (async-native, automatic OpenAPI docs at `/docs`)

### 4.1 Authentication

- Every endpoint except `/health` and `/ready` requires authentication
- **Phase 1 (now):** API key auth via `Authorization: Bearer <key>` header. Keys stored in Azure Key Vault, validated by FastAPI middleware. Configurable per-key.
- **Phase 2 (product):** JWT/OAuth2 — middleware changes, endpoints don't. `user_id` extracted from token replaces the one from API key lookup.
- Telegram webhook verified via `X-Telegram-Bot-Api-Secret-Token` header (Telegram's built-in mechanism)

### 4.2 Rate Limiting

- `slowapi` middleware (built on `limits` library)
- Per-key rate limits, configurable via settings (default: 60 req/min API, 30 msg/min messaging)
- Returns `429 Too Many Requests` with `Retry-After` header

### 4.3 Endpoints

```
Health & Operations (no auth — required by Azure Container Apps liveness/readiness probes):
  GET  /health                         → Agent status, infrastructure status, uptime
  GET  /ready                          → Checks DB + Redis + bus connectivity
  Note: These are only accessible on the internal Container Apps port,
        NOT exposed through API Management to the public internet.

Messaging (authenticated):
  POST /api/v1/messages                → Send a message to Max
                                         Body: { "text": "...", "user_id": "..." }
                                         Returns: { "message_id": "...", "status": "accepted" }
  GET  /api/v1/messages                → Poll for responses
  POST /api/v1/messages/webhook        → Register a webhook URL for push delivery

Telegram (webhook-verified):
  POST /webhook/telegram               → Telegram sends updates here

Introspection (authenticated):
  GET  /api/v1/tasks                   → List active tasks
  GET  /api/v1/tasks/{id}              → Task detail with full history
  GET  /api/v1/evolution               → Evolution state (frozen?, last promotion)
  GET  /api/v1/sentinel                → Latest sentinel scores and verdicts
  GET  /api/v1/dead-letters            → Failed messages from dead letter queue

Admin (authenticated):
  POST /api/v1/admin/evolution/freeze     → Manual evolution freeze
  POST /api/v1/admin/evolution/unfreeze   → Manual evolution unfreeze
  POST /api/v1/admin/sentinel/run         → Trigger sentinel run manually
```

### 4.4 Design Principles

- All endpoints are async, sharing the event loop with agents
- `/api/v1/messages` feeds into the same bus channel (`intents.new`) as Telegram — agents are channel-agnostic
- API is versioned (`/api/v1/`) from day one to avoid breaking clients later
- FastAPI auto-generates OpenAPI docs at `/docs`

## 5. Scheduler

**Problem:** asyncio sleep loops don't survive restarts. Timers reset on reboot.

**Solution:** Database-backed schedule tracking.

### 5.1 Schema

```sql
CREATE TABLE IF NOT EXISTS scheduler_state (
    job_name         TEXT PRIMARY KEY,
    last_run_at      TIMESTAMPTZ,
    next_run_at      TIMESTAMPTZ,
    interval_seconds INTEGER NOT NULL
);
```

### 5.2 Behavior

1. On startup, load all jobs from `scheduler_state`
2. For each job: if `next_run_at` is in the past, fire immediately (catch-up), then update `next_run_at`
3. If `next_run_at` is in the future, sleep until then
4. After every execution, update `last_run_at` and `next_run_at` in the database
5. If Max was down for 2 hours, it catches up on missed scheduled work immediately on boot

### 5.3 Jobs

| Job | Default Interval | Action |
|-----|-----------------|--------|
| `evolution_trigger` | 6h | `bus.publish("evolution.trigger", ...)` |
| `sentinel_monitor` | 12h | `SentinelAgent.run_scheduled_monitoring()` |
| `memory_compaction` | 60s | `WarmMemory.compact()` |
| `anchor_re_evaluation` | 6h | `bus.publish("anchors.re_evaluate", ...)` |

### 5.4 Lifecycle

`Scheduler` class with `start()` / `stop()` methods, same pattern as agents. Started after all agents are subscribed, stopped before agents during shutdown.

## 6. Dockerfile & Local Docker Compose

### 6.1 Dockerfile

Multi-stage build in project root:

- **Stage 1 (builder):** Python 3.12, install uv, copy `pyproject.toml` + `uv.lock`, install all dependencies
- **Stage 2 (runtime):** Python 3.12-slim, copy installed packages + `src/max/` source
- Entry: `python -m max`
- Health: `HEALTHCHECK CMD curl -f http://localhost:8080/health || exit 1`
- Non-root user: `appuser`
- Port: 8080

### 6.2 docker-compose.yml (updated)

```yaml
services:
  max:
    build: .
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
    env_file: .env
    ports: ["8080:8080"]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped

  postgres:   # existing, unchanged
    image: pgvector/pgvector:pg17
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U max"]

  redis:      # existing, unchanged
    image: redis:7-alpine
    volumes: [redisdata:/data]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]

volumes:
  pgdata:
  redisdata:
```

### 6.3 Purpose

The same Dockerfile runs locally via `docker compose up` (dev) and on Azure via Container Apps (production). Only difference is where Postgres and Redis live — local containers vs Azure managed services.

## 7. Azure Infrastructure

### 7.1 Resources

| Resource | Azure Service | Config |
|----------|--------------|--------|
| API Gateway | Azure API Management (Consumption tier) | Auth policy, rate limiting, request logging, future multi-tenant routing |
| Container registry | Azure Container Registry (Basic) | Stores Max Docker images |
| Application | Azure Container Apps | Min 1 / max 10 replicas, scaling on HTTP concurrency + CPU |
| Container Environment | Container Apps Environment | VNet-integrated, Log Analytics connected |
| Database | Azure Database for PostgreSQL Flexible Server | Burstable B1ms (1 vCPU, 2GB), pgvector extension, PgBouncer enabled |
| Cache | Azure Cache for Redis | Basic C0 (250MB), Streams support |
| Secrets | Azure Key Vault | API keys, DB password, bot tokens, Anthropic key |
| Logging | Log Analytics Workspace | All services stream logs here |
| Monitoring | Azure Monitor + alert rules | CPU, memory, error rate, response time alerts |

### 7.2 Networking

- Azure API Management is the public entry point (HTTPS)
- Container Apps, PostgreSQL, and Redis communicate on a private VNet
- No public access to database or cache
- Container Apps gets an internal ingress URL that API Management routes to

### 7.3 Provisioning

`scripts/azure-provision.sh` — Azure CLI commands. One-time setup, documented and idempotent. Terraform comes when Max needs staging + production environments.

### 7.4 Deployment

`scripts/deploy.sh`:
```bash
docker build -t max:latest .
az acr login --name <registry>
docker tag max:latest <registry>.azurecr.io/max:latest
docker push <registry>.azurecr.io/max:latest
az containerapp update --name max --image <registry>.azurecr.io/max:latest
```

### 7.5 Cost Estimate

~$50-65/month: API Management Consumption ~$3-5, PostgreSQL B1ms ~$15, Redis Basic ~$8, Container Apps ~$10-20, ACR ~$5, Monitor ~$5-10.

## 8. Logging, Metrics & Observability

### 8.1 Structured Logging

- JSON format for all log output
- Every log line includes: `timestamp`, `level`, `module`, `message`, `correlation_id`
- Correlation ID assigned when a message enters Max (via API or Telegram), propagated through the entire agent chain via bus message metadata
- Log level controlled by `max_log_level` setting (default: DEBUG)
- Azure Log Analytics ingests and indexes JSON logs natively

### 8.2 Metrics (OpenTelemetry)

OpenTelemetry SDK integrated, exporting to Azure Monitor.

| Metric | Type | Description |
|--------|------|-------------|
| `max.messages.received` | Counter | Inbound messages by channel (telegram/api) |
| `max.messages.processed` | Counter | Messages that completed the full agent chain |
| `max.messages.failed` | Counter | Messages that ended in error |
| `max.message.duration_seconds` | Histogram | End-to-end latency from receive to response |
| `max.agent.invocations` | Counter | Per-agent invocation count |
| `max.agent.errors` | Counter | Per-agent error count |
| `max.llm.requests` | Counter | Anthropic API calls by model |
| `max.llm.tokens` | Counter | Token usage (input/output) by model |
| `max.llm.latency_seconds` | Histogram | Anthropic API response time |
| `max.llm.circuit_breaker.state` | Gauge | 0=closed, 1=open, 2=half-open |
| `max.bus.messages.published` | Counter | Bus messages by channel |
| `max.bus.messages.dead_lettered` | Counter | Messages sent to dead letter |
| `max.tasks.active` | Gauge | Currently in-flight tasks |
| `max.sentinel.score` | Gauge | Latest sentinel score by capability |
| `max.evolution.experiments` | Counter | Experiments by outcome (promoted/rolled_back) |

### 8.3 Health Endpoint

```json
GET /health
{
  "status": "ok",
  "uptime_seconds": 3421,
  "agents": {
    "coordinator": "running",
    "planner": "running",
    "orchestrator": "running",
    "quality_director": "running",
    "evolution_director": "running",
    "sentinel": "running",
    "communicator": "running"
  },
  "infrastructure": {
    "database": "connected",
    "redis": "connected",
    "bus": "listening",
    "circuit_breaker": "closed"
  }
}
```

### 8.4 Azure Monitor Alerts

- Container restart count > 3 in 5 minutes
- Error rate > 5% over 5 minutes
- P95 response time > 30 seconds
- LLM circuit breaker OPEN for > 2 minutes
- Dead letter count increasing

## 9. Reliability & Error Recovery

### 9.1 Durable Message Bus (Redis Streams)

Replace Redis pub/sub with Redis Streams. The `MessageBus` interface (`publish()`, `subscribe()`) stays identical; only the transport changes.

| Feature | Pub/Sub (current) | Streams (revised) |
|---------|-------------------|-------------------|
| Persistence | None | Stored until acknowledged |
| Consumer groups | No | Yes — multiple consumers, load balancing |
| Acknowledgment | No | Yes — done only after handler succeeds |
| Retry on failure | No | Yes — unacknowledged messages re-delivered |
| Message history | No | Yes — queryable per channel |
| Dead letter | No | Yes — after max retries |

**Dead letter handling:**
- After 3 failed delivery attempts, message moves to `dead_letter:{channel}` stream
- Visible via `GET /api/v1/dead-letters`
- Includes: original message, error trace, failure count, timestamps
- Admin can retry or discard via API

### 9.2 Circuit Breaker (LLM Client)

```
CLOSED   → Normal operation. Track consecutive failure count.
OPEN     → After 5 consecutive failures, stop calling Anthropic.
            Return immediate error. Auto-transition to HALF_OPEN after 60s cooldown.
HALF_OPEN → Allow one test request.
            Success → CLOSED (reset failure count).
            Failure → OPEN (reset cooldown).
```

Exposed via `max.llm.circuit_breaker.state` metric and `/health` endpoint.

### 9.3 Task Durability

- Tasks persist in database via `TaskStore` (already implemented)
- On startup, composition root queries for tasks with status `in_progress` (orphaned from previous run)
- Re-publishes orphaned tasks to the appropriate bus channel based on current stage:
  - `planned` → `tasks.execute`
  - `executing` → `tasks.execute` (worker retries)
  - `auditing` → `audit.request`
- **Timeout watchdog:** Background task checks every 60s for tasks stuck in `in_progress` longer than `worker_timeout_seconds`. Timed-out tasks get re-queued or marked failed with a reason.

### 9.4 Graceful Shutdown

On SIGINT/SIGTERM:

1. Stop accepting new HTTP requests (FastAPI shutdown event)
2. Stop scheduler (no new triggers)
3. Wait for in-flight HTTP requests to complete (30s timeout)
4. Stop agents in reverse dependency order:
   - SentinelAgent, EvolutionDirectorAgent
   - QualityDirectorAgent
   - OrchestratorAgent, PlannerAgent
   - CoordinatorAgent
   - MessageRouter (Telegram + Communicator)
5. Wait for bus consumers to finish current messages (10s timeout)
6. Close MessageBus (stops stream consumers)
7. Close Database connection pool (waits for active queries)
8. Close LLMClient
9. Flush OpenTelemetry metrics
10. Exit

In-flight tasks that don't finish within drain timeouts remain in the database and get recovered on next startup (9.3).

## 10. Configuration Additions

New settings added to `src/max/config.py`:

```python
# API Server
max_host: str = "0.0.0.0"
max_port: int = 8080
max_api_keys: str = ""  # comma-separated valid API keys

# Rate Limiting
rate_limit_api: str = "60/minute"
rate_limit_messaging: str = "30/minute"

# Circuit Breaker
llm_circuit_breaker_threshold: int = 5
llm_circuit_breaker_cooldown_seconds: int = 60

# Bus Transport
bus_transport: str = "streams"  # "streams" or "pubsub" (fallback)
bus_dead_letter_max_retries: int = 3
bus_stream_max_len: int = 10000  # max messages per stream before trimming

# Task Recovery
task_recovery_enabled: bool = True
task_timeout_watchdog_interval_seconds: int = 60

# Azure
azure_key_vault_url: str = ""  # if set, secrets loaded from Key Vault
```

## 11. New Files Summary

| File | Purpose |
|------|---------|
| `src/max/__main__.py` | Entry point: `python -m max` |
| `src/max/app.py` | Composition root: `create_app()`, wiring, lifecycle |
| `src/max/api/__init__.py` | API package |
| `src/max/api/router.py` | FastAPI router with all endpoints |
| `src/max/api/auth.py` | Auth middleware (API key, extensible to JWT) |
| `src/max/api/rate_limit.py` | Rate limiting middleware |
| `src/max/scheduler.py` | Database-backed scheduler |
| `src/max/bus/streams.py` | Redis Streams transport for MessageBus |
| `src/max/llm/circuit_breaker.py` | Circuit breaker for LLM client |
| `src/max/observability.py` | OpenTelemetry setup, structured logging config |
| `Dockerfile` | Multi-stage Docker build |
| `scripts/azure-provision.sh` | Azure resource provisioning |
| `scripts/deploy.sh` | Build + push + deploy to Azure |

## 12. What This Design Does NOT Cover (Future Work)

- **Multi-tenancy / user management** — tenant isolation, per-user data, billing. Comes when Max becomes a product.
- **Per-user Telegram bots** — architecture supports it (per-user bot token in config), but provisioning flow is future work.
- **WhatsApp integration** — adapter exists as placeholder, not wired.
- **Alembic migrations** — the idempotent `schema.sql` works for now. Alembic comes when schema changes need to be versioned across production deployments.
- **CI/CD pipeline** — GitHub Actions or Azure DevOps for automated build/test/deploy. Important but separate from the go-live design.
- **Horizontal scaling concerns** — the monolith handles one replica well. Multi-replica requires sticky sessions or stateless agent design. Future work when traffic demands it.
