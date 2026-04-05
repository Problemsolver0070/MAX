"""Grep/search tool — regex search across files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from max.tools.registry import ToolDefinition

TOOL_DEFINITIONS = [
    ToolDefinition(
        tool_id="grep.search",
        category="code",
        description="Search for a regex pattern across files in a directory.",
        permissions=["fs.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory to search in"},
                "pattern": {"type": "string", "description": "Regex pattern to search for"},
                "glob": {
                    "type": "string",
                    "description": "File glob filter (e.g. '*.py')",
                    "default": "*",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max matches to return",
                    "default": 100,
                },
            },
            "required": ["path", "pattern"],
        },
    ),
]


async def handle_grep_search(inputs: dict[str, Any]) -> dict[str, Any]:
    """Search for a regex pattern across files."""
    base = Path(inputs["path"])
    pattern = re.compile(inputs["pattern"])
    file_glob = inputs.get("glob", "*")
    max_results = inputs.get("max_results", 100)

    matches = []
    for filepath in sorted(base.rglob(file_glob)):
        if not filepath.is_file():
            continue
        try:
            text = filepath.read_text(errors="replace")
        except (PermissionError, OSError):
            continue
        for line_num, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                matches.append(
                    {
                        "file": str(filepath),
                        "line_number": line_num,
                        "line": line.rstrip(),
                    }
                )
                if len(matches) >= max_results:
                    return {"matches": matches}
    return {"matches": matches}
