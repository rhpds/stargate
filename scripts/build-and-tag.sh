#!/bin/bash
# Build and tag StarGate images with git SHA for reproducible deployments.
#
# Usage:
#   ./scripts/build-and-tag.sh [--push]
#
# Tags images as:
#   quay.io/rhpds/stargate-api:<git-sha>
#   quay.io/rhpds/stargate-api:latest
#
# With --push, pushes to the registry (requires podman login).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
REGISTRY="${STARGATE_IMAGE_REGISTRY:-quay.io/rhpds}"
GIT_SHA=$(git -C "$PROJECT_DIR" rev-parse --short HEAD)
PUSH=false

for arg in "$@"; do
  case $arg in
    --push) PUSH=true ;;
  esac
done

echo "=== StarGate Build ==="
echo "Registry: ${REGISTRY}"
echo "Git SHA:  ${GIT_SHA}"
echo ""

# Build API image (includes frontend)
echo "Building stargate-api:${GIT_SHA}..."
podman build --platform linux/amd64 \
  -t "${REGISTRY}/stargate-api:${GIT_SHA}" \
  -t "${REGISTRY}/stargate-api:latest" \
  -f "${PROJECT_DIR}/Containerfile" \
  "${PROJECT_DIR}"

echo ""
echo "Tagged:"
echo "  ${REGISTRY}/stargate-api:${GIT_SHA}"
echo "  ${REGISTRY}/stargate-api:latest"

if [ "$PUSH" = true ]; then
  echo ""
  echo "Pushing..."
  podman push "${REGISTRY}/stargate-api:${GIT_SHA}"
  podman push "${REGISTRY}/stargate-api:latest"
  echo "Pushed to ${REGISTRY}"
fi

echo ""
echo "=== Done ==="
echo "To deploy with this image:"
echo "  helm upgrade --install stargate deploy/helm/stargate \\"
echo "    --set api.image=${REGISTRY}/stargate-api:${GIT_SHA}"
echo ""
echo "Or set in AgnosticV:"
echo "  stargate_image_tag: ${GIT_SHA}"
