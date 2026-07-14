"""FastAPI app: JSON API under /api, static SPA at /."""

import os
import sqlite3
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db as dbmod
from .report import food_report

app = FastAPI(title="People")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def get_db():
    conn = dbmod.connect(os.environ.get("PEOPLE_DB", dbmod.DEFAULT_DB_PATH))
    try:
        dbmod.init_db(conn)
        yield conn
    finally:
        conn.close()


# ---------- payload models ----------

class EntityIn(BaseModel):
    name: str = Field(min_length=1)
    notes: str = ""


class FactIn(BaseModel):
    text: str = Field(min_length=1)


class AttributeAssignIn(BaseModel):
    attribute: str = Field(min_length=1)   # attribute name, created if new
    value: str = Field(min_length=1)       # value text, created if new
    note: str = ""


class PolarityIn(BaseModel):
    polarity: str = Field(pattern="^(like|avoid|neutral)$")


class ReportIn(BaseModel):
    person_ids: list[int] = []
    family_ids: list[int] = []  # expanded to their members


# ---------- helpers ----------

def _one(conn, query, args) -> sqlite3.Row:
    row = conn.execute(query, args).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return row


def _entity_detail(conn, entity_type: str, entity_id: int) -> dict:
    """Attributes + facts shared by person and family detail endpoints."""
    attrs = [
        dict(r)
        for r in conn.execute(
            """
            SELECT ea.id, a.id AS attribute_id, a.name AS attribute, a.polarity,
                   av.value, ea.note
            FROM entity_attributes ea
            JOIN attribute_values av ON av.id = ea.attribute_value_id
            JOIN attributes a ON a.id = av.attribute_id
            WHERE ea.entity_type = ? AND ea.entity_id = ?
            ORDER BY a.name, av.value COLLATE NOCASE
            """,
            (entity_type, entity_id),
        )
    ]
    facts = [
        dict(r)
        for r in conn.execute(
            "SELECT id, text, created_at FROM facts "
            "WHERE entity_type = ? AND entity_id = ? ORDER BY created_at DESC, id DESC",
            (entity_type, entity_id),
        )
    ]
    return {"attributes": attrs, "facts": facts}


def _assign_attribute(conn, entity_type: str, entity_id: int, body: AttributeAssignIn):
    attribute = body.attribute.strip()
    value = body.value.strip()
    if not attribute or not value:
        raise HTTPException(status_code=422, detail="empty attribute or value")
    conn.execute(
        "INSERT INTO attributes (name) VALUES (?) ON CONFLICT (name) DO NOTHING",
        (attribute,),
    )
    attr = conn.execute(
        "SELECT id FROM attributes WHERE name = ?", (attribute,)
    ).fetchone()
    conn.execute(
        "INSERT INTO attribute_values (attribute_id, value) VALUES (?, ?) "
        "ON CONFLICT DO NOTHING",
        (attr["id"], value),
    )
    val = conn.execute(
        "SELECT id FROM attribute_values WHERE attribute_id = ? AND value = ? COLLATE NOCASE",
        (attr["id"], value),
    ).fetchone()
    conn.execute(
        "INSERT INTO entity_attributes (entity_type, entity_id, attribute_value_id, note) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT (entity_type, entity_id, attribute_value_id) DO UPDATE SET note = excluded.note",
        (entity_type, entity_id, val["id"], body.note.strip()),
    )
    conn.commit()
    return {"ok": True}


# ---------- persons ----------

@app.get("/api/persons")
def list_persons(q: str = "", conn=Depends(get_db)):
    rows = conn.execute(
        """
        SELECT p.id, p.name, p.notes,
               (SELECT group_concat(f.name, ', ') FROM family_members fm
                JOIN families f ON f.id = fm.family_id
                WHERE fm.person_id = p.id) AS families
        FROM persons p
        WHERE p.name LIKE '%' || ? || '%'
        ORDER BY p.name COLLATE NOCASE
        """,
        (q,),
    )
    return [dict(r) for r in rows]


@app.post("/api/persons", status_code=201)
def create_person(body: EntityIn, conn=Depends(get_db)):
    cur = conn.execute(
        "INSERT INTO persons (name, notes) VALUES (?, ?)",
        (body.name.strip(), body.notes.strip()),
    )
    conn.commit()
    return {"id": cur.lastrowid}


@app.get("/api/persons/{person_id}")
def get_person(person_id: int, conn=Depends(get_db)):
    person = dict(_one(conn, "SELECT * FROM persons WHERE id = ?", (person_id,)))
    person["families"] = [
        dict(r)
        for r in conn.execute(
            "SELECT f.id, f.name FROM families f "
            "JOIN family_members fm ON fm.family_id = f.id "
            "WHERE fm.person_id = ? ORDER BY f.name COLLATE NOCASE",
            (person_id,),
        )
    ]
    person.update(_entity_detail(conn, "person", person_id))
    return person


