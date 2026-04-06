"""Shared FastAPI dependencies and application state container."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import Request


@dataclass
class AppState:
    """Holds all wired dependencies, stored on FastAPI app.state."""

    settings: Any
    db: Any
    redis_client: Any
    bus: Any
    transport: Any
    warm_memory: Any
    llm: Any
    circuit_breaker: Any
    task_store: Any
    quality_store: Any
    evolution_store: Any
    sentinel_store: Any
    state_manager: Any
    scheduler: Any
    tool_registry: Any
    tool_executor: Any
    agents: dict[str, Any] = field(default_factory=dict)
    start_time: float = 0.0


def get_app_state(request: Request) -> AppState:
    """FastAPI dependency: extract AppState from request."""
    return request.app.state.app_state
