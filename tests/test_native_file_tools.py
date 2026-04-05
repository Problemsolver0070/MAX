"""Tests for native file system tools."""

import os
import tempfile

import pytest

from max.tools.native.file_tools import (
    handle_directory_list,
    handle_file_delete,
    handle_file_edit,
    handle_file_glob,
    handle_file_read,
    handle_file_write,
)


class TestFileRead:
    @pytest.mark.asyncio
    async def test_reads_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        result = await handle_file_read({"path": str(f)})
        assert result["content"] == "hello world"

    @pytest.mark.asyncio
    async def test_reads_with_offset_limit(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3\nline4\n")
        result = await handle_file_read({"path": str(f), "offset": 1, "limit": 2})
        assert "line2" in result["content"]
        assert "line3" in result["content"]
        assert "line4" not in result["content"]

    @pytest.mark.asyncio
    async def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            await handle_file_read({"path": str(tmp_path / "nonexistent.txt")})


class TestFileWrite:
    @pytest.mark.asyncio
    async def test_writes_file(self, tmp_path):
        f = tmp_path / "output.txt"
        result = await handle_file_write({"path": str(f), "content": "hello"})
        assert result["bytes_written"] == 5
        assert f.read_text() == "hello"

    @pytest.mark.asyncio
    async def test_creates_parent_dirs(self, tmp_path):
        f = tmp_path / "sub" / "dir" / "output.txt"
        await handle_file_write({"path": str(f), "content": "hello"})
        assert f.read_text() == "hello"


class TestFileEdit:
    @pytest.mark.asyncio
    async def test_search_and_replace(self, tmp_path):
        f = tmp_path / "edit.txt"
        f.write_text("hello world\nfoo bar\n")
        result = await handle_file_edit({
            "path": str(f),
            "old_string": "foo bar",
            "new_string": "baz qux",
        })
        assert result["replacements"] == 1
        assert "baz qux" in f.read_text()

    @pytest.mark.asyncio
    async def test_no_match(self, tmp_path):
        f = tmp_path / "edit.txt"
        f.write_text("hello world\n")
        result = await handle_file_edit({
            "path": str(f),
            "old_string": "nonexistent",
            "new_string": "replaced",
        })
        assert result["replacements"] == 0


class TestDirectoryList:
    @pytest.mark.asyncio
    async def test_lists_directory(self, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        (tmp_path / "subdir").mkdir()
        result = await handle_directory_list({"path": str(tmp_path)})
        names = [e["name"] for e in result["entries"]]
        assert "a.txt" in names
        assert "subdir" in names


class TestFileGlob:
    @pytest.mark.asyncio
    async def test_glob_pattern(self, tmp_path):
        (tmp_path / "a.py").write_text("a")
        (tmp_path / "b.py").write_text("b")
        (tmp_path / "c.txt").write_text("c")
        result = await handle_file_glob({"path": str(tmp_path), "pattern": "*.py"})
        assert len(result["matches"]) == 2


class TestFileDelete:
    @pytest.mark.asyncio
    async def test_deletes_file(self, tmp_path):
        f = tmp_path / "delete_me.txt"
        f.write_text("bye")
        result = await handle_file_delete({"path": str(f)})
        assert result["deleted"] is True
        assert not f.exists()

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            await handle_file_delete({"path": str(tmp_path / "nope.txt")})
