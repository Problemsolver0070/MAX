# Phase 6A: Tool Framework + Core Tools — Design Specification

**Date:** 2026-04-05
**Status:** Approved
**Depends on:** Phase 5 (Quality Gate), Phase 4 (Command Chain), Phase 1 (Tool Registry)

---

## 1. Goal

Build the tool execution infrastructure that enables Max agents to discover, invoke, and audit tools during task execution. Deliver ~15 core tools (file system, shell, git, web) to prove the framework end-to-end. Phase 6B fills in the remaining 60+ tools across all 5 categories using this framework.

---

## 2. Architecture

```
Agent (WorkerAgent / any BaseAgent)
    ↓ LLM returns tool_use content blocks
ToolExecutor (central pipeline)
    ↓ permission check → timeout enforcement → dispatch to provider
ToolProvider (ABC)
    ├── NativeToolProvider  — Python async functions as tools
    └── MCPToolProvider     — Proxies calls to MCP servers via JSON-RPC
    ↓ ToolResult
ToolExecutor
    ↓ audit log to tool_invocations table → return ToolResult
Agent receives tool_result, continues reasoning
```

Three layers:
1. **Registry** — what tools exist, who can use them, health status
2. **Executor** — permission check → execute → audit pipeline
3. **Providers** — how each tool actually runs (native Python, MCP server, etc.)

---

## 3. Tool Provider Interface

```python
class ToolProvider(ABC):
    """Base class for all tool sources."""

    @property
    @abstractmethod
    def provider_id(self) -> str: ...

    @abstractmethod
    async def list_tools(self) -> list[ToolDefinition]: ...

    @abstractmethod
    async def execute(self, tool_id: str, inputs: dict[str, Any]) -> ToolResult: ...

    @abstractmethod
    async def health_check(self) -> bool: ...
```

### 3.1 NativeToolProvider

Wraps Python async functions as tools. Each tool is registered with:
- A tool ID (e.g., `file.read`)
- A JSON Schema for inputs
- An async handler function `(inputs: dict) -> Any`
- Category, permissions, description metadata

The provider holds a dict of `{tool_id: handler}`. Execute dispatches to the handler.

### 3.2 MCPToolProvider

Connects to an MCP server process (stdio transport) or HTTP endpoint (SSE transport):
- On `list_tools()`: sends `tools/list` JSON-RPC call, maps MCP tool definitions to `ToolDefinition`
- On `execute()`: sends `tools/call` JSON-RPC with tool name and arguments
- On `health_check()`: pings the server; returns False if not responding
- Manages server subprocess lifecycle (start/stop)

Uses the `mcp` Python SDK for protocol handling.

---

## 4. Enhanced Tool Registry

Extends Phase 1's `ToolRegistry` (which already has register, get, list_all, list_by_category, check_permission, to_anthropic_tools).

### 4.1 New capabilities

- **Provider management:** `register_provider(provider)` — calls `provider.list_tools()` and registers all discovered tools. Each ToolDefinition gains a `provider_id` field linking it back to its source.
- **Per-agent whitelists:** `AgentToolPolicy` model maps agent name → set of allowed tool IDs or category wildcards (e.g., `"code.*"`). The `check_agent_access(agent_name, tool_id)` method enforces this.
- **Health tracking:** `ProviderHealth` model with `last_checked: datetime`, `is_healthy: bool`, `error_count: int`, `consecutive_failures: int`. Updated on each execute/health_check.
- **Refresh:** `refresh_provider(provider_id)` re-lists tools from a provider (for MCP servers that add/remove tools).

### 4.2 Models

```python
class ToolDefinition(BaseModel):
    """Extends Phase 1 ToolDefinition with provider linkage."""
    tool_id: str
    category: str
    description: str
    permissions: list[str] = []
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}
    cost_tier: str = "low"          # low | medium | high
    reliability: float = 1.0
    avg_latency_ms: int = 0
    provider_id: str = "native"     # NEW: which provider owns this tool
    timeout_seconds: int | None = None  # NEW: per-tool timeout override

class AgentToolPolicy(BaseModel):
    """Per-agent tool access whitelist."""
    agent_name: str
    allowed_tools: list[str] = []      # explicit tool IDs
    allowed_categories: list[str] = [] # category wildcards (e.g., "code")
    denied_tools: list[str] = []       # explicit denials (override allows)

class ProviderHealth(BaseModel):
    """Health status for a tool provider."""
    provider_id: str
    is_healthy: bool = True
    last_checked: datetime | None = None
    error_count: int = 0
    consecutive_failures: int = 0
```

