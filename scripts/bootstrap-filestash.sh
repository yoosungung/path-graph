#!/usr/bin/env bash
# Bootstrap Filestash admin secret for dev cluster (Garage S3 UI).
#
# Usage:
#   ./scripts/bootstrap-filestash.sh
#   FILESTASH_ADMIN_PASSWORD=... ./scripts/bootstrap-filestash.sh
#
# Writes: path-graph/filestash-env (ADMIN_PASSWORD bcrypt, APPLICATION_URL)

set -euo pipefail

TARGET_NS="${PATH_GRAPH_NS:-path-graph}"
ADMIN_PASSWORD="${FILESTASH_ADMIN_PASSWORD:-filestash-dev}"

require_kubectl() {
  command -v kubectl >/dev/null 2>&1 || {
    echo "error: kubectl not found" >&2
    exit 1
  }
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

ADMIN_HASH="$(bcrypt_hash "$ADMIN_PASSWORD")" || {
  echo "error: bcrypt module required — run: uv pip install bcrypt" >&2
  exit 1
}

kubectl -n "$TARGET_NS" create secret generic filestash-env \
  --from-literal=ADMIN_PASSWORD="$ADMIN_HASH" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Secret applied in ${TARGET_NS}: filestash-env (admin password set)"
echo "  Admin: http://filestash.k8s-test/admin (or port-forward :8334)"
echo "  S3 login:"
echo "    Access Key ID  = GARAGE_DEFAULT_ACCESS_KEY (s3-creds S3_ACCESS_KEY_ID)"
echo "    Secret Key     = GARAGE_DEFAULT_SECRET_KEY (s3-creds S3_SECRET_ACCESS_KEY)"
echo "    Advanced endpoint: http://garage-s3.runtime.svc.cluster.local:3900"
echo "    Advanced region:   garage"
