#!/usr/bin/env bash
# Validate create-path-graph-secrets.sh includes Garage S3_REGION for presigned URLs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

ok() { echo -e "${GREEN}[OK]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

SCRIPT="${ROOT_DIR}/scripts/create-path-graph-secrets.sh"
SETUP="${ROOT_DIR}/deploy/SETUP.md"

[[ -f "${SCRIPT}" ]] || fail "Missing ${SCRIPT}"
[[ -f "${SETUP}" ]] || fail "Missing ${SETUP}"

grep -q 'S3_REGION' "${SCRIPT}" \
  || fail "create-path-graph-secrets.sh must set S3_REGION in path-graph-env"
grep -q 'from-literal=S3_REGION=' "${SCRIPT}" \
  || fail "create-path-graph-secrets.sh must pass --from-literal=S3_REGION"
grep -q 'S3_REGION=garage' "${SETUP}" \
  || fail "SETUP.md must document S3_REGION=garage troubleshooting"
grep -q 'path-graph-env.*PIPELINE_AGENT_ACCESS_TOKEN\|PIPELINE_AGENT_ACCESS_TOKEN.*path-graph-env\|기존.*path-graph-env\|preserv' "${SETUP}" \
  || fail "SETUP.md must document PIPELINE_AGENT_ACCESS_TOKEN preservation on re-apply"
grep -q 'path-graph-env' "${SCRIPT}" \
  && grep -q 'PIPELINE_AGENT_ACCESS_TOKEN' "${SCRIPT}" \
  && grep -qE 'get secret path-graph-env|jsonpath=.*PIPELINE_AGENT_ACCESS_TOKEN' "${SCRIPT}" \
  || fail "create-path-graph-secrets.sh must preserve existing PIPELINE_AGENT_ACCESS_TOKEN from path-graph-env"
grep -q 'EXISTING_REGION_RAW' "${SCRIPT}" \
  || fail "create-path-graph-secrets.sh must preserve existing S3_REGION from path-graph-env"

ok "create-path-graph-secrets.sh includes S3_REGION for agent presigned URLs"
ok "create-path-graph-secrets.sh preserves PIPELINE_AGENT_ACCESS_TOKEN on re-apply"
ok "create-path-graph-secrets.sh preserves S3_REGION on re-apply"
