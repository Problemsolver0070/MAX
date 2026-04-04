# Phase 4: Command Chain Design Specification

## 1. Overview

The Command Chain is the orchestration backbone of Max. It receives parsed intents from the Communication Layer (Phase 3), decomposes them into executable plans, spawns worker agents to execute subtasks, and routes results back to the user.

**Goal:** Connect the existing Communication Layer (which publishes `intents.new` into the void) to a working task execution pipeline that produces results the Communicator can deliver to the user.

**Architecture:** Three always-on agents forming a pipeline: Coordinator (classify and route) -> Planner (decompose into subtasks) -> Orchestrator (spawn workers, collect results). A generic WorkerAgent is dynamically configured per subtask. An AgentRunner abstraction enables future subprocess isolation (Phase 6).

**What this unlocks:** After Phase 4, Max can receive a user message, understand it, plan how to accomplish it, execute via worker agents, and return the result. The full intent-to-result loop is closed.

---

## 2. Components

### 2.1 Coordinator

The Coordinator is the central routing agent. It is a singleton, always-on service that subscribes to `intents.new` and `tasks.complete`. Every LLM call loads the State Document from warm memory, makes a routing decision, and writes state changes back before returning.

**Responsibilities:**
- Subscribe to `intents.new` from the Communicator
- Classify each intent into an action type using an LLM call
- Create tasks in the database for new work
- Route tasks to the Planner for decomposition
- Track all active tasks and their progress in the State Document
- Publish results and status updates back to the Communicator
- Handle status queries directly (no planning needed)
- Handle task cancellation

**Action classification (LLM output):**

The Coordinator's LLM receives the intent plus the current State Document summary and returns a structured JSON action:

| Action | Trigger | Coordinator Response |
|--------|---------|---------------------|
| `create_task` | New request from user | Create Task in DB, update state, publish to `tasks.plan` |
| `query_status` | "How's it going?" / "What are you working on?" | Read state, publish StatusUpdate directly |
| `cancel_task` | "Cancel that" / "Stop working on X" | Cancel active task, notify Orchestrator via `tasks.cancel`, publish StatusUpdate |
| `provide_context` | User adds info to an in-progress task | Append context to task, publish to `tasks.context_update` |
| `clarification_response` | User answers a Planner question | Route to `clarifications.response` |

**State Document lifecycle:**
1. Load `CoordinatorState` from `CoordinatorStateManager` at the start of each handler
2. Process the event, update the in-memory state
3. Save state back via `CoordinatorStateManager.save()` before returning
4. Periodic backup to cold storage via `backup_to_cold()`

**System prompt structure:** The Coordinator receives a system prompt containing: its role as a router, the current State Document (serialized summary of active tasks, queue, recent events), and the classification schema. The user message is the raw intent. The LLM returns JSON with the action and parameters.

### 2.2 Planner

The Planner receives tasks from the Coordinator and decomposes them into executable subtasks organized into execution phases. It uses Opus for deep reasoning about task structure.

**Responsibilities:**
- Subscribe to `tasks.plan` from the Coordinator
- Use the ContextPackager to build rich context for planning
- Decompose the task goal into an ordered set of subtasks via LLM
- Determine dependencies and organize subtasks into execution phases
- Assign quality criteria per subtask
- Specify which tool categories each subtask needs (used by Orchestrator to assign tools)
- Persist subtasks to the database
- Publish the ExecutionPlan to `tasks.execute` for the Orchestrator
- Request clarification from the user if the goal is ambiguous
- Handle `clarifications.response` to resume paused planning
- Handle `tasks.context_update` to incorporate new user-provided context

**Execution phases:** Subtasks within the same phase can run in parallel. Phases execute sequentially. The Planner determines this structure.

Example decomposition for "Deploy the app to staging":
```
Phase 1: [Check current build status, Verify staging config]     (parallel)
Phase 2: [Run test suite]                                        (depends on phase 1)
Phase 3: [Deploy to staging, Update deployment log]              (depends on phase 2)
Phase 4: [Verify deployment health]                              (depends on phase 3)
```

**Clarification flow:**
1. Planner determines it needs user input (ambiguous goal, missing parameters)
2. Publishes ClarificationRequest to `clarifications.new` (Communicator delivers to user)
3. Stores task_id in `_pending_clarifications` dict with planning context
4. When `clarifications.response` arrives with matching task_id, resumes planning

**LLM output schema:** The Planner's LLM returns a JSON object with:
- `subtasks`: list of `{description, phase_number, tool_categories, quality_criteria, estimated_complexity}`
- `needs_clarification`: bool
- `clarification_question`: string (if needed)
- `clarification_options`: list of strings (if applicable)
- `reasoning`: string explaining the decomposition logic

