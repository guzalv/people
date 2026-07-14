"""FastAPI app: JSON API under /api, static SPA at /."""

import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints

from . import db as dbmod
from .report import food_report

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _db_path() -> str:
    return os.environ.get("PEOPLE_DB", str(dbmod.DEFAULT_DB_PATH))


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = dbmod.connect(_db_path())
    try:
        dbmod.init_db(conn)
    finally:
        conn.close()
    yield


app = FastAPI(title="People", lifespan=lifespan)


def get_db():
    conn = dbmod.connect(_db_path())
    try:
        yield conn
    finally:
        conn.close()


# ---------- payload models ----------

# Strip before validation so whitespace-only input fails min_length.
NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Stripped = Annotated[str, StringConstraints(strip_whitespace=True)]

POLARITIES = ("like", "avoid", "diet", "neutral")


class EntityIn(BaseModel):
    name: NonEmpty
    notes: Stripped = ""


class FactIn(BaseModel):
    text: NonEmpty


class AttributeAssignIn(BaseModel):
    attribute: NonEmpty  # attribute name, created if new
    value: NonEmpty      # value text, created if new
    note: Stripped = ""


class NoteIn(BaseModel):
    note: Stripped


class PolarityIn(BaseModel):
    polarity: Literal[*POLARITIES]


class ReportIn(BaseModel):
    person_ids: list[int] = []
    family_ids: list[int] = []  # expanded to their members


# ---------- helpers ----------

# 'persons'/'families' as used in URLs -> (entity_type stored in DB, table)
ENTITY_KINDS = {"persons": ("person", "persons"), "families": ("family", "families")}

Kind = Literal["persons", "families"]


def _like(q: str) -> str:
    """Escape LIKE metacharacters; queries must add ESCAPE '\\'."""
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _one(conn, query, args) -> sqlite3.Row:
    row = conn.execute(query, args).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return row


def _exists(conn, kind: Kind, entity_id: int) -> None:
    _one(conn, f"SELECT id FROM {ENTITY_KINDS[kind][1]} WHERE id = ?", (entity_id,))


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


def _create_entity(conn, kind: Kind, body: EntityIn) -> dict:
    cur = conn.execute(
        f"INSERT INTO {ENTITY_KINDS[kind][1]} (name, notes) VALUES (?, ?)",
        (body.name, body.notes),
    )
    conn.commit()
    return {"id": cur.lastrowid}


def _update_entity(conn, kind: Kind, entity_id: int, body: EntityIn) -> dict:
    _exists(conn, kind, entity_id)
    conn.execute(
        f"UPDATE {ENTITY_KINDS[kind][1]} SET name = ?, notes = ? WHERE id = ?",
        (body.name, body.notes, entity_id),
    )
    conn.commit()
    return {"ok": True}


def _delete_entity(conn, kind: Kind, entity_id: int) -> dict:
    # entity_attributes/facts cleanup happens in schema triggers,
    # family_members via FK cascade.
    _exists(conn, kind, entity_id)
    conn.execute(f"DELETE FROM {ENTITY_KINDS[kind][1]} WHERE id = ?", (entity_id,))
    conn.commit()
    return {"ok": True}


def _assign_attribute(conn, kind: Kind, entity_id: int, body: AttributeAssignIn) -> dict:
    _exists(conn, kind, entity_id)
    entity_type = ENTITY_KINDS[kind][0]
    created = (
        conn.execute(
            "INSERT INTO attributes (name, polarity) VALUES (?, ?) "
            "ON CONFLICT (name) DO NOTHING",
            (body.attribute, dbmod.guess_polarity(body.attribute)),
        ).rowcount
        == 1
    )
    attr = conn.execute(
        "SELECT id, polarity FROM attributes WHERE name = ?", (body.attribute,)
    ).fetchone()
    conn.execute(
        "INSERT INTO attribute_values (attribute_id, value) VALUES (?, ?) "
        "ON CONFLICT DO NOTHING",
        (attr["id"], body.value),
    )
    val = conn.execute(
        "SELECT id FROM attribute_values WHERE attribute_id = ? AND value = ? COLLATE NOCASE",
        (attr["id"], body.value),
    ).fetchone()
    # Re-picking an already-assigned value must not wipe an existing note;
    # notes are edited explicitly via PATCH /api/entity-attributes/{id}.
    conn.execute(
        "INSERT INTO entity_attributes (entity_type, entity_id, attribute_value_id, note) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT (entity_type, entity_id, attribute_value_id) DO UPDATE SET "
        "note = CASE WHEN excluded.note != '' THEN excluded.note ELSE note END",
        (entity_type, entity_id, val["id"], body.note),
    )
    conn.commit()
    return {
        "ok": True,
        "attribute_created": created,
        "attribute_polarity": attr["polarity"],
    }


# ---------- persons ----------

@app.get("/api/persons")
def list_persons(q: str = "", conn=Depends(get_db)):
    rows = conn.execute(
        r"""
        SELECT p.id, p.name, p.notes,
               (SELECT group_concat(f.name, ', ') FROM family_members fm
                JOIN families f ON f.id = fm.family_id
                WHERE fm.person_id = p.id) AS families
        FROM persons p
        WHERE p.name LIKE '%' || ? || '%' ESCAPE '\'
        ORDER BY p.name COLLATE NOCASE
        """,
        (_like(q),),
    )
    return [dict(r) for r in rows]


@app.post("/api/persons", status_code=201)
def create_person(body: EntityIn, conn=Depends(get_db)):
    return _create_entity(conn, "persons", body)


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
    return _update_entity(conn, "persons", person_id, body)


