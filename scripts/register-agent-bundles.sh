#!/usr/bin/env bash
# Register path-graph agent bundles (graph-extractor, wiki-synthesizer) via agents-runtime admin.
#
# Usage:
#   ./scripts/register-agent-bundles.sh graph-extractor v2
#   ./scripts/register-agent-bundles.sh wiki-synthesizer v2
#   ./scripts/register-agent-bundles.sh all v2
#
# Env:
#   AGENTS_HOST       default https://agents.k8s-test
#   ADMIN_USER        default admin
#   ADMIN_PASSWORD    required (or read from runtime/initial-admin-password)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENTS_HOST="${AGENTS_HOST:-https://agents.k8s-test}"
ADMIN_USER="${ADMIN_USER:-admin}"

if [[ -z "${ADMIN_PASSWORD:-}" ]]; then
  ADMIN_PASSWORD="$(kubectl -n runtime get secret initial-admin-password \
    -o jsonpath='{.data.password}' 2>/dev/null | base64 -d || true)"
fi
[[ -n "${ADMIN_PASSWORD:-}" ]] || {
  echo "error: set ADMIN_PASSWORD or ensure runtime/initial-admin-password exists" >&2
  exit 1
}

command -v curl >/dev/null || { echo "error: curl required" >&2; exit 1; }
command -v jq >/dev/null || { echo "error: jq required" >&2; exit 1; }
command -v zip >/dev/null || { echo "error: zip required" >&2; exit 1; }

WORK="$ROOT/.work/register-bundles"
COOKIE_JAR="$WORK/cookies.txt"
mkdir -p "$WORK"

login() {
  rm -f "$COOKIE_JAR"
  local body
  body=$(curl -sS --fail-with-body \
    -c "$COOKIE_JAR" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg u "$ADMIN_USER" --arg p "$ADMIN_PASSWORD" '{username:$u, password:$p}')" \
    "$AGENTS_HOST/api/auth/login")
  CSRF=$(awk '/csrf_token/ {print $7}' "$COOKIE_JAR" | tail -n1)
  [[ -n "$CSRF" ]] || { echo "login failed: csrf missing — $body" >&2; exit 1; }
}

build_zip() {
  local agent_name="$1"
  local src_dir="$ROOT/agents/$agent_name/src"
  local out="$WORK/$agent_name.zip"
  rm -f "$out"
  (cd "$src_dir" && zip -q -r "$out" . -x '*/__pycache__/*' '*.pyc')
  echo "$out"
}

register_one() {
  local agent_name="$1" version="$2"
  local package entrypoint config_json
  case "$agent_name" in
    graph-extractor)
      package="graph_extractor"
      entrypoint="graph_extractor.agent:factory"
      config_json='{"langgraph":{"model":"preset:GEMMA412B"},"graph_extractor":{"max_batch_chars":2500,"max_completion_tokens":8192,"chunks_per_group":100,"max_concurrent_workers":2}}'
      ;;
    wiki-synthesizer)
      package="wiki_synthesizer"
      entrypoint="wiki_synthesizer.agent:factory"
      config_json='{"langgraph":{"model":"preset:GEMMA412B"},"wiki_synthesizer":{"max_completion_tokens":2048}}'
      ;;
    *)
      echo "error: unknown agent $agent_name" >&2
      exit 1
      ;;
  esac

  local zipf
  zipf="$(build_zip "$agent_name")"
  local meta
  meta=$(jq -nc \
    --arg k agent --arg n "$agent_name" --arg v "$version" \
    --arg p "agent:compiled_graph" --arg e "$entrypoint" \
    --argjson c "$config_json" \
    '{kind:$k, name:$n, version:$v, runtime_pool:$p, entrypoint:$e, config:$c}')

  echo "Registering $agent_name@$version from $zipf ..."
  local resp
  resp=$(curl -sS --fail-with-body \
    -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
    -H "X-CSRF-Token: $CSRF" \
    -F "file=@$zipf;type=application/zip" \
    -F "meta=$meta" \
    "$AGENTS_HOST/api/source-meta/bundle") || {
      if grep -q 'already exists' <<<"$resp" 2>/dev/null; then
        echo "  already registered: $agent_name@$version"
        return 0
      fi
      echo "register failed: $resp" >&2
      exit 1
    }
  echo "  id=$(jq -r .id <<<"$resp") checksum=$(jq -r .checksum <<<"$resp")"
}

login

TARGET="${1:-all}"
VERSION="${2:-v2}"

case "$TARGET" in
  graph-extractor|wiki-synthesizer)
    register_one "$TARGET" "$VERSION"
    ;;
  all)
    register_one graph-extractor "$VERSION"
    register_one wiki-synthesizer "$VERSION"
    ;;
  *)
    echo "usage: $0 {graph-extractor|wiki-synthesizer|all} [version]" >&2
    exit 1
    ;;
esac

echo "Done."
