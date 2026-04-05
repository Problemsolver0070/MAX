"""Server/SSH tools — system info, SSH execution, and service status."""

from __future__ import annotations

import asyncio
import platform
from typing import Any

import psutil

from max.tools.registry import ToolDefinition

try:
    import asyncssh

    HAS_ASYNCSSH = True
except ImportError:
    asyncssh = None  # type: ignore[assignment]
    HAS_ASYNCSSH = False

# 50KB output cap for SSH and service commands
_OUTPUT_CAP = 50_000

TOOL_DEFINITIONS = [
    ToolDefinition(
        tool_id="server.system_info",
        category="infrastructure",
        description="Get system information including CPU, memory, disk, and platform details.",
        permissions=["system.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {},
        },
    ),
    ToolDefinition(
        tool_id="server.ssh_execute",
        category="infrastructure",
        description="Execute a command on a remote host via SSH.",
        permissions=["ssh.execute"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Remote host to connect to",
                },
                "command": {
                    "type": "string",
                    "description": "Command to execute on the remote host",
                },
                "port": {
                    "type": "integer",
                    "description": "SSH port",
                    "default": 22,
                },
                "username": {
                    "type": "string",
                    "description": "SSH username",
                },
                "password": {
                    "type": "string",
                    "description": "SSH password (prefer key_file instead)",
                },
                "key_file": {
                    "type": "string",
                    "description": "Path to SSH private key file",
                },
            },
            "required": ["host", "command"],
        },
    ),
    ToolDefinition(
        tool_id="server.service_status",
        category="infrastructure",
        description="Check the status of a systemd service.",
        permissions=["system.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "service_name": {
                    "type": "string",
                    "description": "Name of the systemd service to check",
                },
            },
            "required": ["service_name"],
        },
    ),
]


def _check_asyncssh() -> dict[str, Any] | None:
    """Return error dict if asyncssh library is not available, None otherwise."""
    if not HAS_ASYNCSSH:
        return {"error": "asyncssh library is not installed. Install it with: pip install asyncssh"}
    return None


async def handle_server_system_info(inputs: dict[str, Any]) -> dict[str, Any]:
    """Get system information using psutil and platform."""
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    return {
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "cpu_count": psutil.cpu_count(),
        "memory": {
            "total": mem.total,
            "used": mem.used,
            "available": mem.available,
            "percent": mem.percent,
        },
        "disk": {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "percent": disk.percent,
        },
        "boot_time": psutil.boot_time(),
        "platform": platform.system(),
        "hostname": platform.node(),
    }


async def handle_server_ssh_execute(inputs: dict[str, Any]) -> dict[str, Any]:
    """Execute a command on a remote host via SSH."""
    err = _check_asyncssh()
    if err:
        return err

    host = inputs["host"]
    command = inputs["command"]
    port = inputs.get("port", 22)
    username = inputs.get("username")
    password = inputs.get("password")
    key_file = inputs.get("key_file")

    connect_kwargs: dict[str, Any] = {
        "host": host,
        "port": port,
        "known_hosts": None,
    }
    if username is not None:
        connect_kwargs["username"] = username
    if password is not None:
        connect_kwargs["password"] = password
    if key_file is not None:
        connect_kwargs["client_keys"] = [key_file]

    async with asyncssh.connect(**connect_kwargs) as conn:
        result = await conn.run(command)

    stdout = (result.stdout or "")[:_OUTPUT_CAP]
    stderr = (result.stderr or "")[:_OUTPUT_CAP]

    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": result.exit_status or 0,
    }


async def handle_server_service_status(inputs: dict[str, Any]) -> dict[str, Any]:
    """Check the status of a systemd service."""
    service_name = inputs["service_name"]

    proc = await asyncio.create_subprocess_exec(
        "systemctl",
        "is-active",
        service_name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()

    stdout = stdout_bytes.decode(errors="replace")[:_OUTPUT_CAP]
    stderr = stderr_bytes.decode(errors="replace")[:_OUTPUT_CAP]
    exit_code = proc.returncode or 0

    # systemctl is-active returns "active" on stdout when service is running
    active = stdout.strip() == "active"

    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "active": active,
    }
