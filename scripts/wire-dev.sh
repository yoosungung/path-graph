#!/usr/bin/env bash
# Wire local path-graph debug to k8s infra (agents-runtime + path-graph Nebula).
#
# Usage:
#   ./scripts/wire-dev.sh up [--profile core|s3|runtime|test-infra]
#   ./scripts/wire-dev.sh down
#   ./scripts/wire-dev.sh status
#   ./scripts/wire-dev.sh env [--storage local|s3]
#
# Local port map (cluster Service → Mac):
#   runtime/postgres:5432, runtime/envoy:8084, runtime/auth:8081,
#   nebula/nebula-graphd-svc:9669,
#   runtime/garage-s3:3900 (profile s3)
#   llm-serving/bge-m3-tei:8085 (optional; skipped when svc missing)
#
# Prerequisites:
#   agents-runtime dev cluster: make k8s-apply-dev (or wire-dev in ../agents-runtime)
#   path-graph: make deploy-nebula (NebulaGraph)
#
# See scripts/wire-dev.env.example and .vscode/launch.json for debug configs.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_NS="${RUNTIME_NS:-runtime}"
NEBULA_NS="${NEBULA_NS:-nebula}"
LLM_SERVING_NS="${LLM_SERVING_NS:-llm-serving}"
TEI_LOCAL_PORT="${WIRE_DEV_TEI_LOCAL_PORT:-8085}"
STATE_DIR="${WIRE_DEV_STATE_DIR:-$ROOT/.wire-dev}"
PID_DIR="$STATE_DIR/pids"
PROFILE="${WIRE_DEV_PROFILE:-core}"
STORAGE_BACKEND="${WIRE_DEV_STORAGE:-local}"

# Dev Garage defaults — sync with agents-runtime deploy/k8s/garage/garage-secrets.env
GARAGE_ACCESS_KEY="${GARAGE_ACCESS_KEY:-GKdev000000000000000001}"
GARAGE_SECRET_KEY="${GARAGE_SECRET_KEY:-devsecret000000000000000000000000000000000000000000000000000000}"
GARAGE_BUCKET="${GARAGE_BUCKET:-runtime-bundles}"
usage() {
  sed -n '2,10p' "$0" | sed 's/^# \?//'
  echo
  echo "Profiles:"
  echo "  core        postgres, envoy, auth, nebula (default)"
  echo "  s3          core + garage-s3 (PIPELINE_STORAGE_BACKEND=s3)"
  echo "  runtime     agents-runtime only (postgres, envoy, auth)"
  echo "  test-infra  nebula only"
  echo
  echo "env:"
  echo "  --storage local|s3   blob backend in generated .env.dev.local (default: local)"
  echo
  echo "Agent token (env command):"
  echo "  Set WIRE_DEV_AUTH_USER / WIRE_DEV_AUTH_PASSWORD, or ensure auth :8081 is forwarded"
  echo "  and secret initial-admin-password exists in namespace ${RUNTIME_NS}."
}

python_bin() {
  if [[ -x "$ROOT/.venv/bin/python3" ]]; then
    echo "$ROOT/.venv/bin/python3"
  else
    command -v python3
  fi
}

require_kubectl() {
  if ! command -v kubectl >/dev/null 2>&1; then
    echo "error: kubectl not found" >&2
    exit 1
  fi
}

svc_exists() {
  kubectl -n "$1" get "svc/$2" >/dev/null 2>&1
}

port_listen() {
  lsof -i ":$1" -sTCP:LISTEN >/dev/null 2>&1
}

start_pf() {
  local name="$1"
  local local_port="$2"
  local remote_port="$3"
  local svc="$4"
  local ns="$5"
  local pid_file="$PID_DIR/${name}.pid"

  mkdir -p "$PID_DIR"

  if [[ -f "$pid_file" ]]; then
    local old_pid
    old_pid="$(cat "$pid_file")"
    if kill -0 "$old_pid" 2>/dev/null; then
      echo "  [skip] $name already forwarded (pid $old_pid, :$local_port)"
      return 0
    fi
    rm -f "$pid_file"
  fi

  if port_listen "$local_port"; then
    echo "  [warn] port $local_port already in use — skipping $name (svc/$svc)" >&2
    return 0
  fi

  if ! svc_exists "$ns" "$svc"; then
    echo "  [warn] svc/$svc not found in $ns — skipping $name" >&2
    return 0
  fi

  echo "  [start] $name 127.0.0.1:$local_port → svc/$svc:$remote_port ($ns)"
  kubectl -n "$ns" port-forward "svc/$svc" "${local_port}:${remote_port}" \
    >"$STATE_DIR/${name}.log" 2>&1 &
  echo $! >"$pid_file"
  sleep 0.3
}

