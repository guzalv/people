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
  `avoid` (allergy, dislikes, diet), or neutral. Seeded: likes, dislikes,
  allergy, diet. Toggle per attribute on any detail page.
- **Facts**: dated free-text notes on a person or family.
- **Family page** shows the family plus every member's attributes and recent
  facts in one place.
- **Meal plan** (`#/plan`): tick people and/or families, get an aggregated
  report: what to avoid (with who/why, including family-level diets applied to
  members, and a warning when someone else likes the avoided item) and good
  choices ranked by how many of the guests like them.

## Development

```bash
.venv/bin/python -m pytest tests/ -q
```

- `app/db.py` — schema + connection (SQLite, WAL, FKs)
- `app/report.py` — food report aggregation
- `app/main.py` — FastAPI JSON API under `/api`, serves `static/` SPA
- `static/` — no-build vanilla JS frontend (hash routing)
