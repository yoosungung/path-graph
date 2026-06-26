#!/usr/bin/env bash
# Pin dev overlay kustomization to a specific pipeline image tag (not :latest).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAG="${1:-$("$ROOT/scripts/resolve-image-tag.sh")}"
FILE="$ROOT/deploy/k8s/overlays/dev/kustomization.yaml"
TAG_FILE="$ROOT/deploy/k8s/pipeline-image-tag"

if [[ ! "$TAG" =~ ^[a-f0-9]{40}$ ]]; then
  echo "error: IMAGE_TAG must be a full git SHA (40 hex chars), got: $TAG" >&2
  exit 1
fi

perl -pi -e "s/^    newTag: .*/    newTag: $TAG/" "$FILE"
printf '%s\n' "$TAG" >"$TAG_FILE"
echo "Pinned dev overlay: ghcr.io/yoosungung/path-graph/pipeline:$TAG"
