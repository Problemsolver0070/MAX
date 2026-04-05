"""Tests for grep.search tool."""

import pytest

from max.tools.native.search_tools import handle_grep_search


class TestGrepSearch:
    @pytest.mark.asyncio
    async def test_finds_pattern(self, tmp_path):
        (tmp_path / "a.py").write_text("def hello():\n    pass\n")
        (tmp_path / "b.py").write_text("def world():\n    pass\n")
        result = await handle_grep_search(
            {
                "path": str(tmp_path),
                "pattern": "hello",
            }
        )
        assert len(result["matches"]) == 1
        assert "hello" in result["matches"][0]["line"]

    @pytest.mark.asyncio
    async def test_glob_filter(self, tmp_path):
        (tmp_path / "a.py").write_text("target\n")
        (tmp_path / "b.txt").write_text("target\n")
        result = await handle_grep_search(
            {
                "path": str(tmp_path),
                "pattern": "target",
                "glob": "*.py",
            }
        )
        assert len(result["matches"]) == 1

    @pytest.mark.asyncio
    async def test_no_matches(self, tmp_path):
        (tmp_path / "a.txt").write_text("nothing here\n")
        result = await handle_grep_search(
            {
                "path": str(tmp_path),
                "pattern": "nonexistent",
            }
        )
        assert len(result["matches"]) == 0
