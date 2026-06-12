#!/bin/bash
# Deploy StarGate platform to ocpv-infra01
# Usage: ./scripts/deploy-infra01.sh [--build] [--dry-run]
#
# Prerequisites:
#   - oc logged into ocpv-infra01
#   - kubeconfigs in secrets/ with valid SA tokens
#   - LiteLLM API key

set -euo pipefail

NAMESPACE="stargate"
REGISTRY="image-registry.openshift-image-registry.svc:5000/${NAMESPACE}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

BUILD=false
DRY_RUN=false
for arg in "$@"; do
  case $arg in
    --build) BUILD=true ;;
    --dry-run) DRY_RUN=true ;;
  esac
done

echo "=== StarGate Deployment to ocpv-infra01 ==="
echo ""

# Verify cluster connection
echo "1. Verifying cluster connection..."
CLUSTER=$(oc whoami --show-server 2>/dev/null || echo "NOT CONNECTED")
if [[ "$CLUSTER" != *"infra01"* ]]; then
  echo "ERROR: Not connected to infra01. Run:"
  echo "  oc login --server=https://api.cluster.example.com:6443"
  exit 1
fi
echo "   Connected to: $CLUSTER as $(oc whoami)"

# Create namespace
echo "2. Creating namespace..."
oc new-project "$NAMESPACE" 2>/dev/null || oc project "$NAMESPACE"

# Create kubeconfigs secret
echo "3. Creating kubeconfigs secret..."
if oc get secret stargate-kubeconfigs -n "$NAMESPACE" &>/dev/null; then
  echo "   Secret exists — deleting and recreating..."
  oc delete secret stargate-kubeconfigs -n "$NAMESPACE"
fi
oc create secret generic stargate-kubeconfigs -n "$NAMESPACE" \
  --from-file=kubeconfig-ocpv05="${PROJECT_DIR}/secrets/kubeconfig-ocpv05" \
  --from-file=kubeconfig-cnv="${PROJECT_DIR}/secrets/kubeconfig-cnv" \
  --from-file=kubeconfig-ocpv07="${PROJECT_DIR}/secrets/kubeconfig-ocpv07" \
  --from-file=kubeconfig-ocpv08="${PROJECT_DIR}/secrets/kubeconfig-ocpv08" \
  --from-file=kubeconfig-ocpv09="${PROJECT_DIR}/secrets/kubeconfig-ocpv09" \
  --from-file=kubeconfig-ocpv10="${PROJECT_DIR}/secrets/kubeconfig-ocpv10" \
  --from-file=kubeconfig-infra01="${PROJECT_DIR}/secrets/kubeconfig-infra01" \
  --from-file=kubeconfig-infra02="${PROJECT_DIR}/secrets/kubeconfig-infra02" \
  --from-file=kubeconfig="${PROJECT_DIR}/secrets/kubeconfig" \
  --from-file=kubeconfig-executor="${PROJECT_DIR}/secrets/kubeconfig-executor"

# Create app secrets
echo "4. Creating app secrets..."
PG_PASS=$(openssl rand -hex 16)
ADMIN_KEY=$(openssl rand -hex 24)
COOKIE_SECRET=$(openssl rand -hex 16)

if oc get secret stargate-secrets -n "$NAMESPACE" &>/dev/null; then
  echo "   Secret exists — keeping existing values"
else
  echo "   Enter LiteLLM API key (or press Enter to skip LLM features):"
  read -r LITELLM_KEY
  oc create secret generic stargate-secrets -n "$NAMESPACE" \
    --from-literal=postgres-password="$PG_PASS" \
    --from-literal=litellm-api-key="${LITELLM_KEY:-none}" \
    --from-literal=admin-api-key="$ADMIN_KEY"
  echo "   Admin API key: $ADMIN_KEY (save this!)"
fi

# OAuth setup
echo "5. Setting up OAuth..."
oc adm policy add-cluster-role-to-user system:auth-delegator -z stargate-frontend -n "$NAMESPACE" 2>/dev/null || true

# Build images
if [ "$BUILD" = true ]; then
  echo "6. Building and pushing images..."
  oc registry login

  podman build -t "${REGISTRY}/stargate-api:latest" -f "${PROJECT_DIR}/Containerfile" "${PROJECT_DIR}"
  podman build -t "${REGISTRY}/stargate-scanner:latest" -f "${PROJECT_DIR}/Containerfile.scanner" "${PROJECT_DIR}"
  podman build -t "${REGISTRY}/stargate-frontend:latest" -f "${PROJECT_DIR}/Containerfile.frontend" "${PROJECT_DIR}"

  podman push "${REGISTRY}/stargate-api:latest"
  podman push "${REGISTRY}/stargate-scanner:latest"
  podman push "${REGISTRY}/stargate-frontend:latest"
  echo "   Images pushed to internal registry"
else
  echo "6. Skipping image build (use --build to build)"
fi

# Deploy
echo "7. Deploying with Helm..."
HELM_CMD="helm upgrade --install stargate ${PROJECT_DIR}/deploy/helm/stargate \
  -n ${NAMESPACE} \
  -f ${PROJECT_DIR}/deploy/helm/stargate/values-infra01.yaml \
  --set oauth.cookieSecret=${COOKIE_SECRET} \
  --wait --timeout 300s"

if [ "$DRY_RUN" = true ]; then
  echo "   DRY RUN: $HELM_CMD --dry-run"
  eval "$HELM_CMD --dry-run" 2>&1 | head -50
else
  eval "$HELM_CMD"
fi

# Verify
echo ""
echo "=== Deployment Complete ==="
echo ""
oc get pods -n "$NAMESPACE"
echo ""
echo "URLs:"
echo "  Dashboard: https://stargate.apps.cluster.example.com"
echo "  API:       https://stargate-api.apps.cluster.example.com"
echo "  Health:    https://stargate-api.apps.cluster.example.com/health"
echo "  Metrics:   https://stargate-api.apps.cluster.example.com/metrics"
echo "  LLM Admin: https://stargate.apps.cluster.example.com/llm"
echo ""
if [ -n "${ADMIN_KEY:-}" ]; then
  echo "Admin API Key: $ADMIN_KEY"
  echo "(Use with: curl -H 'X-API-Key: $ADMIN_KEY' ...)"
fi
