"""Tests for server tools — system info, SSH execute, and service status."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from max.tools.native.server_tools import (
    TOOL_DEFINITIONS,
    handle_server_service_status,
    handle_server_ssh_execute,
    handle_server_system_info,
)


# ── Tool Definition Tests ────────────────────────────────────────────────


class TestToolDefinitions:
    def test_has_three_definitions(self):
        assert len(TOOL_DEFINITIONS) == 3

    def test_all_category_infrastructure(self):
        for td in TOOL_DEFINITIONS:
            assert td.category == "infrastructure", f"{td.tool_id} has category {td.category}"

    def test_all_provider_native(self):
        for td in TOOL_DEFINITIONS:
            assert td.provider_id == "native", f"{td.tool_id} has provider {td.provider_id}"

    def test_tool_ids(self):
        ids = {td.tool_id for td in TOOL_DEFINITIONS}
        expected = {
            "server.system_info",
            "server.ssh_execute",
            "server.service_status",
        }
        assert ids == expected

    def test_ssh_execute_required_fields(self):
        ssh_tool = next(td for td in TOOL_DEFINITIONS if td.tool_id == "server.ssh_execute")
        assert "host" in ssh_tool.input_schema["required"]
        assert "command" in ssh_tool.input_schema["required"]

    def test_ssh_execute_optional_fields(self):
        ssh_tool = next(td for td in TOOL_DEFINITIONS if td.tool_id == "server.ssh_execute")
        props = ssh_tool.input_schema["properties"]
        assert "port" in props
        assert "username" in props
        assert "password" in props
        assert "key_file" in props
        assert props["port"]["default"] == 22

    def test_service_status_required_fields(self):
        svc_tool = next(td for td in TOOL_DEFINITIONS if td.tool_id == "server.service_status")
        assert "service_name" in svc_tool.input_schema["required"]

    def test_system_info_no_required_fields(self):
        info_tool = next(td for td in TOOL_DEFINITIONS if td.tool_id == "server.system_info")
        assert "required" not in info_tool.input_schema


# ── server.system_info Tests ─────────────────────────────────────────────


class TestServerSystemInfo:
    @pytest.mark.asyncio
    async def test_returns_expected_keys(self):
        """Test with REAL psutil — no mocks needed."""
        result = await handle_server_system_info({})

        assert "cpu_percent" in result
        assert "cpu_count" in result
        assert "memory" in result
        assert "disk" in result
        assert "boot_time" in result
        assert "platform" in result
        assert "hostname" in result

    @pytest.mark.asyncio
    async def test_cpu_values_sensible(self):
        result = await handle_server_system_info({})

        assert isinstance(result["cpu_percent"], float)
        assert 0.0 <= result["cpu_percent"] <= 100.0
        assert isinstance(result["cpu_count"], int)
        assert result["cpu_count"] >= 1

    @pytest.mark.asyncio
    async def test_memory_structure(self):
        result = await handle_server_system_info({})
        mem = result["memory"]

        assert "total" in mem
        assert "used" in mem
        assert "available" in mem
        assert "percent" in mem

        assert mem["total"] > 0
        assert mem["used"] > 0
        assert mem["available"] >= 0
        assert 0.0 <= mem["percent"] <= 100.0

    @pytest.mark.asyncio
    async def test_disk_structure(self):
        result = await handle_server_system_info({})
        disk = result["disk"]

        assert "total" in disk
        assert "used" in disk
        assert "free" in disk
        assert "percent" in disk

        assert disk["total"] > 0
        assert disk["used"] > 0
        assert disk["free"] >= 0
        assert 0.0 <= disk["percent"] <= 100.0

    @pytest.mark.asyncio
    async def test_platform_and_hostname(self):
        result = await handle_server_system_info({})

        assert isinstance(result["platform"], str)
        assert len(result["platform"]) > 0
        assert isinstance(result["hostname"], str)
        assert len(result["hostname"]) > 0

    @pytest.mark.asyncio
    async def test_boot_time_is_positive(self):
        result = await handle_server_system_info({})
        assert isinstance(result["boot_time"], float)
        assert result["boot_time"] > 0


# ── server.ssh_execute Tests ─────────────────────────────────────────────


class TestServerSSHExecute:
    @pytest.mark.asyncio
    async def test_basic_ssh_command(self):
        mock_result = MagicMock()
        mock_result.stdout = "hello world\n"
        mock_result.stderr = ""
        mock_result.exit_status = 0

        mock_conn = AsyncMock()
        mock_conn.run = AsyncMock(return_value=mock_result)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        with patch("max.tools.native.server_tools.asyncssh") as mock_asyncssh:
            mock_asyncssh.connect = MagicMock(return_value=mock_conn)
            with patch("max.tools.native.server_tools.HAS_ASYNCSSH", True):
                result = await handle_server_ssh_execute({
                    "host": "192.168.1.10",
                    "command": "echo hello world",
                })

        assert result["stdout"] == "hello world\n"
        assert result["stderr"] == ""
        assert result["exit_code"] == 0

        mock_asyncssh.connect.assert_called_once_with(
            host="192.168.1.10",
            port=22,
            known_hosts=None,
        )
        mock_conn.run.assert_called_once_with("echo hello world")

    @pytest.mark.asyncio
    async def test_ssh_with_all_options(self):
        mock_result = MagicMock()
        mock_result.stdout = "output"
        mock_result.stderr = ""
        mock_result.exit_status = 0

        mock_conn = AsyncMock()
        mock_conn.run = AsyncMock(return_value=mock_result)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        with patch("max.tools.native.server_tools.asyncssh") as mock_asyncssh:
            mock_asyncssh.connect = MagicMock(return_value=mock_conn)
            with patch("max.tools.native.server_tools.HAS_ASYNCSSH", True):
                result = await handle_server_ssh_execute({
                    "host": "example.com",
                    "command": "ls -la",
                    "port": 2222,
                    "username": "admin",
                    "password": "secret",
                    "key_file": "/home/user/.ssh/id_rsa",
                })

        mock_asyncssh.connect.assert_called_once_with(
            host="example.com",
            port=2222,
            known_hosts=None,
            username="admin",
            password="secret",
            client_keys=["/home/user/.ssh/id_rsa"],
        )
        assert result["stdout"] == "output"

    @pytest.mark.asyncio
    async def test_ssh_with_stderr(self):
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "command not found\n"
        mock_result.exit_status = 127

        mock_conn = AsyncMock()
        mock_conn.run = AsyncMock(return_value=mock_result)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        with patch("max.tools.native.server_tools.asyncssh") as mock_asyncssh:
            mock_asyncssh.connect = MagicMock(return_value=mock_conn)
            with patch("max.tools.native.server_tools.HAS_ASYNCSSH", True):
                result = await handle_server_ssh_execute({
                    "host": "host",
                    "command": "badcmd",
                })

        assert result["stderr"] == "command not found\n"
        assert result["exit_code"] == 127

    @pytest.mark.asyncio
    async def test_ssh_output_cap(self):
        """Verify output is capped at 50KB."""
        large_output = "x" * 60_000
        mock_result = MagicMock()
        mock_result.stdout = large_output
        mock_result.stderr = large_output
        mock_result.exit_status = 0

        mock_conn = AsyncMock()
        mock_conn.run = AsyncMock(return_value=mock_result)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        with patch("max.tools.native.server_tools.asyncssh") as mock_asyncssh:
            mock_asyncssh.connect = MagicMock(return_value=mock_conn)
            with patch("max.tools.native.server_tools.HAS_ASYNCSSH", True):
                result = await handle_server_ssh_execute({
                    "host": "host",
                    "command": "big-output",
                })

        assert len(result["stdout"]) == 50_000
        assert len(result["stderr"]) == 50_000

    @pytest.mark.asyncio
    async def test_ssh_none_stdout_stderr(self):
        """Handle None stdout/stderr gracefully."""
        mock_result = MagicMock()
        mock_result.stdout = None
        mock_result.stderr = None
        mock_result.exit_status = 0

        mock_conn = AsyncMock()
        mock_conn.run = AsyncMock(return_value=mock_result)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        with patch("max.tools.native.server_tools.asyncssh") as mock_asyncssh:
            mock_asyncssh.connect = MagicMock(return_value=mock_conn)
            with patch("max.tools.native.server_tools.HAS_ASYNCSSH", True):
                result = await handle_server_ssh_execute({
                    "host": "host",
                    "command": "true",
                })

        assert result["stdout"] == ""
        assert result["stderr"] == ""
        assert result["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_ssh_none_exit_status(self):
        """Handle None exit_status gracefully."""
        mock_result = MagicMock()
        mock_result.stdout = "ok"
        mock_result.stderr = ""
        mock_result.exit_status = None

        mock_conn = AsyncMock()
        mock_conn.run = AsyncMock(return_value=mock_result)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        with patch("max.tools.native.server_tools.asyncssh") as mock_asyncssh:
            mock_asyncssh.connect = MagicMock(return_value=mock_conn)
            with patch("max.tools.native.server_tools.HAS_ASYNCSSH", True):
                result = await handle_server_ssh_execute({
                    "host": "host",
                    "command": "true",
                })

        assert result["exit_code"] == 0


# ── server.service_status Tests ──────────────────────────────────────────


class TestServerServiceStatus:
    @pytest.mark.asyncio
    async def test_active_service(self):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"active\n", b"")
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            result = await handle_server_service_status({"service_name": "nginx"})

        assert result["active"] is True
        assert result["stdout"] == "active\n"
        assert result["stderr"] == ""
        assert result["exit_code"] == 0

        mock_exec.assert_called_once_with(
            "systemctl", "is-active", "nginx",
            stdout=-1, stderr=-1,
        )

    @pytest.mark.asyncio
    async def test_inactive_service(self):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"inactive\n", b"")
        mock_proc.returncode = 3

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await handle_server_service_status({"service_name": "stopped-svc"})

        assert result["active"] is False
        assert result["stdout"] == "inactive\n"
        assert result["exit_code"] == 3

    @pytest.mark.asyncio
    async def test_failed_service(self):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"failed\n", b"")
        mock_proc.returncode = 3

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await handle_server_service_status({"service_name": "broken-svc"})

        assert result["active"] is False
        assert result["stdout"] == "failed\n"

    @pytest.mark.asyncio
    async def test_unknown_service(self):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            b"unknown\n",
            b"Unit nonexistent.service could not be found.\n",
        )
        mock_proc.returncode = 4

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await handle_server_service_status({"service_name": "nonexistent"})

        assert result["active"] is False
        assert "could not be found" in result["stderr"]
        assert result["exit_code"] == 4

    @pytest.mark.asyncio
    async def test_service_output_cap(self):
        """Verify service status output is capped at 50KB."""
        large_output = b"x" * 60_000
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (large_output, large_output)
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await handle_server_service_status({"service_name": "test-svc"})

        assert len(result["stdout"]) == 50_000
        assert len(result["stderr"]) == 50_000


# ── Missing Dependency Tests ─────────────────────────────────────────────


class TestMissingAsyncSSHDependency:
    @pytest.mark.asyncio
    async def test_ssh_execute_no_asyncssh(self):
        with patch("max.tools.native.server_tools.HAS_ASYNCSSH", False):
            with pytest.raises(RuntimeError, match="asyncssh library is not installed"):
                await handle_server_ssh_execute({
                    "host": "example.com",
                    "command": "ls",
                })

    @pytest.mark.asyncio
    async def test_system_info_works_without_asyncssh(self):
        """system_info does not require asyncssh at all."""
        with patch("max.tools.native.server_tools.HAS_ASYNCSSH", False):
            result = await handle_server_system_info({})
            assert "cpu_percent" in result

    @pytest.mark.asyncio
    async def test_service_status_works_without_asyncssh(self):
        """service_status does not require asyncssh at all."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"active\n", b"")
        mock_proc.returncode = 0

        with patch("max.tools.native.server_tools.HAS_ASYNCSSH", False):
            with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                result = await handle_server_service_status({"service_name": "test"})
                assert result["active"] is True
