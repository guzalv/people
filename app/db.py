"""SQLite storage layer. One connection per request, WAL mode, foreign keys on."""

import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "people.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS persons (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    notes      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS families (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    notes      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS family_members (
    family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    person_id INTEGER NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    PRIMARY KEY (family_id, person_id)
);

-- Attribute *names* (e.g. "likes", "allergy", "hobby"). polarity drives the
-- meal report: 'like' -> serve, 'avoid' -> do not serve, 'diet' -> dietary
-- restriction to accommodate (value names the diet, not a food to avoid),
-- 'neutral' -> ignored.
CREATE TABLE IF NOT EXISTS attributes (
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL UNIQUE COLLATE NOCASE,
    polarity TEXT NOT NULL DEFAULT 'neutral'
             CHECK (polarity IN ('like', 'avoid', 'diet', 'neutral'))
);

-- Attribute *values* (e.g. "tomatoes" under "likes"). Shared vocabulary that
-- powers autocomplete across all persons/families.
CREATE TABLE IF NOT EXISTS attribute_values (
    id           INTEGER PRIMARY KEY,
    attribute_id INTEGER NOT NULL REFERENCES attributes(id) ON DELETE CASCADE,
    value        TEXT NOT NULL,
    UNIQUE (attribute_id, value COLLATE NOCASE)
);

-- Assignment of a value to a person or a family.
CREATE TABLE IF NOT EXISTS entity_attributes (
    id                 INTEGER PRIMARY KEY,
    entity_type        TEXT NOT NULL CHECK (entity_type IN ('person', 'family')),
    entity_id          INTEGER NOT NULL,
    attribute_value_id INTEGER NOT NULL REFERENCES attribute_values(id) ON DELETE CASCADE,
    note               TEXT NOT NULL DEFAULT '',
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (entity_type, entity_id, attribute_value_id)
);

-- Dated free-text facts ("mentioned they're changing jobs").
CREATE TABLE IF NOT EXISTS facts (
    id          INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('person', 'family')),
    entity_id   INTEGER NOT NULL,
    text        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_entity_attributes_entity
    ON entity_attributes (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_facts_entity
    ON facts (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_family_members_person
    ON family_members (person_id);

-- entity_attributes/facts reference persons or families polymorphically, so
-- no FK is possible; triggers keep them consistent on any deletion path.
CREATE TRIGGER IF NOT EXISTS trg_persons_cleanup AFTER DELETE ON persons
BEGIN
    DELETE FROM entity_attributes WHERE entity_type = 'person' AND entity_id = OLD.id;
    DELETE FROM facts WHERE entity_type = 'person' AND entity_id = OLD.id;
END;
CREATE TRIGGER IF NOT EXISTS trg_families_cleanup AFTER DELETE ON families
BEGIN
    DELETE FROM entity_attributes WHERE entity_type = 'family' AND entity_id = OLD.id;
    DELETE FROM facts WHERE entity_type = 'family' AND entity_id = OLD.id;
END;
"""

# The food attributes are a fixed, hardcoded set: always shown in the UI's
# Food section, and the only attributes the meal report reads. Everything the
# user types as a free-form attribute is neutral and never affects reports.
SEED_ATTRIBUTES = [
    ("likes", "like"),
    ("dislikes", "avoid"),
    ("allergy", "avoid"),
    ("diet", "diet"),
]

FOOD_ATTRIBUTE_NAMES = frozenset(name for name, _ in SEED_ATTRIBUTES)


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # FastAPI may run the dependency and the endpoint on different threadpool
    # threads; each connection is still used by one request at a time.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for name, polarity in SEED_ATTRIBUTES:
        conn.execute(
            "INSERT INTO attributes (name, polarity) VALUES (?, ?) "
            "ON CONFLICT (name) DO NOTHING",
            (name, polarity),
        )
    conn.commit()
