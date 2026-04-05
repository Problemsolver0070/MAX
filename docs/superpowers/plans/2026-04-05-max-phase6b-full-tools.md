# Phase 6B: Full Tool Arsenal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 65 new native tools across 12 categories plus an OpenAPI auto-import provider, bringing total tool count to 80.

**Architecture:** Each tool module follows the Phase 6A pattern — `TOOL_DEFINITIONS` list + handler functions + registration in `__init__.py`. External deps use graceful imports with `HAS_<LIB>` flags.

**Tech Stack:** Python 3.12+, asyncio, pydantic v2, optional deps (playwright, boto3, docker, polars, Pillow, etc.)

**Spec:** `docs/superpowers/specs/2026-04-05-max-phase6b-full-tools.md`

---

### Task 1: Config additions + dependency groups

**Files:**
- Modify: `src/max/config.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add config fields to Settings**

Add these fields to the `Settings` class in `src/max/config.py` after the existing tool settings (around line 88):

```python
    # Email (SMTP/IMAP)
    email_smtp_host: str = ""
    email_smtp_port: int = 587
    email_imap_host: str = ""
    email_user: str = ""
    email_password: str = ""

    # Calendar (CalDAV)
    caldav_url: str = ""
    caldav_user: str = ""
    caldav_password: str = ""

    # Web search
    brave_search_api_key: str = ""

    # Browser
    browser_headless: bool = True
    browser_max_pages: int = 5
```

- [ ] **Step 2: Add optional dependency groups to pyproject.toml**

Add these optional dependency groups after the existing `dev` group:

```toml
browser = ["playwright>=1.49"]
aws = ["boto3>=1.35"]
docker = ["docker>=7.1"]
documents = ["PyPDF2>=3.0", "openpyxl>=3.1", "jsonpath-ng>=1.6"]
data = ["polars>=1.0"]
media = ["Pillow>=11.0"]
email-tools = ["aiosmtplib>=3.0", "aioimaplib>=2.0"]
calendar-tools = ["icalendar>=6.0", "caldav>=1.4"]
scraping = ["beautifulsoup4>=4.12"]
ssh = ["asyncssh>=2.17"]
openapi = ["pyyaml>=6.0"]
all-tools = [
    "max[browser,aws,docker,documents,data,media,email-tools,calendar-tools,scraping,ssh,openapi]"
]
```

Also add `aiosqlite>=0.20` to the main dependencies list (needed for SQLite async support, lightweight enough to be non-optional).

- [ ] **Step 3: Verify config loads**

Run: `cd /home/venu/Desktop/everactive/.claude/worktrees/phase6b-full-tools && python -c "from max.config import Settings; s = Settings(); print('email_smtp_host:', s.email_smtp_host)"`
Expected: `email_smtp_host: `

- [ ] **Step 4: Run existing tests**

Run: `python -m pytest tests/ --tb=short -q`
Expected: All 465 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/max/config.py pyproject.toml
git commit -m "feat(tools): add Phase 6B config fields and optional dependency groups"
```

---

### Task 2: Code Analysis Tools (5 tools)

