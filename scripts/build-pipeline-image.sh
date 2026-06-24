#!/usr/bin/env bash
# Build path-graph pipeline image (markitdown + rhwp-batch release binary).
#
# Usage:
#   ./scripts/build-pipeline-image.sh
#   PUSH=1 ./scripts/build-pipeline-image.sh
#   PLATFORM=linux/amd64 PUSH=1 ./scripts/build-pipeline-image.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REGISTRY="${REGISTRY:-ghcr.io/yoosungung/path-graph}"
TAG="${TAG:-latest}"
IMAGE="${REGISTRY}/pipeline:${TAG}"
RHWP_BATCH_VERSION="${RHWP_BATCH_VERSION:-0.7.15}"
PLATFORM="${PLATFORM:-linux/amd64}"

echo "Building $IMAGE (rhwp-batch v${RHWP_BATCH_VERSION}, platform=${PLATFORM}) ..."

build_args=(
  buildx build
  --platform "$PLATFORM"
  -f "$ROOT/pipeline/Dockerfile"
  --build-arg "RHWP_BATCH_VERSION=${RHWP_BATCH_VERSION}"
  -t "$IMAGE"
)

if [[ "${PUSH:-}" == "1" ]]; then
  if ! echo "$(gh auth token)" | docker login ghcr.io -u "$(gh api user -q .login)" --password-stdin; then
    echo "error: docker login ghcr.io failed (need gh auth refresh -s write:packages)" >&2
    exit 1
  fi
  docker "${build_args[@]}" --push "$ROOT"
  echo "Pushed $IMAGE"
else
  docker "${build_args[@]}" --load "$ROOT"
  docker run --rm --platform "$PLATFORM" --entrypoint rhwp-batch "$IMAGE" --help >/dev/null
  docker run --rm --platform "$PLATFORM" "$IMAGE" -c "import openpyxl, xlrd; from markitdown import MarkItDown; print('ok')"
  echo "Smoke OK: rhwp-batch v${RHWP_BATCH_VERSION} + markitdown[xlsx,xls]"
fi
