"""Introspection endpoints — read-only views into Max's state."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from max.api.auth import verify_api_key
from max.api.dependencies import AppState, get_app_state

router = APIRouter(prefix="/api/v1", tags=["introspection"])


@router.get("/tasks")
async def list_tasks(
    app_state: AppState = Depends(get_app_state),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """List active (non-terminal) tasks."""
    tasks = await app_state.task_store.get_active_tasks()
    return {"tasks": tasks}


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: uuid.UUID,
    app_state: AppState = Depends(get_app_state),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """Get a task with its subtasks."""
    task = await app_state.task_store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    subtasks = await app_state.task_store.get_subtasks(task_id)
    return {**task, "subtasks": subtasks}


@router.get("/evolution")
async def evolution_state(
    app_state: AppState = Depends(get_app_state),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """View evolution system state: proposals and journal."""
    proposals = await app_state.evolution_store.get_proposals()
    journal = await app_state.evolution_store.get_journal(limit=20)
    return {"proposals": proposals, "journal": journal}


@router.get("/sentinel")
async def sentinel_state(
    app_state: AppState = Depends(get_app_state),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """View recent sentinel test runs."""
    runs = await app_state.sentinel_store.get_test_runs(limit=10)
    return {"test_runs": runs}


@router.get("/dead-letters")
async def dead_letters(
    channel: str = "dead_letter",
    count: int = 100,
    app_state: AppState = Depends(get_app_state),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """View dead-lettered messages from the bus."""
    if app_state.transport is None:
        return {"dead_letters": []}

    entries = await app_state.transport.get_dead_letters(channel, count=count)
    return {"dead_letters": entries}
