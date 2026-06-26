#!/usr/bin/env bash
# Validate Filestash Garage seed config rendering (TDD gate).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

ok() { echo -e "${GREEN}[OK]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

RENDER="${ROOT_DIR}/deploy/k8s/base/render-filestash-config.sh"
FILESTASH_YAML="${ROOT_DIR}/deploy/k8s/base/filestash.yaml"

[[ -x "${RENDER}" ]] || fail "Missing executable ${RENDER}"
[[ -f "${FILESTASH_YAML}" ]] || fail "Missing ${FILESTASH_YAML}"

grep -q 's3-creds' "${FILESTASH_YAML}" || fail "filestash.yaml must mount s3-creds for seed config"
grep -q 'render-filestash-config.sh' "${FILESTASH_YAML}" || fail "filestash.yaml must invoke render-filestash-config.sh"

TMP="$(mktemp)"
trap 'rm -f "${TMP}"' EXIT

export S3_ACCESS_KEY_ID=GKdev000000000000000001
export S3_SECRET_ACCESS_KEY=devsecret000000000000000000000000000000000000000000000000000000
export S3_ENDPOINT_URL=http://garage-s3.runtime.svc.cluster.local:3900
export S3_BUCKET=runtime-bundles

"${RENDER}" "${TMP}"

python3 - "${TMP}" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as fh:
    data = json.load(fh)

conn = data["connections"][0]
assert conn["type"] == "s3"
assert conn["label"] == "Garage S3"
assert "access_key_id" not in conn

mw = data["middleware"]
assert mw["identity_provider"]["type"] == "passthrough"
idp_params = json.loads(mw["identity_provider"]["params"])
assert idp_params["strategy"] == "direct"

mapping = mw["attribute_mapping"]
assert mapping["related_backend"] == "Garage S3"
mapped = json.loads(mapping["params"])["Garage S3"]
assert mapped["access_key_id"]
assert mapped["secret_access_key"]
assert mapped["endpoint"].startswith("http://")
assert mapped["region"] == "garage"
assert mapped["path"] == "/runtime-bundles/"
PY

ok "render-filestash-config.sh produces valid Garage S3 config.json"

BOOTSTRAP="${ROOT_DIR}/scripts/bootstrap-filestash.sh"

[[ -x "${BOOTSTRAP}" ]] || fail "Missing executable ${BOOTSTRAP}"

grep -q 'APPLICATION_URL="filestash.k8s-test"' "${BOOTSTRAP}" \
  || fail "bootstrap-filestash.sh must set APPLICATION_URL to bare hostname (no http:// scheme)"

grep -q 'APPLICATION_URL="http://' "${BOOTSTRAP}" \
  && fail "bootstrap-filestash.sh must not prefix APPLICATION_URL with http:// (Filestash redirect bug)"

ok "bootstrap-filestash.sh sets APPLICATION_URL to bare hostname"