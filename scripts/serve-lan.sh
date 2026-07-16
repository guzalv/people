#!/usr/bin/env bash
# serve-lan.sh [port] — dev server on all interfaces (default port 8080) so a
# phone on the same Wi-Fi can reach it. Prints the LAN URL.
#
# Run this from a NORMAL terminal, not a sandboxed Claude session: the sandbox
# drops LAN traffic for in-session processes, so the phone can't connect (see
# the README "Docker" note for the same reason).
#
# USAGE: scripts/serve-lan.sh [port]
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${1:-8080}"

if [ ! -d .venv ]; then
  echo "No .venv found; creating it and installing requirements…"
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

# Serving beyond loopback: a password is mandatory (the app holds PII).
if [ -z "${PEOPLE_PASSWORD:-}" ]; then
  echo "ERROR: set PEOPLE_PASSWORD before serving on the network:" >&2
  echo "  PEOPLE_PASSWORD='…' scripts/serve-lan.sh" >&2
  exit 1
fi

IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo 0.0.0.0)"
echo "Serving on http://${IP}:${PORT}  (open this from your phone on the same Wi-Fi)"
echo "NOTE: run from a normal terminal — a sandboxed Claude session blocks LAN access."
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
