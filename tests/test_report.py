import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PEOPLE_DB", str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


def person(client, name):
    return client.post("/api/persons", json={"name": name}).json()["id"]


def give(client, pid, attribute, value):
    r = client.post(f"/api/persons/{pid}/attributes",
                    json={"attribute": attribute, "value": value})
    assert r.status_code == 201


def report(client, person_ids=(), family_ids=()):
    r = client.post("/api/report/food", json={
        "person_ids": list(person_ids), "family_ids": list(family_ids)})
    assert r.status_code == 200
    return r.json()


def test_empty_selection(client):
    assert report(client) == {"people": [], "avoid": [], "serve": []}


def test_serve_ranked_by_popularity(client):
    a, b = person(client, "A"), person(client, "B")
    give(client, a, "likes", "pasta")
    give(client, b, "likes", "pasta")
    give(client, a, "likes", "cheese")
    rep = report(client, [a, b])
    assert [(s["value"], s["count"]) for s in rep["serve"]] == [("pasta", 2), ("cheese", 1)]
    assert rep["avoid"] == []


def test_avoid_collects_allergies_dislikes_diet(client):
    a, b = person(client, "A"), person(client, "B")
    give(client, a, "allergy", "peanuts")
    give(client, a, "dislikes", "olives")
    give(client, b, "diet", "pork")
    rep = report(client, [a, b])
    avoid = {e["value"]: e["who"][0]["reason"] for e in rep["avoid"]}
    assert avoid == {"peanuts": "allergy", "olives": "dislikes", "pork": "diet"}


def test_conflict_avoid_wins_but_is_flagged(client):
    a, b = person(client, "A"), person(client, "B")
    give(client, a, "likes", "shrimp")
    give(client, b, "allergy", "Shrimp")  # case-insensitive match
    rep = report(client, [a, b])
    assert rep["serve"] == []
    assert len(rep["avoid"]) == 1
    entry = rep["avoid"][0]
    assert entry["who"][0]["person"] == "B"
    assert entry["conflicts"][0]["person"] == "A"


def test_only_selected_people_counted(client):
    a, b = person(client, "A"), person(client, "B")
    give(client, a, "likes", "pasta")
    give(client, b, "allergy", "pasta")
    rep = report(client, [a])  # B not invited: pasta is fine
    assert [s["value"] for s in rep["serve"]] == ["pasta"]
    assert rep["avoid"] == []


def test_family_attributes_apply_to_members(client):
    fid = client.post("/api/families", json={"name": "Smiths"}).json()["id"]
    a = person(client, "A")
    client.put(f"/api/families/{fid}/members/{a}")
    client.post(f"/api/families/{fid}/attributes",
                json={"attribute": "diet", "value": "vegetarian"})
    rep = report(client, [a])
    assert rep["avoid"][0]["value"] == "vegetarian"
    assert rep["avoid"][0]["who"][0]["via_family"] == "Smiths"


def test_family_ids_expand_to_members(client):
    fid = client.post("/api/families", json={"name": "Smiths"}).json()["id"]
    a, b = person(client, "A"), person(client, "B")
    client.put(f"/api/families/{fid}/members/{a}")
    give(client, a, "likes", "pasta")
    give(client, b, "likes", "sushi")  # not in family, not selected
    rep = report(client, family_ids=[fid])
    assert [p["name"] for p in rep["people"]] == ["A"]
    assert [s["value"] for s in rep["serve"]] == ["pasta"]


def test_neutral_attributes_ignored(client):
    a = person(client, "A")
    give(client, a, "hobby", "cooking")
    rep = report(client, [a])
    assert rep["serve"] == [] and rep["avoid"] == []


def test_duplicate_via_family_and_direct_deduped(client):
    fid = client.post("/api/families", json={"name": "Smiths"}).json()["id"]
    a = person(client, "A")
    client.put(f"/api/families/{fid}/members/{a}")
    give(client, a, "likes", "pasta")
    rep = report(client, person_ids=[a], family_ids=[fid])
    assert rep["serve"][0]["count"] == 1
    assert len(rep["serve"][0]["who"]) == 1
