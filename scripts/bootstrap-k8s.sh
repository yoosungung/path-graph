#!/usr/bin/env bash
# Sprint 1 bootstrap: Argo + secrets + dev overlay apply (ROADMAP 1.4.7–1.4.8).
#
# Usage:
#   ./scripts/bootstrap-k8s.sh
#   ./scripts/bootstrap-k8s.sh --skip-argo
#
# Images: GitHub Actions only — push 후 `make build-images`

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKIP_ARGO=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-argo) SKIP_ARGO=true; shift ;;
    -h|--help)
      sed -n '2,10p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

cd "$ROOT"

if [[ "$SKIP_ARGO" == false ]]; then
  if kubectl get crd workflows.argoproj.io >/dev/null 2>&1; then
    echo "Argo CRD already present — skip install"
  else
    "$ROOT/scripts/install-argo.sh"
  fi
fi

make k8s-apply-dev
make workflow-validate

echo ""
echo "Bootstrap complete."
echo "  Images: git push && make build-images  (GHCR — no local docker)"
echo "  WorkflowTemplates: kubectl get workflowtemplates -n path-graph"
