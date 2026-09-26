import httpx

from app.providers.google_places import GooglePlacesError, fetch_places


def make_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_places_batches_categories_into_one_request():
    captured = {}

    def handler(request):
        captured["headers"] = request.headers
        captured["body"] = request.content.decode()
        return httpx.Response(
            200,
            json={
                "places": [{
                    "id": "abc123",
                    "displayName": {"text": "City Hospital"},
                    "location": {"latitude": -6.2, "longitude": 106.8},
                    "types": ["hospital"],
                    "rating": 4.2,
                    "nationalPhoneNumber": "+62 21 555 0000",
                    "regularOpeningHours": {
                        "weekdayDescriptions": ["Monday: Open 24 hours"]
                    },
                }],
            },
        )

    client = make_client(handler)
    results = fetch_places(
        client, api_key="fake-key", lat=-6.2, lng=106.8, radius_m=1000,
        categories=["hospital", "pharmacy"],
    )

    assert captured["headers"]["X-Goog-Api-Key"] == "fake-key"
    assert "hospital" in captured["body"] and "pharmacy" in captured["body"]
    assert set(results.keys()) == {"hospital", "pharmacy"}
    assert results["pharmacy"] == []
    assert len(results["hospital"]) == 1

    place = results["hospital"][0]
    assert place.place_id == "abc123"
    assert place.source == "google"
    assert place.name == "City Hospital"
    assert place.category == "hospital"
    assert place.lat == -6.2
    assert place.lng == 106.8
    assert place.rating == 4.2
    assert place.opening_hours == "Monday: Open 24 hours"
    assert place.phone == "+62 21 555 0000"


def test_fetch_places_no_places_key_returns_empty_lists_for_every_category():
    def handler(request):
        return httpx.Response(200, json={})

    client = make_client(handler)
    results = fetch_places(
        client, api_key="fake-key", lat=-6.2, lng=106.8, radius_m=1000,
        categories=["park", "gym"],
    )

    assert results == {"park": [], "gym": []}


def test_fetch_places_raises_on_non_200_status():
    def handler(request):
        return httpx.Response(403, json={"error": {"message": "bad key"}})

    client = make_client(handler)
    try:
        fetch_places(
            client, api_key="bad-key", lat=-6.2, lng=106.8, radius_m=1000,
            categories=["park"],
        )
        assert False, "expected GooglePlacesError"
    except GooglePlacesError:
        pass


def test_fetch_places_raises_google_places_error_on_network_failure():
    # A connection-level failure (DNS, timeout, TLS handshake, ...) must be
    # wrapped as GooglePlacesError so callers can catch one exception type,
    # instead of an unhandled httpx.TransportError crashing the request.
    def handler(request):
        raise httpx.ConnectTimeout("connect timed out")

    client = make_client(handler)
    try:
        fetch_places(
            client, api_key="fake-key", lat=-6.2, lng=106.8, radius_m=1000,
            categories=["park"],
        )
        assert False, "expected GooglePlacesError"
    except GooglePlacesError:
        pass


def test_fetch_places_attributes_bank_atm_types_to_one_category():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "places": [{
                    "id": "bank-1",
                    "displayName": {"text": "Corner Bank"},
                    "location": {"latitude": -6.2, "longitude": 106.8},
                    "types": ["bank", "finance"],
                }],
            },
        )

    client = make_client(handler)
    results = fetch_places(
        client, api_key="fake-key", lat=-6.2, lng=106.8, radius_m=1000,
        categories=["bank_atm"],
    )

    assert len(results["bank_atm"]) == 1
    assert results["bank_atm"][0].category == "bank_atm"
