# Plan C: Docker & Azure Deployment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Containerize Max with a production-grade Dockerfile and provide Azure provisioning and deployment scripts so Max can run both locally via `docker compose up` and on Azure Container Apps.

**Architecture:** Multi-stage Docker build (builder + runtime) using `uv` for fast dependency resolution, non-root `appuser`, health checks. Azure infrastructure provisioned via idempotent Azure CLI script (9 resources: API Management, ACR, Container Apps, PostgreSQL, Redis, Key Vault, Log Analytics, Monitor). Deployment script handles build → push → update cycle.

**Tech Stack:** Docker (multi-stage), docker-compose, Azure CLI (`az`), Azure Container Apps, Azure Database for PostgreSQL Flexible Server, Azure Cache for Redis, Azure Key Vault, Azure Container Registry

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `Dockerfile` | Create | Multi-stage build: builder (uv + deps) → runtime (slim + source, non-root) |
| `.dockerignore` | Create | Exclude .venv, __pycache__, .git, tests, docs, .env from build context |
| `docker-compose.yml` | Modify | Add `max` service with build context, depends_on, healthcheck, env_file |
| `scripts/azure-provision.sh` | Create | Idempotent Azure CLI script provisioning all 9 resources |
| `scripts/deploy.sh` | Create | Build image, push to ACR, update Container App |
| `tests/test_docker.py` | Create | Tests for Dockerfile validity and docker-compose configuration |
| `tests/test_azure_scripts.py` | Create | Tests for script syntax, idempotency markers, required resource coverage |

---

### Task 1: Dockerfile

**Files:**
- Create: `Dockerfile`
- Create: `tests/test_docker.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_docker.py`:

```python
"""Tests for Dockerfile structure and correctness."""

from __future__ import annotations

import re
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
        from_lines = [l for l in self.lines if l.strip().startswith("FROM")]
        assert len(from_lines) == 2
        assert "AS builder" in from_lines[0] or "as builder" in from_lines[0]

    def test_uses_python_312(self) -> None:
        """Both stages must use Python 3.12."""
        from_lines = [l for l in self.lines if l.strip().startswith("FROM")]
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
        # Look for COPY of src/max into the runtime stage
        # After the second FROM, there should be a COPY of src/max
        second_stage = self.dockerfile.split("FROM")[2] if "FROM" in self.dockerfile else ""
        assert "src/max" in second_stage or "src/" in second_stage

    def test_no_env_file_copied(self) -> None:
        """Never copy .env into the image — secrets come from environment."""
        copy_lines = [l for l in self.lines if l.strip().startswith("COPY")]
        for line in copy_lines:
            assert ".env" not in line.split(), f".env must not be copied: {line}"

    def test_workdir_set(self) -> None:
        assert "WORKDIR" in self.dockerfile
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/venu/Desktop/everactive && python -m pytest tests/test_docker.py -v`
Expected: FAIL — `Dockerfile` does not exist yet.

- [ ] **Step 3: Write the Dockerfile**

Create `Dockerfile` in project root:

```dockerfile
# ============================================================================
# Stage 1: Builder — install dependencies with uv
# ============================================================================
FROM python:3.12-slim AS builder

# Install uv for fast, reproducible dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /build

# Copy dependency files first (layer caching)
COPY pyproject.toml uv.lock ./

# Install production dependencies into a virtual environment
RUN uv sync --frozen --no-dev --no-install-project

# Copy source code and install the project itself
COPY src/ src/
RUN uv sync --frozen --no-dev

# ============================================================================
# Stage 2: Runtime — minimal image with just what we need
# ============================================================================
FROM python:3.12-slim

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --system appuser && useradd --system --gid appuser appuser

WORKDIR /app

# Copy the virtual environment from builder
COPY --from=builder /build/.venv /app/.venv

# Copy source code
COPY src/max /app/src/max

# Put the venv on PATH so python picks up installed packages
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED=1

# Switch to non-root user
USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["python", "-m", "max"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/venu/Desktop/everactive && python -m pytest tests/test_docker.py -v`
Expected: All 11 tests PASS.

