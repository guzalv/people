# People

Personal app to remember what acquaintances like, can't eat, and what's going
on in their lives. Single-user, local, no auth.

## Run

```bash
.venv/bin/uvicorn app.main:app --port 8000
# open http://localhost:8000  (works from a phone on the same network with --host 0.0.0.0)
```

Data lives in `data/people.db` (SQLite). Back up by copying the file or
`curl localhost:8000/api/export > backup.json`.

## Concepts

- **People** and **families**: a family groups people (many-to-many); families
  can be empty; a person can be in several families.
- **Attributes**: free-form `name: value` pairs on people or families
  (e.g. `likes: tomatoes`, `allergy: peanuts`, `hobby: chess`). Both names and
  values autocomplete from everything entered before; typing something new
  creates it. Values match case-insensitively ("Tomatoes" reuses "tomatoes").
- **Polarity** on attribute names drives the meal report: `serve` (likes),
  `avoid` (allergy, dislikes), `diet` (restrictions like "vegetarian" — shown
  as their own report section, not as foods to avoid), or neutral (ignored by
  the report — keep non-food attributes like `hobby` neutral). Seeded: likes,
  dislikes, allergy, diet. New attribute names get a polarity guessed from
  the name ("allergies" → avoid) and show a toast saying so; the toggle on
  any detail page changes it — globally, for everyone using that attribute.
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
.venv/bin/python -m pytest tests/ -q     # backend unit tests

# UI smoke test (jsdom drives the real SPA against a live server):
.venv/bin/uvicorn app.main:app --port 8766 &   # with a scratch PEOPLE_DB
cd tools && npm install && APP_JS=../static/app.js node ui-check.js
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
