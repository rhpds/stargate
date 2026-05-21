#!/bin/bash
# Create a long-lived kubeconfig for a StarGate scanner SA on a target cluster.
#
# Usage: ./scripts/refresh-kubeconfigs.sh <cluster-name> <api-url> <user-token>
# Example: ./scripts/refresh-kubeconfigs.sh ocpv05 https://api.cluster.example.com:6443 sha256~abc123
#
# This will:
#   1. Log into the cluster with the provided user token
#   2. Create stargate-scanner SA with cluster-reader role
#   3. Generate a 1-year SA token
#   4. Write a kubeconfig file to secrets/
#   5. Optionally update the stargate-kubeconfigs secret on infra01

set -euo pipefail

CLUSTER_NAME=${1:?Usage: $0 <cluster-name> <api-url> <user-token>}
API_URL=${2:?Usage: $0 <cluster-name> <api-url> <user-token>}
USER_TOKEN=${3:?Usage: $0 <cluster-name> <api-url> <user-token>}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SECRETS_DIR="${PROJECT_DIR}/secrets"
KC_FILE="/tmp/kc-${CLUSTER_NAME}"

echo "=== Creating scanner SA on ${CLUSTER_NAME} ==="

# Login to target cluster
echo "1. Logging into ${CLUSTER_NAME}..."
KUBECONFIG=${KC_FILE} oc login --token="${USER_TOKEN}" --server="${API_URL}" --insecure-skip-tls-verify=true

# Create namespace if needed
echo "2. Setting up namespace..."
KUBECONFIG=${KC_FILE} oc new-project stargate 2>/dev/null || \
  KUBECONFIG=${KC_FILE} oc project stargate 2>/dev/null || true

# Create SA
echo "3. Creating stargate-scanner SA..."
KUBECONFIG=${KC_FILE} oc create sa stargate-scanner -n stargate 2>/dev/null || \
  echo "   SA already exists"

# Grant cluster-reader
echo "4. Granting cluster-reader role..."
KUBECONFIG=${KC_FILE} oc adm policy add-cluster-role-to-user cluster-reader \
  -z stargate-scanner -n stargate 2>&1 | tail -1

# Generate 1-year token
echo "5. Generating 1-year token..."
SA_TOKEN=$(KUBECONFIG=${KC_FILE} oc create token stargate-scanner -n stargate --duration=8760h)

# Verify token works
echo "6. Verifying token..."
VERIFY=$(KUBECONFIG=/dev/null oc login --token="${SA_TOKEN}" --server="${API_URL}" \
  --insecure-skip-tls-verify=true 2>&1 | tail -1)
echo "   ${VERIFY}"

# Map cluster name to kubeconfig filename
case "${CLUSTER_NAME}" in
  ocpv06)       KC_NAME="kubeconfig-cnv" ;;
  ocp-us-east-1) KC_NAME="kubeconfig" ;;
  *)            KC_NAME="kubeconfig-${CLUSTER_NAME}" ;;
esac

# Write kubeconfig
echo "7. Writing kubeconfig to secrets/${KC_NAME}..."
mkdir -p "${SECRETS_DIR}"
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
    namespace: stargate
    user: stargate-scanner
  name: ${CLUSTER_NAME}
current-context: ${CLUSTER_NAME}
users:
- name: stargate-scanner
  user:
    token: ${SA_TOKEN}
EOF

echo ""
echo "=== Done ==="
echo "Kubeconfig: secrets/${KC_NAME}"
echo "Token valid until: $(date -v+1y '+%Y-%m-%d' 2>/dev/null || date -d '+1 year' '+%Y-%m-%d' 2>/dev/null || echo '1 year from now')"
echo ""
echo "To update the cluster secret on infra01, run:"
echo "  oc login --token=\$(cat secrets/deployer-token) --server=https://api.cluster.example.com:6443"
echo "  oc project stargate"
echo "  oc create secret generic stargate-kubeconfigs --from-file=secrets/ --dry-run=client -o yaml | oc apply -f -"

# Cleanup
rm -f "${KC_FILE}"
