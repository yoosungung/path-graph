#!/usr/bin/env bash
# Upload chunks fixture and submit pipeline-graph / pipeline-wiki / pipeline-graphrag E2E.
#
# Usage:
#   ./scripts/submit-downstream-e2e.sh
#   TEMPLATE=pipeline-graph ./scripts/submit-downstream-e2e.sh
#
# Prerequisites: kubectl, make k8s-apply-dev, make build-images (GHCR image).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TENANT="${TENANT:-dev}"
BATCH_ID="${BATCH_ID:-e2e-$(date +%s)}"
SKIP_AGENT="${SKIP_AGENT:-1}"
TEMPLATE="${TEMPLATE:-all}"
NS="${PATH_GRAPH_NS:-path-graph}"
PY="${ROOT}/.venv/bin/python3"
TIMEOUT="${E2E_TIMEOUT:-20m}"

if [[ ! -x "$PY" ]]; then
  echo "error: run make install first" >&2
  exit 1
fi

command -v kubectl >/dev/null 2>&1 || {
  echo "error: kubectl not found" >&2
  exit 1
}

kubectl -n "$NS" get secret path-graph-env >/dev/null 2>&1 || {
  echo "error: path-graph-env missing — run make k8s-apply-dev" >&2
  exit 1
}

eval "$(
  kubectl -n "$NS" get secret path-graph-env -o json \
    | "$PY" -c 'import json,sys,base64; d=json.load(sys.stdin)["data"];
for k,v in d.items(): print(f"export {k}={base64.b64decode(v).decode()!r}")'
)"

export ROOT TENANT BATCH_ID PIPELINE_STORAGE_BACKEND=s3

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

PROJECT_ID="${PROJECT_ID:-550e8400-e29b-41d4-a716-446655440000}"
PROJECT_SLUG="${PROJECT_SLUG:-default}"

read -r CHUNKS_KEY DOC_ID <<<"$("$PY" <<'PY'
import hashlib
import json
import os
import sys
from pathlib import Path

root = Path(os.environ["ROOT"])
sys.path.insert(0, str(root / "pipeline" / "src"))

from path_graph.contracts.schemas import ChunkRecord
from path_graph.ids import chunk_id as make_chunk_id, document_id as make_document_id
from path_graph.storage.blob import make_blob_store, write_jsonl
from path_graph.config import get_settings

get_settings.cache_clear()
tenant = os.environ["TENANT"]
content_hash = hashlib.sha256(b"path-graph downstream e2e fixture").hexdigest()
doc_id = make_document_id(tenant, content_hash)
text = "path-graph e2e [[Alpha]] links to [[Beta]]."
text_hash = hashlib.sha256(text.encode()).hexdigest()
chunk_id_value = make_chunk_id(tenant, doc_id, 0, text_hash)
record = ChunkRecord(
    chunk_id=chunk_id_value,
    document_id=doc_id,
    tenant=tenant,
    chunk_index=0,
    text=text,
    text_hash=text_hash,
    heading_path=["E2E"],
)
chunks_key = f"chunks/{tenant}/{doc_id}/chunks.jsonl"
store = make_blob_store(get_settings())
write_jsonl(chunks_key, [record.model_dump()], store)
print(chunks_key, doc_id)
PY
)"

submit_wf() {
  local template="$1"
  local batch_id="$2"
  local wf_name
  wf_name="$(kubectl create -f - -o jsonpath='{.metadata.name}' <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  generateName: ${template}-e2e-
  namespace: ${NS}
spec:
  workflowTemplateRef:
    name: ${template}
  arguments:
    parameters:
      - name: tenant
        value: ${TENANT}
      - name: batch_id
        value: ${batch_id}
      - name: chunks_key
        value: ${CHUNKS_KEY}
      - name: skip_agent
        value: "${SKIP_AGENT}"
EOF
)"
  echo "Submitted ${template} workflow ${wf_name} (batch_id=${batch_id})..."
  kubectl -n "$NS" wait "workflow/${wf_name}" --for=condition=Completed --timeout="${TIMEOUT}"
  local phase
  phase="$(kubectl -n "$NS" get "workflow/${wf_name}" -o jsonpath='{.status.phase}')"
  if [[ "$phase" != "Succeeded" ]]; then
    echo "workflow ${wf_name} failed: phase=${phase}" >&2
    kubectl -n "$NS" get "workflow/${wf_name}" -o yaml | tail -50 >&2
    exit 1
  fi
  echo "${template} succeeded (${wf_name})."
}

submit_graphrag_wf() {
  local batch_id="$1"
  local wf_name
  wf_name="$(kubectl create -f - -o jsonpath='{.metadata.name}' <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  generateName: pipeline-graphrag-e2e-
  namespace: ${NS}
spec:
  workflowTemplateRef:
    name: pipeline-graphrag
  arguments:
    parameters:
      - name: tenant
        value: ${TENANT}
      - name: project_id
        value: ${PROJECT_ID}
      - name: project_slug
        value: ${PROJECT_SLUG}
      - name: batch_id
        value: ${batch_id}
      - name: chunks_key
        value: ${CHUNKS_KEY}
      - name: skip_agent
        value: "${SKIP_AGENT}"
EOF
)"
  echo "Submitted pipeline-graphrag workflow ${wf_name} (batch_id=${batch_id})..."
  kubectl -n "$NS" wait "workflow/${wf_name}" --for=condition=Completed --timeout="${TIMEOUT}"
  local phase
  phase="$(kubectl -n "$NS" get "workflow/${wf_name}" -o jsonpath='{.status.phase}')"
  if [[ "$phase" != "Succeeded" ]]; then
    echo "workflow ${wf_name} failed: phase=${phase}" >&2
    kubectl -n "$NS" get "workflow/${wf_name}" -o yaml | tail -50 >&2
    exit 1
  fi
  echo "pipeline-graphrag succeeded (${wf_name})."
}

echo "Fixture: chunks_key=${CHUNKS_KEY} doc_id=${DOC_ID} project_id=${PROJECT_ID}"

case "$TEMPLATE" in
  pipeline-graph)
    submit_wf pipeline-graph "$BATCH_ID"
    ;;
  pipeline-wiki)
    submit_wf pipeline-wiki "$BATCH_ID"
    ;;
  pipeline-graphrag)
    submit_graphrag_wf "$BATCH_ID"
    ;;
  all)
    GRAPH_BATCH="${BATCH_ID}-graph"
    WIKI_BATCH="${BATCH_ID}-wiki"
    GRAPHRAG_BATCH="${BATCH_ID}-graphrag"
    submit_wf pipeline-graph "$GRAPH_BATCH"
    submit_wf pipeline-wiki "$WIKI_BATCH"
    submit_graphrag_wf "$GRAPHRAG_BATCH"
    ;;
  *)
    echo "error: unknown TEMPLATE=${TEMPLATE}" >&2
    exit 1
    ;;
esac

echo "Downstream E2E succeeded."
