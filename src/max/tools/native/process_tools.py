"""Process listing tool."""

from __future__ import annotations

from typing import Any

import psutil

from max.tools.registry import ToolDefinition

TOOL_DEFINITIONS = [
    ToolDefinition(
        tool_id="process.list",
        category="code",
        description="List running processes with PID, name, CPU, and memory info.",
        permissions=["system.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max processes to return",
                    "default": 50,
                },
            },
        },
    ),
]


async def handle_process_list(inputs: dict[str, Any]) -> dict[str, Any]:
    """List running processes."""
    limit = inputs.get("limit", 50)
    processes = []
    for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            info = proc.info
            processes.append(
                {
                    "pid": info["pid"],
                    "name": info["name"],
                    "cpu_percent": info.get("cpu_percent", 0.0),
                    "memory_percent": round(info.get("memory_percent", 0.0), 2),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if len(processes) >= limit:
            break
    return {"processes": processes}