@app.put("/api/persons/{person_id}")
def update_person(person_id: int, body: EntityIn, conn=Depends(get_db)):
    _one(conn, "SELECT id FROM persons WHERE id = ?", (person_id,))
    conn.execute(
        "UPDATE persons SET name = ?, notes = ? WHERE id = ?",
        (body.name.strip(), body.notes.strip(), person_id),
    )
    conn.commit()
    return {"ok": True}


@app.delete("/api/persons/{person_id}")
def delete_person(person_id: int, conn=Depends(get_db)):
    _one(conn, "SELECT id FROM persons WHERE id = ?", (person_id,))
    conn.execute(
        "DELETE FROM entity_attributes WHERE entity_type = 'person' AND entity_id = ?",
        (person_id,),
    )
    conn.execute(
        "DELETE FROM facts WHERE entity_type = 'person' AND entity_id = ?", (person_id,)
    )
    conn.execute("DELETE FROM persons WHERE id = ?", (person_id,))
    conn.commit()
    return {"ok": True}


# ---------- families ----------

@app.get("/api/families")
def list_families(q: str = "", conn=Depends(get_db)):
    rows = conn.execute(
        """
        SELECT f.id, f.name, f.notes,
               (SELECT count(*) FROM family_members fm WHERE fm.family_id = f.id)
               AS member_count
        FROM families f
        WHERE f.name LIKE '%' || ? || '%'
        ORDER BY f.name COLLATE NOCASE
        """,
        (q,),
    )
    return [dict(r) for r in rows]


@app.post("/api/families", status_code=201)
def create_family(body: EntityIn, conn=Depends(get_db)):
    cur = conn.execute(
        "INSERT INTO families (name, notes) VALUES (?, ?)",
        (body.name.strip(), body.notes.strip()),
    )
    conn.commit()
    return {"id": cur.lastrowid}


@app.get("/api/families/{family_id}")
def get_family(family_id: int, conn=Depends(get_db)):
    """Family single-page view: family attrs/facts + every member's detail."""
    family = dict(_one(conn, "SELECT * FROM families WHERE id = ?", (family_id,)))
    family.update(_entity_detail(conn, "family", family_id))
    members = []
    for r in conn.execute(
        "SELECT p.id, p.name, p.notes FROM persons p "
        "JOIN family_members fm ON fm.person_id = p.id "
        "WHERE fm.family_id = ? ORDER BY p.name COLLATE NOCASE",
        (family_id,),
    ):
        member = dict(r)
        member.update(_entity_detail(conn, "person", member["id"]))
        members.append(member)
    family["members"] = members
    return family


@app.put("/api/families/{family_id}")
def update_family(family_id: int, body: EntityIn, conn=Depends(get_db)):
    _one(conn, "SELECT id FROM families WHERE id = ?", (family_id,))
    conn.execute(
        "UPDATE families SET name = ?, notes = ? WHERE id = ?",
        (body.name.strip(), body.notes.strip(), family_id),
    )
    conn.commit()
    return {"ok": True}


@app.delete("/api/families/{family_id}")
def delete_family(family_id: int, conn=Depends(get_db)):
    _one(conn, "SELECT id FROM families WHERE id = ?", (family_id,))
    conn.execute(
        "DELETE FROM entity_attributes WHERE entity_type = 'family' AND entity_id = ?",
        (family_id,),
    )
    conn.execute(
        "DELETE FROM facts WHERE entity_type = 'family' AND entity_id = ?", (family_id,)
    )
    conn.execute("DELETE FROM families WHERE id = ?", (family_id,))
    conn.commit()
    return {"ok": True}


@app.put("/api/families/{family_id}/members/{person_id}", status_code=201)
def add_member(family_id: int, person_id: int, conn=Depends(get_db)):
    _one(conn, "SELECT id FROM families WHERE id = ?", (family_id,))
    _one(conn, "SELECT id FROM persons WHERE id = ?", (person_id,))
    conn.execute(
        "INSERT INTO family_members (family_id, person_id) VALUES (?, ?) "
        "ON CONFLICT DO NOTHING",
        (family_id, person_id),
    )
    conn.commit()
    return {"ok": True}


@app.delete("/api/families/{family_id}/members/{person_id}")
def remove_member(family_id: int, person_id: int, conn=Depends(get_db)):
    conn.execute(
        "DELETE FROM family_members WHERE family_id = ? AND person_id = ?",
        (family_id, person_id),
    )
    conn.commit()
    return {"ok": True}


