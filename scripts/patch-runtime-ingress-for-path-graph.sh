#!/usr/bin/env bash
# Allow path-graph workflow pods → agents-runtime services (Garage, PG, Envoy).
#
# k3s on this cluster does not honour cross-namespace namespaceSelector on some
# ingress policies; pod CIDR ipBlock is required (see garage-s3-ingress).
#
# Usage: ./scripts/patch-runtime-ingress-for-path-graph.sh

set -euo pipefail

RUNTIME_NS="${RUNTIME_NS:-runtime}"
NODE_CIDR="$(kubectl get nodes -o jsonpath='{.items[0].spec.podCIDR}')"
# e.g. 10.42.0.0/24 → 10.42.0.0/16
POD_CIDR="${POD_CIDR:-${NODE_CIDR%/*}/16}"

POLICIES=(
  "garage-s3-ingress:3900"
  "postgres-ingress:5432"
  "pgbouncer-rw-ingress:5432"
  "envoy-ingress:8080"
)

python3 - "$RUNTIME_NS" "$POD_CIDR" "${POLICIES[@]}" <<'PY'
import json
import subprocess
import sys

runtime_ns, pod_cidr = sys.argv[1], sys.argv[2]
policies = [p.split(":") for p in sys.argv[3:]]

rule = {
    "from": [{"ipBlock": {"cidr": pod_cidr}}],
    "ports": [],
}

for name, port in policies:
    raw = subprocess.check_output(
        ["kubectl", "-n", runtime_ns, "get", "networkpolicy", name, "-o", "json"],
        text=True,
    )
    np = json.loads(raw)
    rule["ports"] = [{"port": int(port), "protocol": "TCP"}]
    ingress = np["spec"].setdefault("ingress", [])
    if rule not in ingress:
        ingress.append(rule)
        subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=json.dumps(np),
            text=True,
            check=True,
        )
        print(f"Patched {runtime_ns}/{name} (+ {pod_cidr}:{port})")
    else:
        print(f"Skip {runtime_ns}/{name} (rule present)")
PY
