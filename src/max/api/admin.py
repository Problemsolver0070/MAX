"""Admin endpoints — evolution control and sentinel triggers."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from max.api.auth import verify_api_key
from max.api.dependencies import AppState, get_app_state

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.post("/evolution/freeze")
async def freeze_evolution(
    app_state: AppState = Depends(get_app_state),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """Manually freeze evolution — no new experiments will start."""
    await app_state.bus.publish("evolution.freeze", {"source": "admin_api"})
    return {"status": "freeze_requested"}


@router.post("/evolution/unfreeze")
async def unfreeze_evolution(
    app_state: AppState = Depends(get_app_state),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """Manually unfreeze evolution — resume experiments."""
    await app_state.bus.publish("evolution.unfreeze", {"source": "admin_api"})
    return {"status": "unfreeze_requested"}


@router.post("/sentinel/run")
async def trigger_sentinel(
    app_state: AppState = Depends(get_app_state),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """Manually trigger a sentinel monitoring run."""
    await app_state.bus.publish("sentinel.run_request", {"source": "admin_api", "scheduled": False})
    return {"status": "sentinel_run_requested"}
