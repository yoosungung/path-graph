#!/usr/bin/env bash
# path-graph NebulaGraph 조회 스크립트 실행기.
# wire-dev port-forward(:9669) 또는 클러스터 graphd에 연결해 nebula-inspect.ngql을 실행한다.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
NGQL_FILE="${SCRIPT_DIR}/nebula-inspect.ngql"

NEBULA_ADDR="${NEBULA_ADDR:-127.0.0.1}"
NEBULA_PORT="${NEBULA_PORT:-9669}"
NEBULA_USER="${NEBULA_USER:-root}"
NEBULA_PASSWORD="${NEBULA_PASSWORD:-nebula}"
SPACE="${1:-}"

if [[ ! -f "${NGQL_FILE}" ]]; then
  echo "Missing ${NGQL_FILE}" >&2
  exit 1
fi

run_console() {
  local ngql="$1"
  if command -v nebula-console &>/dev/null; then
    nebula-console \
      -addr "${NEBULA_ADDR}" \
      -port "${NEBULA_PORT}" \
      -u "${NEBULA_USER}" \
      -p "${NEBULA_PASSWORD}" \
      -f "${ngql}"
    return
  fi
  if command -v docker &>/dev/null; then
    docker run --rm -i \
      -v "${ngql}:/inspect.ngql:ro" \
      --add-host=host.docker.internal:host-gateway \
      vesoft/nebula-console:v3.8.0 \
      -addr "${NEBULA_ADDR}" \
      -port "${NEBULA_PORT}" \
      -u "${NEBULA_USER}" \
      -p "${NEBULA_PASSWORD}" \
      -f /inspect.ngql
    return
  fi
  echo "nebula-console 또는 docker가 필요합니다." >&2
  echo "  brew install nebula-console  또는  docker pull vesoft/nebula-console:v3.8.0" >&2
  exit 1
}

if [[ -n "${SPACE}" ]]; then
  TMP="$(mktemp)"
  trap 'rm -f "${TMP}"' EXIT
  sed "s|^USE path_graph_acme_docs;|USE ${SPACE};|" "${NGQL_FILE}" > "${TMP}"
  run_console "${TMP}"
else
  echo "Usage: $0 <nebula_space>" >&2
  echo "  예: $0 path_graph_acme_docs" >&2
  echo "  Space 목록: nebula-console ... -e 'SHOW SPACES;'" >&2
  exit 1
fi
