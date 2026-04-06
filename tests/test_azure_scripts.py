"""Tests for Azure provisioning and deployment scripts.

These tests validate script structure, syntax, and completeness
WITHOUT requiring Azure CLI or actual cloud resources.
"""

from __future__ import annotations

import stat
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestAzureProvisionScript:
    """Validate scripts/azure-provision.sh structure and completeness."""

    def setup_method(self) -> None:
        self.script_path = PROJECT_ROOT / "scripts" / "azure-provision.sh"
        self.script = self.script_path.read_text()
        self.lines = self.script.splitlines()

    def test_script_exists(self) -> None:
        assert self.script_path.exists()

    def test_script_is_executable(self) -> None:
        mode = self.script_path.stat().st_mode
        assert mode & stat.S_IXUSR, "Script must be executable (chmod +x)"

    def test_has_bash_shebang(self) -> None:
        assert self.lines[0].startswith("#!/"), "Must have a shebang line"
        assert "bash" in self.lines[0], "Must use bash"

    def test_uses_strict_mode(self) -> None:
        """Script must use set -euo pipefail for safety."""
        assert "set -euo pipefail" in self.script

    def test_defines_resource_group(self) -> None:
        assert "RESOURCE_GROUP" in self.script

    def test_defines_location(self) -> None:
        assert "LOCATION" in self.script

    def test_provisions_resource_group(self) -> None:
        assert "az group create" in self.script

    def test_provisions_log_analytics(self) -> None:
        """Must provision Log Analytics workspace."""
        assert "az monitor log-analytics workspace create" in self.script

    def test_provisions_acr(self) -> None:
        """Must provision Azure Container Registry."""
        assert "az acr create" in self.script

    def test_provisions_postgresql(self) -> None:
        """Must provision PostgreSQL Flexible Server."""
        assert "az postgres flexible-server create" in self.script

    def test_provisions_redis(self) -> None:
        """Must provision Azure Cache for Redis."""
        assert "az redis create" in self.script

    def test_provisions_container_apps_environment(self) -> None:
        """Must provision Container Apps Environment."""
        assert "az containerapp env create" in self.script

    def test_provisions_container_app(self) -> None:
        """Must provision the Container App itself."""
        assert "az containerapp create" in self.script

    def test_provisions_key_vault(self) -> None:
        """Must provision Azure Key Vault."""
        assert "az keyvault create" in self.script

    def test_enables_pgvector_extension(self) -> None:
        """Must enable the pgvector extension on PostgreSQL."""
        assert "pgvector" in self.script or "vector" in self.script

    def test_has_idempotency_notes(self) -> None:
        """Script should document that it's idempotent / safe to re-run."""
        lower = self.script.lower()
        assert "idempotent" in lower or "re-run" in lower or "if-not-exists" in lower

    def test_configures_key_vault_secrets(self) -> None:
        """Must store secrets in Key Vault."""
        assert "az keyvault secret set" in self.script

    def test_no_hardcoded_passwords(self) -> None:
        """Must not contain hardcoded passwords — use variables or generation."""
        import re

        # Only check lines that are shell variable assignments (VAR=value)
        assign_re = re.compile(r"^\s*[A-Z_]+=")
        for i, line in enumerate(self.lines):
            if "PASSWORD" in line and assign_re.match(line) and not line.strip().startswith("#"):
                rhs = line.split("=", 1)[1].strip()
                assert (
                    "$(" in rhs
                    or "${" in rhs
                    or "$" in rhs
                    or "openssl" in rhs
                    or rhs.startswith('"$(')
                    or rhs == '""'
                    or rhs == "''"
                    or len(rhs) == 0
                ), f"Line {i+1} may contain a hardcoded password: {line.strip()}"


class TestDeployScript:
    """Validate scripts/deploy.sh structure and completeness."""

    def setup_method(self) -> None:
        self.script_path = PROJECT_ROOT / "scripts" / "deploy.sh"
        self.script = self.script_path.read_text()
        self.lines = self.script.splitlines()

    def test_script_exists(self) -> None:
        assert self.script_path.exists()

    def test_script_is_executable(self) -> None:
        mode = self.script_path.stat().st_mode
        assert mode & stat.S_IXUSR, "Script must be executable (chmod +x)"

    def test_has_bash_shebang(self) -> None:
        assert self.lines[0].startswith("#!/")
        assert "bash" in self.lines[0]

    def test_uses_strict_mode(self) -> None:
        assert "set -euo pipefail" in self.script

    def test_builds_docker_image(self) -> None:
        """Must build the Docker image."""
        assert "docker build" in self.script

    def test_logs_into_acr(self) -> None:
        """Must authenticate with Azure Container Registry."""
        assert "az acr login" in self.script

    def test_tags_image(self) -> None:
        """Must tag image for ACR."""
        assert "docker tag" in self.script

    def test_pushes_image(self) -> None:
        """Must push image to ACR."""
        assert "docker push" in self.script

    def test_updates_container_app(self) -> None:
        """Must update the Container App with new image."""
        assert "az containerapp update" in self.script

    def test_uses_git_sha_tag(self) -> None:
        """Should tag images with git SHA for traceability."""
        assert "git rev-parse" in self.script or "GIT_SHA" in self.script

    def test_verification_step(self) -> None:
        """Should verify deployment succeeded (health check or status)."""
        assert "health" in self.script.lower() or "verify" in self.script.lower()

    def test_exits_on_health_check_failure(self) -> None:
        """Script must exit non-zero if health check fails after retries."""
        assert "exit 1" in self.script
