from datetime import datetime, timezone

import httpx
import mongomock

from app.config import Settings
from app.db import ensure_indexes, record_coverage, upsert_places
from app.models import NormalizedPlace
from app.services.places_service import search_places


def make_collections():
    client = mongomock.MongoClient()
    collection = client["aroundyourhome"]["places"]
    coverage_collection = client["aroundyourhome"]["search_coverage"]
    ensure_indexes(collection)
    return collection, coverage_collection


def make_settings(api_key=None):
    return Settings(
        mongo_uri="mongodb://unused",
        google_places_api_key=api_key,
        cache_ttl_days=14,
        default_radius_m=1500,
    )


def test_skips_live_fetch_when_coverage_is_fresh():
    collection, coverage_collection = make_collections()
    cached = NormalizedPlace(
        place_id="cached-1", source="osm", name="Cached Pharmacy",
        category="pharmacy", lat=-6.2, lng=106.8,
    )
    now = datetime.now(timezone.utc)
    upsert_places(collection, [cached], fetched_at=now)
    record_coverage(coverage_collection, -6.2, 106.8, 1000, "pharmacy", fetched_at=now)

    def handler(request):
        raise AssertionError("no live HTTP call should be made when coverage is fresh")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    settings = make_settings()

    results, partial = search_places(
        collection, coverage_collection, client, settings, -6.2, 106.8, 1000, ["pharmacy"]
    )

    assert partial is False
    assert len(results) == 1
    assert results[0]["name"] == "Cached Pharmacy"


def test_fetches_from_google_when_api_key_present_and_coverage_is_stale():
    collection, coverage_collection = make_collections()

    def handler(request):
        assert "places.googleapis.com" in str(request.url)
        return httpx.Response(
            200,
            json={
                "places": [{
                    "id": "g-1",
                    "displayName": {"text": "Fresh Hospital"},
                    "location": {"latitude": -6.2, "longitude": 106.8},
                    "types": ["hospital"],
                }],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    settings = make_settings(api_key="fake-key")

    results, partial = search_places(
        collection, coverage_collection, client, settings, -6.2, 106.8, 1000, ["hospital"]
    )

    assert partial is False
    assert len(results) == 1
    assert results[0]["name"] == "Fresh Hospital"
    assert results[0]["source"] == "google"
    assert collection.count_documents({"place_id": "g-1"}) == 1
    assert coverage_collection.count_documents({"category": "hospital"}) == 1


def test_falls_back_to_osm_when_google_fails():
    collection, coverage_collection = make_collections()

    def handler(request):
        if "places.googleapis.com" in str(request.url):
            return httpx.Response(403, json={"error": {"message": "bad key"}})
        return httpx.Response(
            200,
            json={"elements": [{
                "type": "node", "id": 999, "lat": -6.2, "lon": 106.8,
                "tags": {"amenity": "hospital", "name": "OSM Hospital"},
            }]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    settings = make_settings(api_key="bad-key")

    results, partial = search_places(
        collection, coverage_collection, client, settings, -6.2, 106.8, 1000, ["hospital"]
    )

    assert partial is False
    assert len(results) == 1
    assert results[0]["source"] == "osm"
    assert coverage_collection.count_documents({"category": "hospital"}) == 1


def test_marks_partial_when_both_providers_fail():
    collection, coverage_collection = make_collections()

    def handler(request):
        if "places.googleapis.com" in str(request.url):
            return httpx.Response(403, json={"error": {"message": "bad key"}})
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    settings = make_settings(api_key="bad-key")

    results, partial = search_places(
        collection, coverage_collection, client, settings, -6.2, 106.8, 1000, ["hospital"]
    )

    assert partial is True
    assert results == []
    assert coverage_collection.count_documents({}) == 0


def test_zero_google_results_still_records_coverage_no_osm_call():
    collection, coverage_collection = make_collections()

    def handler(request):
        assert "places.googleapis.com" in str(request.url)
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    settings = make_settings(api_key="fake-key")

    results, partial = search_places(
        collection, coverage_collection, client, settings, -6.2, 106.8, 1000, ["park"]
    )

    assert partial is False
    assert results == []
    assert coverage_collection.count_documents({"category": "park"}) == 1


def test_results_sorted_by_distance():
    collection, coverage_collection = make_collections()
    near = NormalizedPlace(
        place_id="near", source="osm", name="Near Park",
        category="park", lat=-6.2001, lng=106.8001,
    )
    far = NormalizedPlace(
        place_id="far", source="osm", name="Far Park",
        category="park", lat=-6.2050, lng=106.8050,
    )
    now = datetime.now(timezone.utc)
    upsert_places(collection, [far, near], fetched_at=now)
    record_coverage(coverage_collection, -6.2, 106.8, 2000, "park", fetched_at=now)

    def handler(request):
        raise AssertionError("coverage is fresh, no live call expected")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    settings = make_settings()

    results, _ = search_places(
        collection, coverage_collection, client, settings, -6.2, 106.8, 2000, ["park"]
    )

    assert [r["name"] for r in results] == ["Near Park", "Far Park"]
