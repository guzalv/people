#!/usr/bin/env bash
# deploy-latest.sh — pull the ghcr.io image and recreate the container only if
# it changed. Safe to run often: `compose up -d` no-ops when the digest didn't
# move, so this is meant to be driven by a periodic timer (see
# systemd/people-update.timer) rather than run once by hand.
#
# USAGE: scripts/deploy-latest.sh
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose pull people
docker compose up -d --remove-orphans
