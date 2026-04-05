"""Tests for shell.execute tool."""

import pytest

from max.tools.native.shell_tools import handle_shell_execute


class TestShellExecute:
    @pytest.mark.asyncio
    async def test_runs_command(self):
        result = await handle_shell_execute({"command": "echo hello"})
        assert result["exit_code"] == 0
        assert "hello" in result["stdout"]

    @pytest.mark.asyncio
    async def test_captures_stderr(self):
        result = await handle_shell_execute({"command": "echo error >&2"})
        assert "error" in result["stderr"]

    @pytest.mark.asyncio
    async def test_nonzero_exit_code(self):
        result = await handle_shell_execute({"command": "exit 1"})
        assert result["exit_code"] == 1

    @pytest.mark.asyncio
    async def test_timeout(self):
        result = await handle_shell_execute({"command": "sleep 60", "timeout": 1})
        assert result["exit_code"] == -1
        assert "timed out" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_working_directory(self, tmp_path):
        result = await handle_shell_execute({"command": "pwd", "cwd": str(tmp_path)})
        assert str(tmp_path) in result["stdout"]
