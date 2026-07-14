import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PEOPLE_DB", str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


def make_person(client, name, **kw):
    r = client.post("/api/persons", json={"name": name, **kw})
    assert r.status_code == 201
    return r.json()["id"]


def make_family(client, name, **kw):
    r = client.post("/api/families", json={"name": name, **kw})
    assert r.status_code == 201
    return r.json()["id"]


# ---------- persons ----------

def test_person_crud(client):
    pid = make_person(client, "Alice", notes="met at work")
    assert client.get(f"/api/persons/{pid}").json()["name"] == "Alice"

    r = client.put(f"/api/persons/{pid}", json={"name": "Alice B", "notes": ""})
    assert r.status_code == 200
    assert client.get(f"/api/persons/{pid}").json()["name"] == "Alice B"

    assert client.delete(f"/api/persons/{pid}").status_code == 200
    assert client.get(f"/api/persons/{pid}").status_code == 404


def test_person_list_filters_by_name(client):
    make_person(client, "Alice")
    make_person(client, "Bob")
    names = [p["name"] for p in client.get("/api/persons", params={"q": "ali"}).json()]
    assert names == ["Alice"]


def test_person_name_required(client):
    assert client.post("/api/persons", json={"name": ""}).status_code == 422


# ---------- families & membership ----------

def test_family_membership(client):
    fid = make_family(client, "Smiths")
    alice = make_person(client, "Alice")
    bob = make_person(client, "Bob")
    for pid in (alice, bob):
        assert client.put(f"/api/families/{fid}/members/{pid}").status_code == 201

    fam = client.get(f"/api/families/{fid}").json()
    assert [m["name"] for m in fam["members"]] == ["Alice", "Bob"]

    # person sees its families; can belong to multiple
    fid2 = make_family(client, "Book club")
    client.put(f"/api/families/{fid2}/members/{alice}")
    families = [f["name"] for f in client.get(f"/api/persons/{alice}").json()["families"]]
    assert sorted(families) == ["Book club", "Smiths"]

    client.delete(f"/api/families/{fid}/members/{bob}")
    fam = client.get(f"/api/families/{fid}").json()
    assert [m["name"] for m in fam["members"]] == ["Alice"]


def test_family_without_members_allowed(client):
    fid = make_family(client, "Empty nesters")
    assert client.get(f"/api/families/{fid}").json()["members"] == []


def test_deleting_person_removes_membership_and_data(client):
    fid = make_family(client, "Smiths")
    pid = make_person(client, "Alice")
    client.put(f"/api/families/{fid}/members/{pid}")
    client.post(f"/api/persons/{pid}/attributes",
                json={"attribute": "likes", "value": "tomatoes"})
    client.post(f"/api/persons/{pid}/facts", json={"text": "starting a new job"})

    client.delete(f"/api/persons/{pid}")
    assert client.get(f"/api/families/{fid}").json()["members"] == []


# ---------- attributes & autocomplete ----------

def test_assign_attribute_creates_and_reuses_vocabulary(client):
    x = make_person(client, "X")
    y = make_person(client, "Y")
    r = client.post(f"/api/persons/{x}/attributes",
                    json={"attribute": "likes", "value": "tomatoes"})
    assert r.status_code == 201

    # editing Y: "tomatoes" is suggested
    sugg = client.get("/api/values", params={"attribute": "likes", "q": "tom"}).json()
    assert [s["value"] for s in sugg] == ["tomatoes"]

    # case-insensitive reuse: no duplicate vocabulary entry
    client.post(f"/api/persons/{y}/attributes",
                json={"attribute": "likes", "value": "Tomatoes"})
    sugg = client.get("/api/values", params={"attribute": "likes"}).json()
    assert len(sugg) == 1
    assert sugg[0]["uses"] == 2


def test_new_attribute_name_created_on_the_fly(client):
    pid = make_person(client, "Alice")
    client.post(f"/api/persons/{pid}/attributes",
                json={"attribute": "hobby", "value": "chess"})
    names = [a["name"] for a in client.get("/api/attributes", params={"q": "hob"}).json()]
    assert names == ["hobby"]


def test_seeded_attributes_present(client):
    names = {a["name"]: a["polarity"] for a in client.get("/api/attributes").json()}
    assert names["likes"] == "like"
    assert names["allergy"] == "avoid"


def test_attribute_polarity_can_change(client):
    pid = make_person(client, "Alice")
    client.post(f"/api/persons/{pid}/attributes",
                json={"attribute": "craves", "value": "chocolate"})
    attr = next(a for a in client.get("/api/attributes").json() if a["name"] == "craves")
    assert attr["polarity"] == "neutral"
    r = client.patch(f"/api/attributes/{attr['id']}", json={"polarity": "like"})
    assert r.status_code == 200


def test_unassign_attribute_keeps_vocabulary(client):
    pid = make_person(client, "Alice")
    client.post(f"/api/persons/{pid}/attributes",
                json={"attribute": "likes", "value": "tomatoes"})
    ea_id = client.get(f"/api/persons/{pid}").json()["attributes"][0]["id"]
    client.delete(f"/api/entity-attributes/{ea_id}")

    assert client.get(f"/api/persons/{pid}").json()["attributes"] == []
    # vocabulary survives for future autocomplete
    assert [s["value"] for s in
            client.get("/api/values", params={"attribute": "likes"}).json()] == ["tomatoes"]


def test_family_attributes(client):
    fid = make_family(client, "Smiths")
    client.post(f"/api/families/{fid}/attributes",
                json={"attribute": "diet", "value": "vegetarian"})
    fam = client.get(f"/api/families/{fid}").json()
    assert fam["attributes"][0]["value"] == "vegetarian"


def test_reassign_same_value_updates_note_no_duplicate(client):
    pid = make_person(client, "Alice")
    for note in ("", "loves them raw"):
        client.post(f"/api/persons/{pid}/attributes",
                    json={"attribute": "likes", "value": "tomatoes", "note": note})
    attrs = client.get(f"/api/persons/{pid}").json()["attributes"]
    assert len(attrs) == 1
    assert attrs[0]["note"] == "loves them raw"


# ---------- facts ----------

def test_facts_crud(client):
    pid = make_person(client, "Alice")
    r = client.post(f"/api/persons/{pid}/facts", json={"text": "changing jobs"})
    assert r.status_code == 201
    facts = client.get(f"/api/persons/{pid}").json()["facts"]
    assert [f["text"] for f in facts] == ["changing jobs"]

    client.delete(f"/api/facts/{facts[0]['id']}")
    assert client.get(f"/api/persons/{pid}").json()["facts"] == []


def test_fact_on_family(client):
    fid = make_family(client, "Smiths")
    client.post(f"/api/families/{fid}/facts", json={"text": "moving to Madrid"})
    assert client.get(f"/api/families/{fid}").json()["facts"][0]["text"] == "moving to Madrid"


# ---------- export ----------

def test_export_contains_all_tables(client):
    make_person(client, "Alice")
    data = client.get("/api/export").json()
    assert {"persons", "families", "attributes", "attribute_values",
            "entity_attributes", "facts", "family_members"} <= set(data)
    assert data["persons"][0]["name"] == "Alice"
