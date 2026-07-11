#!/usr/bin/env bash
# Pre-merge validation for wire-dev TEI port-forward + local RAG env (ROADMAP 1.2.4).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WIRE_DEV="${ROOT_DIR}/scripts/wire-dev.sh"
ENV_EXAMPLE="${ROOT_DIR}/scripts/wire-dev.env.example"
E2E="${ROOT_DIR}/scripts/run-local-rag-e2e.sh"
MAKEFILE="${ROOT_DIR}/Makefile"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

ok() { echo -e "${GREEN}[OK]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

for f in "${WIRE_DEV}" "${ENV_EXAMPLE}" "${E2E}" "${MAKEFILE}"; do
  [[ -f "${f}" ]] || fail "Missing ${f}"
done

grep -q 'wire_tei' "${WIRE_DEV}" || fail "wire-dev.sh must define wire_tei()"
grep -q 'bge-m3-tei' "${WIRE_DEV}" || fail "wire-dev.sh must port-forward bge-m3-tei"
grep -q '8085' "${WIRE_DEV}" || fail "wire-dev.sh must map TEI to local :8085"
grep -q 'llm-serving' "${WIRE_DEV}" || fail "wire-dev.sh must target llm-serving namespace"
grep -q 'resolve_embedding_base_url' "${WIRE_DEV}" \
  || fail "wire-dev.sh must resolve EMBEDDING_BASE_URL from local TEI PF"
grep -q '127.0.0.1:\${TEI_LOCAL_PORT}' "${WIRE_DEV}" \
  || fail "wire-dev env must prefer local TEI URL when PF is active"

grep -q 'bge-m3-tei.*8085' "${ENV_EXAMPLE}" \
  || fail "wire-dev.env.example must document TEI :8085 map"

grep -q 'e2e-local-rag' "${MAKEFILE}" \
  || fail "Makefile must expose e2e-local-rag target"

ok "wire-dev local RAG config validation passed"
