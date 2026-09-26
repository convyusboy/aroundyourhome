import mongomock
from fastapi.testclient import TestClient

from app import main


def test_index_page_serves_expected_markup(monkeypatch):
    monkeypatch.setattr(main.db, "get_client", lambda uri: mongomock.MongoClient())

    with TestClient(main.app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "id=\"search-form\"" in response.text
    assert "leaflet" in response.text.lower()


def test_app_js_is_served(monkeypatch):
    monkeypatch.setattr(main.db, "get_client", lambda uri: mongomock.MongoClient())

    with TestClient(main.app) as client:
        response = client.get("/app.js")

    assert response.status_code == 200
    assert "/api/places" in response.text
