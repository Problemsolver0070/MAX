"""File system tools — read, write, edit, list, glob, delete."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from max.tools.registry import ToolDefinition

TOOL_DEFINITIONS = [
    ToolDefinition(
        tool_id="file.read",
        category="code",
        description="Read a file's contents. Supports optional line offset and limit.",
        permissions=["fs.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute file path"},
                "offset": {"type": "integer", "description": "Line offset (0-based)", "default": 0},
                "limit": {"type": "integer", "description": "Max lines to read", "default": 0},
            },
            "required": ["path"],
        },
    ),
    ToolDefinition(
        tool_id="file.write",
        category="code",
        description="Write content to a file. Creates parent directories if needed.",
        permissions=["fs.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute file path"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        },
    ),
    ToolDefinition(
        tool_id="file.edit",
        category="code",
        description="Search and replace text in a file.",
        permissions=["fs.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute file path"},
                "old_string": {"type": "string", "description": "Text to find"},
                "new_string": {"type": "string", "description": "Replacement text"},
            },
            "required": ["path", "old_string", "new_string"],
        },
    ),
    ToolDefinition(
        tool_id="directory.list",
        category="code",
        description="List directory contents with file metadata.",
        permissions=["fs.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute directory path"},
            },
            "required": ["path"],
        },
    ),
    ToolDefinition(
        tool_id="file.glob",
        category="code",
        description="Search for files matching a glob pattern.",
        permissions=["fs.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Base directory"},
                "pattern": {"type": "string", "description": "Glob pattern (e.g. '*.py')"},
            },
            "required": ["path", "pattern"],
        },
    ),
    ToolDefinition(
        tool_id="file.delete",
        category="code",
        description="Delete a file or empty directory.",
        permissions=["fs.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute file path"},
            },
            "required": ["path"],
        },
    ),
]


async def handle_file_read(inputs: dict[str, Any]) -> dict[str, Any]:
    """Read a file, optionally with line offset and limit."""
    path = Path(inputs["path"])
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    text = path.read_text()
    offset = inputs.get("offset", 0)
    limit = inputs.get("limit", 0)

    if offset or limit:
        lines = text.splitlines(keepends=True)
        if limit:
            lines = lines[offset : offset + limit]
        else:
            lines = lines[offset:]
        text = "".join(lines)

    return {"content": text, "size": path.stat().st_size}


async def handle_file_write(inputs: dict[str, Any]) -> dict[str, Any]:
    """Write content to a file, creating parent dirs if needed."""
    path = Path(inputs["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    content = inputs["content"]
    path.write_text(content)
    return {"bytes_written": len(content.encode())}


async def handle_file_edit(inputs: dict[str, Any]) -> dict[str, Any]:
    """Search and replace text in a file."""
    path = Path(inputs["path"])
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    text = path.read_text()
    old_string = inputs["old_string"]
    new_string = inputs["new_string"]
    count = text.count(old_string)
    if count > 0:
        text = text.replace(old_string, new_string)
        path.write_text(text)
    return {"replacements": count}


async def handle_directory_list(inputs: dict[str, Any]) -> dict[str, Any]:
    """List directory contents with metadata."""
    path = Path(inputs["path"])
    if not path.is_dir():
        raise NotADirectoryError(f"Not a directory: {path}")

    entries = []
    for entry in sorted(path.iterdir()):
        stat = entry.stat()
        entries.append(
            {
                "name": entry.name,
                "type": "directory" if entry.is_dir() else "file",
                "size": stat.st_size if entry.is_file() else 0,
            }
        )
    return {"entries": entries}


async def handle_file_glob(inputs: dict[str, Any]) -> dict[str, Any]:
    """Search for files matching a glob pattern."""
    base = Path(inputs["path"])
    pattern = inputs["pattern"]
    matches = sorted(str(p) for p in base.glob(pattern))
    return {"matches": matches}


async def handle_file_delete(inputs: dict[str, Any]) -> dict[str, Any]:
    """Delete a file or empty directory."""
    path = Path(inputs["path"])
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if path.is_dir():
        path.rmdir()  # Only works on empty directories
    else:
        path.unlink()
    return {"deleted": True}
