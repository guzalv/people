#!/usr/bin/env bash
# backup.sh [dest] — back up data/people.db to dest. Default dest is
# ./backups/people-YYYYMMDD-HHMMSS.db. Uses sqlite3 .backup when available
# (consistent even against a live server, folding WAL into one file); otherwise
# plain cp, copying -wal/-shm too if present.
#
# USAGE: scripts/backup.sh [dest]
set -euo pipefail
cd "$(dirname "$0")/.."

SRC=data/people.db
[ -f "$SRC" ] || { echo "No database at $SRC" >&2; exit 1; }

DEST="${1:-./backups/people-$(date +%Y%m%d-%H%M%S).db}"
mkdir -p "$(dirname "$DEST")"

if command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "$SRC" ".backup '$DEST'"
else
  cp "$SRC" "$DEST"
  for ext in wal shm; do
    [ -f "$SRC-$ext" ] && cp "$SRC-$ext" "$DEST-$ext" || true
  done
fi

echo "Backed up to $DEST"
