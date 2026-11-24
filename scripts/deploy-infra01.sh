#!/bin/bash
# Deploy StarGate platform to ocpv-infra01
# Usage: ./scripts/deploy-infra01.sh [--build] [--dry-run] [--verify-kubeconfigs]
#
# Prerequisites:
#   - oc logged into ocpv-infra01
#   - secrets/kubeconfig-<cluster> for every cluster in scanner.clusters, or
#     that key already present in secret/stargate-kubeconfigs
#   - secrets/kubeconfig-executor (the chart hard-codes that path)
#   - LiteLLM API key
#
# Environment:
#   STARGATE_SECRETS_DIR   where the kubeconfig files live (default ./secrets)
#   STARGATE_VALUES_FILE   values file whose scanner.clusters is authoritative
#                          (default deploy/helm/stargate/values-infra01.yaml)

set -euo pipefail

NAMESPACE="stargate"
REGISTRY="image-registry.openshift-image-registry.svc:5000/${NAMESPACE}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SECRETS_DIR="${STARGATE_SECRETS_DIR:-${PROJECT_DIR}/secrets}"
VALUES_FILE="${STARGATE_VALUES_FILE:-${PROJECT_DIR}/deploy/helm/stargate/values-infra01.yaml}"
KUBECONFIG_SECRET="stargate-kubeconfigs"

BUILD=false
DRY_RUN=false
VERIFY_KUBECONFIGS=false
for arg in "$@"; do
  case $arg in
    --build) BUILD=true ;;
    --dry-run) DRY_RUN=true ;;
    --verify-kubeconfigs) VERIFY_KUBECONFIGS=true ;;
    *)
      echo "ERROR: unknown argument: $arg"
      echo "Usage: $0 [--build] [--dry-run] [--verify-kubeconfigs]"
      exit 2
      ;;
  esac
done

# The fleet is whatever the chart tells the scheduler to scan. It used to be
# repeated here as a hard-coded --from-file list, which is how ocpv03 came to
# be scanned with no credential behind it: the list drifted from
# values-infra01.yaml, the secret was deleted and recreated on every run, and
# nothing failed. Read the value the scheduler actually gets.
if [ ! -f "$VALUES_FILE" ]; then
  echo "ERROR: values file not found: $VALUES_FILE"
  exit 1
fi
FLEET="$(sed -n 's/^[[:space:]]*clusters:[[:space:]]*//p' "$VALUES_FILE" \
  | sed 's/#.*//' | tr -d "\"'" | tr -d '[:space:]' | tr ',' ' ')"

if [ -z "$FLEET" ]; then
  echo "ERROR: no scanner.clusters value in $VALUES_FILE"
  exit 1
fi

LIVE_SECRET_EXISTS=false
LIVE_KEYS=""

read_live_secret() {
  if oc get secret "$KUBECONFIG_SECRET" -n "$NAMESPACE" &>/dev/null; then
    LIVE_SECRET_EXISTS=true
    LIVE_KEYS=$(oc get secret "$KUBECONFIG_SECRET" -n "$NAMESPACE" \
      -o go-template='{{range $k, $v := .data}}{{$k}}{{"\n"}}{{end}}')
  else
    LIVE_SECRET_EXISTS=false
    LIVE_KEYS=""
  fi
}

# A credential exists if there is a local file to push, or the key is already
# in the secret. The second case is why this is not a plain local-file check:
# a laptop that holds three of five kubeconfigs can still deploy safely,
# because `oc apply` leaves the keys it does not mention alone. Only "neither
# locally nor in the secret" is fatal, and that is exactly ocpv03.
fleet_coverage() {
  local cluster covered=0 total=0 missing="" kept="" key
  for cluster in $FLEET; do
    total=$((total + 1))
    if [ -f "$SECRETS_DIR/kubeconfig-$cluster" ]; then
      covered=$((covered + 1))
    elif printf '%s\n' "$LIVE_KEYS" | grep -qx "kubeconfig-$cluster"; then
      covered=$((covered + 1))
      kept="$kept $cluster"
    else
      missing="$missing $cluster"
    fi
  done

  if [ -n "$kept" ]; then
    echo "   from the existing secret, no local copy to refresh:$kept"
  fi
  if [ -n "$missing" ]; then
    echo "ERROR: $VALUES_FILE asks the scheduler to scan these clusters:"
    echo "         $FLEET"
    echo "       but there is no credential for:"
    for key in $missing; do
      echo "         kubeconfig-$key"
      echo "           neither $SECRETS_DIR/kubeconfig-$key"
      if [ "$LIVE_SECRET_EXISTS" = true ]; then
        echo "           nor key kubeconfig-$key in secret/$KUBECONFIG_SECRET"
      else
        echo "           nor any key in secret/$KUBECONFIG_SECRET (secret does not exist)"
      fi
    done
    echo "       Deploying anyway would leave those clusters in scanner.clusters"
    echo "       with nothing behind them: the scanner skips them without failing"
    echo "       and their namespaces quietly leave the sweep."
    return 1
  fi

  # templates/api.yaml mounts this exact filename, so it is required whether
  # or not it also names a cluster in scanner.clusters.
  if [ ! -f "$SECRETS_DIR/kubeconfig-executor" ] \
    && ! printf '%s\n' "$LIVE_KEYS" | grep -qx "kubeconfig-executor"; then
    echo "ERROR: no kubeconfig-executor in $SECRETS_DIR or secret/$KUBECONFIG_SECRET"
    echo "       templates/api.yaml mounts it at STARGATE_EXECUTOR_KUBECONFIG."
    return 1
  fi

  echo "   $covered/$total fleet cluster(s) covered, kubeconfig-executor present"
  return 0
}