**Files:**
- Create: `src/max/tools/native/code_tools.py`
- Create: `tests/test_code_tools.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for code analysis tools."""

import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from max.tools.native.code_tools import (
    TOOL_DEFINITIONS,
    handle_ast_parse,
    handle_code_dependencies,
    handle_code_format,
    handle_code_lint,
    handle_code_test,
)


class TestAstParse:
    async def test_parses_python_file(self, tmp_path: Path):
        f = tmp_path / "example.py"
        f.write_text(
            textwrap.dedent("""\
            import os

            def hello(name: str) -> str:
                return f"Hello {name}"

            class Greeter:
                pass
            """)
        )
        result = await handle_ast_parse({"path": str(f)})
        assert result["functions"] == ["hello"]
        assert result["classes"] == ["Greeter"]
        assert "os" in result["imports"]

    async def test_nonexistent_file(self):
        result = await handle_ast_parse({"path": "/no/such/file.py"})
        assert "error" in result

    async def test_syntax_error(self, tmp_path: Path):
        f = tmp_path / "bad.py"
        f.write_text("def broken(:\n")
        result = await handle_ast_parse({"path": str(f)})
        assert "error" in result


class TestCodeLint:
    async def test_lint_clean_file(self, tmp_path: Path):
        f = tmp_path / "clean.py"
        f.write_text("x = 1\n")
        result = await handle_code_lint({"path": str(f)})
        assert result["exit_code"] == 0

    async def test_lint_returns_output(self, tmp_path: Path):
        f = tmp_path / "messy.py"
        f.write_text("import os\nimport sys\nx=1\n")
        result = await handle_code_lint({"path": str(f)})
        assert "stdout" in result


class TestCodeFormat:
    async def test_format_file(self, tmp_path: Path):
        f = tmp_path / "ugly.py"
        f.write_text("x=1\ny  =  2\n")
        result = await handle_code_format({"path": str(f)})
        assert result["exit_code"] == 0


class TestCodeTest:
    async def test_run_passing_test(self, tmp_path: Path):
        f = tmp_path / "test_ok.py"
        f.write_text("def test_pass():\n    assert True\n")
        result = await handle_code_test({"path": str(f)})
        assert result["exit_code"] == 0
        assert "passed" in result["stdout"].lower()

    async def test_run_failing_test(self, tmp_path: Path):
        f = tmp_path / "test_fail.py"
        f.write_text("def test_fail():\n    assert False\n")
        result = await handle_code_test({"path": str(f)})
        assert result["exit_code"] != 0


class TestCodeDependencies:
    async def test_analyzes_imports(self, tmp_path: Path):
        f = tmp_path / "mod.py"
        f.write_text(
            textwrap.dedent("""\
            import os
            import json
            from pathlib import Path
            from max.tools.registry import ToolDefinition
            """)
        )
        result = await handle_code_dependencies({"path": str(f)})
        assert "os" in result["stdlib"]
        assert "max.tools.registry" in result["third_party"]

    async def test_nonexistent(self):
        result = await handle_code_dependencies({"path": "/no/file.py"})
        assert "error" in result


class TestToolDefinitions:
    def test_has_five_tools(self):
        assert len(TOOL_DEFINITIONS) == 5

    def test_all_code_category(self):
        for td in TOOL_DEFINITIONS:
            assert td.category == "code"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_code_tools.py -v`
Expected: ImportError — module does not exist yet.

- [ ] **Step 3: Implement code_tools.py**

Create `src/max/tools/native/code_tools.py`:

