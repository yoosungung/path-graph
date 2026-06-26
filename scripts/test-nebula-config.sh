#!/usr/bin/env bash
# Pre-deploy validation for NebulaGraph Operator + cluster Helm values (TDD gate).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
INFRA_DIR="${ROOT_DIR}/deploy/k8s/infra"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

ok() { echo -e "${GREEN}[OK]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

if ! command -v helm &>/dev/null; then
  fail "helm is required for NebulaGraph config tests"
fi

OPERATOR_NS="${INFRA_DIR}/manifests/nebula-operator-namespace.yaml"
NEBULA_NS="${INFRA_DIR}/manifests/nebula-namespace.yaml"
OPERATOR_VALUES="${INFRA_DIR}/helm/values/nebula-operator.yaml"
CLUSTER_VALUES="${INFRA_DIR}/helm/values/nebula-cluster.yaml"

for f in "${OPERATOR_NS}" "${NEBULA_NS}" "${OPERATOR_VALUES}" "${CLUSTER_VALUES}"; do
  [[ -f "${f}" ]] || fail "Missing ${f}"
done

kubectl apply --dry-run=client -f "${OPERATOR_NS}" -f "${NEBULA_NS}" >/dev/null
ok "Namespace manifests pass kubectl dry-run"

helm repo add nebula-operator https://vesoft-inc.github.io/nebula-operator/charts 2>/dev/null || true
helm repo update nebula-operator >/dev/null

OPERATOR_RENDERED="$(helm template nebula-operator nebula-operator/nebula-operator \
  -f "${OPERATOR_VALUES}" --version 1.8.0)"
[[ -n "${OPERATOR_RENDERED}" ]] || fail "nebula-operator helm template produced empty output"
ok "NebulaGraph Operator Helm template renders"

CLUSTER_RENDERED="$(helm template nebula nebula-operator/nebula-cluster \
  -f "${CLUSTER_VALUES}" --version 1.8.0 \
  --set nebula.storageClassName=local-path)"
[[ -n "${CLUSTER_RENDERED}" ]] || fail "nebula-cluster helm template produced empty output"
echo "${CLUSTER_RENDERED}" | grep -q 'kind: NebulaCluster' || fail "Expected NebulaCluster CR in rendered chart"
grep -q 'version: v3.8.0' "${CLUSTER_VALUES}" || fail "Expected NebulaGraph v3.8.0 in cluster values"
ok "NebulaGraph cluster Helm template renders NebulaCluster v3.8.0"

ok "NebulaGraph config validation passed"