# ---------- attributes on entities ----------

@app.post("/api/persons/{person_id}/attributes", status_code=201)
def assign_person_attribute(person_id: int, body: AttributeAssignIn, conn=Depends(get_db)):
    _one(conn, "SELECT id FROM persons WHERE id = ?", (person_id,))
    return _assign_attribute(conn, "person", person_id, body)


@app.post("/api/families/{family_id}/attributes", status_code=201)
def assign_family_attribute(family_id: int, body: AttributeAssignIn, conn=Depends(get_db)):
    _one(conn, "SELECT id FROM families WHERE id = ?", (family_id,))
    return _assign_attribute(conn, "family", family_id, body)


@app.delete("/api/entity-attributes/{ea_id}")
def unassign_attribute(ea_id: int, conn=Depends(get_db)):
    _one(conn, "SELECT id FROM entity_attributes WHERE id = ?", (ea_id,))
    conn.execute("DELETE FROM entity_attributes WHERE id = ?", (ea_id,))
    conn.commit()
    return {"ok": True}


# ---------- facts ----------

@app.post("/api/{entity_type}/{entity_id}/facts", status_code=201)
def add_fact(entity_type: str, entity_id: int, body: FactIn, conn=Depends(get_db)):
    table = {"persons": ("person", "persons"), "families": ("family", "families")}.get(
        entity_type
    )
    if table is None:
        raise HTTPException(status_code=404, detail="not found")
    _one(conn, f"SELECT id FROM {table[1]} WHERE id = ?", (entity_id,))
    cur = conn.execute(
        "INSERT INTO facts (entity_type, entity_id, text) VALUES (?, ?, ?)",
        (table[0], entity_id, body.text.strip()),
    )
    conn.commit()
    return {"id": cur.lastrowid}


@app.delete("/api/facts/{fact_id}")
def delete_fact(fact_id: int, conn=Depends(get_db)):
    _one(conn, "SELECT id FROM facts WHERE id = ?", (fact_id,))
    conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
    conn.commit()
    return {"ok": True}


# ---------- autocomplete ----------

@app.get("/api/attributes")
def list_attributes(q: str = "", conn=Depends(get_db)):
    """Attribute names for autocomplete, most-used first."""
    rows = conn.execute(
        """
        SELECT a.id, a.name, a.polarity,
               (SELECT count(*) FROM attribute_values av
                JOIN entity_attributes ea ON ea.attribute_value_id = av.id
                WHERE av.attribute_id = a.id) AS uses
        FROM attributes a
        WHERE a.name LIKE '%' || ? || '%'
        ORDER BY uses DESC, a.name COLLATE NOCASE
        """,
        (q,),
    )
    return [dict(r) for r in rows]


@app.patch("/api/attributes/{attribute_id}")
def set_attribute_polarity(attribute_id: int, body: PolarityIn, conn=Depends(get_db)):
    _one(conn, "SELECT id FROM attributes WHERE id = ?", (attribute_id,))
    conn.execute(
        "UPDATE attributes SET polarity = ? WHERE id = ?",
        (body.polarity, attribute_id),
    )
    conn.commit()
    return {"ok": True}


@app.get("/api/values")
def list_values(attribute: str = "", q: str = "", conn=Depends(get_db)):
    """Value suggestions for autocomplete, scoped to an attribute name,
    most-used first — 'tomatoes' entered for X is offered when editing Y."""
    rows = conn.execute(
        """
        SELECT av.id, av.value,
               (SELECT count(*) FROM entity_attributes ea
                WHERE ea.attribute_value_id = av.id) AS uses
        FROM attribute_values av
        JOIN attributes a ON a.id = av.attribute_id
        WHERE a.name = ? AND av.value LIKE '%' || ? || '%'
        ORDER BY uses DESC, av.value COLLATE NOCASE
        """,
        (attribute, q),
    )
    return [dict(r) for r in rows]


# ---------- report ----------

@app.post("/api/report/food")
def report_food(body: ReportIn, conn=Depends(get_db)):
    ids = set(body.person_ids)
    if body.family_ids:
        placeholders = ",".join("?" * len(body.family_ids))
        ids.update(
            r["person_id"]
            for r in conn.execute(
                f"SELECT person_id FROM family_members WHERE family_id IN ({placeholders})",
                body.family_ids,
            )
        )
    return food_report(conn, sorted(ids))


# ---------- export (backup) ----------

@app.get("/api/export")
def export_all(conn=Depends(get_db)):
    tables = [
        "persons", "families", "family_members",
        "attributes", "attribute_values", "entity_attributes", "facts",
    ]
    return {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t}")] for t in tables}


# ---------- static frontend ----------

@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
