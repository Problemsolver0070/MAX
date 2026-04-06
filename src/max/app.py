"""Composition root — wires all Max subsystems into a running application.

This is the single wiring point that creates all infrastructure, stores,
agents, and starts the system.  It owns the dependency graph and ensures
clean startup/shutdown ordering.

Public API:
    create_app_state(settings) — creates and wires all dependencies
    start_agents(state)        — calls agent.start() for all agents
    start_scheduler_jobs(state)— registers and starts scheduled jobs
    shutdown_app_state(state)  — graceful shutdown in reverse order
    lifespan(app)              — FastAPI async context manager
    create_app()               — creates the fully wired FastAPI application
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as aioredis
from fastapi import FastAPI

from max.agents.base import AgentConfig
from max.api import create_api_app
from max.api.dependencies import AppState
from max.bus.message_bus import MessageBus
from max.bus.streams import StreamsTransport
from max.command.coordinator import CoordinatorAgent
from max.command.orchestrator import OrchestratorAgent
from max.command.planner import PlannerAgent
from max.command.runner import InProcessRunner
from max.command.task_store import TaskStore
from max.config import Settings
from max.db.postgres import Database
from max.db.redis_store import WarmMemory
from max.evolution.canary import CanaryRunner
from max.evolution.director import EvolutionDirectorAgent
from max.evolution.improver import ImprovementAgent
from max.evolution.self_model import SelfModel
from max.evolution.snapshot import SnapshotManager
from max.evolution.store import EvolutionStore
from max.llm.circuit_breaker import CircuitBreaker
from max.llm.client import LLMClient
from max.llm.models import ModelType
from max.memory.coordinator_state import CoordinatorStateManager
from max.memory.metrics import MetricCollector
from max.observability import configure_logging, configure_metrics
from max.quality.director import QualityDirectorAgent
from max.quality.rules import RuleEngine
from max.quality.store import QualityStore
from max.scheduler import Scheduler
from max.sentinel.agent import SentinelAgent
from max.sentinel.benchmarks import BenchmarkRegistry
from max.sentinel.comparator import ScoreComparator
from max.sentinel.runner import TestRunner
from max.sentinel.scorer import SentinelScorer
from max.sentinel.store import SentinelStore
from max.tools.executor import ToolExecutor
from max.tools.registry import ToolRegistry
from max.tools.store import ToolInvocationStore

logger = logging.getLogger(__name__)

# Mapping from settings model name strings to ModelType enum values.
_MODEL_MAP: dict[str, ModelType] = {mt.model_id: mt for mt in ModelType}


def _resolve_model(model_name: str) -> ModelType:
    """Resolve a model name string to a ModelType enum value.

    Falls back to OPUS if the string is not recognized.
    """
    result = _MODEL_MAP.get(model_name)
    if result is None:
        logger.warning("Unknown model name '%s', falling back to OPUS", model_name)
        return ModelType.OPUS
    return result


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def create_app_state(settings: Settings) -> AppState:
    """Create and wire all Max dependencies into an AppState.

    This is a synchronous function that constructs the full dependency graph.
    Async initialization (DB connect, schema migration, etc.) happens later
    during the lifespan startup phase.
    """
    # ── Observability ──────────────────────────────────────────────────
    configure_logging(level=settings.max_log_level)
    configure_metrics(
        service_name=settings.otel_service_name,
        enabled=settings.otel_enabled,
    )

    # ── Infrastructure ─────────────────────────────────────────────────
    db = Database(dsn=settings.postgres_dsn)

    redis_client = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
    )

    warm_memory = WarmMemory(redis_client=redis_client)

    # Bus transport
    transport: StreamsTransport | None = None
    if settings.bus_transport == "streams":
        transport = StreamsTransport(
            redis_client=redis_client,
            consumer_group=settings.bus_consumer_group,
            consumer_name=settings.bus_consumer_name,
            max_retries=settings.bus_dead_letter_max_retries,
            stream_max_len=settings.bus_stream_max_len,
        )

    bus = MessageBus(redis_client=redis_client, transport=transport)

    # LLM client with circuit breaker
    circuit_breaker = CircuitBreaker(
        threshold=settings.llm_circuit_breaker_threshold,
        cooldown_seconds=settings.llm_circuit_breaker_cooldown_seconds,
    )
    llm = LLMClient(
        api_key=settings.anthropic_api_key,
        circuit_breaker=circuit_breaker,
    )

    # ── Stores ─────────────────────────────────────────────────────────
    task_store = TaskStore(db=db)
    quality_store = QualityStore(db=db)
    evolution_store = EvolutionStore(db=db)
    sentinel_store = SentinelStore(db=db)
    tool_invocation_store = ToolInvocationStore(db=db)
    metric_collector = MetricCollector(db=db)

    # ── Coordinator state ──────────────────────────────────────────────
    state_manager = CoordinatorStateManager(db=db, warm_memory=warm_memory)

    # ── Scheduler ──────────────────────────────────────────────────────
    scheduler = Scheduler(db=db)

    # ── Tools ──────────────────────────────────────────────────────────
    tool_registry = ToolRegistry()
    tool_executor = ToolExecutor(
        registry=tool_registry,
        store=tool_invocation_store,
        default_timeout=settings.tool_execution_timeout_seconds,
        audit_enabled=settings.tool_audit_enabled,
    )

    # ── Command Chain Agents ───────────────────────────────────────────
    runner = InProcessRunner(llm=llm)

    coordinator_config = AgentConfig(
        name="coordinator",
        system_prompt="You are the Coordinator for Max.",
        model=_resolve_model(settings.coordinator_model),
    )
    coordinator = CoordinatorAgent(
        config=coordinator_config,
        llm=llm,
        bus=bus,
        db=db,
        warm_memory=warm_memory,
        settings=settings,
        state_manager=state_manager,
        task_store=task_store,
    )

    planner_config = AgentConfig(
        name="planner",
        system_prompt="You are the Planner for Max.",
        model=_resolve_model(settings.planner_model),
    )
    planner = PlannerAgent(
        config=planner_config,
        llm=llm,
        bus=bus,
        db=db,
        warm_memory=warm_memory,
        settings=settings,
        task_store=task_store,
    )

    orchestrator_config = AgentConfig(
        name="orchestrator",
        system_prompt="You are the Orchestrator for Max.",
        model=_resolve_model(settings.orchestrator_model),
    )
    orchestrator = OrchestratorAgent(
        config=orchestrator_config,
        llm=llm,
        bus=bus,
        db=db,
        warm_memory=warm_memory,
        settings=settings,
        task_store=task_store,
        runner=runner,
        quality_store=quality_store,
    )

    # ── Quality Gate ───────────────────────────────────────────────────
    rule_engine = RuleEngine(
        llm=llm,
        quality_store=quality_store,
        max_rules_per_audit=settings.quality_max_rules_per_audit,
    )

    quality_director_config = AgentConfig(
        name="quality_director",
        system_prompt="You are the Quality Director for Max.",
        model=_resolve_model(settings.quality_director_model),
    )
    quality_director = QualityDirectorAgent(
        config=quality_director_config,
        llm=llm,
        bus=bus,
        db=db,
        warm_memory=warm_memory,
        settings=settings,
        task_store=task_store,
        quality_store=quality_store,
        rule_engine=rule_engine,
        state_manager=state_manager,
        metric_collector=metric_collector,
    )

    # ── Evolution System ───────────────────────────────────────────────
    snapshot_manager = SnapshotManager(
        store=evolution_store,
        metrics=metric_collector,
    )
    improver = ImprovementAgent(llm=llm, store=evolution_store)
    self_model = SelfModel(store=evolution_store, metrics=metric_collector)
    canary_runner = CanaryRunner(
        task_store=task_store,
        quality_store=quality_store,
        evo_store=evolution_store,
        llm=llm,
        metrics=metric_collector,
        timeout_seconds=settings.evolution_canary_timeout_seconds,
    )

    # Sentinel components (needed by evolution director)
    sentinel_test_runner = TestRunner(
        llm=llm,
        task_store=task_store,
        quality_store=quality_store,
        evo_store=evolution_store,
    )
    score_comparator = ScoreComparator()
    sentinel_scorer = SentinelScorer(
        store=sentinel_store,
        runner=sentinel_test_runner,
        comparator=score_comparator,
        task_store=task_store,
        replay_count=settings.sentinel_replay_count,
    )

    evolution_director = EvolutionDirectorAgent(
        llm=llm,
        bus=bus,
        evo_store=evolution_store,
        quality_store=quality_store,
        snapshot_manager=snapshot_manager,
        improver=improver,
        canary_runner=canary_runner,
        self_model=self_model,
        settings=settings,
        state_manager=state_manager,
        task_store=task_store,
        sentinel_scorer=sentinel_scorer,
    )

    # ── Sentinel Agent ─────────────────────────────────────────────────
    benchmark_registry = BenchmarkRegistry()
    sentinel_agent = SentinelAgent(
        bus=bus,
        scorer=sentinel_scorer,
        registry=benchmark_registry,
        store=sentinel_store,
    )

    # ── Assemble agents dict ───────────────────────────────────────────
    agents: dict[str, Any] = {
        "coordinator": coordinator,
        "planner": planner,
        "orchestrator": orchestrator,
        "quality_director": quality_director,
        "evolution_director": evolution_director,
        "sentinel": sentinel_agent,
    }

    return AppState(
        settings=settings,
        db=db,
        redis_client=redis_client,
        bus=bus,
        transport=transport,
        warm_memory=warm_memory,
        llm=llm,
        circuit_breaker=circuit_breaker,
        task_store=task_store,
        quality_store=quality_store,
        evolution_store=evolution_store,
        sentinel_store=sentinel_store,
        state_manager=state_manager,
        scheduler=scheduler,
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        agents=agents,
        start_time=time.monotonic(),
    )


# ---------------------------------------------------------------------------
# Agent lifecycle
# ---------------------------------------------------------------------------


async def start_agents(state: AppState) -> None:
    """Start all agents by calling their start() methods."""
    for name, agent in state.agents.items():
        if hasattr(agent, "start"):
            try:
                await agent.start()
                logger.info("Started agent: %s", name)
            except Exception:
                logger.exception("Failed to start agent: %s", name)
                raise


async def start_scheduler_jobs(state: AppState) -> None:
    """Register and start all scheduled jobs."""
    settings = state.settings

    # Evolution scout trigger
    async def evolution_trigger() -> None:
        await state.bus.publish("evolution.trigger", {"source": "scheduler"})

    state.scheduler.register(
        name="evolution_scout",
        interval_seconds=settings.evolution_scout_interval_hours * 3600,
        callback=evolution_trigger,
    )

    # Sentinel scheduled monitoring
    async def sentinel_scheduled() -> None:
        await state.bus.publish(
            "sentinel.run_request",
            {"run_type": "scheduled"},
        )

    state.scheduler.register(
        name="sentinel_monitor",
        interval_seconds=settings.sentinel_monitor_interval_hours * 3600,
        callback=sentinel_scheduled,
    )

    # Memory compaction
    async def memory_compaction() -> None:
        await state.bus.publish("memory.compact", {"source": "scheduler"})

    state.scheduler.register(
        name="memory_compaction",
        interval_seconds=settings.memory_compaction_interval_seconds,
        callback=memory_compaction,
    )

    # Anchor re-evaluation
    async def anchor_re_eval() -> None:
        await state.bus.publish("memory.anchor_re_eval", {"source": "scheduler"})

    state.scheduler.register(
        name="anchor_re_evaluation",
        interval_seconds=settings.memory_anchor_re_evaluation_interval_hours * 3600,
        callback=anchor_re_eval,
    )

    await state.scheduler.load_state()
    await state.scheduler.start()
    logger.info("Scheduler started with all jobs registered")


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------


async def shutdown_app_state(state: AppState) -> None:
    """Graceful shutdown in reverse construction order.

    Stops scheduler first, then agents (reverse order), then infrastructure.
    Each step is wrapped with a 10-second timeout so a hung coroutine cannot
    block the entire shutdown sequence.
    """
    # 1. Scheduler
    try:
        await asyncio.wait_for(state.scheduler.stop(), timeout=10.0)
    except TimeoutError:
        logger.warning("Scheduler stop timed out after 10s")
    except Exception:
        logger.exception("Error stopping scheduler")

    # 2. Agents (reverse order)
    for name in reversed(list(state.agents.keys())):
        agent = state.agents[name]
        if hasattr(agent, "stop"):
            try:
                await asyncio.wait_for(agent.stop(), timeout=10.0)
                logger.info("Stopped agent: %s", name)
            except TimeoutError:
                logger.warning("Agent '%s' stop timed out after 10s", name)
            except Exception:
                logger.exception("Error stopping agent: %s", name)

    # 3. Message bus
    try:
        await asyncio.wait_for(state.bus.close(), timeout=10.0)
    except TimeoutError:
        logger.warning("Message bus close timed out after 10s")
    except Exception:
        logger.exception("Error closing message bus")

    # 4. LLM client
    try:
        await asyncio.wait_for(state.llm.close(), timeout=10.0)
    except TimeoutError:
        logger.warning("LLM client close timed out after 10s")
    except Exception:
        logger.exception("Error closing LLM client")

    # 5. Database
    try:
        await asyncio.wait_for(state.db.close(), timeout=10.0)
    except TimeoutError:
        logger.warning("Database close timed out after 10s")
    except Exception:
        logger.exception("Error closing database")

    # 6. Redis
    try:
        await asyncio.wait_for(state.redis_client.close(), timeout=10.0)
    except TimeoutError:
        logger.warning("Redis close timed out after 10s")
    except Exception:
        logger.exception("Error closing Redis")

    logger.info("All Max subsystems shut down")


# ---------------------------------------------------------------------------
# FastAPI lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI async context manager — startup and shutdown."""
    settings = Settings()
    state = create_app_state(settings)
    app.state.app_state = state

    # Async initialization
    await state.db.connect()
    await state.db.init_schema()
    await state.bus.start_listening()
    await start_agents(state)
    await start_scheduler_jobs(state)

    logger.info("Max application started")

    yield

    await shutdown_app_state(state)
    logger.info("Max application shut down")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Create the fully wired FastAPI application."""
    return create_api_app(lifespan=lifespan)
