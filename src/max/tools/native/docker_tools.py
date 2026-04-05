"""Docker tools — containers, images, and compose."""

from __future__ import annotations

import asyncio
from typing import Any

from max.tools.registry import ToolDefinition

try:
    import docker

    HAS_DOCKER = True
except ImportError:
    docker = None  # type: ignore[assignment]
    HAS_DOCKER = False

TOOL_DEFINITIONS = [
    ToolDefinition(
        tool_id="docker.list_containers",
        category="infrastructure",
        description="List Docker containers with ID, name, image, and status.",
        permissions=["docker.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "all": {
                    "type": "boolean",
                    "description": "Include stopped containers",
                    "default": False,
                },
            },
        },
    ),
    ToolDefinition(
        tool_id="docker.run",
        category="infrastructure",
        description="Run a Docker container from an image.",
        permissions=["docker.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "image": {"type": "string", "description": "Docker image to run"},
                "command": {
                    "type": "string",
                    "description": "Command to run in the container",
                },
                "name": {
                    "type": "string",
                    "description": "Container name",
                },
                "detach": {
                    "type": "boolean",
                    "description": "Run container in detached mode",
                    "default": True,
                },
                "ports": {
                    "type": "object",
                    "description": "Port mappings (e.g. {'8080/tcp': 8080})",
                },
                "environment": {
                    "type": "object",
                    "description": "Environment variables",
                },
            },
            "required": ["image"],
        },
    ),
    ToolDefinition(
        tool_id="docker.stop",
        category="infrastructure",
        description="Stop a running Docker container.",
        permissions=["docker.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "container_id": {
                    "type": "string",
                    "description": "Container ID or name",
                },
            },
            "required": ["container_id"],
        },
    ),
    ToolDefinition(
        tool_id="docker.logs",
        category="infrastructure",
        description="Get logs from a Docker container.",
        permissions=["docker.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "container_id": {
                    "type": "string",
                    "description": "Container ID or name",
                },
                "tail": {
                    "type": "integer",
                    "description": "Number of lines from the end",
                    "default": 100,
                },
            },
            "required": ["container_id"],
        },
    ),
    ToolDefinition(
        tool_id="docker.build",
        category="infrastructure",
        description="Build a Docker image from a Dockerfile.",
        permissions=["docker.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the build context directory",
                },
                "tag": {
                    "type": "string",
                    "description": "Image tag (e.g. myapp:latest)",
                },
            },
            "required": ["path", "tag"],
        },
    ),
    ToolDefinition(
        tool_id="docker.compose",
        category="infrastructure",
        description="Run docker compose commands (up, down, ps).",
        permissions=["docker.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Compose action: up, down, or ps",
                    "enum": ["up", "down", "ps"],
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory containing compose file",
                },
                "file": {
                    "type": "string",
                    "description": "Compose file name (default: docker-compose.yml)",
                },
            },
            "required": ["action", "cwd"],
        },
    ),
]


def _check_docker() -> None:
    """Raise RuntimeError if docker library is not available."""
    if not HAS_DOCKER:
        raise RuntimeError(
            "Docker Python library is not installed. "
            "Install it with: pip install docker"
        )


def _get_client() -> Any:
    """Create a Docker client from environment."""
    _check_docker()
    return docker.from_env()


async def handle_docker_list_containers(inputs: dict[str, Any]) -> dict[str, Any]:
    """List Docker containers."""
    _check_docker()
    show_all = inputs.get("all", False)
    loop = asyncio.get_event_loop()
    client = await loop.run_in_executor(None, _get_client)
    try:
        containers_raw = await loop.run_in_executor(
            None, lambda: client.containers.list(all=show_all)
        )
        containers = []
        for c in containers_raw:
            containers.append(
                {
                    "id": c.short_id,
                    "name": c.name,
                    "image": str(c.image.tags[0]) if c.image.tags else str(c.image.id),
                    "status": c.status,
                }
            )
        return {"containers": containers}
    finally:
        await loop.run_in_executor(None, client.close)


async def handle_docker_run(inputs: dict[str, Any]) -> dict[str, Any]:
    """Run a Docker container."""
    _check_docker()
    image = inputs["image"]
    command = inputs.get("command")
    name = inputs.get("name")
    detach = inputs.get("detach", True)
    ports = inputs.get("ports")
    environment = inputs.get("environment")

    loop = asyncio.get_event_loop()
    client = await loop.run_in_executor(None, _get_client)
    try:
        kwargs: dict[str, Any] = {
            "image": image,
            "detach": detach,
        }
        if command is not None:
            kwargs["command"] = command
        if name is not None:
            kwargs["name"] = name
        if ports is not None:
            kwargs["ports"] = ports
        if environment is not None:
            kwargs["environment"] = environment

        container = await loop.run_in_executor(
            None, lambda: client.containers.run(**kwargs)
        )
        return {
            "container_id": container.short_id,
            "name": container.name,
        }
    finally:
        await loop.run_in_executor(None, client.close)


async def handle_docker_stop(inputs: dict[str, Any]) -> dict[str, Any]:
    """Stop a Docker container."""
    _check_docker()
    container_id = inputs["container_id"]

    loop = asyncio.get_event_loop()
    client = await loop.run_in_executor(None, _get_client)
    try:
        container = await loop.run_in_executor(
            None, lambda: client.containers.get(container_id)
        )
        await loop.run_in_executor(None, container.stop)
        return {"stopped": True}
    finally:
        await loop.run_in_executor(None, client.close)


async def handle_docker_logs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Get container logs."""
    _check_docker()
    container_id = inputs["container_id"]
    tail = inputs.get("tail", 100)

    loop = asyncio.get_event_loop()
    client = await loop.run_in_executor(None, _get_client)
    try:
        container = await loop.run_in_executor(
            None, lambda: client.containers.get(container_id)
        )
        raw_logs = await loop.run_in_executor(
            None, lambda: container.logs(tail=tail)
        )
        # raw_logs is bytes; decode and cap at 50KB
        logs_str = raw_logs.decode(errors="replace")[:50000]
        return {"logs": logs_str}
    finally:
        await loop.run_in_executor(None, client.close)


async def handle_docker_build(inputs: dict[str, Any]) -> dict[str, Any]:
    """Build a Docker image."""
    _check_docker()
    path = inputs["path"]
    tag = inputs["tag"]

    loop = asyncio.get_event_loop()
    client = await loop.run_in_executor(None, _get_client)
    try:
        image, _build_logs = await loop.run_in_executor(
            None, lambda: client.images.build(path=path, tag=tag)
        )
        return {
            "image_id": image.short_id,
            "tag": tag,
        }
    finally:
        await loop.run_in_executor(None, client.close)


async def handle_docker_compose(inputs: dict[str, Any]) -> dict[str, Any]:
    """Run docker compose commands using asyncio subprocess."""
    action = inputs["action"]
    cwd = inputs["cwd"]
    compose_file = inputs.get("file")

    args = ["docker", "compose"]
    if compose_file:
        args.extend(["-f", compose_file])

    if action == "up":
        args.extend(["up", "-d"])
    elif action == "down":
        args.append("down")
    elif action == "ps":
        args.append("ps")
    else:
        return {"stdout": "", "stderr": f"Unknown action: {action}", "exit_code": 1}

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout, stderr = await proc.communicate()
    return {
        "stdout": stdout.decode(errors="replace"),
        "stderr": stderr.decode(errors="replace"),
        "exit_code": proc.returncode or 0,
    }
