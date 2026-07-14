import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PEOPLE_DB", str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


@pytest.fixture
def make_person(client):
    def make(name, **kw):
        r = client.post("/api/persons", json={"name": name, **kw})
        assert r.status_code == 201
        return r.json()["id"]
    return make


@pytest.fixture
def make_family(client):
    def make(name, **kw):
        r = client.post("/api/families", json={"name": name, **kw})
        assert r.status_code == 201
        return r.json()["id"]
    return make


@pytest.fixture
def give(client):
    """Assign attribute=value to a person."""
    def _give(pid, attribute, value, **kw):
        r = client.post(f"/api/persons/{pid}/attributes",
                        json={"attribute": attribute, "value": value, **kw})
        assert r.status_code == 201
        return r.json()
    return _give
