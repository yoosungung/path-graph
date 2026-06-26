#!/usr/bin/env bash
# Wrapper — canonical script lives in deploy/k8s/base/ for kustomize ConfigMap.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${ROOT}/deploy/k8s/base/render-filestash-config.sh" "$@"