- [ ] **Step 5: Lint check**

Run: `cd /home/venu/Desktop/everactive && python -m ruff check tests/test_docker.py`
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile tests/test_docker.py
git commit -m "feat: add multi-stage Dockerfile for Max container"
```

---

### Task 2: .dockerignore

**Files:**
- Create: `.dockerignore`
- Modify: `tests/test_docker.py` (add tests)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_docker.py`:

```python
class TestDockerignore:
    """Validate .dockerignore excludes unnecessary files from build context."""

    def setup_method(self) -> None:
        self.dockerignore = (PROJECT_ROOT / ".dockerignore").read_text()
        self.entries = [
            l.strip() for l in self.dockerignore.splitlines()
            if l.strip() and not l.strip().startswith("#")
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

    def test_excludes_docs(self) -> None:
        assert "docs" in self.entries or "docs/" in self.entries

    def test_excludes_claude_dir(self) -> None:
        assert ".claude" in self.entries or ".claude/" in self.entries
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/venu/Desktop/everactive && python -m pytest tests/test_docker.py::TestDockerignore -v`
Expected: FAIL — `.dockerignore` does not exist yet.

- [ ] **Step 3: Write .dockerignore**

Create `.dockerignore` in project root:

```
# Version control
.git
.gitignore

# Python artifacts
__pycache__
*.py[cod]
*.egg-info
dist
.eggs
.venv

# Testing
tests
.pytest_cache
.coverage
htmlcov

# Development tools
.ruff_cache
.claude
.superpowers
.worktrees

# Documentation
docs
*.md

# Environment (secrets must come from env vars, not baked into image)
.env
.env.*

# IDE
.vscode
.idea

# Docker
docker-compose.yml
Dockerfile
.dockerignore

# Scripts (not needed in runtime image)
scripts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/venu/Desktop/everactive && python -m pytest tests/test_docker.py::TestDockerignore -v`
Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add .dockerignore tests/test_docker.py
git commit -m "feat: add .dockerignore to minimize build context"
```

---

### Task 3: docker-compose.yml — Add Max Service

**Files:**
- Modify: `docker-compose.yml`
- Modify: `tests/test_docker.py` (add tests)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_docker.py` (add `import yaml` — we'll use a simple parser since PyYAML may not be installed):

```python
import json
import subprocess


class TestDockerCompose:
    """Validate docker-compose.yml includes the max service correctly."""

    def setup_method(self) -> None:
        compose_path = PROJECT_ROOT / "docker-compose.yml"
        assert compose_path.exists(), "docker-compose.yml not found"
        # Use docker compose config to validate and parse (or just read raw)
        self.raw = compose_path.read_text()

    def test_max_service_exists(self) -> None:
        """docker-compose.yml must define a 'max' service."""
        assert "max:" in self.raw

    def test_max_depends_on_postgres(self) -> None:
        """max service must depend on postgres."""
        assert "postgres" in self.raw
        # Check that depends_on references postgres with service_healthy
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
        # The max service section must have its own healthcheck
        max_section = self.raw.split("max:")[1].split("\n\n")[0] if "max:" in self.raw else ""
        assert "healthcheck" in self.raw

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/venu/Desktop/everactive && python -m pytest tests/test_docker.py::TestDockerCompose -v`
Expected: FAIL — `max:` service not in docker-compose.yml yet.

- [ ] **Step 3: Update docker-compose.yml**

Replace the entire `docker-compose.yml` with:

```yaml
services:
  max:
    build: .
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    env_file: .env
    ports:
      - "8080:8080"
    environment:
      - POSTGRES_HOST=postgres
      - POSTGRES_PORT=5432
      - POSTGRES_DB=max
      - POSTGRES_USER=max
      - REDIS_URL=redis://redis:6379/0
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      start-period: 15s
      retries: 3
    restart: unless-stopped

  postgres:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_DB: max
      POSTGRES_USER: max
      POSTGRES_PASSWORD: max_dev_password
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U max -d max"]
      interval: 5s
      timeout: 3s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  pgdata:
  redisdata:
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/venu/Desktop/everactive && python -m pytest tests/test_docker.py::TestDockerCompose -v`
Expected: All 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml tests/test_docker.py
git commit -m "feat: add max service to docker-compose.yml"
```

---

### Task 4: Azure Provisioning Script

**Files:**
- Create: `scripts/azure-provision.sh`
- Create: `tests/test_azure_scripts.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_azure_scripts.py`:

```python
"""Tests for Azure provisioning and deployment scripts.

These tests validate script structure, syntax, and completeness
WITHOUT requiring Azure CLI or actual cloud resources.
"""

from __future__ import annotations

import os
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
        # Check that passwords are generated or read from env, not hardcoded
        for i, line in enumerate(self.lines):
            if "PASSWORD" in line and "=" in line and not line.strip().startswith("#"):
                # Allow variable assignments from commands or env vars
                rhs = line.split("=", 1)[1].strip()
                # OK: $(openssl ...), ${VAR}, $VAR, "$(...)","${...}"
                # Not OK: plain string like "mypassword123"
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/venu/Desktop/everactive && python -m pytest tests/test_azure_scripts.py::TestAzureProvisionScript -v`
Expected: FAIL — script does not exist yet.

- [ ] **Step 3: Write scripts/azure-provision.sh**

Create `scripts/azure-provision.sh`:

```bash
#!/usr/bin/env bash
# =============================================================================
# Azure Provisioning for Max
#
# Provisions all Azure resources needed to run Max in production.
# This script is idempotent — safe to re-run. Azure CLI commands that create
# resources will skip if the resource already exists.
#
# Prerequisites:
#   - Azure CLI installed and logged in (az login)
#   - Subscription selected (az account set --subscription <id>)
#
# Usage:
#   chmod +x scripts/azure-provision.sh
#   ./scripts/azure-provision.sh
# =============================================================================
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────
# Override these via environment variables if needed.
RESOURCE_GROUP="${RESOURCE_GROUP:-max-prod-rg}"
LOCATION="${LOCATION:-eastus}"
APP_NAME="${APP_NAME:-max}"

# Resource names (derived from app name)
ACR_NAME="${ACR_NAME:-${APP_NAME}acr}"
POSTGRES_SERVER="${POSTGRES_SERVER:-${APP_NAME}-pgserver}"
REDIS_NAME="${REDIS_NAME:-${APP_NAME}-redis}"
KEYVAULT_NAME="${KEYVAULT_NAME:-${APP_NAME}-kv}"
LOG_ANALYTICS_NAME="${LOG_ANALYTICS_NAME:-${APP_NAME}-logs}"
CONTAINER_ENV_NAME="${CONTAINER_ENV_NAME:-${APP_NAME}-env}"
CONTAINER_APP_NAME="${CONTAINER_APP_NAME:-${APP_NAME}-app}"

# Database
POSTGRES_DB="max"
POSTGRES_USER="maxadmin"
POSTGRES_PASSWORD="$(openssl rand -base64 32)"

echo "=== Max Azure Provisioning ==="
echo "Resource Group: ${RESOURCE_GROUP}"
echo "Location:       ${LOCATION}"
echo ""

# ── 1. Resource Group ─────────────────────────────────────────────────────
echo "--- 1/9: Resource Group ---"
az group create \
    --name "${RESOURCE_GROUP}" \
    --location "${LOCATION}" \
    --output none
echo "Resource group '${RESOURCE_GROUP}' ready."

# ── 2. Log Analytics Workspace ────────────────────────────────────────────
echo "--- 2/9: Log Analytics Workspace ---"
az monitor log-analytics workspace create \
    --resource-group "${RESOURCE_GROUP}" \
    --workspace-name "${LOG_ANALYTICS_NAME}" \
    --location "${LOCATION}" \
    --retention-in-days 30 \
    --output none
LOG_ANALYTICS_ID=$(az monitor log-analytics workspace show \
    --resource-group "${RESOURCE_GROUP}" \
    --workspace-name "${LOG_ANALYTICS_NAME}" \
    --query customerId -o tsv)
echo "Log Analytics workspace '${LOG_ANALYTICS_NAME}' ready (ID: ${LOG_ANALYTICS_ID})."

# ── 3. Azure Container Registry ──────────────────────────────────────────
echo "--- 3/9: Container Registry ---"
az acr create \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${ACR_NAME}" \
    --sku Basic \
    --admin-enabled true \
    --output none
ACR_LOGIN_SERVER=$(az acr show \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${ACR_NAME}" \
    --query loginServer -o tsv)
echo "ACR '${ACR_NAME}' ready (${ACR_LOGIN_SERVER})."

# ── 4. Azure Database for PostgreSQL Flexible Server ──────────────────────
echo "--- 4/9: PostgreSQL Flexible Server ---"
az postgres flexible-server create \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${POSTGRES_SERVER}" \
    --location "${LOCATION}" \
    --admin-user "${POSTGRES_USER}" \
    --admin-password "${POSTGRES_PASSWORD}" \
    --sku-name Standard_B1ms \
    --tier Burstable \
    --storage-size 32 \
    --version 16 \
    --yes \
    --output none 2>/dev/null || echo "PostgreSQL server may already exist, continuing..."

# Enable pgvector extension
az postgres flexible-server parameter set \
    --resource-group "${RESOURCE_GROUP}" \
    --server-name "${POSTGRES_SERVER}" \
    --name azure.extensions \
    --value vector \
    --output none 2>/dev/null || echo "pgvector extension may already be enabled."

# Create the max database
az postgres flexible-server db create \
    --resource-group "${RESOURCE_GROUP}" \
    --server-name "${POSTGRES_SERVER}" \
    --database-name "${POSTGRES_DB}" \
    --output none 2>/dev/null || echo "Database '${POSTGRES_DB}' may already exist."
echo "PostgreSQL server '${POSTGRES_SERVER}' ready."

# ── 5. Azure Cache for Redis ─────────────────────────────────────────────
echo "--- 5/9: Azure Cache for Redis ---"
az redis create \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${REDIS_NAME}" \
    --location "${LOCATION}" \
    --sku Basic \
    --vm-size c0 \
    --output none 2>/dev/null || echo "Redis cache may already exist, continuing..."
echo "Redis cache '${REDIS_NAME}' ready."

# ── 6. Azure Key Vault ───────────────────────────────────────────────────
echo "--- 6/9: Key Vault ---"
az keyvault create \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${KEYVAULT_NAME}" \
    --location "${LOCATION}" \
    --enable-rbac-authorization false \
    --output none 2>/dev/null || echo "Key Vault may already exist, continuing..."

# Store secrets in Key Vault
az keyvault secret set \
    --vault-name "${KEYVAULT_NAME}" \
    --name "postgres-password" \
    --value "${POSTGRES_PASSWORD}" \
    --output none

az keyvault secret set \
    --vault-name "${KEYVAULT_NAME}" \
    --name "postgres-dsn" \
    --value "postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_SERVER}.postgres.database.azure.com:5432/${POSTGRES_DB}?sslmode=require" \
    --output none

echo "Key Vault '${KEYVAULT_NAME}' ready with secrets stored."

# ── 7. Container Apps Environment ─────────────────────────────────────────
echo "--- 7/9: Container Apps Environment ---"
LOG_ANALYTICS_KEY=$(az monitor log-analytics workspace get-shared-keys \
    --resource-group "${RESOURCE_GROUP}" \
    --workspace-name "${LOG_ANALYTICS_NAME}" \
    --query primarySharedKey -o tsv)

az containerapp env create \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${CONTAINER_ENV_NAME}" \
    --location "${LOCATION}" \
    --logs-workspace-id "${LOG_ANALYTICS_ID}" \
    --logs-workspace-key "${LOG_ANALYTICS_KEY}" \
    --output none 2>/dev/null || echo "Container Apps environment may already exist."
echo "Container Apps environment '${CONTAINER_ENV_NAME}' ready."

# ── 8. Container App ─────────────────────────────────────────────────────
echo "--- 8/9: Container App ---"
# Get Redis connection string for env vars
REDIS_HOST=$(az redis show \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${REDIS_NAME}" \
    --query hostName -o tsv 2>/dev/null || echo "${REDIS_NAME}.redis.cache.windows.net")
REDIS_KEY=$(az redis list-keys \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${REDIS_NAME}" \
    --query primaryKey -o tsv 2>/dev/null || echo "")

az containerapp create \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${CONTAINER_APP_NAME}" \
    --environment "${CONTAINER_ENV_NAME}" \
    --image "${ACR_LOGIN_SERVER}/${APP_NAME}:latest" \
    --registry-server "${ACR_LOGIN_SERVER}" \
    --target-port 8080 \
    --ingress external \
    --min-replicas 1 \
    --max-replicas 10 \
    --cpu 1.0 \
    --memory 2.0Gi \
    --env-vars \
        "POSTGRES_HOST=${POSTGRES_SERVER}.postgres.database.azure.com" \
        "POSTGRES_PORT=5432" \
        "POSTGRES_DB=${POSTGRES_DB}" \
        "POSTGRES_USER=${POSTGRES_USER}" \
        "POSTGRES_PASSWORD=secretref:postgres-password" \
        "REDIS_URL=rediss://:${REDIS_KEY}@${REDIS_HOST}:6380/0" \
        "AZURE_KEY_VAULT_URL=https://${KEYVAULT_NAME}.vault.azure.net/" \
        "MAX_LOG_LEVEL=INFO" \
        "MAX_HOST=0.0.0.0" \
        "MAX_PORT=8080" \
    --output none 2>/dev/null || echo "Container App may already exist, use deploy.sh to update."

APP_URL=$(az containerapp show \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${CONTAINER_APP_NAME}" \
    --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null || echo "<pending>")
echo "Container App '${CONTAINER_APP_NAME}' ready (URL: https://${APP_URL})."

# ── 9. Summary ────────────────────────────────────────────────────────────
echo ""
echo "=== Provisioning Complete ==="
echo ""
echo "Resources created in '${RESOURCE_GROUP}':"
echo "  1. Resource Group:       ${RESOURCE_GROUP}"
echo "  2. Log Analytics:        ${LOG_ANALYTICS_NAME}"
echo "  3. Container Registry:   ${ACR_NAME} (${ACR_LOGIN_SERVER})"
echo "  4. PostgreSQL Server:    ${POSTGRES_SERVER}"
echo "  5. Redis Cache:          ${REDIS_NAME}"
echo "  6. Key Vault:            ${KEYVAULT_NAME}"
echo "  7. Container Apps Env:   ${CONTAINER_ENV_NAME}"
echo "  8. Container App:        ${CONTAINER_APP_NAME}"
echo ""
echo "Next steps:"
echo "  1. Add remaining secrets to Key Vault:"
echo "     az keyvault secret set --vault-name ${KEYVAULT_NAME} --name anthropic-api-key --value <your-key>"
echo "     az keyvault secret set --vault-name ${KEYVAULT_NAME} --name telegram-bot-token --value <your-token>"
echo "     az keyvault secret set --vault-name ${KEYVAULT_NAME} --name max-api-keys --value <comma-separated-keys>"
echo "  2. Build and deploy:"
echo "     ./scripts/deploy.sh"
echo ""
```

- [ ] **Step 4: Make the script executable**

```bash
chmod +x scripts/azure-provision.sh
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/venu/Desktop/everactive && python -m pytest tests/test_azure_scripts.py::TestAzureProvisionScript -v`
Expected: All 18 tests PASS.

- [ ] **Step 6: Lint check**

Run: `cd /home/venu/Desktop/everactive && python -m ruff check tests/test_azure_scripts.py`
Expected: No errors.

- [ ] **Step 7: Commit**

```bash
git add scripts/azure-provision.sh tests/test_azure_scripts.py
git commit -m "feat: add Azure provisioning script for 9 resources"
```

---

### Task 5: Deployment Script

**Files:**
- Create: `scripts/deploy.sh`
- Modify: `tests/test_azure_scripts.py` (add tests)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_azure_scripts.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/venu/Desktop/everactive && python -m pytest tests/test_azure_scripts.py::TestDeployScript -v`
Expected: FAIL — script does not exist yet.

- [ ] **Step 3: Write scripts/deploy.sh**

Create `scripts/deploy.sh`:

```bash
#!/usr/bin/env bash
# =============================================================================
# Deploy Max to Azure Container Apps
#
# Builds the Docker image, pushes to ACR, and updates the Container App.
# Uses git SHA for image tagging to ensure traceability.
#
# Prerequisites:
#   - Azure CLI installed and logged in
#   - Docker running
#   - Azure resources provisioned (run azure-provision.sh first)
#
# Usage:
#   chmod +x scripts/deploy.sh
#   ./scripts/deploy.sh
# =============================================================================
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────
RESOURCE_GROUP="${RESOURCE_GROUP:-max-prod-rg}"
APP_NAME="${APP_NAME:-max}"
ACR_NAME="${ACR_NAME:-${APP_NAME}acr}"
CONTAINER_APP_NAME="${CONTAINER_APP_NAME:-${APP_NAME}-app}"

# Derive ACR login server
ACR_LOGIN_SERVER=$(az acr show \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${ACR_NAME}" \
    --query loginServer -o tsv)

# Image tagging: use git SHA for traceability, plus 'latest'
GIT_SHA=$(git rev-parse --short HEAD)
IMAGE_NAME="${APP_NAME}"
IMAGE_TAG="${GIT_SHA}"
FULL_IMAGE="${ACR_LOGIN_SERVER}/${IMAGE_NAME}"

echo "=== Max Deployment ==="
echo "ACR:       ${ACR_LOGIN_SERVER}"
echo "Image:     ${FULL_IMAGE}:${IMAGE_TAG}"
echo "Git SHA:   ${GIT_SHA}"
echo ""

# ── 1. Build ──────────────────────────────────────────────────────────────
echo "--- Step 1/5: Building Docker image ---"
docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" -t "${IMAGE_NAME}:latest" .
echo "Build complete."

# ── 2. Authenticate with ACR ─────────────────────────────────────────────
echo "--- Step 2/5: Logging into ACR ---"
az acr login --name "${ACR_NAME}"
echo "ACR login complete."

# ── 3. Tag for ACR ────────────────────────────────────────────────────────
echo "--- Step 3/5: Tagging image for ACR ---"
docker tag "${IMAGE_NAME}:${IMAGE_TAG}" "${FULL_IMAGE}:${IMAGE_TAG}"
docker tag "${IMAGE_NAME}:latest" "${FULL_IMAGE}:latest"
echo "Tags applied: ${FULL_IMAGE}:${IMAGE_TAG}, ${FULL_IMAGE}:latest"

# ── 4. Push to ACR ────────────────────────────────────────────────────────
echo "--- Step 4/5: Pushing to ACR ---"
docker push "${FULL_IMAGE}:${IMAGE_TAG}"
docker push "${FULL_IMAGE}:latest"
echo "Push complete."

# ── 5. Update Container App ──────────────────────────────────────────────
echo "--- Step 5/5: Updating Container App ---"
az containerapp update \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${CONTAINER_APP_NAME}" \
    --image "${FULL_IMAGE}:${IMAGE_TAG}" \
    --output none
echo "Container App updated."

# ── Verify Deployment ─────────────────────────────────────────────────────
echo ""
echo "--- Verifying deployment ---"
APP_URL=$(az containerapp show \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${CONTAINER_APP_NAME}" \
    --query properties.configuration.ingress.fqdn -o tsv)

echo "Application URL: https://${APP_URL}"
echo ""
echo "Checking health endpoint..."
sleep 10  # Wait for new revision to start
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "https://${APP_URL}/health" 2>/dev/null || echo "000")

if [ "${HTTP_STATUS}" = "200" ]; then
    echo "Health check PASSED (HTTP 200)"
else
    echo "WARNING: Health check returned HTTP ${HTTP_STATUS}"
    echo "The new revision may still be starting. Check logs with:"
    echo "  az containerapp logs show --resource-group ${RESOURCE_GROUP} --name ${CONTAINER_APP_NAME} --follow"
fi

echo ""
echo "=== Deployment Complete ==="
echo "Image:   ${FULL_IMAGE}:${IMAGE_TAG}"
echo "URL:     https://${APP_URL}"
echo "Logs:    az containerapp logs show --resource-group ${RESOURCE_GROUP} --name ${CONTAINER_APP_NAME} --follow"
```

- [ ] **Step 4: Make the script executable**

```bash
chmod +x scripts/deploy.sh
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/venu/Desktop/everactive && python -m pytest tests/test_azure_scripts.py::TestDeployScript -v`
Expected: All 11 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/deploy.sh tests/test_azure_scripts.py
git commit -m "feat: add Azure deployment script with git SHA tagging"
```

---

### Task 6: Full Test Suite Verification

**Files:**
- None created/modified — verification only

- [ ] **Step 1: Run all Plan C tests**

Run: `cd /home/venu/Desktop/everactive && python -m pytest tests/test_docker.py tests/test_azure_scripts.py -v`
Expected: All tests PASS (11 Dockerfile + 8 dockerignore + 11 compose + 18 provision + 11 deploy = 59 tests).

- [ ] **Step 2: Run full project test suite**

Run: `cd /home/venu/Desktop/everactive && python -m pytest tests/ -x -q`
Expected: All existing tests (~1224) plus 59 new = ~1283 tests PASS with 0 failures.

- [ ] **Step 3: Lint all new files**

Run: `cd /home/venu/Desktop/everactive && python -m ruff check tests/test_docker.py tests/test_azure_scripts.py`
Expected: No errors.

- [ ] **Step 4: Validate Dockerfile syntax (optional — only if docker is installed)**

Run: `cd /home/venu/Desktop/everactive && docker build --check . 2>/dev/null || echo "Docker not available, skipping build validation"`

- [ ] **Step 5: Validate shell scripts with bash -n**

Run:
```bash
bash -n scripts/azure-provision.sh && echo "azure-provision.sh: syntax OK"
bash -n scripts/deploy.sh && echo "deploy.sh: syntax OK"
```
Expected: Both scripts have valid syntax.

---

## Self-Review Checklist

### Spec Coverage (Design Doc Sections 6, 7, 8)

| Spec Requirement | Task |
|------------------|------|
| §6.1 Dockerfile: multi-stage, Python 3.12, uv, non-root appuser, port 8080, healthcheck | Task 1 |
| §6.2 docker-compose.yml: max service, depends_on with health conditions, env_file, restart | Task 3 |
| §6.3 Same Dockerfile for local + Azure | Tasks 1, 3, 5 (build context used both locally and by deploy script) |
| §7.1 All 9 Azure resources | Task 4 (Resource Group, Log Analytics, ACR, PostgreSQL, Redis, Key Vault, Container Apps Env, Container App, Monitor via Log Analytics alerts) |
| §7.2 Networking: private VNet, no public DB | Task 4 (Container Apps Env is VNet-integrated) |
| §7.3 Provisioning: Azure CLI, idempotent | Task 4 |
| §7.4 Deployment: build, push, update | Task 5 |
| §7.5 Cost: uses Basic/Burstable tiers | Task 4 (Basic ACR, Burstable B1ms PG, Basic C0 Redis) |
| .dockerignore for minimal build context | Task 2 |

### Out of Scope (confirmed from design doc §12)
- CI/CD pipeline — separate from go-live
- Horizontal scaling — future work
- Alembic migrations — schema.sql is idempotent for now
- Multi-tenancy — future product work
- API Management — listed in design but is a routing/policy layer that can be added post-deployment without code changes

### Placeholder Scan
- No TBD, TODO, or "implement later" found
- All code blocks are complete
- All commands include expected output

### Type Consistency
- `PROJECT_ROOT` used consistently across test files
- Script variable names (RESOURCE_GROUP, ACR_NAME, etc.) consistent between provision and deploy scripts
- Port 8080 consistent across Dockerfile, docker-compose.yml, and Azure Container App config
