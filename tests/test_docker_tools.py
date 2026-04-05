"""Tests for Docker tools — all mocked, no real Docker daemon needed."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from max.tools.native.docker_tools import (
    TOOL_DEFINITIONS,
    handle_docker_build,
    handle_docker_compose,
    handle_docker_list_containers,
    handle_docker_logs,
    handle_docker_run,
    handle_docker_stop,
)


# ── Tool Definition Tests ────────────────────────────────────────────────


class TestToolDefinitions:
    def test_has_six_definitions(self):
        assert len(TOOL_DEFINITIONS) == 6

    def test_all_category_infrastructure(self):
        for td in TOOL_DEFINITIONS:
            assert td.category == "infrastructure", f"{td.tool_id} has category {td.category}"

    def test_all_provider_native(self):
        for td in TOOL_DEFINITIONS:
            assert td.provider_id == "native", f"{td.tool_id} has provider {td.provider_id}"

    def test_tool_ids(self):
        ids = {td.tool_id for td in TOOL_DEFINITIONS}
        expected = {
            "docker.list_containers",
            "docker.run",
            "docker.stop",
            "docker.logs",
            "docker.build",
            "docker.compose",
        }
        assert ids == expected

    def test_required_fields_docker_run(self):
        run_tool = next(td for td in TOOL_DEFINITIONS if td.tool_id == "docker.run")
        assert "image" in run_tool.input_schema["required"]

    def test_required_fields_docker_stop(self):
        stop_tool = next(td for td in TOOL_DEFINITIONS if td.tool_id == "docker.stop")
        assert "container_id" in stop_tool.input_schema["required"]

    def test_required_fields_docker_build(self):
        build_tool = next(td for td in TOOL_DEFINITIONS if td.tool_id == "docker.build")
        assert "path" in build_tool.input_schema["required"]
        assert "tag" in build_tool.input_schema["required"]

    def test_required_fields_docker_compose(self):
        compose_tool = next(td for td in TOOL_DEFINITIONS if td.tool_id == "docker.compose")
        assert "action" in compose_tool.input_schema["required"]
        assert "cwd" in compose_tool.input_schema["required"]

    def test_compose_action_enum(self):
        compose_tool = next(td for td in TOOL_DEFINITIONS if td.tool_id == "docker.compose")
        action_schema = compose_tool.input_schema["properties"]["action"]
        assert set(action_schema["enum"]) == {"up", "down", "ps"}


# ── Helper: mock Docker client ──────────────────────────────────────────


def _make_mock_client():
    """Create a mock docker client with containers and images attributes."""
    client = MagicMock()
    client.close = MagicMock()
    return client


def _make_mock_container(
    short_id="abc123",
    name="my-container",
    image_tags=None,
    image_id="sha256:deadbeef",
    status="running",
):
    """Create a mock container object."""
    container = MagicMock()
    container.short_id = short_id
    container.name = name
    container.status = status

    image = MagicMock()
    image.tags = image_tags if image_tags is not None else ["myimage:latest"]
    image.id = image_id
    container.image = image

    return container


# ── docker.list_containers Tests ─────────────────────────────────────────


def _patch_docker_available():
    """Context manager to patch HAS_DOCKER=True and mock _get_client together."""
    return patch("max.tools.native.docker_tools.HAS_DOCKER", True)


class TestDockerListContainers:
    @pytest.mark.asyncio
    async def test_list_running_containers(self):
        mock_client = _make_mock_client()
        c1 = _make_mock_container(short_id="abc1", name="web", status="running")
        c2 = _make_mock_container(short_id="abc2", name="db", status="running")
        mock_client.containers.list.return_value = [c1, c2]

        with _patch_docker_available(), patch("max.tools.native.docker_tools._get_client", return_value=mock_client):
            result = await handle_docker_list_containers({"all": False})

        assert len(result["containers"]) == 2
        assert result["containers"][0]["id"] == "abc1"
        assert result["containers"][0]["name"] == "web"
        assert result["containers"][1]["name"] == "db"
        mock_client.containers.list.assert_called_once_with(all=False)

    @pytest.mark.asyncio
    async def test_list_all_containers(self):
        mock_client = _make_mock_client()
        c1 = _make_mock_container(short_id="abc1", name="web", status="running")
        c2 = _make_mock_container(short_id="abc2", name="old", status="exited")
        mock_client.containers.list.return_value = [c1, c2]

        with _patch_docker_available(), patch("max.tools.native.docker_tools._get_client", return_value=mock_client):
            result = await handle_docker_list_containers({"all": True})

        assert len(result["containers"]) == 2
        assert result["containers"][1]["status"] == "exited"
        mock_client.containers.list.assert_called_once_with(all=True)

    @pytest.mark.asyncio
    async def test_list_empty(self):
        mock_client = _make_mock_client()
        mock_client.containers.list.return_value = []

        with _patch_docker_available(), patch("max.tools.native.docker_tools._get_client", return_value=mock_client):
            result = await handle_docker_list_containers({})

        assert result["containers"] == []

    @pytest.mark.asyncio
    async def test_container_without_image_tags(self):
        mock_client = _make_mock_client()
        c = _make_mock_container(image_tags=[], image_id="sha256:deadbeef")
        mock_client.containers.list.return_value = [c]

        with _patch_docker_available(), patch("max.tools.native.docker_tools._get_client", return_value=mock_client):
            result = await handle_docker_list_containers({})

        assert result["containers"][0]["image"] == "sha256:deadbeef"


# ── docker.run Tests ─────────────────────────────────────────────────────


class TestDockerRun:
    @pytest.mark.asyncio
    async def test_run_basic(self):
        mock_client = _make_mock_client()
        mock_container = _make_mock_container(short_id="new123", name="new-container")
        mock_client.containers.run.return_value = mock_container

        with _patch_docker_available(), patch("max.tools.native.docker_tools._get_client", return_value=mock_client):
            result = await handle_docker_run({"image": "ubuntu:22.04"})

        assert result["container_id"] == "new123"
        assert result["name"] == "new-container"
        mock_client.containers.run.assert_called_once_with(
            image="ubuntu:22.04", detach=True
        )

    @pytest.mark.asyncio
    async def test_run_with_all_options(self):
        mock_client = _make_mock_client()
        mock_container = _make_mock_container(short_id="full123", name="my-app")
        mock_client.containers.run.return_value = mock_container

        with _patch_docker_available(), patch("max.tools.native.docker_tools._get_client", return_value=mock_client):
            result = await handle_docker_run(
                {
                    "image": "nginx:latest",
                    "command": "nginx -g 'daemon off;'",
                    "name": "my-app",
                    "detach": True,
                    "ports": {"80/tcp": 8080},
                    "environment": {"ENV": "prod"},
                }
            )

        assert result["container_id"] == "full123"
        mock_client.containers.run.assert_called_once_with(
            image="nginx:latest",
            detach=True,
            command="nginx -g 'daemon off;'",
            name="my-app",
            ports={"80/tcp": 8080},
            environment={"ENV": "prod"},
        )

    @pytest.mark.asyncio
    async def test_run_non_detached(self):
        mock_client = _make_mock_client()
        mock_container = _make_mock_container(short_id="fg123", name="foreground")
        mock_client.containers.run.return_value = mock_container

        with _patch_docker_available(), patch("max.tools.native.docker_tools._get_client", return_value=mock_client):
            result = await handle_docker_run(
                {"image": "alpine", "detach": False}
            )

        assert result["container_id"] == "fg123"
        mock_client.containers.run.assert_called_once_with(
            image="alpine", detach=False
        )


# ── docker.stop Tests ────────────────────────────────────────────────────


class TestDockerStop:
    @pytest.mark.asyncio
    async def test_stop_container(self):
        mock_client = _make_mock_client()
        mock_container = MagicMock()
        mock_container.stop = MagicMock()
        mock_client.containers.get.return_value = mock_container

        with _patch_docker_available(), patch("max.tools.native.docker_tools._get_client", return_value=mock_client):
            result = await handle_docker_stop({"container_id": "abc123"})

        assert result["stopped"] is True
        mock_client.containers.get.assert_called_once_with("abc123")
        mock_container.stop.assert_called_once()


# ── docker.logs Tests ────────────────────────────────────────────────────


class TestDockerLogs:
    @pytest.mark.asyncio
    async def test_get_logs(self):
        mock_client = _make_mock_client()
        mock_container = MagicMock()
        mock_container.logs.return_value = b"Starting server...\nListening on :8080\n"
        mock_client.containers.get.return_value = mock_container

        with _patch_docker_available(), patch("max.tools.native.docker_tools._get_client", return_value=mock_client):
            result = await handle_docker_logs({"container_id": "abc123"})

        assert "Starting server" in result["logs"]
        assert "Listening on :8080" in result["logs"]
        mock_container.logs.assert_called_once_with(tail=100)

    @pytest.mark.asyncio
    async def test_get_logs_custom_tail(self):
        mock_client = _make_mock_client()
        mock_container = MagicMock()
        mock_container.logs.return_value = b"line\n"
        mock_client.containers.get.return_value = mock_container

        with _patch_docker_available(), patch("max.tools.native.docker_tools._get_client", return_value=mock_client):
            result = await handle_docker_logs({"container_id": "abc123", "tail": 50})

        mock_container.logs.assert_called_once_with(tail=50)

    @pytest.mark.asyncio
    async def test_logs_output_cap(self):
        """Verify logs are capped at 50KB (50000 chars)."""
        mock_client = _make_mock_client()
        mock_container = MagicMock()
        # Return >50KB of log data
        mock_container.logs.return_value = b"x" * 60000
        mock_client.containers.get.return_value = mock_container

        with _patch_docker_available(), patch("max.tools.native.docker_tools._get_client", return_value=mock_client):
            result = await handle_docker_logs({"container_id": "abc123"})

        assert len(result["logs"]) == 50000


# ── docker.build Tests ───────────────────────────────────────────────────


class TestDockerBuild:
    @pytest.mark.asyncio
    async def test_build_image(self):
        mock_client = _make_mock_client()
        mock_image = MagicMock()
        mock_image.short_id = "sha256:abc123"
        mock_client.images.build.return_value = (mock_image, [{"stream": "Step 1/3"}])

        with _patch_docker_available(), patch("max.tools.native.docker_tools._get_client", return_value=mock_client):
            result = await handle_docker_build({"path": "/app", "tag": "myapp:v1"})

        assert result["image_id"] == "sha256:abc123"
        assert result["tag"] == "myapp:v1"
        mock_client.images.build.assert_called_once_with(path="/app", tag="myapp:v1")


# ── docker.compose Tests ────────────────────────────────────────────────


class TestDockerCompose:
    @pytest.mark.asyncio
    async def test_compose_up(self):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            b"Creating network...\nStarting service...\n",
            b"",
        )
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            result = await handle_docker_compose({"action": "up", "cwd": "/project"})

        assert result["exit_code"] == 0
        assert "Creating network" in result["stdout"]
        mock_exec.assert_called_once_with(
            "docker", "compose", "up", "-d",
            stdout=-1, stderr=-1, cwd="/project",
        )

    @pytest.mark.asyncio
    async def test_compose_down(self):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"Stopping...\n", b"")
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            result = await handle_docker_compose({"action": "down", "cwd": "/project"})

        assert result["exit_code"] == 0
        mock_exec.assert_called_once_with(
            "docker", "compose", "down",
            stdout=-1, stderr=-1, cwd="/project",
        )

    @pytest.mark.asyncio
    async def test_compose_ps(self):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"NAME  STATUS\nweb   running\n", b"")
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            result = await handle_docker_compose({"action": "ps", "cwd": "/project"})

        assert result["exit_code"] == 0
        assert "web" in result["stdout"]
        mock_exec.assert_called_once_with(
            "docker", "compose", "ps",
            stdout=-1, stderr=-1, cwd="/project",
        )

    @pytest.mark.asyncio
    async def test_compose_with_file(self):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"OK\n", b"")
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            result = await handle_docker_compose(
                {"action": "up", "cwd": "/project", "file": "docker-compose.prod.yml"}
            )

        assert result["exit_code"] == 0
        mock_exec.assert_called_once_with(
            "docker", "compose", "-f", "docker-compose.prod.yml", "up", "-d",
            stdout=-1, stderr=-1, cwd="/project",
        )

    @pytest.mark.asyncio
    async def test_compose_unknown_action(self):
        # The handler has a guard against unknown actions (even though schema has enum)
        result = await handle_docker_compose(
            {"action": "restart", "cwd": "/project"}
        )
        assert result["exit_code"] == 1
        assert "Unknown action" in result["stderr"]

    @pytest.mark.asyncio
    async def test_compose_error(self):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"No such file\n")
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await handle_docker_compose({"action": "up", "cwd": "/nonexist"})

        assert result["exit_code"] == 1
        assert "No such file" in result["stderr"]


# ── Missing Dependency Tests ─────────────────────────────────────────────


class TestMissingDockerDependency:
    @pytest.mark.asyncio
    async def test_list_containers_no_docker(self):
        with patch("max.tools.native.docker_tools.HAS_DOCKER", False):
            with pytest.raises(RuntimeError, match="Docker Python library is not installed"):
                await handle_docker_list_containers({})

    @pytest.mark.asyncio
    async def test_run_no_docker(self):
        with patch("max.tools.native.docker_tools.HAS_DOCKER", False):
            with pytest.raises(RuntimeError, match="Docker Python library is not installed"):
                await handle_docker_run({"image": "ubuntu"})

    @pytest.mark.asyncio
    async def test_stop_no_docker(self):
        with patch("max.tools.native.docker_tools.HAS_DOCKER", False):
            with pytest.raises(RuntimeError, match="Docker Python library is not installed"):
                await handle_docker_stop({"container_id": "abc"})

    @pytest.mark.asyncio
    async def test_logs_no_docker(self):
        with patch("max.tools.native.docker_tools.HAS_DOCKER", False):
            with pytest.raises(RuntimeError, match="Docker Python library is not installed"):
                await handle_docker_logs({"container_id": "abc"})

    @pytest.mark.asyncio
    async def test_build_no_docker(self):
        with patch("max.tools.native.docker_tools.HAS_DOCKER", False):
            with pytest.raises(RuntimeError, match="Docker Python library is not installed"):
                await handle_docker_build({"path": "/app", "tag": "test:v1"})
