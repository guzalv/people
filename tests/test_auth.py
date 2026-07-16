import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import TEST_PASSWORD


def test_no_credentials_rejected(client):
    r = client.get("/api/persons", auth=None)
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"].startswith("Basic")


def test_wrong_password_rejected(client):
    assert client.get("/api/persons", auth=("user", "nope")).status_code == 401


def test_username_is_ignored(client):
    assert client.get("/api/persons", auth=("anything", TEST_PASSWORD)).status_code == 200


def test_garbage_authorization_header_rejected(client):
    r = client.get("/api/persons", auth=None,
                   headers={"Authorization": "Basic not!!base64"})
    assert r.status_code == 401


def test_ui_and_static_also_protected(client):
    assert client.get("/", auth=None).status_code == 401
    assert client.get("/static/app.js", auth=None).status_code == 401


def test_missing_password_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("PEOPLE_DB", str(tmp_path / "test.db"))
    monkeypatch.delenv("PEOPLE_PASSWORD", raising=False)
    monkeypatch.delenv("PEOPLE_AUTH_DISABLED", raising=False)
    with TestClient(app) as c:
        r = c.get("/api/persons")
        assert r.status_code == 503
        assert "PEOPLE_PASSWORD" in r.json()["detail"]


def test_explicit_disable_for_local_dev(tmp_path, monkeypatch):
    monkeypatch.setenv("PEOPLE_DB", str(tmp_path / "test.db"))
    monkeypatch.delenv("PEOPLE_PASSWORD", raising=False)
    monkeypatch.setenv("PEOPLE_AUTH_DISABLED", "1")
    with TestClient(app) as c:
        assert c.get("/api/persons").status_code == 200
