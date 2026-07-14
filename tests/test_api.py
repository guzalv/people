import pytest


# ---------- persons ----------

def test_person_crud(client, make_person):
    pid = make_person("Alice", notes="met at work")
    assert client.get(f"/api/persons/{pid}").json()["name"] == "Alice"

    r = client.put(f"/api/persons/{pid}", json={"name": "Alice B", "notes": ""})
    assert r.status_code == 200
    assert client.get(f"/api/persons/{pid}").json()["name"] == "Alice B"

    assert client.delete(f"/api/persons/{pid}").status_code == 200
    assert client.get(f"/api/persons/{pid}").status_code == 404


def test_person_list_filters_by_name(client, make_person):
    make_person("Alice")
    make_person("Bob")
    names = [p["name"] for p in client.get("/api/persons", params={"q": "ali"}).json()]
    assert names == ["Alice"]


@pytest.mark.parametrize("name", ["", " ", "\t \n"])
def test_person_name_must_not_be_blank(client, name):
    assert client.post("/api/persons", json={"name": name}).status_code == 422


def test_whitespace_only_fact_rejected(client, make_person):
    pid = make_person("Alice")
    assert client.post(f"/api/persons/{pid}/facts",
                       json={"text": "  "}).status_code == 422


def test_like_metacharacters_matched_literally(client, make_person):
    make_person("Mr. 100%")
    make_person("Mr. 100x")
    names = [p["name"] for p in client.get("/api/persons", params={"q": "100%"}).json()]
    assert names == ["Mr. 100%"]
    assert client.get("/api/persons", params={"q": "_"}).json() == []


# ---------- families & membership ----------

def test_family_membership(client, make_person, make_family):
    fid = make_family("Smiths")
    alice = make_person("Alice")
    bob = make_person("Bob")
    for pid in (alice, bob):
        assert client.put(f"/api/families/{fid}/members/{pid}").status_code == 201

    fam = client.get(f"/api/families/{fid}").json()
    assert [m["name"] for m in fam["members"]] == ["Alice", "Bob"]

    # person sees its families; can belong to multiple
    fid2 = make_family("Book club")
    client.put(f"/api/families/{fid2}/members/{alice}")
    families = [f["name"] for f in client.get(f"/api/persons/{alice}").json()["families"]]
    assert sorted(families) == ["Book club", "Smiths"]

    client.delete(f"/api/families/{fid}/members/{bob}")
    fam = client.get(f"/api/families/{fid}").json()
    assert [m["name"] for m in fam["members"]] == ["Alice"]


def test_family_without_members_allowed(client, make_family):
    fid = make_family("Empty nesters")
    assert client.get(f"/api/families/{fid}").json()["members"] == []


def test_deleting_person_removes_membership_and_data(client, make_person, make_family, give):
    fid = make_family("Smiths")
    pid = make_person("Alice")
    client.put(f"/api/families/{fid}/members/{pid}")
    give(pid, "likes", "tomatoes")
    client.post(f"/api/persons/{pid}/facts", json={"text": "starting a new job"})

    client.delete(f"/api/persons/{pid}")
    assert client.get(f"/api/families/{fid}").json()["members"] == []
    # cleanup triggers removed the orphaned rows
    export = client.get("/api/export").json()
    assert export["entity_attributes"] == []
    assert export["facts"] == []


# ---------- attributes & autocomplete ----------

def test_assign_attribute_creates_and_reuses_vocabulary(client, make_person, give):
    x = make_person("X")
    y = make_person("Y")
    give(x, "likes", "tomatoes")

    # editing Y: "tomatoes" is suggested
    sugg = client.get("/api/values", params={"attribute": "likes", "q": "tom"}).json()
    assert [s["value"] for s in sugg] == ["tomatoes"]

    # case-insensitive reuse: no duplicate vocabulary entry
    give(y, "likes", "Tomatoes")
    sugg = client.get("/api/values", params={"attribute": "likes"}).json()
    assert len(sugg) == 1
    assert sugg[0]["uses"] == 2


def test_new_attribute_name_created_on_the_fly(client, make_person, give):
    pid = make_person("Alice")
    res = give(pid, "hobby", "chess")
    assert res["attribute_created"] is True
    names = [a["name"] for a in client.get("/api/attributes", params={"q": "hob"}).json()]
    assert names == ["hobby"]


def test_seeded_attributes_present(client):
    names = {a["name"]: a["polarity"] for a in client.get("/api/attributes").json()}
    assert names["likes"] == "like"
    assert names["allergy"] == "avoid"
    assert names["diet"] == "diet"


