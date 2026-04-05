"""Tests for code analysis tools."""

import pytest

from max.tools.native.code_tools import (
    TOOL_DEFINITIONS,
    handle_code_ast_parse,
    handle_code_dependencies,
    handle_code_format,
    handle_code_lint,
    handle_code_test,
)

# ── AST Parse ─────────────────────────────────────────────────────────


class TestAstParse:
    @pytest.mark.asyncio
    async def test_parses_python_file(self, tmp_path):
        src = tmp_path / "sample.py"
        src.write_text(
            "import os\n"
            "from pathlib import Path\n"
            "\n"
            "class Foo:\n"
            "    pass\n"
            "\n"
            "def bar():\n"
            "    pass\n"
            "\n"
            "async def baz():\n"
            "    pass\n"
        )
        result = await handle_code_ast_parse({"path": str(src)})
        assert "error" not in result
        assert "bar" in result["functions"]
        assert "baz" in result["functions"]
        assert "Foo" in result["classes"]
        assert "os" in result["imports"]
        assert "pathlib" in result["imports"]

    @pytest.mark.asyncio
    async def test_nonexistent_file(self):
        result = await handle_code_ast_parse({"path": "/tmp/does_not_exist_xyz.py"})
        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_syntax_error(self, tmp_path):
        src = tmp_path / "bad.py"
        src.write_text("def broken(\n")
        result = await handle_code_ast_parse({"path": str(src)})
        assert "error" in result
        assert "syntax" in result["error"].lower()


# ── Code Lint ──────────────────────────────────────────────────────────


class TestCodeLint:
    @pytest.mark.asyncio
    async def test_lint_clean_file(self, tmp_path):
        src = tmp_path / "clean.py"
        src.write_text("x = 1\n")
        result = await handle_code_lint({"path": str(src)})
        assert result["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_lint_returns_output(self, tmp_path):
        src = tmp_path / "messy.py"
        # unused import triggers ruff F401
        src.write_text("import os\n")
        result = await handle_code_lint({"path": str(src)})
        # ruff should report the unused import
        assert "stdout" in result
        assert "stderr" in result
        assert "exit_code" in result


# ── Code Format ────────────────────────────────────────────────────────


class TestCodeFormat:
    @pytest.mark.asyncio
    async def test_format_file(self, tmp_path):
        src = tmp_path / "ugly.py"
        src.write_text("x=1\ny  =   2\n")
        result = await handle_code_format({"path": str(src)})
        assert result["exit_code"] == 0
        # File should be reformatted
        formatted = src.read_text()
        assert "x = 1" in formatted


# ── Code Test ──────────────────────────────────────────────────────────


class TestCodeTest:
    @pytest.mark.asyncio
    async def test_run_passing_test(self, tmp_path):
        test_file = tmp_path / "test_pass.py"
        test_file.write_text("def test_ok():\n    assert 1 + 1 == 2\n")
        result = await handle_code_test({"path": str(test_file)})
        assert result["exit_code"] == 0
        assert "passed" in result["stdout"].lower()

    @pytest.mark.asyncio
    async def test_run_failing_test(self, tmp_path):
        test_file = tmp_path / "test_fail.py"
        test_file.write_text("def test_bad():\n    assert 1 == 2\n")
        result = await handle_code_test({"path": str(test_file)})
        assert result["exit_code"] != 0
        assert "failed" in result["stdout"].lower()


# ── Code Dependencies ─────────────────────────────────────────────────


class TestCodeDependencies:
    @pytest.mark.asyncio
    async def test_analyzes_imports(self, tmp_path):
        src = tmp_path / "sample.py"
        src.write_text(
            "import os\n"
            "import sys\n"
            "from pathlib import Path\n"
            "from max.tools import registry\n"
            "import requests\n"
        )
        result = await handle_code_dependencies({"path": str(src)})
        assert "error" not in result
        assert "os" in result["stdlib"]
        assert "sys" in result["stdlib"]
        assert "pathlib" in result["stdlib"]
        assert "max.tools" in result["third_party"]
        assert "requests" in result["third_party"]

    @pytest.mark.asyncio
    async def test_nonexistent(self):
        result = await handle_code_dependencies({"path": "/tmp/no_such_file_xyz.py"})
        assert "error" in result
        assert "not found" in result["error"].lower()


# ── Tool Definitions ──────────────────────────────────────────────────


class TestToolDefinitions:
    def test_has_five_tools(self):
        assert len(TOOL_DEFINITIONS) == 5

    def test_all_code_category(self):
        for tool in TOOL_DEFINITIONS:
            assert tool.category == "code"

    def test_all_native_provider(self):
        for tool in TOOL_DEFINITIONS:
            assert tool.provider_id == "native"

    def test_tool_ids(self):
        ids = {t.tool_id for t in TOOL_DEFINITIONS}
        assert ids == {
            "code.ast_parse",
            "code.lint",
            "code.format",
            "code.test",
            "code.dependencies",
        }
