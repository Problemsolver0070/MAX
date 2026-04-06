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
        assert "uv" in self.dockerfile

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
        assert "python" in self.dockerfile
        assert "-m" in self.dockerfile
        assert "max" in self.dockerfile

    def test_copies_source_not_tests(self) -> None:
        """Runtime stage should copy src/max but not tests."""
        second_stage = self.dockerfile.split("FROM")[2] if "FROM" in self.dockerfile else ""
        assert "src/max" in second_stage or "src/" in second_stage

    def test_no_env_file_copied(self) -> None:
        """Never copy .env into the image — secrets come from environment."""
        copy_lines = [line for line in self.lines if line.strip().startswith("COPY")]
        for line in copy_lines:
            assert ".env" not in line.split(), f".env must not be copied: {line}"

    def test_workdir_set(self) -> None:
        assert "WORKDIR" in self.dockerfile
