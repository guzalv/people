# People

Personal app to remember what acquaintances like, can't eat, and what's going
on in their lives. Single-user, local, no auth.

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

For a deployment that doesn't need the `.venv` around — and that serves the LAN
(so a phone can reach it) from a normal terminal:

```bash
docker compose up -d --build
# open http://localhost:8080  (and http://<this-machine-ip>:8080 from a phone)
```

The SQLite file stays a plain file on the host at `./data/people.db` (compose
bind-mounts `./data` to `/data` in the container), so `scripts/backup.sh` and
plain copies still work. `restart: unless-stopped` keeps it up across reboots.

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
