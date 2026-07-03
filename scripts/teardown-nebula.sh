#!/usr/bin/env bash
# Remove NebulaGraph Helm releases (path-graph owned infra).
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]$(date +'%Y-%m-%d %H:%M:%S') $1${NC}"; }
log_warn() { echo -e "${YELLOW}[WARN]$(date +'%Y-%m-%d %H:%M:%S') $1${NC}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
INFRA_DIR="${ROOT_DIR}/deploy/k8s/infra"

if [[ "${1:-}" != "--force" ]]; then
  read -p "Teardown NebulaGraph on [$(kubectl config current-context)]? (y/N): " confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    log_warn "Teardown cancelled."
    exit 0
  fi
fi

if command -v helm &>/dev/null; then
  log_info "Uninstalling NebulaGraph cluster..."
  helm uninstall nebula --namespace nebula 2>/dev/null || true
  log_info "Uninstalling NebulaGraph Operator..."
  helm uninstall nebula-operator --namespace nebula-operator-system 2>/dev/null || true
else
  log_warn "helm not found; skipping Helm uninstall"
fi

log_info "Removing Studio + Ingress manifests..."
kubectl delete -f "${INFRA_DIR}/manifests/ingress-routes.yaml" --ignore-not-found
kubectl delete -f "${INFRA_DIR}/manifests/nebula-studio.yaml" --ignore-not-found

log_info "Teardown completed. Namespaces and PVCs are retained (delete manually to wipe data)."