```python
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
        description="Parse a Python source file and return its structure (functions, classes, imports).",
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
        description="Run ruff linter on a file or directory.",
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
        description="Format Python code with ruff format.",
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
        description="Run pytest on a file or directory.",
        permissions=["fs.read", "process.execute"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Test file or directory"},
                "verbose": {
                    "type": "boolean",
                    "description": "Verbose output",
                    "default": False,
                },
            },
            "required": ["path"],
        },
    ),
    ToolDefinition(
        tool_id="code.dependencies",
        category="code",
        description="Analyze imports in a Python file and categorize as stdlib or third-party.",
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


async def _run_cmd(cmd: list[str]) -> dict[str, Any]:
    """Run a subprocess command and return stdout, stderr, exit_code."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return {
        "stdout": stdout.decode(errors="replace"),
        "stderr": stderr.decode(errors="replace"),
        "exit_code": proc.returncode or 0,
    }


async def handle_ast_parse(inputs: dict[str, Any]) -> dict[str, Any]:
    """Parse Python file to AST and extract structure."""
    from pathlib import Path

    path = Path(inputs["path"])
    if not path.exists():
        return {"error": f"File not found: {path}"}

    try:
        source = path.read_text()
        tree = ast.parse(source)
    except SyntaxError as e:
        return {"error": f"Syntax error: {e}"}

    functions = []
    classes = []
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

    return {"functions": functions, "classes": classes, "imports": imports}


async def handle_code_lint(inputs: dict[str, Any]) -> dict[str, Any]:
    """Run ruff linter."""
    return await _run_cmd(["ruff", "check", inputs["path"]])


async def handle_code_format(inputs: dict[str, Any]) -> dict[str, Any]:
    """Format code with ruff."""
    return await _run_cmd(["ruff", "format", inputs["path"]])


async def handle_code_test(inputs: dict[str, Any]) -> dict[str, Any]:
    """Run pytest."""
    cmd = [sys.executable, "-m", "pytest", inputs["path"], "--tb=short", "-q"]
    if inputs.get("verbose"):
        cmd.append("-v")
    return await _run_cmd(cmd)


async def handle_code_dependencies(inputs: dict[str, Any]) -> dict[str, Any]:
    """Analyze imports and categorize them."""
    from pathlib import Path

    path = Path(inputs["path"])
    if not path.exists():
        return {"error": f"File not found: {path}"}

    try:
        source = path.read_text()
        tree = ast.parse(source)
    except SyntaxError as e:
        return {"error": f"Syntax error: {e}"}

    stdlib_modules = set(sys.stdlib_module_names)
    stdlib: list[str] = []
    third_party: list[str] = []

    for node in ast.walk(tree):
        module_name = None
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_name = alias.name
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module

        if module_name:
            top_level = module_name.split(".")[0]
            if top_level in stdlib_modules:
                stdlib.append(module_name)
            else:
                third_party.append(module_name)

    return {"stdlib": stdlib, "third_party": third_party}
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_code_tools.py -v`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/max/tools/native/code_tools.py tests/test_code_tools.py
git commit -m "feat(tools): add code analysis tools (ast, lint, format, test, deps)"
```

---

### Task 3: Database Tools (6 tools)

**Files:**
- Create: `src/max/tools/native/database_tools.py`
- Create: `tests/test_database_tools.py`

- [ ] **Step 1: Write tests**

Test `handle_sqlite_query` and `handle_sqlite_execute` with real SQLite via `tmp_path`. Test `handle_postgres_query`, `handle_postgres_execute`, `handle_redis_get`, `handle_redis_set` with mocked clients. Test missing-dep case for aiosqlite. Verify 6 tool definitions, all category "database".

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement database_tools.py**

6 handlers using:
- `asyncpg` for PostgreSQL (existing dep) — `handle_postgres_query`, `handle_postgres_execute`
- `aiosqlite` for SQLite (optional) — `handle_sqlite_query`, `handle_sqlite_execute`
- `redis.asyncio` for Redis (existing dep) — `handle_redis_get`, `handle_redis_set`

Each handler takes connection params in `inputs` dict. Postgres/Redis handlers accept `connection_string` param. SQLite handlers accept `database` (file path).

The `_run_cmd` helper pattern from git_tools is NOT used here — these use their respective async clients directly.

Key implementation details:
- `handle_postgres_query`: `asyncpg.connect(dsn)` → `conn.fetch(query)` → return rows as list of dicts
- `handle_postgres_execute`: same but `conn.execute(query)` → return affected row count
- `handle_sqlite_query`: `aiosqlite.connect(db_path)` → `cursor.execute(query)` → `fetchall()` → return rows
- `handle_sqlite_execute`: same but return `cursor.rowcount`
- `handle_redis_get`: `redis.from_url(url)` → `client.get(key)` or `client.mget(keys)`
- `handle_redis_set`: `redis.from_url(url)` → `client.set(key, value, ex=ttl)`

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Commit**

```bash
git add src/max/tools/native/database_tools.py tests/test_database_tools.py
git commit -m "feat(tools): add database tools (postgres, sqlite, redis)"
```

---

### Task 4: Document Tools (5 tools)

**Files:**
- Create: `src/max/tools/native/document_tools.py`
- Create: `tests/test_document_tools.py`

- [ ] **Step 1: Write tests**

Test `handle_read_spreadsheet` and `handle_write_csv` with real CSV files via `tmp_path`. Test `handle_read_pdf` with mocked PyPDF2. Test `handle_write_spreadsheet` with mocked openpyxl. Test `handle_parse_json` with real JSON files. Test missing-dep cases. Verify 5 tool definitions.

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement document_tools.py**

5 handlers:
- `handle_read_pdf`: optional PyPDF2 → extract text from pages
- `handle_read_spreadsheet`: optional openpyxl for xlsx, stdlib csv for csv → return rows as list of dicts
- `handle_write_csv`: stdlib csv → write records to file
- `handle_write_spreadsheet`: optional openpyxl → write records to xlsx
- `handle_parse_json`: stdlib json → read JSON file, optional JSONPath query

Key: CSV reading/writing uses stdlib only (no optional dep needed). For spreadsheets, the xlsx format needs openpyxl.

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Commit**

```bash
git add src/max/tools/native/document_tools.py tests/test_document_tools.py
git commit -m "feat(tools): add document tools (pdf, spreadsheet, csv, json)"
```

---

### Task 5: Docker Tools (6 tools)

**Files:**
- Create: `src/max/tools/native/docker_tools.py`
- Create: `tests/test_docker_tools.py`

- [ ] **Step 1: Write tests**

All Docker tests mock `docker.from_env()` — no real Docker daemon needed. Test each handler returns expected format. Test missing-dep case. `handle_docker_compose` uses `asyncio.create_subprocess_exec` — mock that. Verify 6 tool definitions, category "infrastructure".

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement docker_tools.py**

6 handlers:
- `handle_docker_list_containers`: `docker.from_env().containers.list(all=...)` → return name, image, status, id
- `handle_docker_run`: `client.containers.run(image, command, detach=True, ...)` → return container id
- `handle_docker_stop`: `client.containers.get(id).stop()`
- `handle_docker_logs`: `client.containers.get(id).logs(tail=...)` → return decoded string, 50KB cap
- `handle_docker_build`: `client.images.build(path=..., tag=...)` → return image id
- `handle_docker_compose`: `asyncio.create_subprocess_exec("docker", "compose", action, ...)` — action is up/down/ps

All use `HAS_DOCKER` guard except compose (uses subprocess).

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Commit**

```bash
git add src/max/tools/native/docker_tools.py tests/test_docker_tools.py
git commit -m "feat(tools): add docker tools (containers, build, compose)"
```

---

### Task 6: AWS Tools (8 tools)

**Files:**
- Create: `src/max/tools/native/aws_tools.py`
- Create: `tests/test_aws_tools.py`

- [ ] **Step 1: Write tests**

All AWS tests mock boto3 clients. Test each handler returns expected format. Test missing-dep case. Verify 8 tool definitions, category "cloud".

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement aws_tools.py**

8 handlers using `boto3.client(service)`:
- S3: `handle_s3_list` (list_buckets/list_objects_v2), `handle_s3_get` (get_object → body.read()), `handle_s3_put` (put_object), `handle_s3_delete` (delete_object)
- EC2: `handle_ec2_list` (describe_instances), `handle_ec2_manage` (start/stop/reboot_instances)
- Lambda: `handle_lambda_invoke` (invoke → response payload.read())
- CloudWatch: `handle_cloudwatch_query` (filter_log_events)

All wrapped in `HAS_BOTO3` guard. Boto3 is sync — run in executor: `await asyncio.get_event_loop().run_in_executor(None, sync_call)`.

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Commit**

```bash
git add src/max/tools/native/aws_tools.py tests/test_aws_tools.py
git commit -m "feat(tools): add AWS tools (s3, ec2, lambda, cloudwatch)"
```

---

### Task 7: Browser Automation Tools (7 tools)

**Files:**
- Create: `src/max/tools/native/browser_tools.py`
- Create: `tests/test_browser_tools.py`

- [ ] **Step 1: Write tests**

All browser tests mock Playwright's async API. Test each handler returns expected format. Test missing-dep case. Test shared browser context lifecycle. Verify 7 tool definitions, category "browser".

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement browser_tools.py**

Module-level state for shared browser:
```python
_browser: Browser | None = None
_context: BrowserContext | None = None
_pages: dict[str, Page] = {}
```

Helper `_get_page(page_id=None)` returns existing or creates new page. Max `browser_max_pages` enforced.

7 handlers:
- `handle_browser_navigate`: create/get page → `page.goto(url)` → return `page.content()` truncated to 50KB, plus `page_id`
- `handle_browser_click`: `page.click(selector)`
- `handle_browser_type`: `page.fill(selector, text)` or `page.type(selector, text)`
- `handle_browser_screenshot`: `page.screenshot()` → base64 encode
- `handle_browser_get_content`: `page.content()` or `page.inner_text("body")`
- `handle_browser_fill_form`: iterate `fields` dict → `page.fill(selector, value)` for each
- `handle_browser_evaluate`: `page.evaluate(expression)` → return serialized result

All wrapped in `HAS_PLAYWRIGHT` guard. Add `close_browser()` cleanup function.

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Commit**

```bash
git add src/max/tools/native/browser_tools.py tests/test_browser_tools.py
git commit -m "feat(tools): add browser automation tools (playwright)"
```

---

### Task 8: Email Tools (4 tools)

**Files:**
- Create: `src/max/tools/native/email_tools.py`
- Create: `tests/test_email_tools.py`

- [ ] **Step 1: Write tests**

All tests mock aiosmtplib and aioimaplib. Test each handler with expected params/returns. Test missing-dep case. Verify 4 tool definitions, category "communication".

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement email_tools.py**

4 handlers:
- `handle_email_send`: `aiosmtplib.send(message, hostname, port, username, password, use_tls=True)` — build `EmailMessage` from inputs (to, subject, body, cc, bcc)
- `handle_email_read`: connect IMAP → select folder → fetch recent N messages → return list of {from, to, subject, date, body_preview}
- `handle_email_search`: connect IMAP → search by criteria (from, subject, since) → fetch matching → return list
- `handle_email_list_folders`: connect IMAP → list() → return folder names

All take connection params from inputs (host, port, user, password) with fallback to Settings env vars.

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Commit**

```bash
git add src/max/tools/native/email_tools.py tests/test_email_tools.py
git commit -m "feat(tools): add email tools (smtp send, imap read/search)"
```

---

### Task 9: Calendar Tools (4 tools)

**Files:**
- Create: `src/max/tools/native/calendar_tools.py`
- Create: `tests/test_calendar_tools.py`

- [ ] **Step 1: Write tests**

All tests mock caldav client. Test each handler. Test missing-dep case. Verify 4 tool definitions, category "productivity".

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement calendar_tools.py**

4 handlers using CalDAV:
- `handle_calendar_list_events`: connect → get calendar → `date_search(start, end)` → return events as list of {summary, start, end, location, description}
- `handle_calendar_create_event`: build iCalendar event → `calendar.save_event(ical_str)`
- `handle_calendar_update_event`: find event by uid → update fields → save
- `handle_calendar_delete_event`: find event by uid → delete

All take connection params from inputs with fallback to Settings env vars.

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Commit**

```bash
git add src/max/tools/native/calendar_tools.py tests/test_calendar_tools.py
git commit -m "feat(tools): add calendar tools (caldav list/create/update/delete)"
```

---

### Task 10: Data Analysis Tools (5 tools)

**Files:**
- Create: `src/max/tools/native/data_tools.py`
- Create: `tests/test_data_tools.py`

- [ ] **Step 1: Write tests**

Test `handle_data_load`, `handle_data_query`, `handle_data_summarize` with real CSV files via `tmp_path` and mocked polars. Test `handle_data_transform` and `handle_data_export`. Test missing-dep case. Verify 5 tool definitions, category "data".

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement data_tools.py**

5 handlers using Polars:
- `handle_data_load`: `pl.read_csv/read_json/read_parquet(path)` → return shape, columns, first 10 rows as preview
- `handle_data_query`: `pl.SQLContext` → register df → execute SQL → return rows
- `handle_data_summarize`: `df.describe()` → return as dict
- `handle_data_transform`: apply operations list [{op: "filter", column, value}, {op: "sort", column, descending}, {op: "group_by", columns, agg}] → return result preview
- `handle_data_export`: load → write to csv/json/parquet

All wrapped in `HAS_POLARS` guard.

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Commit**

```bash
git add src/max/tools/native/data_tools.py tests/test_data_tools.py
git commit -m "feat(tools): add data analysis tools (polars load/query/summarize/transform/export)"
```

---

### Task 11: Media Tools (5 tools)

**Files:**
- Create: `src/max/tools/native/media_tools.py`
- Create: `tests/test_media_tools.py`

- [ ] **Step 1: Write tests**

Test `handle_image_info` and `handle_image_resize` with real images created via Pillow (or mocked if Pillow not available). Test `handle_image_convert`. Test `handle_audio_transcribe` and `handle_video_info` with mocked libraries. Test missing-dep cases. Verify 5 tool definitions, category "media".

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement media_tools.py**

5 handlers:
- `handle_image_resize`: `Image.open(path).resize((w, h)).save(output_path)`
- `handle_image_convert`: `Image.open(path).save(output_path, format=target_format)`
- `handle_image_info`: `Image.open(path)` → return {size, mode, format, info (EXIF subset)}
- `handle_audio_transcribe`: `whisper.load_model(model).transcribe(path)` → return text. Run in executor (CPU-bound).
- `handle_video_info`: `ffmpeg.probe(path)` → extract duration, resolution, codec, format

All wrapped in respective `HAS_PILLOW`, `HAS_WHISPER`, `HAS_FFMPEG` guards.

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Commit**

```bash
git add src/max/tools/native/media_tools.py tests/test_media_tools.py
git commit -m "feat(tools): add media tools (image, audio, video)"
```

---

### Task 12: Web Scraping Tools (3 tools)

**Files:**
- Create: `src/max/tools/native/scraping_tools.py`
- Create: `tests/test_scraping_tools.py`

- [ ] **Step 1: Write tests**

Test `handle_web_scrape` and `handle_extract_links` with mocked httpx responses. Test `handle_web_search` with mocked Brave API response. Test missing-dep case for beautifulsoup4. Verify 3 tool definitions, category "web".

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement scraping_tools.py**

3 handlers:
- `handle_web_scrape`: `httpx.AsyncClient().get(url)` → `BeautifulSoup(html, "html.parser")` → extract text, truncate to 50KB
- `handle_extract_links`: same fetch → `soup.find_all("a", href=True)` → return list of {text, href}
- `handle_web_search`: `httpx.AsyncClient().get("https://api.search.brave.com/res/v1/web/search", headers={"X-Subscription-Token": api_key}, params={"q": query})` → return results list

BeautifulSoup is optional; httpx is existing dep. Brave API key from inputs or Settings.

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Commit**

```bash
git add src/max/tools/native/scraping_tools.py tests/test_scraping_tools.py
git commit -m "feat(tools): add web scraping tools (scrape, links, search)"
```

---

### Task 13: Git Extension Tools (4 tools)

**Files:**
- Create: `src/max/tools/native/git_ext_tools.py`
- Create: `tests/test_git_ext_tools.py`

- [ ] **Step 1: Write tests**

Test `handle_git_clone` with real git clone on tmp_path (small repo or --depth=1). Test `handle_git_branch`, `handle_git_push` (mocked remote), `handle_git_pr_create` (mocked gh CLI). Verify 4 tool definitions, category "code".

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement git_ext_tools.py**

Reuse `_run_git` helper pattern from `git_tools.py`.

4 handlers:
- `handle_git_clone`: `git clone [--depth=depth] url target_dir`
- `handle_git_branch`: `git branch` (list), `git checkout -b name` (create), `git checkout name` (switch)
- `handle_git_push`: `git push [-u origin branch]`
- `handle_git_pr_create`: `gh pr create --title "..." --body "..."` — uses `asyncio.create_subprocess_exec`

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Commit**

```bash
git add src/max/tools/native/git_ext_tools.py tests/test_git_ext_tools.py
git commit -m "feat(tools): add git extension tools (clone, branch, push, pr)"
```

---

### Task 14: Server/SSH Tools (3 tools)

**Files:**
- Create: `src/max/tools/native/server_tools.py`
- Create: `tests/test_server_tools.py`

- [ ] **Step 1: Write tests**

Test `handle_system_info` with real psutil (already installed). Test `handle_ssh_execute` with mocked asyncssh. Test `handle_service_status` with mocked subprocess. Test missing-dep case for asyncssh. Verify 3 tool definitions, category "infrastructure".

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement server_tools.py**

3 handlers:
- `handle_system_info`: `psutil.cpu_percent()`, `psutil.virtual_memory()`, `psutil.disk_usage("/")` → return {cpu_percent, memory_total/used/percent, disk_total/used/percent, boot_time, platform}
- `handle_ssh_execute`: `asyncssh.connect(host, port, username, password/key)` → `conn.run(command)` → return {stdout, stderr, exit_code}. 50KB output cap.
- `handle_service_status`: `systemctl status service_name` via subprocess → parse output

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Commit**

```bash
git add src/max/tools/native/server_tools.py tests/test_server_tools.py
git commit -m "feat(tools): add server tools (system info, ssh, service status)"
```

---

### Task 15: OpenAPI Auto-Import Provider

**Files:**
- Create: `src/max/tools/providers/openapi.py`
- Create: `tests/test_openapi_provider.py`

- [ ] **Step 1: Write tests**

Test `load_spec` with a fixture OpenAPI 3.0 spec (petstore-like). Test `list_tools` returns correct tool definitions. Test `execute` makes correct HTTP call. Test `health_check` pings base URL. Test missing yaml dep case. Verify provider_id format.

Create fixture spec as a dict in the test file:

```python
PETSTORE_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Petstore", "version": "1.0.0"},
    "servers": [{"url": "https://petstore.example.com/v1"}],
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "summary": "List all pets",
                "parameters": [
                    {"name": "limit", "in": "query", "schema": {"type": "integer"}}
                ],
                "responses": {"200": {"description": "A list of pets"}},
            },
            "post": {
                "operationId": "createPet",
                "summary": "Create a pet",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"name": {"type": "string"}},
                                "required": ["name"],
                            }
                        }
                    }
                },
                "responses": {"201": {"description": "Pet created"}},
            },
        }
    },
}
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement openapi.py**

