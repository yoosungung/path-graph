#!/usr/bin/env bash
# Install or upgrade Argo Workflows controller (ROADMAP 1.4.7).
#
# Usage:
#   ./scripts/install-argo.sh
#   ARGO_NS=argo ARGO_RELEASE=argo-workflows ./scripts/install-argo.sh
#
# Prerequisites: helm 3, kubectl, cluster admin

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARGO_NS="${ARGO_NS:-argo}"
ARGO_RELEASE="${ARGO_RELEASE:-argo-workflows}"
VALUES_FILE="${ARGO_VALUES_FILE:-$ROOT/deploy/k8s/argo/values.yaml}"

require() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "error: $1 not found" >&2
    exit 1
  }
}

require helm
require kubectl

if [[ ! -f "$VALUES_FILE" ]]; then
  echo "error: values file not found: $VALUES_FILE" >&2
  exit 1
fi

helm repo add argo https://argoproj.github.io/argo-helm 2>/dev/null || true
helm repo update argo

helm upgrade --install "$ARGO_RELEASE" argo/argo-workflows \
  --namespace "$ARGO_NS" \
  --create-namespace \
  -f "$VALUES_FILE" \
  --wait \
  --timeout 5m

echo "Argo Workflows installed in namespace ${ARGO_NS}."
kubectl -n "$ARGO_NS" rollout status deploy/"${ARGO_RELEASE}-workflow-controller" --timeout=120s
if kubectl -n "$ARGO_NS" get deploy "${ARGO_RELEASE}-server" >/dev/null 2>&1; then
  kubectl -n "$ARGO_NS" rollout status deploy/"${ARGO_RELEASE}-server" --timeout=120s
fi

if kubectl get crd workflows.argoproj.io >/dev/null 2>&1; then
  echo "CRD workflows.argoproj.io: OK"
else
  echo "error: workflows.argoproj.io CRD missing after install" >&2
  exit 1
fi