---

## 5. Tool Executor

Central pipeline all tool calls flow through. Single class, injected into agents.

### 5.1 Execution pipeline

```
execute(agent_name, tool_id, inputs) -> ToolResult
  1. Resolve tool → ToolDefinition (fail if not found)
  2. Permission check → AgentToolPolicy (fail if denied)
  3. Provider health check → skip if provider unhealthy
  4. Timeout wrap → asyncio.wait_for (per-tool or default timeout)
  5. Dispatch → provider.execute(tool_id, inputs)
  6. Audit log → insert into tool_invocations table
  7. Return → ToolResult
```

### 5.2 ToolResult model

```python
class ToolResult(BaseModel):
    """Result of a tool invocation."""
    tool_id: str
    success: bool
    output: Any = None
    error: str | None = None
    duration_ms: int = 0
```

### 5.3 Error handling

- Tool not found → ToolResult(success=False, error="Tool not found: {tool_id}")
- Permission denied → ToolResult(success=False, error="Permission denied: {agent_name} cannot use {tool_id}")
- Provider unhealthy → ToolResult(success=False, error="Provider {provider_id} is unhealthy")
- Timeout → ToolResult(success=False, error="Tool execution timed out after {timeout}s")
- Exception → ToolResult(success=False, error=str(exc)), logged at ERROR level

All errors are returned as ToolResults, never raised. The agent decides how to handle.

---

## 6. Agent Tool Loop

### 6.1 New method: `BaseAgent.think_with_tools()`

Wraps the existing `think()` in a tool-use loop:

```
think_with_tools(messages, system_prompt, tools, tool_executor) -> LLMResponse
  1. Call think(messages, system_prompt, tools=tools)
  2. If response has tool_calls:
     a. For each tool_call: executor.execute(agent_name, tool_call.name, tool_call.input)
     b. Append tool_result messages to conversation
     c. Increment turn count, check max_turns
     d. Go to step 1 with updated messages
  3. If response has no tool_calls: return response (final answer)
```

This preserves backward compatibility — agents that don't use tools keep calling `think()` directly. Agents that need tools call `think_with_tools()`.

### 6.2 WorkerAgent integration

WorkerAgent.run() changes to:
1. Get available tools from registry (filtered by agent policy)
2. Convert to Anthropic format via `registry.to_anthropic_tools()`
3. Call `think_with_tools()` instead of `think()`
4. Parse final response as before

---

## 7. Tool Invocation Store

### 7.1 Database table

```sql
CREATE TABLE IF NOT EXISTS tool_invocations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id VARCHAR(100) NOT NULL,
    tool_id VARCHAR(100) NOT NULL,
    inputs JSONB NOT NULL DEFAULT '{}',
    output JSONB,
    success BOOLEAN NOT NULL,
    error TEXT,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tool_invocations_agent ON tool_invocations(agent_id);
CREATE INDEX IF NOT EXISTS idx_tool_invocations_tool ON tool_invocations(tool_id);
CREATE INDEX IF NOT EXISTS idx_tool_invocations_created ON tool_invocations(created_at DESC);
```

### 7.2 ToolInvocationStore class

Async CRUD over the tool_invocations table:
- `record(agent_id, tool_id, inputs, output, success, error, duration_ms)` — insert
- `get_invocations(tool_id, limit)` — recent invocations for a tool
- `get_agent_invocations(agent_id, limit)` — recent invocations by an agent
- `get_stats(tool_id, hours)` — success rate, avg duration, invocation count

---

## 8. Core Tools (15 tools)

All implemented as NativeToolProvider handlers. Each is an async function with a JSON schema.

### 8.1 File System (6 tools)

| Tool ID | Description | Permissions |
|---------|-------------|-------------|
| `file.read` | Read file contents, optional line offset/limit | `fs.read` |
| `file.write` | Write/overwrite file contents | `fs.write` |
| `file.edit` | Search-and-replace edit within a file | `fs.write` |
| `directory.list` | List directory contents with metadata | `fs.read` |
| `file.glob` | Glob pattern file search | `fs.read` |
| `file.delete` | Delete a file or empty directory | `fs.write` |

