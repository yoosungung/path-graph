#!/bin/sh
# Render Filestash config.json with Garage S3 auto-login (passthrough direct).
#
# Required env (from path-graph/s3-creds, copied from runtime/s3-creds):
#   S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_ENDPOINT_URL, S3_BUCKET
# Optional:
#   FILESTASH_S3_REGION (default: garage)
#   FILESTASH_S3_LABEL   (default: Garage S3)
#
# Usage:
#   ./render-filestash-config.sh [/path/to/config.json]

set -eu

OUT="${1:-}"

require_env() {
  eval "val=\${$1:-}"
  if [ -z "$val" ]; then
    echo "error: $1 is required" >&2
    exit 1
  fi
}

require_env S3_ACCESS_KEY_ID
require_env S3_SECRET_ACCESS_KEY
require_env S3_ENDPOINT_URL
require_env S3_BUCKET

json="$(python3 - <<'PY'
import json
import os

label = os.environ.get("FILESTASH_S3_LABEL", "Garage S3")
bucket = os.environ["S3_BUCKET"].strip("/")
s3_backend = {
    "type": "s3",
    "access_key_id": os.environ["S3_ACCESS_KEY_ID"],
    "secret_access_key": os.environ["S3_SECRET_ACCESS_KEY"],
    "endpoint": os.environ["S3_ENDPOINT_URL"],
    "region": os.environ.get("FILESTASH_S3_REGION", "garage"),
    "path": f"/{bucket}/",
    "advanced": True,
}
config = {
    "connections": [{"type": "s3", "label": label}],
    "middleware": {
        "identity_provider": {
            "type": "passthrough",
            "params": json.dumps({"type": "passthrough", "strategy": "direct"}),
        },
        "attribute_mapping": {
            "related_backend": label,
            "params": json.dumps({label: s3_backend}),
        },
    },
    "general": {"host": ""},
}
print(json.dumps(config, indent=2))
PY
)"

if [ -n "$OUT" ]; then
  mkdir -p "$(dirname "$OUT")"
  printf '%s\n' "$json" >"$OUT"
else
  printf '%s\n' "$json"
fi
