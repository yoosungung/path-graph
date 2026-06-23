#!/usr/bin/env bash
# Upload a tiny fixture to blob store and submit pipeline-ingest-rag (ROADMAP 2.4.2 E2E).
#
# Usage:
#   ./scripts/submit-ingest-rag-e2e.sh
#   TENANT=dev SOURCE_ID=e2e ./scripts/submit-ingest-rag-e2e.sh
#
# Prerequisites: kubectl, argo CLI, make k8s-apply-dev, make build-images (GHCR image).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TENANT="${TENANT:-dev}"
SOURCE_ID="${SOURCE_ID:-e2e}"
NS="${PATH_GRAPH_NS:-path-graph}"
PY="${ROOT}/.venv/bin/python3"

if [[ ! -x "$PY" ]]; then
  echo "error: run make install first" >&2
  exit 1
fi

for cmd in kubectl argo; do
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "error: $cmd not found" >&2
    exit 1
  }
done

kubectl -n "$NS" get secret path-graph-env >/dev/null 2>&1 || {
  echo "error: path-graph-env missing — run make k8s-apply-dev" >&2
  exit 1
}

# Load cluster pipeline env so local upload lands in the same Garage bucket as WF pods.
eval "$(
  kubectl -n "$NS" get secret path-graph-env -o json \
    | "$PY" -c 'import json,sys,base64; d=json.load(sys.stdin)["data"];
for k,v in d.items(): print(f"export {k}={base64.b64decode(v).decode()!r}")'
)"

export ROOT TENANT SOURCE_ID PIPELINE_STORAGE_BACKEND=s3

PF_PID=""
cleanup() {
  [[ -n "$PF_PID" ]] && kill "$PF_PID" 2>/dev/null || true
}
trap cleanup EXIT

if [[ "${S3_ENDPOINT_URL:-}" == *".svc"* ]]; then
  echo "Port-forwarding runtime/garage-s3 :3900 for local upload..."
  kubectl -n runtime port-forward svc/garage-s3 3900:3900 >/dev/null 2>&1 &
  PF_PID=$!
  sleep 2
  export S3_ENDPOINT_URL=http://127.0.0.1:3900
fi

BATCH_JSON="$("$PY" <<'PY'
import json
import os
import sys
import tempfile
from pathlib import Path

root = Path(os.environ["ROOT"])
sys.path.insert(0, str(root / "pipeline" / "src"))

from path_graph.collectors.remote import collect_local_file
from path_graph.steps.ingest_helpers import parse_manifest_line

tenant = os.environ["TENANT"]
source_id = os.environ["SOURCE_ID"]

with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
    f.write("path-graph e2e ingest manifest line\n")
    tmp = f.name

meta = collect_local_file(Path(tmp), tenant, source_id)
line = parse_manifest_line(meta)
print(json.dumps([line], separators=(",", ":")))
PY
)"

echo "Submitting ingest-rag for tenant=${TENANT} (1 manifest line)..."
argo submit -n "$NS" --from workflowtemplate/pipeline-ingest-rag \
  -p "tenant=${TENANT}" \
  -p "batch_manifest=${BATCH_JSON}" \
  --wait

echo "E2E workflow succeeded."
