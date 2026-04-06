"""Task recovery — re-queue orphaned in-flight tasks after a restart."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from max.api.dependencies import AppState

logger = logging.getLogger(__name__)

# Map task status to the bus channel for recovery
_RECOVERY_CHANNELS: dict[str, str] = {
    "planned": "tasks.execute",
    "executing": "tasks.execute",
    "auditing": "audit.request",
}


async def recover_orphaned_tasks(state: AppState) -> int:
    """Find in-flight tasks from a previous run and re-publish them.

    Returns the number of tasks recovered.
    """
    active_tasks = await state.task_store.get_active_tasks()
    recovered = 0

    for task in active_tasks:
        status = task.get("status", "")
        channel = _RECOVERY_CHANNELS.get(status)

        if channel is None:
            continue

        task_id = str(task["id"])
        await state.bus.publish(channel, {"task_id": task_id, "recovery": True})
        recovered += 1
        logger.info("Recovered orphaned task %s (status=%s) → %s", task_id, status, channel)

    if recovered:
        logger.info("Recovered %d orphaned task(s)", recovered)

    return recovered
