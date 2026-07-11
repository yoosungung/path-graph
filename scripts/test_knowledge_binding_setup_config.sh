#!/usr/bin/env bash
# Pre-merge validation for Knowledge Binding cluster verification runbook (ROADMAP 3.2.0).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SETUP="${ROOT_DIR}/deploy/SETUP.md"
ROADMAP="${ROOT_DIR}/ROADMAP.md"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

ok() { echo -e "${GREEN}[OK]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

for f in "${SETUP}" "${ROADMAP}"; do
  [[ -f "${f}" ]] || fail "Missing ${f}"
done

grep -q '## 관리자 클러스터 검증' "${SETUP}" \
  || fail "deploy/SETUP.md must document admin cluster verification"
grep -q 'Knowledge Binding' "${SETUP}" \
  || fail "deploy/SETUP.md must document Knowledge Binding verification"
grep -q 'api_get_binding' "${SETUP}" \
  || fail "deploy/SETUP.md must reference api_get_binding smoke"
grep -q 'requires_project=true' "${SETUP}" \
  || fail "deploy/SETUP.md must document MCP requires_project"
grep -q 'knowledge_binding_resolve' "${SETUP}" \
  || fail "deploy/SETUP.md must document knowledge_binding_resolve log check"
grep -q '보류' "${ROADMAP}" \
  || fail "ROADMAP must note SharePoint delta deferral in admin checklist"

ok "Knowledge Binding setup config validation passed"
