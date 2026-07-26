# People

Personal app to remember what acquaintances like, can't eat, and what's going
on in their lives. Single-user, protected by one password.

## Auth

Everything (UI and API) sits behind HTTP Basic auth: any username, the
password from the `PEOPLE_PASSWORD` env var. Without it the server answers
503 to everything (fail closed); `PEOPLE_AUTH_DISABLED=1` turns auth off for
loopback dev (what `scripts/run.sh` and the test scripts do).

**Before exposing to the internet:** Basic auth sends the password with every
request, so it is only safe over HTTPS. Put the app behind something that
terminates TLS — a Cloudflare Tunnel, or caddy/nginx with a certificate —
and use a long random password (`openssl rand -base64 24`). Never
port-forward plain HTTP from the router.

## Run

```bash
scripts/run.sh            # dev server on http://127.0.0.1:8000 (creates .venv on first run)
scripts/serve-lan.sh      # same, on 0.0.0.0:8080, prints the LAN URL for phone access
```

Or drive uvicorn directly: `.venv/bin/uvicorn app.main:app --port 8000`.

Data lives in `data/people.db` (SQLite). Back up with `scripts/backup.sh`
(sqlite3 `.backup` under the hood), by copying the file, or
`curl localhost:8000/api/export > backup.json`.

## Docker

Every push to `main` builds the image and publishes it to
`ghcr.io/guzalv/people:latest` (see `.github/workflows/docker-publish.yml`) —
deployment just pulls it, no build step or checkout needed on the host:

```bash
echo "PEOPLE_PASSWORD=$(openssl rand -base64 24)" > .env   # once; compose reads it
docker compose up -d
# open http://localhost:8080  (and http://<this-machine-ip>:8080 from a phone)
```

The first pull needs the GHCR package set to public (or `docker login ghcr.io`
on the host) — see the package settings on GitHub after the first workflow
run. The SQLite file stays a plain file on the host at `./data/people.db`
(compose bind-mounts `./data` to `/data` in the container), so
`scripts/backup.sh` and plain copies still work. `restart: unless-stopped`
keeps it up across reboots; `pull_policy: always` means a plain
`docker compose up -d` re-pulls and recreates whenever `latest` has moved.

The container fixes ownership of the bind-mounted `./data` on every start
(root briefly, via `docker-entrypoint.sh`, then drops to the non-root
`appuser` to actually run the server) — you don't need to `chown` it
yourself. One side effect of that pattern: `docker exec people sh` opens as
root by default; add `-u appuser` if you want a non-root debug shell.

`docker-compose.yml` is set up for a host that runs several services behind
a shared reverse proxy: no `ports:` mapping, just an explicit `networks:`
attach to the proxy's network (`proxy_default` below — Compose names a
project's default network `<project>_default`, so match whatever your proxy
stack is actually called) so the proxy can reach the container by service
name. A service only joins a network it explicitly lists — declaring
`networks:` at the top level alone does *not* attach anything to it, a
common gotcha. In your proxy config, `proxy_pass` (nginx) / the router
service port (traefik) etc. targets `http://people:8080` — the container's
internal port, not any host-published one.

To expose a host port instead (no reverse proxy), drop the `networks:`
block and add back `ports: ["${PEOPLE_PORT:-8080}:8080"]` — override
`PEOPLE_PORT` in `.env` if 8080 is already taken by a neighbor.

To rebuild locally instead of pulling (e.g. testing an unpushed change),
swap the `image:`/`pull_policy:` lines for `build: .`.

### Auto-updating on the deploy host

To pick up new pushes to `main` without logging in by hand, install the
`systemd/` unit + `scripts/deploy-latest.sh` pair on the deploy host — a
timer that runs `docker compose pull && docker compose up -d
--remove-orphans` every 15 minutes. `up -d` only recreates the container when
the pulled digest actually changed, so idle runs are a fast no-op; no extra
container, no `docker.sock` handed to anything, no CI credentials on the
host (rejected watchtower and a CI→SSH deploy for exactly those reasons — see
`~/ai/current-work/people-tracker.md` for the comparison).

```bash
sudo cp systemd/people-update.* /etc/systemd/system/
sudo sed -i "s#/path/to/sw/people#$(pwd)#" /etc/systemd/system/people-update.service
sudo systemctl enable --now people-update.timer
```

The GHCR package must be public (or the host needs `docker login ghcr.io`)
for the pull to work unattended.

## Concepts

- **People** and **families**: a family groups people (many-to-many); families
  can be empty; a person can be in several families.
- **Food** is a fixed, always-visible section on every person/family page
  with four hardcoded attributes — Likes, Dislikes, Allergies, Diet — and it
  is exactly what the meal report reads. Values autocomplete from everything
  entered before (case-insensitively: "Tomatoes" reuses "tomatoes"); typing
  something new creates it. Diet values ("vegetarian", "no pork") appear in
  the report as restrictions to accommodate, not as foods to avoid. The food
  attributes cannot be deleted.
- **Other attributes**: free-form `name: value` pairs (e.g. `hobby: chess`,
  `birthday: May 12`). Names and values autocomplete-with-create the same
  way. These never affect the meal report.
- **Notes** on an assignment ("only raw, roasted is fine"): tap a chip's text
  to add/edit. Re-picking a value from autocomplete never erases a note.
- **Facts**: dated free-text notes on a person or family.
- **Family page** shows the family plus every member's attributes and recent
  facts in one place.
- **Meal plan** (`#/plan`): tick people and/or families, get an aggregated
  report: what to avoid (with who/why, including family-level diets applied to
  members, and a warning when someone else likes the avoided item) and good
  choices ranked by how many of the guests like them.

## Cleaning up vocabulary typos

Mistyped values/attributes stay in autocomplete forever (unassigning keeps the
vocabulary on purpose). Remove them via the API:

```bash
curl localhost:8000/api/values?attribute=likes   # find the id
curl -X DELETE localhost:8000/api/values/<id>    # removes value + assignments
curl -X DELETE localhost:8000/api/attributes/<id>  # same for an attribute name
```

## Development

```bash
scripts/test.sh          # backend unit tests, plus the UI smoke test if tools/node_modules exists
```

`scripts/test.sh` runs pytest and, when `tools/node_modules` is present, starts
a scratch-DB server on a free port and runs the jsdom UI smoke test against it.
To run the pieces by hand:

```bash
.venv/bin/python -m pytest tests/ -q     # backend unit tests

# UI smoke test (jsdom drives the real SPA against a live server):
.venv/bin/uvicorn app.main:app --port 8766 &   # with a scratch PEOPLE_DB
cd tools && npm install && APP_JS=../static/app.js node ui-check.js
# ui-check.js targets $BASE (default http://127.0.0.1:8766)
```

- `app/db.py` — schema + connection (SQLite, WAL, FKs, cleanup triggers)
- `app/report.py` — food report aggregation
- `app/main.py` — FastAPI JSON API under `/api`, serves `static/` SPA
- `static/` — no-build vanilla JS frontend (hash routing)
- `tools/ui-check.js` — jsdom UI smoke test (needs a fresh/empty DB)

Known accepted trade-offs (personal scale): the family page issues one query
pair per member; every mutation re-renders the whole view (the add-row
remembers the last attribute to keep bulk entry fast); home search filters
client-side while comboboxes filter server-side.