@app.delete("/api/persons/{person_id}")
def delete_person(person_id: int, conn=Depends(get_db)):
    return _delete_entity(conn, "persons", person_id)


# ---------- families ----------

@app.get("/api/families")
def list_families(q: str = "", conn=Depends(get_db)):
    rows = conn.execute(
        r"""
        SELECT f.id, f.name, f.notes,
               (SELECT count(*) FROM family_members fm WHERE fm.family_id = f.id)
               AS member_count
        FROM families f
        WHERE f.name LIKE '%' || ? || '%' ESCAPE '\'
        ORDER BY f.name COLLATE NOCASE
        """,
        (_like(q),),
    )
    return [dict(r) for r in rows]


@app.post("/api/families", status_code=201)
def create_family(body: EntityIn, conn=Depends(get_db)):
    return _create_entity(conn, "families", body)


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
    return _update_entity(conn, "families", family_id, body)


@app.delete("/api/families/{family_id}")
def delete_family(family_id: int, conn=Depends(get_db)):
    return _delete_entity(conn, "families", family_id)


@app.put("/api/families/{family_id}/members/{person_id}", status_code=201)
def add_member(family_id: int, person_id: int, conn=Depends(get_db)):
    _exists(conn, "families", family_id)
    _exists(conn, "persons", person_id)
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

@app.post("/api/{kind}/{entity_id}/attributes", status_code=201)
def assign_attribute(kind: Kind, entity_id: int, body: AttributeAssignIn,
                     conn=Depends(get_db)):
    return _assign_attribute(conn, kind, entity_id, body)


@app.delete("/api/entity-attributes/{ea_id}")
def unassign_attribute(ea_id: int, conn=Depends(get_db)):
    _one(conn, "SELECT id FROM entity_attributes WHERE id = ?", (ea_id,))
    conn.execute("DELETE FROM entity_attributes WHERE id = ?", (ea_id,))
    conn.commit()
    return {"ok": True}


@app.patch("/api/entity-attributes/{ea_id}")
def set_attribute_note(ea_id: int, body: NoteIn, conn=Depends(get_db)):
    _one(conn, "SELECT id FROM entity_attributes WHERE id = ?", (ea_id,))
    conn.execute("UPDATE entity_attributes SET note = ? WHERE id = ?",
                 (body.note, ea_id))
    conn.commit()
    return {"ok": True}


# ---------- facts ----------

@app.post("/api/{kind}/{entity_id}/facts", status_code=201)
def add_fact(kind: Kind, entity_id: int, body: FactIn, conn=Depends(get_db)):
    _exists(conn, kind, entity_id)
    cur = conn.execute(
        "INSERT INTO facts (entity_type, entity_id, text) VALUES (?, ?, ?)",
        (ENTITY_KINDS[kind][0], entity_id, body.text),
    )
    conn.commit()
    return {"id": cur.lastrowid}


@app.delete("/api/facts/{fact_id}")
def delete_fact(fact_id: int, conn=Depends(get_db)):
    _one(conn, "SELECT id FROM facts WHERE id = ?", (fact_id,))
    conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
    conn.commit()
    return {"ok": True}


# ---------- attribute vocabulary ----------

@app.get("/api/attributes")
def list_attributes(q: str = "", conn=Depends(get_db)):
    """Attribute names for autocomplete, most-used first."""
    rows = conn.execute(
        r"""
        SELECT a.id, a.name, a.polarity,
               (SELECT count(*) FROM attribute_values av
                JOIN entity_attributes ea ON ea.attribute_value_id = av.id
                WHERE av.attribute_id = a.id) AS uses
        FROM attributes a
        WHERE a.name LIKE '%' || ? || '%' ESCAPE '\'
        ORDER BY uses DESC, a.name COLLATE NOCASE
        """,
        (_like(q),),
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


@app.delete("/api/attributes/{attribute_id}")
def delete_attribute(attribute_id: int, conn=Depends(get_db)):
    """Remove an attribute name (typo cleanup); cascades values + assignments."""
    _one(conn, "SELECT id FROM attributes WHERE id = ?", (attribute_id,))
    conn.execute("DELETE FROM attributes WHERE id = ?", (attribute_id,))
    conn.commit()
    return {"ok": True}


@app.get("/api/values")
def list_values(attribute: str = "", q: str = "", conn=Depends(get_db)):
    """Value suggestions for autocomplete, scoped to an attribute name,
    most-used first — 'tomatoes' entered for X is offered when editing Y."""
    rows = conn.execute(
        r"""
        SELECT av.id, av.value,
               (SELECT count(*) FROM entity_attributes ea
                WHERE ea.attribute_value_id = av.id) AS uses
        FROM attribute_values av
        JOIN attributes a ON a.id = av.attribute_id
        WHERE a.name = ? AND av.value LIKE '%' || ? || '%' ESCAPE '\'
        ORDER BY uses DESC, av.value COLLATE NOCASE
        """,
        (attribute, _like(q)),
    )
    return [dict(r) for r in rows]


@app.delete("/api/values/{value_id}")
def delete_value(value_id: int, conn=Depends(get_db)):
    """Remove a vocabulary value (typo cleanup); cascades assignments."""
    _one(conn, "SELECT id FROM attribute_values WHERE id = ?", (value_id,))
    conn.execute("DELETE FROM attribute_values WHERE id = ?", (value_id,))
    conn.commit()
    return {"ok": True}


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
