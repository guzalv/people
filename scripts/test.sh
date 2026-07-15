#!/usr/bin/env bash
# test.sh — backend unit tests (pytest), plus the jsdom UI smoke test when node
# and tools/node_modules are present. The UI test runs a scratch-DB server on a
# free port and never touches port 8080.
#
# USAGE: scripts/test.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python
[ -x "$PY" ] || PY=python3

echo "== pytest =="
"$PY" -m pytest tests/ -q

if command -v node >/dev/null 2>&1 && [ -d tools/node_modules ]; then
  echo "== UI smoke test (jsdom) =="
  # Free port picked by the OS — explicitly never 8080.
  PORT="$(node -e 'const s=require("net").createServer();s.listen(0,"127.0.0.1",()=>{const p=s.address().port;s.close(()=>console.log(p));});')"
  DB="/private/tmp/people-uitest-$$.db"
  rm -f "$DB" "$DB-wal" "$DB-shm"

  PEOPLE_DB="$DB" .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT" \
    >/private/tmp/people-uitest-$$.log 2>&1 &
  SRV=$!
  # kill may fail inside a sandbox — tolerate it.
  cleanup() { kill "$SRV" 2>/dev/null || true; rm -f "$DB" "$DB-wal" "$DB-shm"; }
  trap cleanup EXIT

  for _ in $(seq 1 50); do
    curl -sf "http://127.0.0.1:$PORT/" >/dev/null 2>&1 && break
    sleep 0.1
  done

  ( cd tools && BASE="http://127.0.0.1:$PORT" APP_JS=../static/app.js node ui-check.js )
else
  echo "== UI smoke test skipped (node or tools/node_modules missing; run 'cd tools && npm install') =="
fi
