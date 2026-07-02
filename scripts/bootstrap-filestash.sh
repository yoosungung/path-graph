#!/usr/bin/env bash
# Bootstrap Filestash admin secret for dev cluster (Garage S3 UI).
#
# Usage:
#   ./scripts/bootstrap-filestash.sh
#   FILESTASH_ADMIN_PASSWORD=... ./scripts/bootstrap-filestash.sh
#   (unset) ./scripts/bootstrap-filestash.sh  # preserves existing filestash-env ADMIN_PASSWORD hash
#
# Writes: path-graph/filestash-env (ADMIN_PASSWORD bcrypt, APPLICATION_URL)

set -euo pipefail

TARGET_NS="${PATH_GRAPH_NS:-path-graph}"
ADMIN_PASSWORD_FROM_ENV="${FILESTASH_ADMIN_PASSWORD:-}"

require_kubectl() {
  command -v kubectl >/dev/null 2>&1 || {
    echo "error: kubectl not found" >&2
    exit 1
  }
}

b64dec() {
  python3 -c "import base64,sys; print(base64.b64decode(sys.stdin.read()).decode(), end='')" <<<"$1"
}

bcrypt_hash() {
  local plain="$1"
  if [[ -x ".venv/bin/python3" ]]; then
    .venv/bin/python3 - "$plain" <<'PY'
import sys

plain = sys.argv[1].encode()
try:
    import bcrypt
except ImportError:
    sys.exit(2)
print(bcrypt.hashpw(plain, bcrypt.gensalt(rounds=10)).decode())
PY
    return
  fi
  python3 - "$plain" <<'PY'
import sys

plain = sys.argv[1].encode()
try:
    import bcrypt
except ImportError:
    sys.exit(2)
print(bcrypt.hashpw(plain, bcrypt.gensalt(rounds=10)).decode())
PY
}

require_kubectl

kubectl get namespace "$TARGET_NS" >/dev/null 2>&1 || {
  echo "error: namespace $TARGET_NS not found (run create-path-graph-secrets.sh first)" >&2
  exit 1
}

ADMIN_HASH=""
EXISTING_ADMIN_HASH_RAW=""
APPLICATION_URL="${FILESTASH_APPLICATION_URL:-}"

if [[ -z "$ADMIN_PASSWORD_FROM_ENV" ]]; then
  EXISTING_ADMIN_HASH_RAW="$(kubectl -n "$TARGET_NS" get secret filestash-env \
    -o jsonpath='{.data.ADMIN_PASSWORD}' 2>/dev/null || true)"
  if [[ -n "$EXISTING_ADMIN_HASH_RAW" ]]; then
    ADMIN_HASH="$(b64dec "$EXISTING_ADMIN_HASH_RAW")"
  fi
fi

if [[ -z "$ADMIN_HASH" ]]; then
  ADMIN_HASH="$(bcrypt_hash "${ADMIN_PASSWORD_FROM_ENV:-filestash-dev}")" || {
    echo "error: bcrypt module required — run: uv pip install bcrypt" >&2
    exit 1
  }
fi

if [[ -z "$APPLICATION_URL" ]]; then
  EXISTING_URL_RAW="$(kubectl -n "$TARGET_NS" get secret filestash-env \
    -o jsonpath='{.data.APPLICATION_URL}' 2>/dev/null || true)"
  if [[ -n "$EXISTING_URL_RAW" ]]; then
    APPLICATION_URL="$(b64dec "$EXISTING_URL_RAW")"
  else
    APPLICATION_URL="filestash.k8s-test"
  fi
fi

kubectl -n "$TARGET_NS" create secret generic filestash-env \
  --from-literal=ADMIN_PASSWORD="$ADMIN_HASH" \
  --from-literal=APPLICATION_URL="$APPLICATION_URL" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Secret applied in ${TARGET_NS}: filestash-env (admin password set)"
if [[ -z "$ADMIN_PASSWORD_FROM_ENV" && -n "$EXISTING_ADMIN_HASH_RAW" ]]; then
  echo "note: preserved existing filestash-env ADMIN_PASSWORD"
fi
echo "  Admin: http://filestash.k8s-test/admin (or port-forward :8334)"
echo "  S3: credentials pre-seeded from path-graph/s3-creds on pod start (select 'Garage S3' on login)"
