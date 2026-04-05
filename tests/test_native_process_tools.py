"""Tests for process.list tool."""

import pytest

from max.tools.native.process_tools import handle_process_list


class TestProcessList:
    @pytest.mark.asyncio
    async def test_lists_processes(self):
        result = await handle_process_list({})
        assert len(result["processes"]) > 0
        proc = result["processes"][0]
        assert "pid" in proc
        assert "name" in proc
