#!/usr/bin/env bash
# run.sh [port] — dev server on 127.0.0.1 (default port 8000) using .venv.
# Creates .venv and installs requirements.txt if .venv is missing.
#
# USAGE: scripts/run.sh [port]
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${1:-8000}"

if [ ! -d .venv ]; then
  echo "No .venv found; creating it and installing requirements…"
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

# Loopback-only dev server: skip auth unless a password is explicitly set.
if [ -z "${PEOPLE_PASSWORD:-}" ]; then
  export PEOPLE_AUTH_DISABLED=1
  echo "Auth disabled (loopback dev). Set PEOPLE_PASSWORD to test with auth."
fi

echo "Serving on http://127.0.0.1:${PORT}"
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
