# Max — Design Specification

**Date:** 2026-04-04
**Status:** Approved
**Author:** Venu + Claude

---

## 1. Overview

Max is a self-evolving, autonomous AI agent system that operates 24/7 as a personal powerhouse — accessible through Telegram and WhatsApp in mirror mode. It plans, delegates, executes, audits, and delivers — then improves itself based on usage.

**Core principles:**
- Quality is the only concern — no cost compromises
- Full autonomy including self-modification
- Every output is audited before delivery
- Context never degrades
- The system only gets better over time

---

## 2. Architecture: Modular Monolith

Single deployment with internally separated modules. Each agent type is an independent Python module with clean interfaces. Sub-agents run as isolated subprocesses. Internal message bus (Redis) for inter-agent communication. Can evolve into microservices later if needed.

### 2.1 Agent Hierarchy

```
You (Telegram / WhatsApp)
    ↕ mirror-synced messages
COMMUNICATOR — sole user interface, translates between natural language and structured intents
    ↕ internal message bus (Redis)
COORDINATOR — thin 24/7 router, classifies and routes, maintains State Document
    ↕ routes to directors
┌─────────────┬──────────────────┬───────────────────┬──────────────────┐
│  PLANNER    │  ORCHESTRATOR    │ QUALITY DIRECTOR  │ EVOLUTION DIR.   │
│  strategic  │  ops manager     │ standards enforcer│ growth engine    │
│  reasoning  │  agent lifecycle │ audit oversight   │ self-improvement │
└─────┬───────┴────────┬─────────┴─────────┬─────────┴────────┬─────────┘
      │                │                   │                  │
  Sub-Agents      Sub-Agents          Auditors          Scouts +
  (execution)     (parallel)          (quality gate)    Improvement Agents
```

### 2.2 Agent Roles

**Communicator** (Singleton, always-on)
- Sole interface between user and Max
- Receives messages from Telegram & WhatsApp simultaneously
- Maintains mirror sync — both platforms always show the same state
- Translates natural language ↔ structured intents
- Urgency classification — decides when to bother user vs. handle silently
- Batches non-urgent updates intelligently
- Adapts to user's communication style and mood
- Model: Claude Opus

