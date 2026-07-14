def report(client, person_ids=(), family_ids=()):
    r = client.post("/api/report/food", json={
        "person_ids": list(person_ids), "family_ids": list(family_ids)})
    assert r.status_code == 200
    return r.json()


def test_empty_selection(client):
    assert report(client) == {"people": [], "avoid": [], "serve": [], "diets": []}


def test_serve_ranked_by_popularity(client, make_person, give):
    a, b = make_person("A"), make_person("B")
    give(a, "likes", "pasta")
    give(b, "likes", "pasta")
    give(a, "likes", "cheese")
    rep = report(client, [a, b])
    assert [(s["value"], s["count"]) for s in rep["serve"]] == [("pasta", 2), ("cheese", 1)]
    assert rep["avoid"] == []


def test_avoid_collects_allergies_and_dislikes(client, make_person, give):
    a, b = make_person("A"), make_person("B")
    give(a, "allergy", "peanuts")
    give(a, "dislikes", "olives")
    give(b, "dislikes", "cilantro")
    rep = report(client, [a, b])
    avoid = {e["value"]: e["who"][0]["reason"] for e in rep["avoid"]}
    assert avoid == {"peanuts": "allergy", "olives": "dislikes", "cilantro": "dislikes"}


def test_diet_is_a_restriction_not_a_food_to_avoid(client, make_person, give):
    a = make_person("A")
    give(a, "diet", "vegetarian")
    rep = report(client, [a])
    assert rep["avoid"] == []  # "avoid vegetarian" would be nonsense
    assert [d["value"] for d in rep["diets"]] == ["vegetarian"]
    assert rep["diets"][0]["who"][0] == {"person": "A", "reason": "diet"}


def test_conflict_avoid_wins_but_is_flagged(client, make_person, give):
    a, b = make_person("A"), make_person("B")
    give(a, "likes", "shrimp")
    give(b, "allergy", "Shrimp")  # case-insensitive match
    rep = report(client, [a, b])
    assert rep["serve"] == []
    assert len(rep["avoid"]) == 1
    entry = rep["avoid"][0]
    assert entry["who"][0]["person"] == "B"
    assert entry["conflicts"][0]["person"] == "A"


def test_only_selected_people_counted(client, make_person, give):
    a, b = make_person("A"), make_person("B")
    give(a, "likes", "pasta")
    give(b, "allergy", "pasta")
    rep = report(client, [a])  # B not invited: pasta is fine
    assert [s["value"] for s in rep["serve"]] == ["pasta"]
    assert rep["avoid"] == []


def test_family_attributes_apply_to_members(client, make_person, make_family):
    fid = make_family("Smiths")
    a = make_person("A")
    client.put(f"/api/families/{fid}/members/{a}")
    client.post(f"/api/families/{fid}/attributes",
                json={"attribute": "dislikes", "value": "olives"})
    rep = report(client, [a])
    assert rep["avoid"][0]["value"] == "olives"
    assert rep["avoid"][0]["who"][0]["via_family"] == "Smiths"


def test_family_diet_applies_to_members(client, make_person, make_family):
    fid = make_family("Smiths")
    a = make_person("A")
    client.put(f"/api/families/{fid}/members/{a}")
    client.post(f"/api/families/{fid}/attributes",
                json={"attribute": "diet", "value": "halal"})
    rep = report(client, [a])
    assert rep["diets"][0]["value"] == "halal"
    assert rep["diets"][0]["who"][0]["via_family"] == "Smiths"


def test_family_ids_expand_to_members(client, make_person, make_family, give):
    fid = make_family("Smiths")
    a, b = make_person("A"), make_person("B")
    client.put(f"/api/families/{fid}/members/{a}")
    give(a, "likes", "pasta")
    give(b, "likes", "sushi")  # not in family, not selected
    rep = report(client, family_ids=[fid])
    assert [p["name"] for p in rep["people"]] == ["A"]
    assert [s["value"] for s in rep["serve"]] == ["pasta"]


def test_neutral_attributes_ignored(client, make_person, give):
    a = make_person("A")
    give(a, "hobby", "cooking")
    rep = report(client, [a])
    assert rep["serve"] == [] and rep["avoid"] == [] and rep["diets"] == []


def test_guessed_avoid_polarity_reaches_report(client, make_person, give):
    """A brand-new attribute named like an allergy must not vanish from the
    report just because it isn't one of the seeded names."""
    a = make_person("A")
    give(a, "allergies", "shellfish")  # plural — not the seeded "allergy"
    rep = report(client, [a])
    assert [e["value"] for e in rep["avoid"]] == ["shellfish"]


def test_duplicate_via_family_and_direct_deduped(client, make_person, make_family, give):
    fid = make_family("Smiths")
    a = make_person("A")
    client.put(f"/api/families/{fid}/members/{a}")
    give(a, "likes", "pasta")
    rep = report(client, person_ids=[a], family_ids=[fid])
    assert rep["serve"][0]["count"] == 1
    assert len(rep["serve"][0]["who"]) == 1
