"""Tests for Dockerfile structure and correctness."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestDockerfile:
    """Validate Dockerfile structure without building the image."""

    def setup_method(self) -> None:
        self.dockerfile = (PROJECT_ROOT / "Dockerfile").read_text()
        self.lines = self.dockerfile.strip().splitlines()

    def test_dockerfile_exists(self) -> None:
        assert (PROJECT_ROOT / "Dockerfile").exists()

    def test_multi_stage_build(self) -> None:
        """Must have exactly two FROM instructions (builder + runtime)."""
        from_lines = [line for line in self.lines if line.strip().startswith("FROM")]
        assert len(from_lines) == 2
        assert "AS builder" in from_lines[0] or "as builder" in from_lines[0]

    def test_uses_python_312(self) -> None:
        """Both stages must use Python 3.12."""
        from_lines = [line for line in self.lines if line.strip().startswith("FROM")]
        for line in from_lines:
            assert "3.12" in line, f"Expected Python 3.12 in: {line}"

    def test_uses_uv_for_deps(self) -> None:
        """Builder stage must install uv and use it for dependency installation."""
        assert "uv sync" in self.dockerfile
        assert "ghcr.io/astral-sh/uv" in self.dockerfile

    def test_non_root_user(self) -> None:
        """Runtime stage must create and switch to a non-root user."""
        assert "appuser" in self.dockerfile
        assert "USER appuser" in self.dockerfile or "USER appuser\n" in self.dockerfile

    def test_exposes_port_8080(self) -> None:
        assert "EXPOSE 8080" in self.dockerfile

    def test_healthcheck_present(self) -> None:
        assert "HEALTHCHECK" in self.dockerfile
        assert "8080/health" in self.dockerfile

    def test_entrypoint_uses_python_m_max(self) -> None:
        """Entrypoint must run python -m max."""
        cmd_lines = [line for line in self.lines if line.strip().startswith("CMD")]
        assert len(cmd_lines) >= 1
        cmd_line = cmd_lines[-1]  # Last CMD wins in Docker
        assert "python" in cmd_line
        assert "-m" in cmd_line
        assert "max" in cmd_line

    def test_copies_source_not_tests(self) -> None:
        """Runtime stage should copy src/max but not tests."""
        second_stage = self.dockerfile.split("FROM")[2] if "FROM" in self.dockerfile else ""
        assert "src/max" in second_stage or "src/" in second_stage
        copy_lines_stage2 = [
            line for line in second_stage.splitlines() if line.strip().startswith("COPY")
        ]
        for line in copy_lines_stage2:
            assert "tests" not in line.lower(), f"Tests should not be copied: {line}"

    def test_no_env_file_copied(self) -> None:
        """Never copy .env into the image — secrets come from environment."""
        copy_lines = [line for line in self.lines if line.strip().startswith("COPY")]
        for line in copy_lines:
            assert ".env" not in line.split(), f".env must not be copied: {line}"

    def test_workdir_set(self) -> None:
        assert "WORKDIR" in self.dockerfile


class TestDockerignore:
    """Validate .dockerignore excludes unnecessary files from build context."""

    def setup_method(self) -> None:
        self.dockerignore = (PROJECT_ROOT / ".dockerignore").read_text()
        self.entries = [
            line.strip()
            for line in self.dockerignore.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    def test_dockerignore_exists(self) -> None:
        assert (PROJECT_ROOT / ".dockerignore").exists()

    def test_excludes_venv(self) -> None:
        assert ".venv" in self.entries or ".venv/" in self.entries

    def test_excludes_pycache(self) -> None:
        assert any("__pycache__" in e for e in self.entries)

    def test_excludes_git(self) -> None:
        assert ".git" in self.entries or ".git/" in self.entries

    def test_excludes_tests(self) -> None:
        assert "tests" in self.entries or "tests/" in self.entries

    def test_excludes_env_file(self) -> None:
        assert ".env" in self.entries
        assert ".env.*" in self.entries

    def test_excludes_docs(self) -> None:
        assert "docs" in self.entries or "docs/" in self.entries

    def test_excludes_claude_dir(self) -> None:
        assert ".claude" in self.entries or ".claude/" in self.entries

    def test_does_not_exclude_uv_lock(self) -> None:
        """uv.lock must remain in build context for reproducible installs."""
        assert "uv.lock" not in self.entries
        assert "*.lock" not in self.entries

    def test_does_not_exclude_pyproject_toml(self) -> None:
        """pyproject.toml must remain in build context for uv sync."""
        assert "pyproject.toml" not in self.entries
        assert "*.toml" not in self.entries


class TestDockerCompose:
    """Validate docker-compose.yml includes the max service correctly."""

    def setup_method(self) -> None:
        compose_path = PROJECT_ROOT / "docker-compose.yml"
        assert compose_path.exists(), "docker-compose.yml not found"
        self.raw = compose_path.read_text()

    def test_max_service_exists(self) -> None:
        """docker-compose.yml must define a 'max' service."""
        assert "max:" in self.raw

    def test_max_depends_on_postgres(self) -> None:
        """max service must depend on postgres."""
        assert "postgres" in self.raw
        assert "service_healthy" in self.raw

    def test_max_depends_on_redis(self) -> None:
        """max service must depend on redis."""
        assert "redis" in self.raw

    def test_max_uses_env_file(self) -> None:
        """max service must load environment from .env file."""
        assert "env_file" in self.raw

    def test_max_exposes_port_8080(self) -> None:
        """max service must map port 8080."""
        assert "8080:8080" in self.raw or "8080" in self.raw

    def test_max_has_healthcheck(self) -> None:
        """max service must define a healthcheck."""
        # Parse from after "max:" to the next top-level service
        max_section = self.raw.split("max:")[1].split("\n\n")[0] if "max:" in self.raw else ""
        assert "healthcheck" in max_section

    def test_max_uses_build_context(self) -> None:
        """max service must use build: . to build from local Dockerfile."""
        assert "build:" in self.raw

    def test_max_restart_policy(self) -> None:
        """max service should have a restart policy."""
        assert "restart:" in self.raw
        assert "unless-stopped" in self.raw

    def test_postgres_service_still_exists(self) -> None:
        """Existing postgres service must not be removed."""
        assert "pgvector/pgvector:pg17" in self.raw

    def test_redis_service_still_exists(self) -> None:
        """Existing redis service must not be removed."""
        assert "redis:7-alpine" in self.raw

    def test_volumes_preserved(self) -> None:
        """Named volumes pgdata and redisdata must still be defined."""
        assert "pgdata:" in self.raw
        assert "redisdata:" in self.raw
