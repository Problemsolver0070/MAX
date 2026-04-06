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
