#!/usr/bin/env bash
# Post-deploy checks for NebulaGraph cluster (graphd readiness).
set -euo pipefail

NEBULA_NAMESPACE="${NEBULA_NAMESPACE:-nebula}"
NEBULA_CLUSTER_RELEASE="${NEBULA_CLUSTER_RELEASE:-nebula}"
GRAPH_SVC="${NEBULA_GRAPH_SVC:-nebula-graphd-svc}"
GRAPH_PORT="${NEBULA_GRAPH_PORT:-9669}"
NEBULA_USER="${NEBULA_USER:-root}"
NEBULA_PASSWORD="${NEBULA_PASSWORD:-nebula}"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

ok() { echo -e "${GREEN}[OK]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

echo "Context: $(kubectl config current-context)"
echo "Waiting for NebulaGraph cluster to become ready..."
kubectl wait --for=condition=Ready "nebulacluster/${NEBULA_CLUSTER_RELEASE}" \
  -n "${NEBULA_NAMESPACE}" --timeout=300s
ok "NebulaCluster ${NEBULA_CLUSTER_RELEASE} is Ready"

kubectl run nebula-console-test --restart=Never \
  --image=vesoft/nebula-console:v3.8.0 -n "${NEBULA_NAMESPACE}" -- \
  nebula-console \
    -addr "${GRAPH_SVC}.${NEBULA_NAMESPACE}.svc.cluster.local" \
    -port "${GRAPH_PORT}" \
    -u "${NEBULA_USER}" \
    -p "${NEBULA_PASSWORD}" \
    -e 'SHOW HOSTS;'
kubectl wait --for=condition=Ready "pod/nebula-console-test" -n "${NEBULA_NAMESPACE}" --timeout=120s
kubectl logs nebula-console-test -n "${NEBULA_NAMESPACE}" | grep -q 'Host' \
  || fail "SHOW HOSTS did not return expected output"
kubectl delete pod nebula-console-test -n "${NEBULA_NAMESPACE}" --ignore-not-found
ok "graphd accepts nGQL (SHOW HOSTS)"

ok "NebulaGraph verification passed"