### 2.3 Orchestrator

The Orchestrator receives execution plans and manages the lifecycle of worker agents that execute subtasks.

**Responsibilities:**
- Subscribe to `tasks.execute` from the Planner
- Execute subtasks phase by phase, respecting dependency order
- Spawn WorkerAgents via the AgentRunner for each subtask
- Track active workers in the agent registry (part of CoordinatorState)
- Collect subtask results and update the database
- Publish StatusUpdates for progress tracking
- Handle subtask failures with retry logic (up to `WORKER_MAX_RETRIES`)
- When all phases complete, assemble the final result and publish to `tasks.complete`
- Handle `tasks.cancel` to abort running workers
- Handle `tasks.context_update` to forward new context to active workers

**Phase execution flow:**
1. Receive ExecutionPlan
2. For each phase (in order):
   a. Spawn a WorkerAgent for each subtask in the phase (parallel via asyncio.gather)
   b. Wait for all workers in the phase to complete
   c. If any subtask fails after retries, mark the task as failed, publish to `tasks.complete` with failure
   d. Update the Coordinator's state with progress
3. After all phases complete:
   a. Assemble the combined result from all subtask outputs
   b. Create a Result record in the database
   c. Publish to `tasks.complete`

**Worker lifecycle:**
1. Orchestrator creates WorkerConfig (system prompt, tool IDs, context package)
2. AgentRunner.run(config) spawns the worker and returns the result
3. Worker executes, returns result dict
4. Orchestrator updates subtask in DB with result
5. Worker is garbage collected (ephemeral)

**Failure handling:**
- Worker raises exception or returns error: retry up to `WORKER_MAX_RETRIES` with the same config
- Worker exceeds timeout: kill and mark as failed
- All retries exhausted: mark subtask failed, mark parent task failed, publish failure result

### 2.4 WorkerAgent

A generic, dynamically-configured agent that executes a single subtask. Workers are ephemeral -- they are created, execute, and self-terminate.

**Configuration (from Orchestrator):**
- `system_prompt`: Crafted from subtask description + context package summary
- `tools`: Tool definitions from ToolRegistry (empty in Phase 4, populated in Phase 6)
- `max_turns`: Configurable, default 10
- `context_package`: Full ContextPackage from the memory system

**Execution:**
1. Worker receives input_data containing: subtask description, context package, quality criteria
2. Makes LLM call(s) to reason about and produce the subtask result
3. Returns result dict with: `content` (the work product), `confidence` (0.0-1.0), `reasoning` (how it approached the task)

In Phase 4, workers are pure LLM reasoning agents (no external tools). Phase 6 adds MCP tools for code execution, web access, etc.

### 2.5 AgentRunner

An abstraction layer for agent execution. This exists to enable future subprocess isolation without changing the Orchestrator.

**Interface:**
```python
class AgentRunner(ABC):
    async def run(self, worker_config: WorkerConfig, context: AgentContext) -> SubtaskResult:
        """Run a worker agent and return its result."""
```

**InProcessRunner (Phase 4):** Creates a WorkerAgent instance in the current process, calls `agent.run()`, wraps the result in SubtaskResult.

**SubprocessRunner (Phase 6):** Will spawn a separate Python process, serialize the config, collect the result via stdout/pipe. Provides crash isolation and memory limits.

### 2.6 TaskStore

A thin persistence layer over PostgreSQL for Task and SubTask CRUD operations. Wraps raw SQL queries behind a clean async interface.

**Methods:**
- `create_task(intent_id, goal_anchor, priority, quality_criteria) -> Task`
- `get_task(task_id) -> Task | None`
- `get_active_tasks() -> list[Task]`
- `update_task_status(task_id, status, completed_at=None)`
- `create_subtask(task_id, description, phase_number, tool_categories, quality_criteria) -> SubTask`
- `get_subtasks(task_id) -> list[SubTask]`
- `update_subtask_status(subtask_id, status, completed_at=None)`
- `update_subtask_result(subtask_id, result_data)`
- `create_result(task_id, content, confidence, artifacts) -> uuid.UUID`

---

## 3. Data Models

New models in `src/max/command/models.py`:

