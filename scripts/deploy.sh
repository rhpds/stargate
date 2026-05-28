#!/bin/bash
# ============================================================
# StarGate Deploy Script
# ============================================================
# Usage:
#   ./scripts/deploy.sh                    # Build + deploy
#   ./scripts/deploy.sh --build-only       # Build without deploying
#   ./scripts/deploy.sh --deploy-only      # Deploy existing image
#   ./scripts/deploy.sh --set-secret KEY=VALUE  # Update a secret
#
# Prerequisites:
#   - secrets/deployer-token (SA token for oc rollout)
#   - oc login session for image push (user token)
#
# Environment:
#   STARGATE_CLUSTER  — API server URL (default: infra01)
#   STARGATE_NS       — namespace (default: stargate)
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

CLUSTER="${STARGATE_CLUSTER:-https://api.ocpv-infra01.dal12.infra.demo.redhat.com:6443}"
NS="${STARGATE_NS:-stargate}"
REGISTRY="default-route-openshift-image-registry.apps.ocpv-infra01.dal12.infra.demo.redhat.com"
INTERNAL_REG="image-registry.openshift-image-registry.svc:5000/${NS}"
GIT_SHA=$(git rev-parse --short HEAD)
DEPLOYER_TOKEN="${PROJECT_DIR}/secrets/deployer-token"

BUILD=true
DEPLOY=true
SET_SECRET=""

for arg in "$@"; do
  case $arg in
    --build-only)  DEPLOY=false ;;
    --deploy-only) BUILD=false ;;
    --set-secret)  shift; SET_SECRET="$1" ;;
    --set-secret=*) SET_SECRET="${arg#*=}" ;;
  esac
done

echo "=== StarGate Deploy ==="
echo "Cluster:  ${CLUSTER}"
echo "Git SHA:  ${GIT_SHA}"
echo ""

# --- Update secret ---
if [ -n "${SET_SECRET}" ]; then
  KEY="${SET_SECRET%%=*}"
  VALUE="${SET_SECRET#*=}"
  echo "Updating secret: ${KEY}"

  if [ -f "$DEPLOYER_TOKEN" ]; then
    oc login --token="$(cat "$DEPLOYER_TOKEN")" --server="$CLUSTER" 2>&1 | tail -1
  fi
  oc project "$NS" 2>/dev/null

  oc patch secret stargate-secrets -n "$NS" \
    -p "{\"stringData\":{\"${KEY}\":\"${VALUE}\"}}"
  echo "Secret updated. Restarting..."
  oc rollout restart deployment/stargate-api -n "$NS"
  oc rollout status deployment/stargate-api -n "$NS" --timeout=120s
  exit 0
fi

# --- Build ---
if [ "$BUILD" = true ]; then
  echo "1. Building stargate-api:${GIT_SHA}..."
  podman build --platform linux/amd64 \
    -t "${INTERNAL_REG}/stargate-api:${GIT_SHA}" \
    -t "${INTERNAL_REG}/stargate-api:latest" \
    -f Containerfile . 2>&1 | tail -3

  echo ""
  echo "2. Pushing to registry..."
  podman tag "${INTERNAL_REG}/stargate-api:latest" "${REGISTRY}/${NS}/stargate-api:latest"

  # Try user token for push (SA can't push to registry)
  if ! podman push --tls-verify=false --creds="$(oc whoami 2>/dev/null):$(oc whoami -t 2>/dev/null)" \
    "${REGISTRY}/${NS}/stargate-api:latest" 2>&1 | tail -3; then
    echo ""
    echo "Push failed — need user token. Run:"
    echo "  oc login --server=${CLUSTER}"
    echo "Then re-run this script."
    exit 1
  fi
  echo "Image pushed: ${GIT_SHA}"
fi

# --- Deploy ---
if [ "$DEPLOY" = true ]; then
  echo ""
  echo "3. Deploying..."

  if [ -f "$DEPLOYER_TOKEN" ]; then
    oc login --token="$(cat "$DEPLOYER_TOKEN")" --server="$CLUSTER" 2>&1 | tail -1
  fi
  oc project "$NS" 2>/dev/null

  oc rollout restart deployment/stargate-api -n "$NS"
  oc rollout status deployment/stargate-api -n "$NS" --timeout=180s
fi

echo ""
echo "=== Done ==="
echo "Dashboard: https://stargate.apps.ocpv-infra01.dal12.infra.demo.redhat.com"
echo "Image:     stargate-api:${GIT_SHA}"