```python
class OpenAPIToolProvider(ToolProvider):
    def __init__(self, spec_prefix: str, auth_headers: dict[str, str] | None = None):
        self._prefix = spec_prefix
        self._auth_headers = auth_headers or {}
        self._base_url = ""
        self._tools: list[ToolDefinition] = []
        self._endpoints: dict[str, dict] = {}  # tool_id → {method, path, params}

    @property
    def provider_id(self) -> str:
        return f"openapi:{self._prefix}"

    async def load_spec(self, spec: dict | str) -> None:
        """Load from dict, JSON string, YAML string, URL, or file path."""
        # Parse spec → extract servers[0].url as base_url
        # For each path + method: generate tool_id = f"{prefix}.{operationId}"
        # Build ToolDefinition from parameters + requestBody schema
        # Store endpoint info for execute()

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools)

    async def execute(self, tool_id: str, params: dict) -> ToolResult:
        endpoint = self._endpoints[tool_id]
        # Build URL from base_url + path (substitute path params)
        # Build query params, headers, body from params
        # Call httpx.AsyncClient with method, url, params, json, headers + auth_headers
        # Return ToolResult with response body

    async def health_check(self) -> bool:
        # HEAD request to base_url
```

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Commit**

```bash
git add src/max/tools/providers/openapi.py tests/test_openapi_provider.py
git commit -m "feat(tools): add OpenAPI auto-import provider"
```

