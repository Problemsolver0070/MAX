"""Git extension tools — clone, branch, push, pr_create."""

from __future__ import annotations

import asyncio
from typing import Any

from max.tools.registry import ToolDefinition

TOOL_DEFINITIONS = [
    ToolDefinition(
        tool_id="git.clone",
        category="code",
        description="Clone a git repository to a target directory.",
        permissions=["git.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Repository URL to clone"},
                "target_dir": {
                    "type": "string",
                    "description": "Directory to clone into",
                },
                "depth": {
                    "type": "integer",
                    "description": "Shallow clone depth (omit for full clone)",
                },
            },
            "required": ["url", "target_dir"],
        },
    ),
    ToolDefinition(
        tool_id="git.branch",
        category="code",
        description="List, create, or switch git branches.",
        permissions=["git.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Repository directory"},
                "action": {
                    "type": "string",
                    "enum": ["list", "create", "switch"],
                    "description": "Branch operation to perform",
                },
                "name": {
                    "type": "string",
                    "description": "Branch name (required for create/switch)",
                },
            },
            "required": ["cwd", "action"],
        },
    ),
    ToolDefinition(
        tool_id="git.push",
        category="code",
        description="Push commits to a remote repository.",
        permissions=["git.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Repository directory"},
                "remote": {
                    "type": "string",
                    "description": "Remote name",
                    "default": "origin",
                },
                "branch": {
                    "type": "string",
                    "description": "Branch to push (omit for current branch)",
                },
                "set_upstream": {
                    "type": "boolean",
                    "description": "Set upstream tracking (-u flag)",
                    "default": False,
                },
            },
            "required": ["cwd"],
        },
    ),
    ToolDefinition(
        tool_id="git.pr_create",
        category="code",
        description="Create a GitHub pull request using the gh CLI.",
        permissions=["git.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Repository directory"},
                "title": {
                    "type": "string",
                    "description": "Pull request title",
                },
                "body": {
                    "type": "string",
                    "description": "Pull request description",
                },
                "base": {
                    "type": "string",
                    "description": "Base branch for the PR (e.g. main)",
                },
            },
            "required": ["cwd", "title"],
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


async def _run_cmd(args: list[str], cwd: str) -> dict[str, Any]:
    """Run an arbitrary command and return stdout, stderr, exit_code."""
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


async def handle_git_clone(inputs: dict[str, Any]) -> dict[str, Any]:
    """Clone a git repository."""
    url = inputs["url"]
    target_dir = inputs["target_dir"]
    depth = inputs.get("depth")

    args = ["clone"]
    if depth is not None:
        args.append(f"--depth={depth}")
    args.extend([url, target_dir])

    # Clone runs from a parent context; use target_dir's parent or "." as cwd.
    # Since target_dir may not exist yet, we use "." as the working directory.
    result = await _run_git(args, ".")
    result["target_dir"] = target_dir
    return result


async def handle_git_branch(inputs: dict[str, Any]) -> dict[str, Any]:
    """List, create, or switch branches."""
    cwd = inputs["cwd"]
    action = inputs["action"]
    name = inputs.get("name")

    if action == "list":
        return await _run_git(["branch"], cwd)
    elif action == "create":
        if not name:
            return {
                "stdout": "",
                "stderr": "Branch name is required for create action",
                "exit_code": 1,
            }
        return await _run_git(["checkout", "-b", name], cwd)
    elif action == "switch":
        if not name:
            return {
                "stdout": "",
                "stderr": "Branch name is required for switch action",
                "exit_code": 1,
            }
        return await _run_git(["checkout", name], cwd)
    else:
        return {
            "stdout": "",
            "stderr": f"Unknown action: {action}",
            "exit_code": 1,
        }


async def handle_git_push(inputs: dict[str, Any]) -> dict[str, Any]:
    """Push to a remote repository."""
    cwd = inputs["cwd"]
    remote = inputs.get("remote", "origin")
    branch = inputs.get("branch")
    set_upstream = inputs.get("set_upstream", False)

    args = ["push"]
    if set_upstream:
        args.append("-u")
    if branch:
        args.extend([remote, branch])
    return await _run_git(args, cwd)


async def handle_git_pr_create(inputs: dict[str, Any]) -> dict[str, Any]:
    """Create a GitHub pull request using gh CLI."""
    cwd = inputs["cwd"]
    title = inputs["title"]
    body = inputs.get("body", "")
    base = inputs.get("base")

    args = ["gh", "pr", "create", "--title", title, "--body", body]
    if base:
        args.extend(["--base", base])
    return await _run_cmd(args, cwd)
