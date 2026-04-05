"""Git tools — status, diff, commit, log."""

from __future__ import annotations

import asyncio
from typing import Any

from max.tools.registry import ToolDefinition

TOOL_DEFINITIONS = [
    ToolDefinition(
        tool_id="git.status",
        category="code",
        description="Show git working tree status.",
        permissions=["fs.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Repository directory"},
            },
            "required": ["cwd"],
        },
    ),
    ToolDefinition(
        tool_id="git.diff",
        category="code",
        description="Show git diff of staged and unstaged changes.",
        permissions=["fs.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Repository directory"},
                "staged": {
                    "type": "boolean",
                    "description": "Show staged changes only",
                    "default": False,
                },
            },
            "required": ["cwd"],
        },
    ),
    ToolDefinition(
        tool_id="git.log",
        category="code",
        description="Show recent git commit history.",
        permissions=["fs.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Repository directory"},
                "count": {
                    "type": "integer",
                    "description": "Number of commits",
                    "default": 10,
                },
            },
            "required": ["cwd"],
        },
    ),
    ToolDefinition(
        tool_id="git.commit",
        category="code",
        description="Stage files and create a git commit.",
        permissions=["fs.write", "git.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Repository directory"},
                "message": {"type": "string", "description": "Commit message"},
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Files to stage (relative paths)",
                },
            },
            "required": ["cwd", "message", "files"],
        },
    ),
]


async def _run_git(args: list[str], cwd: str) -> dict[str, Any]:
    """Run a git command and return stdout, stderr, exit_code."""
    proc = await asyncio.create_subprocess_exec(
        "git",
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


async def handle_git_status(inputs: dict[str, Any]) -> dict[str, Any]:
    """Show git status."""
    return await _run_git(["status", "--short"], inputs["cwd"])


async def handle_git_diff(inputs: dict[str, Any]) -> dict[str, Any]:
    """Show git diff."""
    args = ["diff"]
    if inputs.get("staged"):
        args.append("--staged")
    return await _run_git(args, inputs["cwd"])


async def handle_git_log(inputs: dict[str, Any]) -> dict[str, Any]:
    """Show git log."""
    count = inputs.get("count", 10)
    return await _run_git(["log", f"--max-count={count}", "--oneline"], inputs["cwd"])


async def handle_git_commit(inputs: dict[str, Any]) -> dict[str, Any]:
    """Stage files and commit."""
    cwd = inputs["cwd"]
    files = inputs["files"]
    message = inputs["message"]

    # Stage files
    add_result = await _run_git(["add"] + files, cwd)
    if add_result["exit_code"] != 0:
        return add_result

    # Commit
    return await _run_git(["commit", "-m", message], cwd)