@pytest.mark.parametrize("name,expected", [
    ("allergies", "avoid"),      # plural of the seeded name
    ("intolerances", "avoid"),
    ("hates", "avoid"),
    ("food loves", "like"),
    ("dietary restriction", "diet"),
    ("hobby", "neutral"),
])
def test_new_attribute_polarity_guessed_from_name(client, make_person, give, name, expected):
    pid = make_person("Alice")
    res = give(pid, name, "something")
    assert res["attribute_polarity"] == expected


def test_attribute_polarity_can_change(client, make_person, give):
    pid = make_person("Alice")
    give(pid, "craves", "chocolate")
    attr = next(a for a in client.get("/api/attributes").json() if a["name"] == "craves")
    assert attr["polarity"] == "neutral"
    r = client.patch(f"/api/attributes/{attr['id']}", json={"polarity": "like"})
    assert r.status_code == 200


def test_unassign_attribute_keeps_vocabulary(client, make_person, give):
    pid = make_person("Alice")
    give(pid, "likes", "tomatoes")
    ea_id = client.get(f"/api/persons/{pid}").json()["attributes"][0]["id"]
    client.delete(f"/api/entity-attributes/{ea_id}")

    assert client.get(f"/api/persons/{pid}").json()["attributes"] == []
    # vocabulary survives for future autocomplete
    assert [s["value"] for s in
            client.get("/api/values", params={"attribute": "likes"}).json()] == ["tomatoes"]


def test_delete_value_removes_suggestion_and_assignments(client, make_person, give):
    pid = make_person("Alice")
    give(pid, "likes", "tomatos")  # typo
    vid = client.get("/api/values", params={"attribute": "likes"}).json()[0]["id"]
    assert client.delete(f"/api/values/{vid}").status_code == 200
    assert client.get("/api/values", params={"attribute": "likes"}).json() == []
    assert client.get(f"/api/persons/{pid}").json()["attributes"] == []


def test_delete_attribute_cascades(client, make_person, give):
    pid = make_person("Alice")
    give(pid, "alergy", "nuts")  # typo attribute
    aid = next(a["id"] for a in client.get("/api/attributes").json()
               if a["name"] == "alergy")
    assert client.delete(f"/api/attributes/{aid}").status_code == 200
    assert client.get(f"/api/persons/{pid}").json()["attributes"] == []


def test_family_attributes(client, make_family):
    fid = make_family("Smiths")
    client.post(f"/api/families/{fid}/attributes",
                json={"attribute": "diet", "value": "vegetarian"})
    fam = client.get(f"/api/families/{fid}").json()
    assert fam["attributes"][0]["value"] == "vegetarian"


def test_repick_with_empty_note_preserves_existing_note(client, make_person, give):
    pid = make_person("Alice")
    give(pid, "allergy", "nuts", note="only raw, roasted is fine")
    give(pid, "allergy", "nuts")  # re-pick from autocomplete, no note typed
    attrs = client.get(f"/api/persons/{pid}").json()["attributes"]
    assert len(attrs) == 1
    assert attrs[0]["note"] == "only raw, roasted is fine"


def test_note_patch_sets_and_clears(client, make_person, give):
    pid = make_person("Alice")
    give(pid, "likes", "tomatoes")
    ea_id = client.get(f"/api/persons/{pid}").json()["attributes"][0]["id"]

    client.patch(f"/api/entity-attributes/{ea_id}", json={"note": "loves them raw"})
    assert client.get(f"/api/persons/{pid}").json()["attributes"][0]["note"] == "loves them raw"

    client.patch(f"/api/entity-attributes/{ea_id}", json={"note": ""})
    assert client.get(f"/api/persons/{pid}").json()["attributes"][0]["note"] == ""


# ---------- facts ----------

def test_facts_crud(client, make_person):
    pid = make_person("Alice")
    r = client.post(f"/api/persons/{pid}/facts", json={"text": "changing jobs"})
    assert r.status_code == 201
    facts = client.get(f"/api/persons/{pid}").json()["facts"]
    assert [f["text"] for f in facts] == ["changing jobs"]

    client.delete(f"/api/facts/{facts[0]['id']}")
    assert client.get(f"/api/persons/{pid}").json()["facts"] == []


def test_fact_on_family(client, make_family):
    fid = make_family("Smiths")
    client.post(f"/api/families/{fid}/facts", json={"text": "moving to Madrid"})
    assert client.get(f"/api/families/{fid}").json()["facts"][0]["text"] == "moving to Madrid"


def test_fact_on_unknown_kind_rejected(client):
    assert client.post("/api/gadgets/1/facts", json={"text": "x"}).status_code == 422


# ---------- export ----------

def test_export_contains_all_tables(client, make_person):
    make_person("Alice")
    data = client.get("/api/export").json()
    assert {"persons", "families", "attributes", "attribute_values",
            "entity_attributes", "facts", "family_members"} <= set(data)
    assert data["persons"][0]["name"] == "Alice"
