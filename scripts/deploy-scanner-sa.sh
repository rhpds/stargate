#!/bin/bash
# ============================================================
# Deploy StarGate scanner ServiceAccount to a target cluster
# ============================================================
# Usage:
#   ./scripts/deploy-scanner-sa.sh <cluster-name> <api-url>
#   ./scripts/deploy-scanner-sa.sh ocpv05 https://api.ocpv05.example.com:6443
#   ./scripts/deploy-scanner-sa.sh ocpv-infra01 https://api.ocpv-infra01.dal12.infra.demo.redhat.com:6443 --with-executor
#
# Prerequisites:
#   - oc CLI logged into the target cluster (user with cluster-admin)
#   - Helm 3 installed
#
# What this does:
#   1. Deploys the stargate-scanner-sa Helm chart (SA + ClusterRoleBinding)
#   2. Waits for the token Secret to be populated
#   3. Extracts the token and writes a kubeconfig to secrets/
#   4. Verifies the token has cluster-reader access
# ============================================================

set -euo pipefail

CLUSTER_NAME=${1:?"Usage: $0 <cluster-name> <api-url> [--with-executor]"}
API_URL=${2:?"Usage: $0 <cluster-name> <api-url> [--with-executor]"}
WITH_EXECUTOR=false

for arg in "$@"; do
  case $arg in
    --with-executor) WITH_EXECUTOR=true ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CHART_DIR="${PROJECT_DIR}/deploy/helm/stargate-scanner-sa"
SECRETS_DIR="${PROJECT_DIR}/secrets"

echo "=== StarGate Scanner SA → ${CLUSTER_NAME} ==="
echo "API: ${API_URL}"
echo ""

# Verify oc is logged into the right cluster
CURRENT_SERVER=$(oc whoami --show-server 2>/dev/null || echo "not logged in")
if [[ "${CURRENT_SERVER}" != *"${CLUSTER_NAME}"* ]] && [[ "${CURRENT_SERVER}" != "${API_URL}" ]]; then
  echo "WARNING: Current oc context points to ${CURRENT_SERVER}"
  echo "Make sure you're logged into ${CLUSTER_NAME} before proceeding."
  read -p "Continue? [y/N] " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then exit 1; fi
fi

# Deploy Helm chart
echo "1. Deploying Helm chart..."
HELM_ARGS=""
if [ "$WITH_EXECUTOR" = true ]; then
  HELM_ARGS="--set executor.enabled=true"
  echo "   (executor SA enabled)"
fi

helm upgrade --install stargate-scanner-sa "${CHART_DIR}" \
  ${HELM_ARGS} \
  --create-namespace 2>&1 | sed 's/^/   /'

# Wait for token
echo "2. Waiting for token Secret..."
for i in $(seq 1 30); do
  TOKEN=$(oc get secret stargate-scanner-token -n stargate-scanner \
    -o jsonpath='{.data.token}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
  if [ -n "$TOKEN" ]; then break; fi
  sleep 1
done

if [ -z "$TOKEN" ]; then
  echo "ERROR: Token not populated after 30s. Check:"
  echo "  oc get sa -n stargate-scanner"
  echo "  oc get secret -n stargate-scanner"
  exit 1
fi

echo "   Token ready (${#TOKEN} chars)"

# Verify access
echo "3. Verifying cluster-reader access..."
VERIFY=$(oc --token="${TOKEN}" --server="${API_URL}" --insecure-skip-tls-verify=true \
  get nodes --no-headers 2>&1 | head -1)
if echo "$VERIFY" | grep -q "Forbidden\|Error\|error"; then
  echo "   WARNING: Token verification failed: ${VERIFY}"
else
  NODE_COUNT=$(oc --token="${TOKEN}" --server="${API_URL}" --insecure-skip-tls-verify=true \
    get nodes --no-headers 2>/dev/null | wc -l | tr -d ' ')
  echo "   OK — can see ${NODE_COUNT} nodes"
fi

# Map cluster name to kubeconfig filename
case "${CLUSTER_NAME}" in
  ocpv06)         KC_NAME="kubeconfig-cnv" ;;
  ocp-us-east-1)  KC_NAME="kubeconfig" ;;
  *)              KC_NAME="kubeconfig-${CLUSTER_NAME}" ;;
esac

# Write kubeconfig
echo "4. Writing kubeconfig to secrets/${KC_NAME}..."
mkdir -p "${SECRETS_DIR}"

# Back up existing
if [ -f "${SECRETS_DIR}/${KC_NAME}" ]; then
  cp "${SECRETS_DIR}/${KC_NAME}" "${SECRETS_DIR}/${KC_NAME}.bak"
fi

cat > "${SECRETS_DIR}/${KC_NAME}" <<EOF
apiVersion: v1
kind: Config
clusters:
- cluster:
    insecure-skip-tls-verify: true
    server: ${API_URL}
  name: ${CLUSTER_NAME}
contexts:
- context:
    cluster: ${CLUSTER_NAME}
    namespace: stargate-scanner
    user: stargate-scanner
  name: ${CLUSTER_NAME}
current-context: ${CLUSTER_NAME}
users:
- name: stargate-scanner
  user:
    token: ${TOKEN}
EOF

chmod 600 "${SECRETS_DIR}/${KC_NAME}"

# Extract executor token if enabled
if [ "$WITH_EXECUTOR" = true ]; then
  echo "5. Extracting executor token..."
  EXEC_TOKEN=""
  for i in $(seq 1 30); do
    EXEC_TOKEN=$(oc get secret stargate-executor-token -n stargate-scanner \
      -o jsonpath='{.data.token}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
    if [ -n "$EXEC_TOKEN" ]; then break; fi
    sleep 1
  done
  if [ -n "$EXEC_TOKEN" ]; then
    cat > "${SECRETS_DIR}/kubeconfig-executor" <<EOF
apiVersion: v1
kind: Config
clusters:
- cluster:
    insecure-skip-tls-verify: true
    server: ${API_URL}
  name: ${CLUSTER_NAME}-executor
contexts:
- context:
    cluster: ${CLUSTER_NAME}-executor
    namespace: stargate-test
    user: stargate-executor
  name: ${CLUSTER_NAME}-executor
current-context: ${CLUSTER_NAME}-executor
users:
- name: stargate-executor
  user:
    token: ${EXEC_TOKEN}
EOF
    chmod 600 "${SECRETS_DIR}/kubeconfig-executor"
    echo "   Executor kubeconfig: secrets/kubeconfig-executor"
  else
    echo "   WARNING: Executor token not populated"
  fi
fi

echo ""
echo "=== Done ==="
echo "Kubeconfig: secrets/${KC_NAME}"
echo "Token type: kubernetes.io/service-account-token (does not expire)"
echo ""
echo "To sync kubeconfigs to infra01:"
echo "  oc login --token=\$(cat secrets/deployer-token) --server=https://api.ocpv-infra01.dal12.infra.demo.redhat.com:6443"
echo "  oc project stargate"
echo "  oc create secret generic stargate-kubeconfigs \\"
echo "    --from-file=kubeconfig-${CLUSTER_NAME}=secrets/${KC_NAME} \\"
echo "    --dry-run=client -o yaml | oc apply -f -"
