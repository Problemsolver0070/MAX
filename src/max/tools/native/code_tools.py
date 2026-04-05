"""Code analysis tools — AST parsing, linting, formatting, testing, dependency analysis."""

from __future__ import annotations

import ast
import asyncio
import sys
from typing import Any

from max.tools.registry import ToolDefinition

TOOL_DEFINITIONS = [
    ToolDefinition(
        tool_id="code.ast_parse",
        category="code",
        description="Parse a Python file and return its functions, classes, and imports.",
        permissions=["fs.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the Python file"},
            },
            "required": ["path"],
        },
    ),
    ToolDefinition(
        tool_id="code.lint",
        category="code",
        description="Run ruff check on a Python file or directory.",
        permissions=["fs.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or directory to lint"},
            },
            "required": ["path"],
        },
    ),
    ToolDefinition(
        tool_id="code.format",
        category="code",
        description="Run ruff format on a Python file or directory.",
        permissions=["fs.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or directory to format"},
            },
            "required": ["path"],
        },
    ),
    ToolDefinition(
        tool_id="code.test",
        category="code",
        description="Run pytest on a file or directory with short traceback and quiet output.",
        permissions=["fs.read", "system.shell"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Test file or directory"},
            },
            "required": ["path"],
        },
    ),
    ToolDefinition(
        tool_id="code.dependencies",
        category="code",
        description="Parse a Python file's imports and categorize them as stdlib or third-party.",
        permissions=["fs.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the Python file"},
            },
            "required": ["path"],
        },
    ),
]


MAX_OUTPUT = 50_000  # 50 KB cap for subprocess output


async def _run_cmd(cmd: list[str]) -> dict[str, Any]:
    """Run a subprocess command and return stdout, stderr, exit_code."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return {
        "stdout": stdout.decode(errors="replace")[:MAX_OUTPUT],
        "stderr": stderr.decode(errors="replace")[:MAX_OUTPUT],
        "exit_code": proc.returncode or 0,
    }


async def handle_code_ast_parse(inputs: dict[str, Any]) -> dict[str, Any]:
    """Parse a Python file and extract functions, classes, and imports."""
    path = inputs["path"]
    try:
        with open(path) as f:
            source = f.read()
    except FileNotFoundError:
        return {"error": f"File not found: {path}"}
    except OSError as exc:
        return {"error": f"Cannot read file: {exc}"}

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return {"error": f"Syntax error: {exc}"}

    functions: list[str] = []
    classes: list[str] = []
    imports: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            functions.append(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)

    return {
        "functions": functions,
        "classes": classes,
        "imports": imports,
    }


async def handle_code_lint(inputs: dict[str, Any]) -> dict[str, Any]:
    """Run ruff check on a path."""
    return await _run_cmd(["ruff", "check", inputs["path"]])


async def handle_code_format(inputs: dict[str, Any]) -> dict[str, Any]:
    """Run ruff format on a path."""
    return await _run_cmd(["ruff", "format", inputs["path"]])


async def handle_code_test(inputs: dict[str, Any]) -> dict[str, Any]:
    """Run pytest on a path."""
    return await _run_cmd([sys.executable, "-m", "pytest", inputs["path"], "--tb=short", "-q"])


async def handle_code_dependencies(inputs: dict[str, Any]) -> dict[str, Any]:
    """Analyze imports in a Python file and categorize as stdlib or third-party."""
    path = inputs["path"]
    try:
        with open(path) as f:
            source = f.read()
    except FileNotFoundError:
        return {"error": f"File not found: {path}"}
    except OSError as exc:
        return {"error": f"Cannot read file: {exc}"}

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return {"error": f"Syntax error: {exc}"}

    stdlib_names = sys.stdlib_module_names
    stdlib: list[str] = []
    third_party: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_level = alias.name.split(".")[0]
                if top_level in stdlib_names:
                    stdlib.append(alias.name)
                else:
                    third_party.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top_level = node.module.split(".")[0]
                if top_level in stdlib_names:
                    stdlib.append(node.module)
                else:
                    third_party.append(node.module)

    return {
        "stdlib": stdlib,
        "third_party": third_party,
    }
