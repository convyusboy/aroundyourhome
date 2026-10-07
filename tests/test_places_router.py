from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models import CATEGORIES
from app.config import Settings
from app.ratelimit import RateLimiter
from app.routers.places import router


def make_app(monkeypatch, search_places_result=([], False)):
    app = FastAPI()
    app.include_router(router)
    app.state.settings = Settings(
        mongo_uri="mongodb://unused",
        google_places_api_key=None,
        cache_ttl_days=14,
        default_radius_m=1500,
    )
    app.state.rate_limiter = RateLimiter(0)
    app.state.collection = object()
    app.state.coverage_collection = object()
    app.state.http_client = object()

    def fake_search_places(
        collection, coverage_collection, http_client, settings, lat, lng, radius_m, categories
    ):
        return search_places_result

    monkeypatch.setattr(
        "app.routers.places.places_service.search_places", fake_search_places
    )
    return app


def test_missing_lat_lng_returns_422(monkeypatch):
    app = make_app(monkeypatch)
    client = TestClient(app)

    response = client.get("/api/places")

    assert response.status_code == 422


def test_out_of_range_radius_returns_400(monkeypatch):
    app = make_app(monkeypatch)
    client = TestClient(app)

    response = client.get("/api/places", params={"lat": -6.2, "lng": 106.8, "radius": 50})

    assert response.status_code == 400


def test_out_of_range_lat_returns_400(monkeypatch):
    app = make_app(monkeypatch)
    client = TestClient(app)

    response = client.get("/api/places", params={"lat": 200, "lng": 106.8})

    assert response.status_code == 400


def test_out_of_range_lng_returns_400(monkeypatch):
    app = make_app(monkeypatch)
    client = TestClient(app)

    response = client.get("/api/places", params={"lat": -6.2, "lng": -200})

    assert response.status_code == 400


def test_unknown_category_returns_400(monkeypatch):
    app = make_app(monkeypatch)
    client = TestClient(app)

    response = client.get(
        "/api/places", params={"lat": -6.2, "lng": 106.8, "categories": "not_a_category"}
    )

    assert response.status_code == 400


def test_defaults_radius_and_categories_when_omitted(monkeypatch):
    captured = {}

    def fake_search_places(
        collection, coverage_collection, http_client, settings, lat, lng, radius_m, categories
    ):
        captured["radius_m"] = radius_m
        captured["categories"] = categories
        return [], False

    app = make_app(monkeypatch)
    monkeypatch.setattr(
        "app.routers.places.places_service.search_places", fake_search_places
    )
    client = TestClient(app)

    response = client.get("/api/places", params={"lat": -6.2, "lng": 106.8})

    assert response.status_code == 200
    assert captured["radius_m"] == 1500
    assert captured["categories"] == CATEGORIES


def test_successful_response_shape(monkeypatch):
    result = [{
        "name": "City Hospital", "category": "hospital", "distance_m": 320,
        "location": {"lat": -6.2, "lng": 106.8}, "phone": None,
        "opening_hours": None, "rating": None, "gojek_link": None, "source": "osm",
    }]
    app = make_app(monkeypatch, search_places_result=(result, True))
    client = TestClient(app)

    response = client.get(
        "/api/places", params={"lat": -6.2, "lng": 106.8, "categories": "hospital"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["partial"] is True
    assert body["query"] == {
        "lat": -6.2, "lng": 106.8, "radius": 1500, "categories": ["hospital"]
    }
    assert body["results"][0]["name"] == "City Hospital"


def test_returns_429_once_rate_limit_is_exceeded(monkeypatch):
    app = make_app(monkeypatch)
    app.state.rate_limiter = RateLimiter(2)
    client = TestClient(app)

    statuses = [client.get("/api/places?lat=-6.2&lng=106.8").status_code for _ in range(3)]

    assert statuses == [200, 200, 429]