stop_pf() {
  local name="$1"
  local pid_file="$PID_DIR/${name}.pid"
  if [[ ! -f "$pid_file" ]]; then
    return 0
  fi
  local pid
  pid="$(cat "$pid_file")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    echo "  [stop] $name (pid $pid)"
  fi
  rm -f "$pid_file"
}

wire_runtime() {
  start_pf postgres 5432 5432 postgres "$RUNTIME_NS"
  start_pf envoy 8084 8080 envoy "$RUNTIME_NS"
  start_pf auth 8081 8080 auth "$RUNTIME_NS"
}

wire_test_infra() {
  start_pf nebula 9669 9669 nebula-graphd-svc "$NEBULA_NS"
}

wire_garage() {
  start_pf garage-s3 3900 3900 garage-s3 "$RUNTIME_NS"
}

wire_tei() {
  start_pf bge-m3-tei "$TEI_LOCAL_PORT" 8080 bge-m3-tei "$LLM_SERVING_NS"
}

resolve_embedding_base_url() {
  if port_listen "$TEI_LOCAL_PORT"; then
    echo "http://127.0.0.1:${TEI_LOCAL_PORT}"
  else
    echo "http://bge-m3-tei.llm-serving.svc.cluster.local:8080"
  fi
}

cmd_up() {
  local profile="$1"
  require_kubectl
  mkdir -p "$STATE_DIR"
  echo "wire-dev: profile=$profile runtime_ns=$RUNTIME_NS"
  case "$profile" in
    core)
      wire_runtime
      wire_test_infra
      wire_tei
      ;;
    s3)
      wire_runtime
      wire_test_infra
      wire_garage
      wire_tei
      ;;
    runtime) wire_runtime ;;
    test-infra) wire_test_infra ;;
    *)
      echo "error: unknown profile '$profile'" >&2
      exit 1
      ;;
  esac
  echo "$profile" >"$STATE_DIR/profile"
  echo "wire-dev: up done (pids in $PID_DIR)"
  echo "hint: ./scripts/wire-dev.sh env"
}

