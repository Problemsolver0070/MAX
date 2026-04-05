"""Tests for git tools."""

import pytest

from max.tools.native.git_tools import (
    handle_git_commit,
    handle_git_diff,
    handle_git_log,
    handle_git_status,
)


class TestGitStatus:
    @pytest.mark.asyncio
    async def test_returns_status(self, tmp_path):
        import subprocess
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path), capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path), capture_output=True,
        )
        (tmp_path / "test.txt").write_text("hello")
        result = await handle_git_status({"cwd": str(tmp_path)})
        assert "test.txt" in result["stdout"]


class TestGitDiff:
    @pytest.mark.asyncio
    async def test_returns_diff(self, tmp_path):
        import subprocess
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path), capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path), capture_output=True,
        )
        (tmp_path / "test.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=str(tmp_path), capture_output=True,
        )
        (tmp_path / "test.txt").write_text("hello world")
        result = await handle_git_diff({"cwd": str(tmp_path)})
        assert "hello world" in result["stdout"]


class TestGitLog:
    @pytest.mark.asyncio
    async def test_returns_log(self, tmp_path):
        import subprocess
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path), capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path), capture_output=True,
        )
        (tmp_path / "test.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial commit"],
            cwd=str(tmp_path), capture_output=True,
        )
        result = await handle_git_log({"cwd": str(tmp_path), "count": 5})
        assert "initial commit" in result["stdout"]


class TestGitCommit:
    @pytest.mark.asyncio
    async def test_commits_changes(self, tmp_path):
        import subprocess
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path), capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path), capture_output=True,
        )
        (tmp_path / "test.txt").write_text("hello")
        result = await handle_git_commit({
            "cwd": str(tmp_path),
            "message": "test commit",
            "files": ["test.txt"],
        })
        assert result["exit_code"] == 0
