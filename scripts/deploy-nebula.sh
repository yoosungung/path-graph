#!/usr/bin/env bash
# Deploy NebulaGraph to k8s-test cluster (path-graph owned infra).
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]$(date +'%Y-%m-%d %H:%M:%S') $1${NC}"; }
log_warn() { echo -e "${YELLOW}[WARN]$(date +'%Y-%m-%d %H:%M:%S') $1${NC}"; }
log_error() { echo -e "${RED}[ERROR]$(date +'%Y-%m-%d %H:%M:%S') $1${NC}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
INFRA_DIR="${ROOT_DIR}/deploy/k8s/infra"

NEBULA_OPERATOR_NAMESPACE="nebula-operator-system"
NEBULA_OPERATOR_RELEASE="nebula-operator"
NEBULA_CLUSTER_NAMESPACE="nebula"
NEBULA_CLUSTER_RELEASE="nebula"
NEBULA_OPERATOR_CHART_VERSION="${NEBULA_OPERATOR_CHART_VERSION:-1.8.0}"
NEBULA_CLUSTER_CHART_VERSION="${NEBULA_CLUSTER_CHART_VERSION:-1.8.0}"
NEBULA_STORAGE_CLASS="${NEBULA_STORAGE_CLASS:-local-path}"

K8S_TEST_DOMAIN_SUFFIX="${K8S_TEST_DOMAIN_SUFFIX:-k8s-test}"

deploy_nebula() {
  log_info "Ensuring NebulaGraph Operator Helm repo is registered..."
  helm repo add nebula-operator https://vesoft-inc.github.io/nebula-operator/charts 2>/dev/null || true
  helm repo update nebula-operator

  log_info "Installing/upgrading NebulaGraph Operator (chart ${NEBULA_OPERATOR_CHART_VERSION})..."
  helm upgrade --install "${NEBULA_OPERATOR_RELEASE}" nebula-operator/nebula-operator \
    --namespace "${NEBULA_OPERATOR_NAMESPACE}" \
    --create-namespace \
    --version "${NEBULA_OPERATOR_CHART_VERSION}" \
    -f "${INFRA_DIR}/helm/values/nebula-operator.yaml" \
    --wait \
    --timeout 10m

  log_info "Waiting for NebulaGraph CRDs..."
  kubectl wait --for=condition=Established crd/nebulaclusters.apps.nebula-graph.io --timeout=120s

  log_info "Installing/upgrading NebulaGraph cluster (chart ${NEBULA_CLUSTER_CHART_VERSION}, v3.8.0)..."
  helm upgrade --install "${NEBULA_CLUSTER_RELEASE}" nebula-operator/nebula-cluster \
    --namespace "${NEBULA_CLUSTER_NAMESPACE}" \
    --create-namespace \
    --version "${NEBULA_CLUSTER_CHART_VERSION}" \
    -f "${INFRA_DIR}/helm/values/nebula-cluster.yaml" \
    --set "nebula.storageClassName=${NEBULA_STORAGE_CLASS}" \
    --wait \
    --timeout 15m

  log_info "Waiting for NebulaGraph cluster to become ready..."
  kubectl wait --for=condition=Ready "nebulacluster/${NEBULA_CLUSTER_RELEASE}" \
    -n "${NEBULA_CLUSTER_NAMESPACE}" --timeout=300s

  log_info "NebulaGraph graphd: nebula-graphd-svc.${NEBULA_CLUSTER_NAMESPACE}.svc.cluster.local:9669"
  log_info "NebulaGraph Studio: http://nebula-studio.${K8S_TEST_DOMAIN_SUFFIX}:7001/"
}

apply_manifests() {
  log_info "Applying namespaces..."
  kubectl apply -f "${INFRA_DIR}/manifests/nebula-operator-namespace.yaml"
  kubectl apply -f "${INFRA_DIR}/manifests/nebula-namespace.yaml"

  log_info "Applying NebulaGraph Studio..."
  kubectl apply -f "${INFRA_DIR}/manifests/nebula-studio.yaml"

  log_info "Applying Ingress routes (nebula-studio)..."
  kubectl apply -f "${INFRA_DIR}/manifests/ingress-routes.yaml"
}

log_info "Verifying prerequisites..."
if ! command -v kubectl &>/dev/null; then
  log_error "kubectl is not installed. Exiting."
  exit 1
fi
if ! command -v helm &>/dev/null; then
  log_error "helm is not installed. Exiting."
  exit 1
fi

CURRENT_CONTEXT="$(kubectl config current-context)"
log_info "Current Kubernetes Context: ${CURRENT_CONTEXT}"

if [[ "${1:-}" != "--force" ]]; then
  read -p "Deploy NebulaGraph to [${CURRENT_CONTEXT}]? (y/N): " confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    log_warn "Deployment cancelled by user."
    exit 0
  fi
fi

log_info "Running pre-deploy config tests..."
"${ROOT_DIR}/scripts/test-nebula-config.sh"
"${ROOT_DIR}/scripts/test-nebula-studio-config.sh"

apply_manifests
deploy_nebula

log_info "Deployment completed."
log_info "Verify: make verify-nebula"
log_info "Local debug: ./scripts/wire-dev.sh up"