### 8.2 Shell (1 tool)

| Tool ID | Description | Permissions |
|---------|-------------|-------------|
| `shell.execute` | Run shell command with timeout, working dir, capture stdout/stderr | `system.shell` |

Sandboxed: configurable working directory, timeout from `tool_shell_timeout_seconds`, captures both stdout and stderr, returns exit code.

### 8.3 Git (4 tools)

| Tool ID | Description | Permissions |
|---------|-------------|-------------|
| `git.status` | Working tree status | `fs.read` |
| `git.diff` | Show staged/unstaged changes | `fs.read` |
| `git.commit` | Stage files and commit with message | `fs.write`, `git.write` |
| `git.log` | Recent commit history (configurable count) | `fs.read` |

Implemented via `asyncio.subprocess` calling git CLI.

### 8.4 Web (2 tools)

| Tool ID | Description | Permissions |
|---------|-------------|-------------|
| `http.fetch` | HTTP GET/POST with headers, follow redirects | `network.http` |
| `http.request` | Full HTTP methods (PUT/DELETE/PATCH/HEAD) | `network.http` |

Implemented via `httpx.AsyncClient` with configurable timeout from `tool_http_timeout_seconds`.

### 8.5 Process (1 tool)

| Tool ID | Description | Permissions |
|---------|-------------|-------------|
| `process.list` | List running processes with PID, name, CPU, memory | `system.read` |

Implemented via `psutil`.

### 8.6 Search (1 tool)

| Tool ID | Description | Permissions |
|---------|-------------|-------------|
| `grep.search` | Regex search across files with glob filtering | `fs.read` |

---

## 9. Config Settings

Added to `Settings` class:

```python
# Tool system
tool_execution_timeout_seconds: int = 60
tool_max_concurrent: int = 10
tool_audit_enabled: bool = True
tool_shell_timeout_seconds: int = 30
tool_http_timeout_seconds: int = 30
```

---

## 10. File Structure

```
src/max/tools/
├── __init__.py               # Package exports
├── registry.py               # Enhanced ToolRegistry (extends Phase 1)
├── models.py                 # ToolResult, AgentToolPolicy, ProviderHealth
├── executor.py               # ToolExecutor pipeline
├── store.py                  # ToolInvocationStore (audit trail)
├── providers/
│   ├── __init__.py
│   ├── base.py               # ToolProvider ABC
│   ├── native.py             # NativeToolProvider
│   └── mcp.py                # MCPToolProvider
└── native/
    ├── __init__.py
    ├── file_tools.py          # file.read, file.write, file.edit, directory.list, file.glob, file.delete
    ├── shell_tools.py         # shell.execute
    ├── git_tools.py           # git.status, git.diff, git.commit, git.log
    ├── web_tools.py           # http.fetch, http.request
    ├── process_tools.py       # process.list
    └── search_tools.py        # grep.search

src/max/db/migrations/
└── 006_tool_system.sql        # tool_invocations table
```

---

## 11. Testing Strategy

- Unit tests for each tool (mocked file system / subprocess / httpx)
- Unit tests for ToolExecutor pipeline (permission, timeout, audit)
- Unit tests for NativeToolProvider and registry integration
- Unit tests for ToolInvocationStore
- Integration test: WorkerAgent uses tools in a think_with_tools loop (mocked LLM returns tool_use, tool executes, result fed back)
- MCPToolProvider tested with a mock MCP server

---

## 12. Dependencies

New pip packages:
- `mcp` — MCP Python SDK for MCPToolProvider
- `psutil` — process listing tool
- `httpx` — already used transitively, but now direct dependency for web tools

---

## 13. What Phase 6B Adds

Phase 6B uses this framework to add tools across all remaining categories:
- Browser automation (Playwright)
- Email (Gmail API, IMAP)
- Calendar (Google Calendar)
- Documents (PDF, spreadsheets)
- AWS (boto3)
- Docker (docker-py)
- Database tools (PostgreSQL, SQLite, Redis)
- Data analysis (pandas/polars)
- Media (Pillow, whisper, ffmpeg)
- OpenAPI auto-import provider

All built as NativeToolProvider handlers or new ToolProvider implementations, registered through the framework from 6A.
