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

# Check if PostgreSQL server already exists to preserve existing password
if az postgres flexible-server show \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${POSTGRES_SERVER}" \
    --output none 2>/dev/null; then
    echo "PostgreSQL server exists, retrieving password from Key Vault..."
    POSTGRES_PASSWORD=$(az keyvault secret show \
        --vault-name "${KEYVAULT_NAME}" \
        --name "postgres-password" \
        --query value -o tsv 2>/dev/null || echo "")
    if [ -z "${POSTGRES_PASSWORD}" ]; then
        echo "WARNING: Could not retrieve password from Key Vault, generating new one."
        POSTGRES_PASSWORD="$(openssl rand -base64 32)"
    fi
else
    POSTGRES_PASSWORD="$(openssl rand -base64 32)"
fi

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

# Fetch Redis connection details for Key Vault storage and Container App secrets
REDIS_HOST=$(az redis show \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${REDIS_NAME}" \
    --query hostName -o tsv 2>/dev/null || echo "${REDIS_NAME}.redis.cache.windows.net")
REDIS_KEY=$(az redis list-keys \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${REDIS_NAME}" \
    --query primaryKey -o tsv 2>/dev/null || echo "")
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

# Store Redis connection URL in Key Vault
if [ -n "${REDIS_KEY}" ]; then
    az keyvault secret set \
        --vault-name "${KEYVAULT_NAME}" \
        --name "redis-url" \
        --value "rediss://:${REDIS_KEY}@${REDIS_HOST}:6380/0" \
        --output none
fi

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
    --secrets \
        "postgres-password=${POSTGRES_PASSWORD}" \
        "redis-url=rediss://:${REDIS_KEY}@${REDIS_HOST}:6380/0" \
    --env-vars \
        "POSTGRES_HOST=${POSTGRES_SERVER}.postgres.database.azure.com" \
        "POSTGRES_PORT=5432" \
        "POSTGRES_DB=${POSTGRES_DB}" \
        "POSTGRES_USER=${POSTGRES_USER}" \
        "POSTGRES_PASSWORD=secretref:postgres-password" \
        "REDIS_URL=secretref:redis-url" \
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
