#!/usr/bin/env bash
# Create path-graph namespace secrets from existing dev cluster infra (ROADMAP 1.4.5).
#
# Usage:
#   ./scripts/create-path-graph-secrets.sh
#   PIPELINE_AGENT_ACCESS_TOKEN=... ./scripts/create-path-graph-secrets.sh
#   (unset) ./scripts/create-path-graph-secrets.sh  # preserves existing path-graph-env token + S3_REGION
#   S3_REGION=garage (optional — override; else existing path-graph-env, then runtime/s3-creds, then garage)
#
# Reads: runtime/postgres-credentials, runtime/s3-creds, qdrant/qdrant-apikey
# Writes: path-graph/path-graph-env, path-graph/s3-creds (copy for Argo artifacts)

set -euo pipefail

TARGET_NS="${PATH_GRAPH_NS:-path-graph}"
RUNTIME_NS="${RUNTIME_NS:-runtime}"
QDRANT_NS="${QDRANT_NS:-qdrant}"

require_kubectl() {
  command -v kubectl >/dev/null 2>&1 || {
    echo "error: kubectl not found" >&2
    exit 1
  }
}

b64dec() {
  python3 -c "import base64,sys; print(base64.b64decode(sys.stdin.read()).decode(), end='')" <<<"$1"
}

require_kubectl

for ns in "$RUNTIME_NS" "$QDRANT_NS"; do
  kubectl get namespace "$ns" >/dev/null 2>&1 || {
    echo "error: namespace $ns not found" >&2
    exit 1
  }
done

kubectl create namespace "$TARGET_NS" --dry-run=client -o yaml | kubectl apply -f -

# Argo artifact repository references s3-creds in path-graph NS.
kubectl get secret s3-creds -n "$RUNTIME_NS" -o yaml \
  | sed "s/namespace: ${RUNTIME_NS}/namespace: ${TARGET_NS}/" \
  | grep -v '^\s*resourceVersion:' \
  | grep -v '^\s*uid:' \
  | grep -v '^\s*creationTimestamp:' \
  | kubectl apply -f -

PG_DSN_RAW="$(kubectl -n "$RUNTIME_NS" get secret postgres-credentials -o jsonpath='{.data.POSTGRES_DIRECT_DSN}')"
if [[ -z "$PG_DSN_RAW" ]]; then
  PG_DSN_RAW="$(kubectl -n "$RUNTIME_NS" get secret postgres-credentials -o jsonpath='{.data.POSTGRES_DSN}')"
fi
PG_DSN="$(b64dec "$PG_DSN_RAW" | sed 's/postgresql+asyncpg/postgresql/')"

S3_ENDPOINT="$(b64dec "$(kubectl -n "$RUNTIME_NS" get secret s3-creds -o jsonpath='{.data.S3_ENDPOINT_URL}')")"
S3_ACCESS="$(b64dec "$(kubectl -n "$RUNTIME_NS" get secret s3-creds -o jsonpath='{.data.S3_ACCESS_KEY_ID}')")"
S3_SECRET="$(b64dec "$(kubectl -n "$RUNTIME_NS" get secret s3-creds -o jsonpath='{.data.S3_SECRET_ACCESS_KEY}')")"
S3_BUCKET_RUNTIME="$(b64dec "$(kubectl -n "$RUNTIME_NS" get secret s3-creds -o jsonpath='{.data.S3_BUCKET}')")"
S3_BUCKET="${PATH_GRAPH_S3_BUCKET:-$S3_BUCKET_RUNTIME}"
S3_REGION_RAW="$(kubectl -n "$RUNTIME_NS" get secret s3-creds -o jsonpath='{.data.S3_REGION}' 2>/dev/null || true)"
S3_REGION_RUNTIME=""
if [[ -n "$S3_REGION_RAW" ]]; then
  S3_REGION_RUNTIME="$(b64dec "$S3_REGION_RAW")"
