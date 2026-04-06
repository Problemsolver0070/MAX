"""Health and readiness endpoints -- no authentication required."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from max.api.dependencies import AppState, get_app_state

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict:
    """Liveness check with infrastructure and agent status."""
    state: AppState = get_app_state(request)

    # Database check
    db_status = "connected"
    try:
        await state.db.fetchone("SELECT 1")
    except Exception:
        db_status = "disconnected"

    # Redis check
    redis_status = "connected"
    try:
        await state.redis_client.ping()
    except Exception:
        redis_status = "disconnected"

    # Agent statuses
    agent_statuses = {name: "running" for name in state.agents}

    return {
        "status": "ok",
        "uptime_seconds": round(time.monotonic() - state.start_time, 1),
        "agents": agent_statuses,
        "infrastructure": {
            "database": db_status,
            "redis": redis_status,
            "bus": "listening" if state.bus._running else "stopped",
            "circuit_breaker": state.circuit_breaker.state.value,
        },
    }


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Readiness check -- verifies DB and Redis connectivity."""
    state: AppState = get_app_state(request)
    checks: dict[str, str] = {}
    all_ok = True

    try:
        await state.db.fetchone("SELECT 1")
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "failed"
        all_ok = False

    try:
        await state.redis_client.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "failed"
        all_ok = False

    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"ready": all_ok, "checks": checks},
    )