### CoordinatorAction
```python
class CoordinatorActionType(StrEnum):
    CREATE_TASK = "create_task"
    QUERY_STATUS = "query_status"
    CANCEL_TASK = "cancel_task"
    PROVIDE_CONTEXT = "provide_context"
    CLARIFICATION_RESPONSE = "clarification_response"

class CoordinatorAction(BaseModel):
    action: CoordinatorActionType
    task_id: uuid.UUID | None = None          # For cancel/context/clarification
    goal_anchor: str = ""                      # For create_task
    priority: Priority = Priority.NORMAL       # For create_task
    quality_criteria: dict[str, Any] = {}      # For create_task (LLM-extracted)
    context_text: str = ""                     # For provide_context
    clarification_answer: str = ""             # For clarification_response
    reasoning: str = ""                        # LLM's classification reasoning
```

### ExecutionPlan
```python
class PlannedSubtask(BaseModel):
    description: str
    phase_number: int
    tool_categories: list[str] = []
    quality_criteria: dict[str, Any] = {}
    estimated_complexity: str = "moderate"      # low/moderate/high

class ExecutionPlan(BaseModel):
    task_id: uuid.UUID
    goal_anchor: str
    subtasks: list[PlannedSubtask]
    total_phases: int
    reasoning: str                              # Planner's decomposition logic
    created_at: datetime
```

### WorkerConfig
```python
class WorkerConfig(BaseModel):
    subtask_id: uuid.UUID
    task_id: uuid.UUID
    system_prompt: str
    tool_ids: list[str] = []
    context_package: dict[str, Any] = {}
    quality_criteria: dict[str, Any] = {}
    max_turns: int = 10
```

### SubtaskResult
```python
class SubtaskResult(BaseModel):
    subtask_id: uuid.UUID
    task_id: uuid.UUID
    success: bool
    content: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = ""
    error: str | None = None
```

---

## 4. Bus Channel Topology

### Channel Map

| Channel | Publisher | Subscriber | Payload |
|---------|-----------|------------|---------|
| `intents.new` | CommunicatorAgent | **Coordinator** | Intent dict |
| `tasks.plan` | Coordinator | **Planner** | `{task_id, goal_anchor, priority, quality_criteria}` |
| `tasks.execute` | Planner | **Orchestrator** | ExecutionPlan dict |
| `tasks.complete` | Orchestrator | **Coordinator** | `{task_id, success, result_content, confidence, error}` |
| `tasks.cancel` | Coordinator | **Orchestrator** | `{task_id}` |
| `tasks.context_update` | Coordinator | **Planner, Orchestrator** | `{task_id, context_text}` |
| `results.new` | Coordinator | CommunicatorAgent | Result dict |
| `status_updates.new` | Coordinator, Orchestrator | CommunicatorAgent | StatusUpdate dict |
| `clarifications.new` | Planner | CommunicatorAgent | ClarificationRequest dict |
| `clarifications.response` | MessageRouter | **Planner** | `{task_id, answer}` |
| `anchors.re_evaluate` | CommunicatorAgent | AnchorManager (future) | `{anchor_ids}` |

**Bold** = new subscriber added in Phase 4.

### Channel Design Principles
- Each channel has a single semantic meaning
- Payloads are JSON-serializable dicts (model_dump(mode="json"))
- Channels use dot notation: `<entity>.<event>`
- New channels added: `tasks.plan`, `tasks.execute`, `tasks.complete`, `tasks.cancel`, `tasks.context_update`

---

## 5. Data Flow: Happy Path

```
User: "Research the latest Python 3.13 features and summarize them"
  |
  v
[CommunicatorAgent] -- publishes --> intents.new
  |
  v
[Coordinator]
  1. Loads CoordinatorState from warm memory
  2. LLM classifies: action=create_task, goal="Research Python 3.13 features"
  3. Creates Task in DB (status=pending)
  4. Updates state: adds ActiveTaskSummary
  5. Saves state
  6. Publishes StatusUpdate: "Planning your request..."
  7. Publishes to tasks.plan: {task_id, goal_anchor}
  |
  v
[Planner]
  1. Receives task from tasks.plan
  2. Uses ContextPackager to build planning context
  3. LLM decomposes into subtasks:
     Phase 1: "Search for Python 3.13 release notes and PEPs"
     Phase 1: "Identify key new features and changes"  (parallel)
     Phase 2: "Synthesize findings into a structured summary"
  4. Creates SubTasks in DB
  5. Publishes ExecutionPlan to tasks.execute
  |
  v
[Orchestrator]
  1. Receives ExecutionPlan
  2. Phase 1: Spawns 2 WorkerAgents in parallel
     - Worker A: Reasons about Python 3.13 release notes (LLM reasoning)
     - Worker B: Reasons about key features (LLM reasoning)
  3. Both complete, results collected
  4. Publishes StatusUpdate: "2/3 subtasks complete, synthesizing..."
  5. Phase 2: Spawns 1 WorkerAgent for synthesis
     - Worker C: Combines Phase 1 results into summary
  6. All phases complete
  7. Assembles final result
  8. Creates Result in DB
  9. Publishes to tasks.complete
  |
  v
[Coordinator]
  1. Receives tasks.complete
  2. Updates task status to completed
  3. Updates state: removes from active, records completion
  4. Publishes Result to results.new
  5. Saves state
  |
  v
[CommunicatorAgent] -- formats and sends to Telegram
```