fi
S3_REGION_FROM_ENV="${S3_REGION:-}"
S3_REGION="${S3_REGION:-}"
if [[ -z "$S3_REGION" ]]; then
  EXISTING_REGION_RAW="$(kubectl -n "$TARGET_NS" get secret path-graph-env \
    -o jsonpath='{.data.S3_REGION}' 2>/dev/null || true)"
  if [[ -n "$EXISTING_REGION_RAW" ]]; then
    S3_REGION="$(b64dec "$EXISTING_REGION_RAW")"
  else
    S3_REGION="${S3_REGION_RUNTIME:-garage}"
  fi
fi

QDRANT_KEY="$(b64dec "$(kubectl -n "$QDRANT_NS" get secret qdrant-apikey -o jsonpath='{.data.api-key}')")"
if [[ -z "$QDRANT_KEY" ]]; then
  echo "error: qdrant/qdrant-apikey secret missing or empty — run make deploy-qdrant-nebula" >&2
  exit 1
fi

AGENT_TOKEN="${PIPELINE_AGENT_ACCESS_TOKEN:-}"
if [[ -z "$AGENT_TOKEN" ]]; then
  EXISTING_TOKEN_RAW="$(kubectl -n "$TARGET_NS" get secret path-graph-env \
    -o jsonpath='{.data.PIPELINE_AGENT_ACCESS_TOKEN}' 2>/dev/null || true)"
  if [[ -n "$EXISTING_TOKEN_RAW" ]]; then
    AGENT_TOKEN="$(b64dec "$EXISTING_TOKEN_RAW")"
  fi
fi

kubectl -n "$TARGET_NS" create secret generic path-graph-env \
  --from-literal=PATH_GRAPH_DSN="$PG_DSN" \
  --from-literal=PIPELINE_STORAGE_BACKEND=s3 \
  --from-literal=S3_ENDPOINT_URL="$S3_ENDPOINT" \
  --from-literal=S3_BUCKET="$S3_BUCKET" \
  --from-literal=S3_ACCESS_KEY="$S3_ACCESS" \
  --from-literal=S3_SECRET_KEY="$S3_SECRET" \
  --from-literal=S3_REGION="$S3_REGION" \
  --from-literal=QDRANT_URL='http://qdrant.qdrant.svc:6333' \
  --from-literal=QDRANT_API_KEY="$QDRANT_KEY" \
  --from-literal=NEBULA_HOST='nebula-graphd-svc.nebula.svc' \
  --from-literal=NEBULA_PORT='9669' \
  --from-literal=NEBULA_USER='root' \
  --from-literal=NEBULA_PASSWORD='nebula' \
  --from-literal=ENVOY_URL='http://envoy.runtime.svc:8080' \
  --from-literal=PIPELINE_AGENT_ACCESS_TOKEN="$AGENT_TOKEN" \
  --from-literal=EMBEDDING_BASE_URL='http://bge-m3-tei.llm-serving.svc:8080' \
  --from-literal=OCR_LLM_BASE_URL='http://sglang-gemma4-12b.llm-serving.svc.cluster.local:30000' \
  --from-literal=OCR_LLM_MODEL='nmilosev/gemma-4-12B-it-quantized.w4a16' \
  --from-literal=OCR_LLM_API_KEY='EMPTY' \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Secrets applied in namespace ${TARGET_NS}: path-graph-env, s3-creds"
if [[ -z "$AGENT_TOKEN" ]]; then
  echo "note: PIPELINE_AGENT_ACCESS_TOKEN empty — graph/wiki steps need token (wire-dev.sh env)"
elif [[ -z "${PIPELINE_AGENT_ACCESS_TOKEN:-}" ]]; then
  echo "note: preserved existing PIPELINE_AGENT_ACCESS_TOKEN from path-graph-env"
fi
if [[ -z "$S3_REGION_FROM_ENV" && -n "${EXISTING_REGION_RAW:-}" ]]; then
  echo "note: preserved existing S3_REGION from path-graph-env"
fi