---

### Task 16: Registration update + package exports

**Files:**
- Modify: `src/max/tools/native/__init__.py`
- Modify: `src/max/tools/__init__.py`
- Modify: `src/max/tools/providers/__init__.py`

- [ ] **Step 1: Update native/__init__.py**

Import all 13 new modules' `TOOL_DEFINITIONS` and handler functions. Add all new handlers to `_HANDLER_MAP`. Add all new `TOOL_DEFINITIONS` to `ALL_TOOL_DEFINITIONS`.

The new _HANDLER_MAP entries (65 new handlers):

```python
# Code tools
"code.ast_parse": handle_ast_parse,
"code.lint": handle_code_lint,
"code.format": handle_code_format,
"code.test": handle_code_test,
"code.dependencies": handle_code_dependencies,
# Database tools
"database.postgres_query": handle_postgres_query,
"database.postgres_execute": handle_postgres_execute,
"database.sqlite_query": handle_sqlite_query,
"database.sqlite_execute": handle_sqlite_execute,
"database.redis_get": handle_redis_get,
"database.redis_set": handle_redis_set,
# Document tools
"document.read_pdf": handle_read_pdf,
"document.read_spreadsheet": handle_read_spreadsheet,
"document.write_csv": handle_write_csv,
"document.write_spreadsheet": handle_write_spreadsheet,
"document.parse_json": handle_parse_json,
# Docker tools
"docker.list_containers": handle_docker_list_containers,
"docker.run": handle_docker_run,
"docker.stop": handle_docker_stop,
"docker.logs": handle_docker_logs,
"docker.build": handle_docker_build,
"docker.compose": handle_docker_compose,
# AWS tools
"aws.s3_list": handle_s3_list,
"aws.s3_get": handle_s3_get,
"aws.s3_put": handle_s3_put,
"aws.s3_delete": handle_s3_delete,
"aws.ec2_list": handle_ec2_list,
"aws.ec2_manage": handle_ec2_manage,
"aws.lambda_invoke": handle_lambda_invoke,
"aws.cloudwatch_query": handle_cloudwatch_query,
# Browser tools
"browser.navigate": handle_browser_navigate,
"browser.click": handle_browser_click,
"browser.type": handle_browser_type,
"browser.screenshot": handle_browser_screenshot,
"browser.get_content": handle_browser_get_content,
"browser.fill_form": handle_browser_fill_form,
"browser.evaluate": handle_browser_evaluate,
# Email tools
"email.send": handle_email_send,
"email.read": handle_email_read,
"email.search": handle_email_search,
"email.list_folders": handle_email_list_folders,
# Calendar tools
"calendar.list_events": handle_calendar_list_events,
"calendar.create_event": handle_calendar_create_event,
"calendar.update_event": handle_calendar_update_event,
"calendar.delete_event": handle_calendar_delete_event,
# Data tools
"data.load": handle_data_load,
"data.query": handle_data_query,
"data.summarize": handle_data_summarize,
"data.transform": handle_data_transform,
"data.export": handle_data_export,
# Media tools
"media.image_resize": handle_image_resize,
"media.image_convert": handle_image_convert,
"media.image_info": handle_image_info,
"media.audio_transcribe": handle_audio_transcribe,
"media.video_info": handle_video_info,
# Scraping tools
"web.scrape": handle_web_scrape,
"web.extract_links": handle_extract_links,
"web.search": handle_web_search,
# Git extension tools
"git.clone": handle_git_clone,
"git.branch": handle_git_branch,
"git.push": handle_git_push,
"git.pr_create": handle_git_pr_create,
# Server tools
"server.ssh_execute": handle_ssh_execute,
"server.system_info": handle_system_info,
"server.service_status": handle_service_status,
```

