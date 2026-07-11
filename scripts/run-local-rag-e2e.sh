#!/usr/bin/env bash
# Local RAG E2E: wire-dev PG + TEI → ingest_web --rag → pgvector verify (ROADMAP 1.2.4).
#
# Usage:
#   ./scripts/run-local-rag-e2e.sh
#   TENANT=dev PROJECT_ID=550e8400-e29b-41d4-a716-446655440000 ./scripts/run-local-rag-e2e.sh
#
# Prerequisites:
#   make install
#   ./scripts/wire-dev.sh up && ./scripts/wire-dev.sh env
#   llm-serving/bge-m3-tei reachable (wire-dev forwards :8085 when svc exists)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TENANT="${TENANT:-dev}"
PROJECT_ID="${PROJECT_ID:-550e8400-e29b-41d4-a716-446655440000}"
SAMPLE="${SAMPLE:-${ROOT}/pipeline/dev/sample.txt}"
PY="${ROOT}/.venv/bin/python3"
ENV_FILE="${ROOT}/.env.dev.local"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

ok() { echo -e "${GREEN}[OK]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

if [[ ! -x "$PY" ]]; then
  fail "run make install first"
fi

if [[ ! -f "$ENV_FILE" ]]; then
  fail "missing ${ENV_FILE} — run ./scripts/wire-dev.sh up && ./scripts/wire-dev.sh env"
fi

# shellcheck disable=SC1090
set -a
source "$ENV_FILE"
set +a

[[ -n "${PATH_GRAPH_DSN:-}" ]] || fail "PATH_GRAPH_DSN empty in ${ENV_FILE}"
[[ -f "$SAMPLE" ]] || fail "sample file missing: ${SAMPLE}"

port_listen() {
  lsof -i ":$1" -sTCP:LISTEN >/dev/null 2>&1
}

if ! port_listen 5432; then
  fail "postgres :5432 not listening — run ./scripts/wire-dev.sh up"
fi

EMBED_URL="${EMBEDDING_BASE_URL:-}"
if [[ -z "$EMBED_URL" ]]; then
  fail "EMBEDDING_BASE_URL unset in ${ENV_FILE}"
fi

echo "Probing TEI at ${EMBED_URL} ..."
if ! "$PY" - <<PY
import os
import sys
import urllib.error
import urllib.request

url = os.environ["EMBED_URL"].rstrip("/") + "/health"
try:
    with urllib.request.urlopen(url, timeout=15) as resp:
        sys.exit(0 if resp.status == 200 else 1)
except urllib.error.HTTPError as exc:
    sys.exit(0 if exc.code in (200, 404) else 1)
except urllib.error.URLError:
    sys.exit(1)
PY
then
  fail "TEI unreachable at ${EMBED_URL} — ensure llm-serving/bge-m3-tei and ./scripts/wire-dev.sh up"
fi
ok "TEI reachable (${EMBED_URL})"

echo "Ensuring project for tenant=${TENANT} ..."
PROJECT_ID="$(
  ROOT="$ROOT" TENANT="$TENANT" PROJECT_ID="$PROJECT_ID" PATH_GRAPH_DSN="$PATH_GRAPH_DSN" "$PY" - <<'PY'
import os
import sys
from pathlib import Path

root = Path(os.environ["ROOT"])
sys.path.insert(0, str(root / "pipeline" / "src"))

from path_graph.admin.projects import ProjectStore

tenant = os.environ["TENANT"]
requested = os.environ.get("PROJECT_ID", "").strip()
dsn = os.environ["PATH_GRAPH_DSN"]
store = ProjectStore(dsn)
if requested and store.get_project(tenant, requested) is not None:
    print(requested)
else:
    print(store.ensure_default_project(tenant).id)
PY
)"
export PROJECT_ID
ok "project_id=${PROJECT_ID}"

echo "Running ingest_web --rag ..."
set +e
INGEST_OUT="$(
  "$PY" -m path_graph.steps.ingest_web \
    --tenant "$TENANT" \
    --project-id "$PROJECT_ID" \
    --file "$SAMPLE" \
    --rag 2>&1
)"
INGEST_RC=$?
set -e
echo "$INGEST_OUT"
[[ "$INGEST_RC" -eq 0 ]] || fail "ingest_web --rag failed (exit ${INGEST_RC})"

DOC_ID="$(
  ROOT="$ROOT" TENANT="$TENANT" PROJECT_ID="$PROJECT_ID" SAMPLE="$SAMPLE" "$PY" - <<'PY'
import hashlib
import os
import sys
from pathlib import Path

root = Path(os.environ["ROOT"])
sys.path.insert(0, str(root / "pipeline" / "src"))

from path_graph.collectors.remote import collect_local_file

meta = collect_local_file(
    Path(os.environ["SAMPLE"]),
    os.environ["TENANT"],
    os.environ["PROJECT_ID"],
    "local-rag-e2e",
)
print(meta["document_id"])
PY
)"

echo "Verifying pgvector rows for document_id=${DOC_ID} ..."
CHUNK_ROWS="$(
  PATH_GRAPH_DSN="$PATH_GRAPH_DSN" TENANT="$TENANT" DOC_ID="$DOC_ID" "$PY" - <<'PY'
import os
import sys

import psycopg

dsn = os.environ["PATH_GRAPH_DSN"]
tenant = os.environ["TENANT"]
doc_id = os.environ["DOC_ID"]

with psycopg.connect(dsn) as conn:
    row = conn.execute(
        """
        SELECT count(*)::int
        FROM path_graph.chunks
        WHERE tenant = %s
          AND document_id = %s
          AND embedding IS NOT NULL
        """,
        (tenant, doc_id),
    ).fetchone()

count = row[0] if row else 0
print(count)
if count < 1:
    sys.exit(1)
PY
)" || fail "no embedded chunks in path_graph.chunks for ${DOC_ID}"

ok "local RAG E2E passed (${CHUNK_ROWS} embedded chunk(s))"