# Verify mode's per-cluster view: which side of the secret each cluster's
# credential is on, because "covered" hides whether a key is being refreshed
# or merely inherited from a previous deploy.
report_matrix() {
  local cluster key local_present live_present state
  for cluster in $FLEET; do
    key="kubeconfig-$cluster"
    if [ -f "$SECRETS_DIR/$key" ]; then local_present=true; else local_present=false; fi
    if printf '%s\n' "$LIVE_KEYS" | grep -qx "$key"; then
      live_present=true
    else
      live_present=false
    fi
    case "$local_present/$live_present" in
      true/true) state="local + secret" ;;
      true/false) state="local only (will be applied)" ;;
      false/true) state="secret only (no local copy to refresh)" ;;
      *) state="MISSING" ;;
    esac
    printf '   %-8s %s\n' "$cluster" "$state"
  done
}

# Merge rather than replace. `oc delete secret` + `oc create` dropped every key
# that was not in the hard-coded list, so a run of this script could subtract
# clusters from production and leave the scheduler scanning namespaces it had
# no token for.
apply_kubeconfig_secret() {
  local from_files="" f
  for f in "$SECRETS_DIR"/kubeconfig-*; do
    [ -f "$f" ] || continue
    from_files="$from_files --from-file=$(basename "$f")=\"$f\""
  done
  if [ -z "$from_files" ]; then
    echo "ERROR: no kubeconfig-* files in $SECRETS_DIR"
    return 1
  fi
  eval "oc create secret generic $KUBECONFIG_SECRET -n $NAMESPACE $from_files \
    --dry-run=client -o yaml" | oc apply -f -
}

if [ "$VERIFY_KUBECONFIGS" = true ]; then
  # Read-only: never writes. Reports what is local, what is live, and which
  # clusters have neither, so one run answers the whole question.
  echo "=== StarGate kubeconfig check (read-only) ==="
  if ! oc whoami &>/dev/null; then
    echo "ERROR: not logged in; --verify-kubeconfigs reads secret/$KUBECONFIG_SECRET"
    exit 1
  fi
  read_live_secret
  rc=0
  fleet_coverage || rc=1
  report_matrix
  if [ "$LIVE_SECRET_EXISTS" = true ]; then
    echo "   secret/$KUBECONFIG_SECRET keys:"
    printf '%s\n' "$LIVE_KEYS" | sed 's/^/         /'
  else
    echo "   secret/$KUBECONFIG_SECRET does not exist in namespace $NAMESPACE"
  fi
  exit $rc
fi

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
IDENTITY=$(oc whoami 2>/dev/null || true)
if [ -z "$IDENTITY" ]; then
  # `oc whoami --show-server` answers from the kubeconfig even when the token
  # is expired, so the server URL alone is not a connection.
  echo "ERROR: reached $CLUSTER but the token is not accepted (oc whoami is empty)."
  echo "  oc login --server=$CLUSTER"
  exit 1
fi
echo "   Connected to: $CLUSTER as $IDENTITY"

# Create namespace
echo "2. Creating namespace..."
oc new-project "$NAMESPACE" 2>/dev/null || oc project "$NAMESPACE"

# Check coverage, then merge kubeconfigs into the existing secret. Coverage is
# decided before the write: a secret is not recreated here, but a cluster
# named in scanner.clusters with no credential is still a silent gap.
echo "3. Applying kubeconfigs secret..."
read_live_secret
fleet_coverage

if [ "$DRY_RUN" = true ]; then
  echo "   DRY RUN: not writing secret/$KUBECONFIG_SECRET; keys that would be applied:"
  for f in "$SECRETS_DIR"/kubeconfig-*; do
    [ -f "$f" ] || continue
    echo "     $(basename "$f")"
  done
else
  apply_kubeconfig_secret
fi

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
