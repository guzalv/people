#!/bin/sh
# Runs as root so it can fix ownership of the bind-mounted /data volume —
# the host directory belongs to whatever uid created it, not the container's
# appuser, so SQLite can't create people.db there without this. Then drops to
# appuser for the real process, same pattern as the official postgres image.
set -e
chown -R appuser:appuser /data
exec gosu appuser "$@"