**Coordinator** (Singleton, always-on)
- Thin routing layer — classifies, routes, tracks state
- Maintains the State Document (always-current structured state)
- Operates as a persistent state machine — each LLM call loads fresh context
- Writes state changes back before each call ends
- Model: Claude Sonnet (routing doesn't need deep reasoning)

**Planner** (On-demand)
- Deep task analysis and decomposition
- Identifies clarifying questions needed
- Determines dependencies and parallel opportunities
- Estimates resource requirements per subtask
- Crafts context packages for each sub-agent
- Model: Claude Opus

**Orchestrator** (On-demand)
- Receives execution plans from Planner
- Spawns sub-agent subprocesses with correct context and tools
- Manages agent lifecycle (start, monitor, kill)
- Handles parallel execution coordination
- Collects results and routes to Quality Director
- Re-spawns sub-agents for fixes after audit failures
- Model: Claude Sonnet

**Quality Director** (On-demand)
- Defines audit criteria per subtask before execution begins
- Spawns Auditor agents for completed work
- Collects and analyzes audit reports
- Decides: pass, fix, or escalate to user
- Tracks quality metrics over time
- Feeds quality patterns to Evolution Director
- Model: Claude Opus

**Evolution Director** (Scheduled + triggered)
- Processes all scout findings
- Evaluates improvement proposals (cost/benefit)
- Manages the self-modification pipeline
- Spawns Improvement Agents in sandbox
- Coordinates canary testing
- Manages snapshots and rollbacks
- Learns behavioral patterns from user's usage
- Model: Claude Opus

**Sub-Agents** (Ephemeral, 0-N)
- Execute a single, well-defined subtask
- Work within curated context packages
- Isolated subprocesses with whitelisted tool access
- Deliver structured output (result + metadata + execution log + confidence score)
- Accept fix instructions after audit feedback
- Self-terminate after completion or timeout
- Stateless — Coordinator holds all persistent state
- Dynamically configured by Orchestrator (not pre-defined types)
- Model: Claude Opus

**Auditors** (Ephemeral, 1 per sub-agent)
- Review output against original goal anchor and quality criteria
- NEVER modify work — only judge and report
- Separation of execution and judgment: auditors do NOT see the sub-agent's reasoning or self-assessment
- Produce structured audit reports (verdict, score, issues, goal alignment, confidence)
- Model: Claude Opus

**Scouts** (Scheduled)
- Tool Scout: daily scan of package registries, GitHub trending, AI tool directories
- Pattern Scout: triggered every 10 completed tasks — analyzes work patterns
- Quality Scout: triggered on audit failures — root-cause analysis
- Ecosystem Scout: weekly deep research into AI/agent developments
- Model: Claude Sonnet

**Improvement Agents** (Ephemeral, on-demand)
- Implement system upgrades approved by Evolution Director
- Always work in canary sandbox — never touch live system directly
- Write tests for their changes
- Get audited before promotion to live
- Model: Claude Opus

---

## 3. Context Management

### 3.1 Three-Tier Memory

**Hot — Working Memory** (in LLM context window)
- Current task + subtasks
- Active conversation thread
- Immediate tool outputs
- Current agent's instructions
- Scope: single agent session

**Warm — Session Memory** (Redis + SQLite)
- Recent task history (last 24-48h)
- Active task tree + statuses
- Recent conversation summaries
- Pending decisions & follow-ups
- Current goal stack
- Scope: cross-agent, current session

**Cold — Long-Term Memory** (PostgreSQL + pgvector)
- All past task records & outcomes
- User preference profile (evolving)
- Learned patterns & behavioral rules
- Knowledge base (docs, notes, facts)
- System evolution history
- Audit trail & quality metrics
- Scope: permanent

### 3.2 Context Anchors

Certain context is tagged as Anchors — never compressed, summarized, or dropped:
- Original user goals (exact words)
- Critical decisions made during clarification
- Quality standards set or confirmed
- Corrections ("no, I meant X")
- System rules learned about the user

Anchors are stored in both Warm and Cold memory with `priority: anchor` tag. Verified after every compaction.

### 3.3 Context Packaging

When the Coordinator spawns a sub-agent via the Orchestrator, it builds a curated Context Package:
- **Goal Anchor** — original user intent, word for word
- **Task Scope** — exactly what this sub-agent must do (and must NOT do)
- **Relevant Context** — retrieved via semantic search, only what's relevant to THIS subtask
- **Quality Criteria** — how the auditor will judge this work
- **User Preferences** — relevant behavioral preferences for this task type

### 3.4 Structured Compaction

When context approaches window limit:
1. Extract & preserve all anchors
2. Classify remaining: decisions, outcomes, conversation, tool output, reasoning
3. Compress by type — each content type has its own compaction strategy
4. Verify — compaction verifier confirms no anchors lost, no critical decisions altered

### 3.5 Context Retrieval (Hybrid)

- **Semantic search** — vector similarity (pgvector)
- **Keyword search** — exact match (PostgreSQL FTS)
- **Temporal search** — time-based queries
- **Graph traversal** — follow relationships (task → subtasks → outcomes → corrections)
- Results ranked by relevance + recency + anchor priority

### 3.6 Coordinator Continuity

The Coordinator operates as a persistent state machine:
- Maintains a structured **State Document** in Warm memory (active tasks, pending decisions, improvement initiatives, scout findings, system health)
- Every LLM call loads: core identity → State Document → relevant anchors → task-specific context
- After every action, writes state changes back before the call ends
- Nothing lives only in the context window

---

## 4. Tool System

### 4.1 Architecture

Every tool is exposed as an **MCP (Model Context Protocol) server**:
- Standardized interface across all tools
- Hot-pluggable — add/remove without restart
- Discoverable — agents query the Tool Registry
- Permissioned — per-agent tool access whitelisting
- Auditable — every invocation logged with inputs, outputs, timestamps

Tool Registry stores metadata: tool_id, category, description, permissions, cost_tier, reliability score, average latency.

### 4.2 Categories (80+ tools on day one)

**Code & Development**
- File system: read/write/edit, directory ops, glob/regex search, file watching (pathlib, watchdog, aiofiles)
- Shell & process: sandboxed execution, process management, cron (asyncio.subprocess)
- Git & VCS: clone, commit, push, PR creation, diff analysis (GitPython, PyGithub, gh CLI)
- Code analysis: AST parsing, linting, formatting, dependency analysis, test execution (tree-sitter, ruff, pytest)

**Web & Browser**
- Browser automation: navigate, click, type, screenshot, forms, auth (Playwright Python + MCP)
- Web scraping & search: URL fetching, content extraction, structured data (httpx, BeautifulSoup, Crawl4AI, Brave Search API)
- API integration: REST, GraphQL, OAuth2, webhooks, OpenAPI auto-import (httpx, gql, authlib)

**Communication & Productivity**
- Email: send, read, search, drafts, attachments (Gmail API, IMAP, SendGrid/SES)
- Calendar: create, read, update events, availability, timezone management (Google Calendar API, caldav)
- Documents: PDF, spreadsheets, markdown, rich text (PyPDF2, openpyxl, python-pptx)
- Notes: Notion, Obsidian integration (notion-client)
- Messaging: Telegram Bot API, WhatsApp, Slack, Discord

**Infrastructure & Cloud**
- AWS: EC2, S3, Lambda, RDS, DynamoDB, CloudWatch, IAM, ECS/ECR (boto3)
- Docker: build, run, stop, compose, logs, networks (docker-py)
- Server: SSH, system monitoring, service management, log analysis, DNS (paramiko, psutil)

**Data & Knowledge**
- Databases: PostgreSQL, SQLite, Redis, Vector DB (asyncpg, aiosqlite, redis-py, chromadb)
- Data analysis: dataframes, visualization, statistics (pandas, polars, matplotlib, plotly)
- Knowledge: semantic search, document embedding, FTS (sentence-transformers, chromadb)
- Media: image processing, audio transcription, TTS, video (Pillow, openai-whisper, ffmpeg-python)

### 4.3 Polyglot Code Support

Three-step pipeline for any codebase:
1. **Auto-detect** — scan signature files (package.json, Cargo.toml, go.mod, pom.xml, etc.)
2. **Provision environment** — Docker container with correct runtime, dependencies installed, env configured
3. **Execute with full toolchain** — package managers, build tools, test runners, linters, debuggers, framework CLIs, version managers

Pre-built cached base images: Python, Node, Rust, Go, Java, .NET, Ruby, PHP, C/C++, Dart/Flutter, Elixir, Swift.

Key principle: Max adapts to the codebase, not the other way around. Reads existing configs (.nvmrc, .python-version, CI configs), follows the project's patterns. Self-expanding — Evolution Director builds new base images for unknown languages.

### 4.4 Extensibility

1. **MCP servers** — any MCP-compatible server plugs in instantly (75+ available)
2. **Custom tools** — Python function + schema, registered in Tool Registry
3. **Scout-discovered** — Scouts find → Evolution Director evaluates → Improvement Agent installs → Auditor verifies → promoted to live
4. **OpenAPI auto-import** — point at any Swagger spec, auto-generate tool wrapper

---

## 5. Self-Evolution System

### 5.1 Pillar 1: Behavioral Adaptation (Learning the User)

**Observation signals:**
- Corrections ("no, I meant X") — strongest signal, stored as anchors
- Acceptances (work accepted without changes) — positive pattern reinforcement
- Choices (when given options, which is picked) — pattern emerges over time
- Modifications (user edits Max's output) — diff reveals preferences
- Timing (active hours, response time expectations, urgency patterns)
- Language (tone, vocabulary, expected detail level)

**Preference Profile** — a living structured document in Cold memory:
- Communication: tone, detail level, update frequency, languages, timezone
- Code: style preferences per language, review depth, test coverage expectations, commit style
- Workflow: clarification threshold, autonomy level, reporting style
- Domain knowledge: expertise areas, client contexts, project conventions

Injected into every agent's context package. Shapes Communicator (tone), Planner (autonomy), Sub-Agents (code style), Auditors (quality criteria), Quality Director (thresholds).

### 5.2 Pillar 2: System Evolution (Upgrading Itself)

**7-step evolution pipeline:**
1. **Discover** — Scouts find improvement opportunity
2. **Evaluate** — Evolution Director assesses impact vs effort
3. **Snapshot** — Capture current system state to S3
4. **Implement** — Improvement Agent builds in sandbox
5. **Audit** — Auditor reviews changes (blind, without seeing Improvement Agent's reasoning)
6. **Canary test** — replay 5-10 recent tasks in sandbox, compare outputs
7. **Promote** — deploy to live if all passes; auto-rollback if anything breaks

**What can be evolved:**
- Agent prompts (system prompts for every agent type)
- Tool configurations (parameters, timeouts, retry policies)
- New tools (discovered by scouts, installed and integrated)
- Workflow patterns (better task decomposition strategies)
- Context packaging rules (proactive inclusion of frequently-requested context)
- Max's own code (performance optimizations, bug fixes, new capabilities)

**Canary testing rule:** A change must be strictly non-regressive. Equal or better on every replayed task. Never sacrifice quality in one area for gains in another.

### 5.3 Pillar 3: Quality Ratchet (Only Goes Up)

**Learning from failures:**
- Auditor flags issue → Quality Director categorizes → Quality Rule generated
- Rule added to relevant agents' context packages
- Future auditors also check for the specific issue
- Rules are never deleted, only superseded (append-only Quality Ledger)

**Learning from successes:**
- Work passes audit with high scores → Quality Director analyzes what made it good
- Quality Pattern extracted with reinforcement count
- Pattern promoted as "preferred approach" for sub-agents
- Higher reinforcement count = stronger preference

**Quality Ledger** — permanent, append-only record in Cold memory:
- Every audit verdict (pass/fail + score)
- Every quality rule generated
- Every quality pattern extracted
- Every user correction
- Quality score trends over time
- System evolution history

**Anti-degradation trigger:** If any quality metric drops for 2 consecutive measurement periods, Evolution Director freezes all non-critical evolution and launches a focused investigation.

### 5.4 Meta-Learning: Self-Model

Max maintains a Self-Model — understanding of its own capabilities and limitations:
- **Capability Map** — what Max is good at, what it struggles with
- **Performance Baselines** — expected quality scores per task type
- **Failure Taxonomy** — categorized history of how/why things go wrong
- **Evolution Journal** — every change, why it was made, what effect it had
- **Confidence Calibration** — tracks how well confidence scores predict actual quality, recalibrates over time

### 5.5 The Flywheel

You use Max → Auditors evaluate → Rules + patterns extracted → Scouts find improvements → Evolution Director upgrades → Canary tests verify → Max gets better → You use Max more.

---

## 6. Communication Layer

### 6.1 Telegram + WhatsApp Mirror Mode

Both platforms show the same conversation state. User can switch between them seamlessly.

- **Telegram**: python-telegram-bot library, Bot API
- **WhatsApp**: Baileys or whatsapp-web.js (Node.js bridge)
- Messages from either platform → Communicator → same internal processing
- Responses sent to both platforms simultaneously
- Media (images, voice notes, documents) supported on both

### 6.2 Message Flow

Inbound: Text, voice notes, images, documents, commands
Outbound: Formatted messages, status updates, file attachments, choices
Internal: Structured intent objects, clarification requests, result payloads, priority signals

---

## 7. Infrastructure (AWS)

### 7.1 Compute

- **Primary EC2** (t3.xlarge, 4 vCPU, 16GB RAM) — always-on Coordinator + Communicator + Redis
- **ECS Fargate** — elastic agent worker pool (Planner, Orchestrator, Directors, Sub-Agents, Auditors, Scouts). Scale to 0 when idle, burst when busy.
- **Sandbox** — isolated Fargate environment for canary testing. Spun up only during evolution cycles.

### 7.2 Data

- **RDS PostgreSQL + pgvector** (db.t3.medium) — Cold memory, Quality Ledger, task history, vector search
- **ElastiCache Redis** (t3.small) — message bus, Warm memory, session state
- **S3** — snapshots, artifacts, file storage
- **ECR** — Docker images for agent containers and polyglot base images

### 7.3 Operations

- **CloudWatch** — logs, metrics, alarms (60s health checks)
- **SNS** — alert notifications to Telegram
- **Systems Manager** — secrets and parameter management
- **VPC** — private networking, no public subnets for compute
- **EventBridge** — scheduled triggers for scouts and maintenance

### 7.4 Resilience

- **Auto-restart**: systemd manages core processes. State is in Redis/PostgreSQL, not in-process.
- **Health checks**: CloudWatch 60s heartbeat. SNS alert at 3min unresponsive. Auto-recovery at 10min.
- **Snapshots**: Daily automated EBS + PostgreSQL backups to S3. Full snapshot before every self-modification. 30-day retention.
- **Graceful degradation**: If Anthropic API goes down, requests queue and user is notified. Non-critical tasks pause first.

### 7.5 Estimated Monthly Cost

| Service | Cost |
|---------|------|
| EC2 t3.xlarge (1yr reserved) | ~$72 |
| RDS PostgreSQL db.t3.medium | ~$50 |
| ElastiCache Redis t3.small | ~$25 |
| ECS Fargate (variable) | ~$30-80 |
| S3 + ECR + misc | ~$15 |
| CloudWatch + SNS | ~$10 |
| **Total Infrastructure** | **~$200-250/mo** |

Note: Anthropic API costs separate (~$500-2000+/mo depending on usage).

---

## 8. Security Model

### 8.1 Six Layers of Defense

**Layer 1: Network Isolation**
- Private VPC, no public subnets for compute
- Security groups: only outbound HTTPS to Anthropic API, Telegram API, WhatsApp endpoints
- Webhook ingress via API Gateway with auth token validation
- No SSH — AWS Systems Manager Session Manager only

**Layer 2: Secrets Management**
- All API keys in AWS Secrets Manager
- Automatic rotation where supported
- Per-agent scoped access
- Audit trail on every secret access

**Layer 3: Agent Sandboxing**
- Sub-agents execute inside Docker containers (Fargate)
- Read-only filesystem except designated work directory
- No direct network access — HTTP proxied through controlled gateway
- Resource limits (CPU, memory, execution time)
- Tool access whitelisted per agent

**Layer 4: Input Sanitization**
- All external content tagged as `untrusted`
- Untrusted content placed in delimited blocks, never mixed with system instructions
- Prompt injection detection: pattern scanning on inbound content
- User ID verification — only authorized Telegram/WhatsApp accounts

**Layer 5: Audit & Logging**
- Every tool invocation logged (who, what, when, inputs, outputs)
- Every agent spawn/kill logged
- Every self-modification recorded
- 90-day CloudWatch retention
- Anomaly detection on unusual patterns

**Layer 6: Identity & Auth**
- Single-user system — only authorized Telegram/WhatsApp user IDs
- Hardcoded at setup — no dynamic pairing
- Unrecognized messages silently dropped and logged
- Webhook endpoints use per-service auth tokens
- AWS IAM: least-privilege roles per service

### 8.2 Self-Modification Security

- Snapshot before every modification (full system state to S3)
- Sandbox-only implementation (Improvement Agents never touch live code)
- Independent audit (Auditor blind to Improvement Agent's reasoning)
- Canary testing with real task replay
- Diff review in Evolution Journal
- Rollback within seconds on any breakage
- Core protection — security config, auth logic, snapshot engine require multi-step verification for modification

---

## 9. Tech Stack Summary

| Component | Technology |
|-----------|-----------|
| Language | Python (asyncio) |
| AI Model | Claude Opus 4.6 (reasoning), Claude Sonnet 4.6 (routing/ops) |
| Agent Framework | Claude Agent SDK + custom orchestration |
| Tool Protocol | MCP (Model Context Protocol) |
| Messaging | Telegram Bot API (python-telegram-bot), WhatsApp (Baileys/WWebJS) |
| Databases | PostgreSQL + pgvector, Redis, SQLite |
| Browser | Playwright (Python + MCP) |
| Containers | Docker (agent sandboxing, polyglot execution, canary testing) |
| Cloud | AWS (EC2, ECS Fargate, RDS, ElastiCache, S3, ECR, CloudWatch, Secrets Manager, EventBridge, VPC) |
| Architecture | Modular Monolith (subprocess isolation, clean module boundaries) |

---

## 10. Future: Anti-Degradation Strategy

To be designed post-build. User has specific ideas for preventing system degradation over time. Foundation already laid:
- Quality Ratchet (one-way quality rules)
- Anti-degradation trigger (freeze evolution on quality drops)
- Self-Model with confidence calibration
- Canary testing requirement (strictly non-regressive changes)
- Snapshot + rollback safety net
