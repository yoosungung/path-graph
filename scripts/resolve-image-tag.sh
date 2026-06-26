#!/usr/bin/env bash
# Canonical pipeline image tag: full git commit SHA (matches GHA build-images.yml).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
git -C "$ROOT" rev-parse HEAD