cmd_down() {
  if [[ ! -d "$PID_DIR" ]]; then
    echo "wire-dev: nothing to stop"
    return 0
  fi
  echo "wire-dev: stopping port-forwards"
  for pid_file in "$PID_DIR"/*.pid; do
    [[ -e "$pid_file" ]] || continue
    name="$(basename "$pid_file" .pid)"
    stop_pf "$name"
  done
  rm -f "$STATE_DIR/profile"
  echo "wire-dev: down done"
}

cmd_status() {
  if [[ ! -d "$PID_DIR" ]]; then
    echo "wire-dev: no active forwards"
    return 0
  fi
  echo "wire-dev: active forwards"
  local any=0
  for pid_file in "$PID_DIR"/*.pid; do
    [[ -e "$pid_file" ]] || continue
    any=1
    local name pid
    name="$(basename "$pid_file" .pid)"
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      echo "  ok  $name pid=$pid"
    else
      echo "  dead $name pid=$pid (stale pid file)"
    fi
  done
  if [[ "$any" -eq 0 ]]; then
    echo "  (none)"
  fi
  if [[ -f "$STATE_DIR/profile" ]]; then
    echo "profile: $(cat "$STATE_DIR/profile")"
  fi
}

fetch_agent_token() {
  local user pass token
  user="${WIRE_DEV_AUTH_USER:-admin}"
  pass="${WIRE_DEV_AUTH_PASSWORD:-}"

  if [[ -z "$pass" ]]; then
    pass="$(kubectl -n "$RUNTIME_NS" get secret initial-admin-password \
      -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || true)"
  fi
  if [[ -z "$pass" ]]; then
    echo ""
    return 0
  fi

  if ! port_listen 8081; then
    echo "wire-dev: auth :8081 not listening — run ./scripts/wire-dev.sh up first" >&2
    echo ""
    return 0
  fi

  token="$("$(python_bin)" - "$user" "$pass" <<'PY'
import json
import sys
import urllib.error
import urllib.request

user, password = sys.argv[1], sys.argv[2]
req = urllib.request.Request(
    "http://127.0.0.1:8081/login",
    data=json.dumps({"username": user, "password": password}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read().decode())
        print(body.get("access_token", ""))
except (urllib.error.URLError, json.JSONDecodeError, KeyError):
    print("")
PY
)"
  echo "$token"
}

cmd_env() {
  local storage="$1"
  require_kubectl
  local env_file="$ROOT/.env.dev.local"
  local token
  local embedding_base_url
  token="$(fetch_agent_token)"
  embedding_base_url="$(resolve_embedding_base_url)"

  local storage_backend="$storage"
  local storage_dir=".data/pipeline"
  local s3_block=""
  if [[ "$storage" == "s3" ]]; then
    storage_backend="s3"
    s3_block=$(cat <<EOF

S3_ENDPOINT_URL=http://127.0.0.1:3900
S3_BUCKET=${GARAGE_BUCKET}
S3_ACCESS_KEY=${GARAGE_ACCESS_KEY}
S3_SECRET_KEY=${GARAGE_SECRET_KEY}
EOF
)
  fi

  cat >"$env_file" <<EOF
# Generated by scripts/wire-dev.sh env — do not commit (.gitignore)
# Re-run: ./scripts/wire-dev.sh up && ./scripts/wire-dev.sh env

ENV=dev
LOG_LEVEL=DEBUG
PATH_GRAPH_TENANT=dev

# runtime PG (wire-dev → postgres :5432)
PATH_GRAPH_DSN=postgresql://runtime:runtime@127.0.0.1:5432/runtime?sslmode=disable

# blob
PIPELINE_STORAGE_BACKEND=${storage_backend}
PIPELINE_STORAGE_DIR=${storage_dir}${s3_block}

# path-graph deploy/k8s/infra (wire-dev → nebula :9669)

NEBULA_HOST=127.0.0.1
NEBULA_PORT=9669
NEBULA_USER=root
NEBULA_PASSWORD=nebula

# agents-runtime invoke (wire-dev → envoy :8084)
ENVOY_URL=http://127.0.0.1:8084
PIPELINE_AGENT_ACCESS_TOKEN=${token}

# RAG embed (외부 TEI — BAAI/bge-m3)
# Active when wire-dev forwards bge-m3-tei → 127.0.0.1:${TEI_LOCAL_PORT}
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIM=1024
EMBEDDING_BASE_URL=${embedding_base_url}

# HWP parser (rhwp_batch)
RHWP_BATCH_BIN=rhwp-batch

# OAuth collectors (optional — collectors/remote.py)
# GDRIVE_REFRESH_TOKEN=
# ONEDRIVE_REFRESH_TOKEN=
EOF

  chmod 600 "$env_file"
  echo "wire-dev: wrote $env_file (storage=${storage_backend})"
  if [[ -z "$token" ]]; then
    echo "wire-dev: PIPELINE_AGENT_ACCESS_TOKEN empty — set WIRE_DEV_AUTH_PASSWORD or login manually"
  fi
}

main() {
  local cmd="${1:-}"
  shift || true

  case "$cmd" in
    up)
      local profile="$PROFILE"
      while [[ $# -gt 0 ]]; do
        case "$1" in
          --profile)
            profile="$2"
            shift 2
            ;;
          *)
            echo "error: unknown option '$1'" >&2
            usage
            exit 1
            ;;
        esac
      done
      cmd_up "$profile"
      ;;
    down) cmd_down ;;
    status) cmd_status ;;
    env)
      local storage="$STORAGE_BACKEND"
      while [[ $# -gt 0 ]]; do
        case "$1" in
          --storage)
            storage="$2"
            shift 2
            ;;
          *)
            echo "error: unknown option '$1'" >&2
            usage
            exit 1
            ;;
        esac
      done
      cmd_env "$storage"
      ;;
    -h | --help | help) usage ;;
    *)
      echo "error: unknown command '${cmd:-}'" >&2
      usage
      exit 1
      ;;
  esac
}

main "$@"