- [ ] **Step 2: Update providers/__init__.py**

Add `OpenAPIToolProvider` to exports.

- [ ] **Step 3: Update tools/__init__.py**

Add `OpenAPIToolProvider` to exports.

- [ ] **Step 4: Run all tests**

Run: `python -m pytest tests/ --tb=short -q`
Expected: All tests pass (465 existing + ~130 new ≈ 595+).

- [ ] **Step 5: Lint and format**

Run: `ruff check src/max/tools/ tests/ --fix && ruff format src/max/tools/ tests/`

- [ ] **Step 6: Commit**

```bash
git add src/max/tools/native/__init__.py src/max/tools/__init__.py src/max/tools/providers/__init__.py
git commit -m "feat(tools): register all 80 tools and update package exports"
```

---

### Task 17: Integration test

**Files:**
- Create: `tests/test_phase6b_integration.py`

- [ ] **Step 1: Write integration test**

Test that:
1. All 80 tools register correctly via `register_all_native_tools()`
2. Each category has the expected tool count
3. All tool definitions have valid schemas
4. A sample tool from each new category can be executed (with mocked deps where needed)

```python
async def test_all_80_tools_register():
    provider = NativeToolProvider()
    register_all_native_tools(provider)
    tools = provider.list_tools()
    assert len(tools) == 80

async def test_category_counts():
    provider = NativeToolProvider()
    register_all_native_tools(provider)
    tools = provider.list_tools()
    categories = {}
    for t in tools:
        categories[t.category] = categories.get(t.category, 0) + 1
    assert categories["code"] == 14  # 6A: 5 (git4+search1) + 6B: 5 code + 4 git_ext
    assert categories["browser"] == 7
    assert categories["database"] == 6
    ...
```

- [ ] **Step 2: Run test**

- [ ] **Step 3: Commit**

```bash
git add tests/test_phase6b_integration.py
git commit -m "test(tools): add Phase 6B integration test verifying all 80 tools"
```
