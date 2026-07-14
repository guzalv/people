"""Aggregated food report for a set of people.

Groups every food-relevant attribute value assigned to the selected people
(directly, or via a family they belong to) into:
  - avoid: values coming from 'avoid'-polarity attributes (allergies, dislikes,
    diets). If somebody also *likes* the value, it stays in avoid but the
    conflict is recorded so the cook knows.
  - serve: values from 'like'-polarity attributes not blocked by any avoid,
    ranked by how many of the selected people like them.
"""

import sqlite3
from collections import defaultdict


def food_report(conn: sqlite3.Connection, person_ids: list[int]) -> dict:
    if not person_ids:
        return {"people": [], "avoid": [], "serve": []}

    placeholders = ",".join("?" * len(person_ids))
    people = [
        dict(r)
        for r in conn.execute(
            f"SELECT id, name FROM persons WHERE id IN ({placeholders}) ORDER BY name",
            person_ids,
        )
    ]
    found_ids = [p["id"] for p in people]
    if not found_ids:
        return {"people": [], "avoid": [], "serve": []}
    placeholders = ",".join("?" * len(found_ids))

    # Direct person attributes, plus attributes of every family the person
    # belongs to (a family-level "diet: vegetarian" applies to its members).
    rows = conn.execute(
        f"""
        SELECT p.id AS person_id, p.name AS person_name,
               a.name AS attribute, a.polarity, av.value, NULL AS via_family
        FROM entity_attributes ea
        JOIN persons p ON ea.entity_type = 'person' AND ea.entity_id = p.id
        JOIN attribute_values av ON av.id = ea.attribute_value_id
        JOIN attributes a ON a.id = av.attribute_id
        WHERE p.id IN ({placeholders}) AND a.polarity != 'neutral'
        UNION ALL
        SELECT p.id, p.name, a.name, a.polarity, av.value, f.name
        FROM entity_attributes ea
        JOIN families f ON ea.entity_type = 'family' AND ea.entity_id = f.id
        JOIN family_members fm ON fm.family_id = f.id
        JOIN persons p ON p.id = fm.person_id
        JOIN attribute_values av ON av.id = ea.attribute_value_id
        JOIN attributes a ON a.id = av.attribute_id
        WHERE p.id IN ({placeholders}) AND a.polarity != 'neutral'
        """,
        found_ids * 2,
    ).fetchall()

    # key: lowercased value -> {display, avoid_by, liked_by}
    values: dict[str, dict] = defaultdict(
        lambda: {"display": "", "avoid_by": [], "liked_by": []}
    )
    for r in rows:
        entry = values[r["value"].lower()]
        entry["display"] = entry["display"] or r["value"]
        who = {"person": r["person_name"], "reason": r["attribute"]}
        if r["via_family"]:
            who["via_family"] = r["via_family"]
        bucket = entry["avoid_by"] if r["polarity"] == "avoid" else entry["liked_by"]
        # Same value can arrive twice (e.g. directly and via family); dedup.
        if who not in bucket:
            bucket.append(who)

    avoid, serve = [], []
    for entry in values.values():
        if entry["avoid_by"]:
            avoid.append(
                {
                    "value": entry["display"],
                    "who": entry["avoid_by"],
                    "conflicts": entry["liked_by"],  # people who like it anyway
                }
            )
        elif entry["liked_by"]:
            serve.append(
                {
                    "value": entry["display"],
                    "who": entry["liked_by"],
                    "count": len({w["person"] for w in entry["liked_by"]}),
                }
            )

    avoid.sort(key=lambda e: (-len(e["who"]), e["value"].lower()))
    serve.sort(key=lambda e: (-e["count"], e["value"].lower()))
    return {"people": people, "avoid": avoid, "serve": serve}
