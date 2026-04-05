"""Shell execution tool — sandboxed command execution."""

from __future__ import annotations

import asyncio
from typing import Any

from max.tools.registry import ToolDefinition

MAX_OUTPUT = 50_000  # 50KB cap matching web tools

TOOL_DEFINITIONS = [
    ToolDefinition(
        tool_id="shell.execute",
        category="code",
        description="Execute a shell command. Returns stdout, stderr, and exit code.",
        permissions=["system.shell"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "cwd": {"type": "string", "description": "Working directory"},
                "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30},
            },
            "required": ["command"],
        },
    ),
]


async def handle_shell_execute(inputs: dict[str, Any]) -> dict[str, Any]:
    """Execute a shell command with timeout."""
    command = inputs["command"]
    cwd = inputs.get("cwd")
    timeout = inputs.get("timeout", 30)

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        stdout_text = stdout.decode(errors="replace")[:MAX_OUTPUT]
        stderr_text = stderr.decode(errors="replace")[:MAX_OUTPUT]
        return {
            "stdout": stdout_text,
            "stderr": stderr_text,
            "exit_code": proc.returncode or 0,
            "error": None,
        }
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return {
            "stdout": "",
            "stderr": "",
            "exit_code": -1,
            "error": f"Command timed out after {timeout}s",
        }