---

## 6. Data Flow: Clarification Path

```
User: "Deploy the thing"
  |
  v
[Coordinator] -> create_task -> tasks.plan
  |
  v
[Planner]
  1. LLM determines goal is ambiguous ("which thing? which environment?")
  2. Stores planning context in _pending_clarifications[task_id]
  3. Publishes ClarificationRequest to clarifications.new
     {task_id, question: "Which application and target environment?", options: ["App A to staging", "App B to production"]}
  |
  v
[CommunicatorAgent] -> sends to user via Telegram
  |
User: "App A to staging"
  |
  v
[CommunicatorAgent] -> publishes to intents.new
  |
  v
[Coordinator]
  1. LLM classifies: action=clarification_response (recognizes this answers a pending question)
  2. Publishes to clarifications.response: {task_id, answer: "App A to staging"}
  |
  v
[Planner]
  1. Receives clarification response, retrieves pending context
  2. Resumes planning with clarified goal
  3. Decomposes and publishes ExecutionPlan
  |
  v
[Orchestrator] -> normal execution flow
```

---

## 7. Data Flow: Cancellation Path

```
User: "Cancel that"
  |
  v
[Coordinator]
  1. LLM classifies: action=cancel_task
  2. Identifies most recent active task (or specific task if named)
  3. Updates task status to failed in DB
  4. Publishes to tasks.cancel: {task_id}
  5. Publishes StatusUpdate: "Cancelled: <goal>"
  6. Updates state, saves
  |
  v
[Orchestrator]
  1. Receives tasks.cancel
  2. If task has active workers: cancels their asyncio tasks
  3. Marks remaining subtasks as failed
  4. Cleans up worker entries from agent registry
```

---

## 8. Error Handling

| Scenario | Handler | Response |
|----------|---------|----------|
| LLM rate limit during classification | Coordinator | LLMClient handles retry with backoff; if persistent, publishes error StatusUpdate |
| Planner can't decompose | Planner | Requests clarification from user |
| Worker times out | Orchestrator | Cancels worker, marks subtask failed, retries up to WORKER_MAX_RETRIES |
| Worker returns error | Orchestrator | Retries with same config, or marks failed if retries exhausted |
| All subtasks in a phase fail | Orchestrator | Marks task as failed, publishes failure to tasks.complete |
| State load fails | Coordinator | Creates fresh default state, logs warning |
| DB write fails | TaskStore | Raises exception, caller handles (Coordinator publishes error StatusUpdate) |

---

## 9. Configuration

New settings in `src/max/config.py`:

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `coordinator_model` | `COORDINATOR_MODEL` | `claude-opus-4-6` | Model for Coordinator LLM calls |
| `planner_model` | `PLANNER_MODEL` | `claude-opus-4-6` | Model for Planner LLM calls |
| `orchestrator_model` | `ORCHESTRATOR_MODEL` | `claude-opus-4-6` | Model for Orchestrator LLM calls |
| `worker_model` | `WORKER_MODEL` | `claude-opus-4-6` | Default model for WorkerAgent LLM calls |
| `coordinator_max_active_tasks` | `COORDINATOR_MAX_ACTIVE_TASKS` | `5` | Max concurrent tasks |
| `planner_max_subtasks` | `PLANNER_MAX_SUBTASKS` | `10` | Max subtasks per task |
| `worker_max_retries` | `WORKER_MAX_RETRIES` | `2` | Max retry attempts per failed subtask |
| `worker_timeout_seconds` | `WORKER_TIMEOUT_SECONDS` | `300` | Timeout for a single worker execution |

---

## 10. Database Changes

### Schema Migration: `004_command_chain.sql`

Alter existing `subtasks` table to add Phase 4 columns:

```sql
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS phase_number INTEGER NOT NULL DEFAULT 0;
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS tool_categories JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS worker_agent_id UUID;
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS quality_criteria JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS estimated_complexity VARCHAR(20) NOT NULL DEFAULT 'moderate';

CREATE INDEX IF NOT EXISTS idx_subtasks_phase ON subtasks(parent_task_id, phase_number);
```

