"""Tests for git extension tools — clone, branch, push, pr_create."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from max.tools.native.git_ext_tools import (
    TOOL_DEFINITIONS,
    handle_git_branch,
    handle_git_clone,
    handle_git_pr_create,
    handle_git_push,
)

# ── Helpers ──────────────────────────────────────────────────────────────


def _run_sync(coro):
    """Run an async coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


async def _git(args: list[str], cwd: str) -> None:
    """Run a git helper for test setup."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    await proc.communicate()


async def _init_repo(path) -> str:
    """Create a git repo with one commit. Returns repo path as string."""
    repo = str(path)
    await _git(["init", repo], ".")
    await _git(["config", "user.email", "test@test.com"], repo)
    await _git(["config", "user.name", "Test"], repo)
    # Create initial commit so HEAD exists
    readme = path / "README.md"
    readme.write_text("# test\n")
    await _git(["add", "README.md"], repo)
    await _git(["commit", "-m", "init"], repo)
    return repo


async def _init_bare_repo(path) -> str:
    """Create a bare git repo. Returns path as string."""
    repo = str(path)
    await _git(["init", "--bare", repo], ".")
    return repo


# ── git.clone ────────────────────────────────────────────────────────────


class TestGitClone:
    @pytest.mark.asyncio
    async def test_clone_local_bare_repo(self, tmp_path):
        """Clone a local bare repo — no network needed."""
        bare = tmp_path / "bare.git"
        bare.mkdir()
        await _init_bare_repo(bare)

        # Push something into the bare repo via a temp working copy
        working = tmp_path / "working"
        working.mkdir()
        await _git(["clone", str(bare), str(working)], ".")
        await _git(["config", "user.email", "test@test.com"], str(working))
        await _git(["config", "user.name", "Test"], str(working))
        readme = working / "README.md"
        readme.write_text("# hello\n")
        await _git(["add", "README.md"], str(working))
        await _git(["commit", "-m", "init"], str(working))
        await _git(["push", "origin", "master"], str(working))

        # Now clone via the handler
        target = tmp_path / "cloned"
        result = await handle_git_clone({"url": str(bare), "target_dir": str(target)})
        assert result["exit_code"] == 0
        assert result["target_dir"] == str(target)
        assert (target / "README.md").exists()

    @pytest.mark.asyncio
    async def test_clone_with_depth(self, tmp_path):
        """Clone with --depth flag."""
        bare = tmp_path / "bare.git"
        bare.mkdir()
        await _init_bare_repo(bare)

        working = tmp_path / "working"
        working.mkdir()
        await _git(["clone", str(bare), str(working)], ".")
        await _git(["config", "user.email", "test@test.com"], str(working))
        await _git(["config", "user.name", "Test"], str(working))
        readme = working / "README.md"
        readme.write_text("# hello\n")
        await _git(["add", "README.md"], str(working))
        await _git(["commit", "-m", "init"], str(working))
        await _git(["push", "origin", "master"], str(working))

        target = tmp_path / "shallow"
        result = await handle_git_clone({"url": str(bare), "target_dir": str(target), "depth": 1})
        assert result["exit_code"] == 0
        assert (target / "README.md").exists()

    @pytest.mark.asyncio
    async def test_clone_invalid_url(self, tmp_path):
        """Clone from a non-existent URL returns non-zero exit code."""
        target = tmp_path / "bad_clone"
        result = await handle_git_clone({"url": "/nonexistent/repo.git", "target_dir": str(target)})
        assert result["exit_code"] != 0


# ── git.branch ───────────────────────────────────────────────────────────


class TestGitBranch:
    @pytest.mark.asyncio
    async def test_list_branches(self, tmp_path):
        repo = await _init_repo(tmp_path / "repo")
        result = await handle_git_branch({"cwd": repo, "action": "list"})
        assert result["exit_code"] == 0
        assert "master" in result["stdout"] or "main" in result["stdout"]

    @pytest.mark.asyncio
    async def test_create_branch(self, tmp_path):
        repo = await _init_repo(tmp_path / "repo")
        result = await handle_git_branch({"cwd": repo, "action": "create", "name": "feature-x"})
        assert result["exit_code"] == 0

        # Verify branch exists
        list_result = await handle_git_branch({"cwd": repo, "action": "list"})
        assert "feature-x" in list_result["stdout"]

    @pytest.mark.asyncio
    async def test_switch_branch(self, tmp_path):
        repo = await _init_repo(tmp_path / "repo")
        # Create a branch first
        await handle_git_branch({"cwd": repo, "action": "create", "name": "other"})
        # Switch back to master/main
        # Determine default branch name
        list_result = await handle_git_branch({"cwd": repo, "action": "list"})
        default = "master" if "master" in list_result["stdout"] else "main"

        result = await handle_git_branch({"cwd": repo, "action": "switch", "name": default})
        assert result["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_create_without_name_fails(self, tmp_path):
        repo = await _init_repo(tmp_path / "repo")
        result = await handle_git_branch({"cwd": repo, "action": "create"})
        assert result["exit_code"] == 1
        assert "required" in result["stderr"].lower()

    @pytest.mark.asyncio
    async def test_switch_without_name_fails(self, tmp_path):
        repo = await _init_repo(tmp_path / "repo")
        result = await handle_git_branch({"cwd": repo, "action": "switch"})
        assert result["exit_code"] == 1
        assert "required" in result["stderr"].lower()

    @pytest.mark.asyncio
    async def test_unknown_action(self, tmp_path):
        repo = await _init_repo(tmp_path / "repo")
        result = await handle_git_branch({"cwd": repo, "action": "delete"})
        assert result["exit_code"] == 1
        assert "unknown" in result["stderr"].lower()


# ── git.push ─────────────────────────────────────────────────────────────


class TestGitPush:
    @pytest.mark.asyncio
    async def test_push_to_local_bare_remote(self, tmp_path):
        """Push to a local bare repo — no network needed."""
        bare = tmp_path / "remote.git"
        bare.mkdir()
        await _init_bare_repo(bare)

        repo_path = tmp_path / "local"
        repo_path.mkdir()
        await _git(["clone", str(bare), str(repo_path)], ".")
        await _git(["config", "user.email", "test@test.com"], str(repo_path))
        await _git(["config", "user.name", "Test"], str(repo_path))

        # Create a commit to push
        f = repo_path / "file.txt"
        f.write_text("content\n")
        await _git(["add", "file.txt"], str(repo_path))
        await _git(["commit", "-m", "add file"], str(repo_path))

        result = await handle_git_push(
            {"cwd": str(repo_path), "remote": "origin", "branch": "master"}
        )
        assert result["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_push_with_set_upstream(self, tmp_path):
        """Push with -u flag to set upstream tracking."""
        bare = tmp_path / "remote.git"
        bare.mkdir()
        await _init_bare_repo(bare)

        repo_path = tmp_path / "local"
        repo_path.mkdir()
        await _git(["clone", str(bare), str(repo_path)], ".")
        await _git(["config", "user.email", "test@test.com"], str(repo_path))
        await _git(["config", "user.name", "Test"], str(repo_path))

        f = repo_path / "file.txt"
        f.write_text("content\n")
        await _git(["add", "file.txt"], str(repo_path))
        await _git(["commit", "-m", "add file"], str(repo_path))

        # Create a new branch and push with -u
        await _git(["checkout", "-b", "new-branch"], str(repo_path))
        result = await handle_git_push(
            {
                "cwd": str(repo_path),
                "remote": "origin",
                "branch": "new-branch",
                "set_upstream": True,
            }
        )
        assert result["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_push_no_remote_fails(self, tmp_path):
        """Push with no remote configured fails."""
        repo = await _init_repo(tmp_path / "repo")
        result = await handle_git_push({"cwd": repo})
        assert result["exit_code"] != 0


# ── git.pr_create ────────────────────────────────────────────────────────


class TestGitPrCreate:
    @pytest.mark.asyncio
    async def test_pr_create_basic(self, tmp_path):
        """PR creation calls gh with correct arguments (mocked)."""
        mock_result = {
            "stdout": "https://github.com/org/repo/pull/42\n",
            "stderr": "",
            "exit_code": 0,
        }
        with patch(
            "max.tools.native.git_ext_tools._run_cmd",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_cmd:
            result = await handle_git_pr_create(
                {"cwd": str(tmp_path), "title": "My PR", "body": "Description"}
            )
            assert result["exit_code"] == 0
            assert "pull/42" in result["stdout"]
            mock_cmd.assert_called_once_with(
                ["gh", "pr", "create", "--title", "My PR", "--body", "Description"],
                str(tmp_path),
            )

    @pytest.mark.asyncio
    async def test_pr_create_with_base(self, tmp_path):
        """PR creation with --base flag."""
        mock_result = {
            "stdout": "https://github.com/org/repo/pull/99\n",
            "stderr": "",
            "exit_code": 0,
        }
        with patch(
            "max.tools.native.git_ext_tools._run_cmd",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_cmd:
            result = await handle_git_pr_create(
                {
                    "cwd": str(tmp_path),
                    "title": "Feature PR",
                    "body": "Adds feature",
                    "base": "main",
                }
            )
            assert result["exit_code"] == 0
            mock_cmd.assert_called_once_with(
                [
                    "gh",
                    "pr",
                    "create",
                    "--title",
                    "Feature PR",
                    "--body",
                    "Adds feature",
                    "--base",
                    "main",
                ],
                str(tmp_path),
            )

    @pytest.mark.asyncio
    async def test_pr_create_no_body(self, tmp_path):
        """PR creation without body defaults to empty string."""
        mock_result = {
            "stdout": "https://github.com/org/repo/pull/1\n",
            "stderr": "",
            "exit_code": 0,
        }
        with patch(
            "max.tools.native.git_ext_tools._run_cmd",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_cmd:
            result = await handle_git_pr_create({"cwd": str(tmp_path), "title": "Quick fix"})
            assert result["exit_code"] == 0
            mock_cmd.assert_called_once_with(
                ["gh", "pr", "create", "--title", "Quick fix", "--body", ""],
                str(tmp_path),
            )

    @pytest.mark.asyncio
    async def test_pr_create_failure(self, tmp_path):
        """PR creation failure is surfaced correctly."""
        mock_result = {
            "stdout": "",
            "stderr": "not authenticated",
            "exit_code": 1,
        }
        with patch(
            "max.tools.native.git_ext_tools._run_cmd",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await handle_git_pr_create({"cwd": str(tmp_path), "title": "Won't work"})
            assert result["exit_code"] == 1
            assert "not authenticated" in result["stderr"]


# ── Tool Definitions ─────────────────────────────────────────────────────


class TestToolDefinitions:
    def test_has_four_tools(self):
        assert len(TOOL_DEFINITIONS) == 4

    def test_all_code_category(self):
        for tool in TOOL_DEFINITIONS:
            assert tool.category == "code"

    def test_all_native_provider(self):
        for tool in TOOL_DEFINITIONS:
            assert tool.provider_id == "native"

    def test_all_have_git_write_permission(self):
        for tool in TOOL_DEFINITIONS:
            assert "git.write" in tool.permissions

    def test_tool_ids(self):
        ids = {t.tool_id for t in TOOL_DEFINITIONS}
        assert ids == {"git.clone", "git.branch", "git.push", "git.pr_create"}

    def test_tool_schemas_have_required_fields(self):
        for tool in TOOL_DEFINITIONS:
            schema = tool.input_schema
            assert schema["type"] == "object"
            assert "properties" in schema
            assert "required" in schema
