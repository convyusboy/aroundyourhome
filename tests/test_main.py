import mongomock
from fastapi.testclient import TestClient

from app import main


def test_health_endpoint_reports_ok(monkeypatch):
    monkeypatch.setattr(main.db, "get_client", lambda uri: mongomock.MongoClient())

    with TestClient(main.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "mongo": True}


def test_places_route_is_registered(monkeypatch):
    monkeypatch.setattr(main.db, "get_client", lambda uri: mongomock.MongoClient())

    with TestClient(main.app) as client:
        response = client.get("/api/places")  # missing required lat/lng

    assert response.status_code == 422


def test_shared_http_client_sends_identifying_user_agent(monkeypatch):
    monkeypatch.setattr(main.db, "get_client", lambda uri: mongomock.MongoClient())

    with TestClient(main.app):
        ua = main.app.state.http_client.headers["User-Agent"]

    assert ua.startswith("aroundyourhome/")