Also alter `tasks` table to add priority:

```sql
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS priority VARCHAR(20) NOT NULL DEFAULT 'normal';
```

No new tables needed. The existing `tasks`, `subtasks`, `results`, `status_updates`, `clarification_requests` tables have the right structure.

---

## 11. File Structure

```
src/max/command/
    __init__.py               # Package exports
    models.py                 # CoordinatorAction, ExecutionPlan, WorkerConfig, SubtaskResult, etc.
    task_store.py             # TaskStore: async CRUD for tasks/subtasks over PostgreSQL
    coordinator.py            # CoordinatorAgent: intent classification, routing, state management
    planner.py                # PlannerAgent: task decomposition, clarification, execution plan creation
    orchestrator.py           # OrchestratorAgent: phase execution, worker lifecycle, result assembly
    worker.py                 # WorkerAgent: generic subtask executor
    runner.py                 # AgentRunner ABC + InProcessRunner

src/max/db/migrations/
    004_command_chain.sql     # ALTER subtasks + tasks

tests/
    test_command_models.py    # Model validation tests
    test_task_store.py        # TaskStore CRUD tests (real PostgreSQL)
    test_coordinator.py       # Coordinator classification and routing tests (mocked LLM)
    test_planner.py           # Planner decomposition tests (mocked LLM)
    test_orchestrator.py      # Orchestrator phase execution tests (mocked workers)
    test_worker.py            # Worker execution tests (mocked LLM)
    test_runner.py            # AgentRunner tests
    test_command_integration.py # End-to-end intent-to-result pipeline test
```

---

## 12. Testing Strategy

**Unit tests (mocked LLM):**
- Coordinator: Verify each action type produces correct bus publications and state changes
- Planner: Verify decomposition produces valid ExecutionPlans with correct phase structure
- Orchestrator: Verify phase-by-phase execution, retry logic, failure handling
- Worker: Verify subtask execution produces valid SubtaskResult
- TaskStore: CRUD operations against real PostgreSQL
- Models: Validation, serialization, edge cases

**Integration tests:**
- Full pipeline: Inject an intent, verify it flows through Coordinator -> Planner -> Orchestrator -> Workers -> back to Coordinator -> Result published
- Clarification flow: Verify clarification request/response cycle works end-to-end
- Cancellation flow: Verify cancel propagates and cleans up correctly
- Multi-task: Two intents in quick succession, both execute correctly

**Bus wiring tests:**
- Verify each agent subscribes to correct channels
- Verify publications arrive at expected subscribers
- Verify payloads serialize/deserialize correctly

---

## 13. Integration Points

### Phase 3 (Communication Layer) -- upstream
- **Consumes:** `intents.new` (from CommunicatorAgent)
- **Produces:** `results.new`, `status_updates.new`, `clarifications.new` (consumed by CommunicatorAgent)
- **Receives:** `clarifications.response` (from MessageRouter)

### Phase 2 (Memory System) -- support
- **Uses:** `CoordinatorStateManager` for persistent state
- **Uses:** `ContextPackager` for building subtask context
- **Uses:** `AnchorManager` (Coordinator may create/update context anchors for significant tasks)

### Phase 5 (Quality Gate) -- downstream (future)
- **Will produce:** `audit.request` channel for completed subtasks
- **Will consume:** `audit.complete` channel with audit verdicts
- For Phase 4, the audit step is skipped. The Orchestrator publishes directly to `tasks.complete` after all subtasks finish. Phase 5 will insert the Quality Director between subtask completion and task completion.

### Phase 6 (Tool Arsenal) -- downstream (future)
- Workers will receive real MCP tools via ToolRegistry
- AgentRunner will gain a SubprocessRunner for crash isolation
- Tool permissions and cost tracking will be integrated

---

## 14. Constraints and Non-Goals

**Constraints:**
- All agents use async Python (asyncio), no threading
- Bus messages are the only inter-agent communication (no direct method calls between agents)
- State Document is the single source of truth for the Coordinator's world view
- Workers are stateless and ephemeral -- no persistent worker processes

**Non-goals for Phase 4:**
- Quality auditing (Phase 5)
- External tool execution (Phase 6)
- Multi-user support (single owner only)
- WhatsApp integration (deferred)
- Sub-agent subprocess isolation (abstraction present, implementation in Phase 6)
- Concurrent task limit enforcement with queuing (simple max check sufficient for now)
