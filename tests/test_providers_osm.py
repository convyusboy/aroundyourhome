from urllib.parse import parse_qs

import httpx

from app.providers.osm_overpass import OverpassError, fetch_places


def make_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_places_batches_categories_into_one_query_and_normalizes():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "elements": [
                    {
                        "type": "node",
                        "id": 111,
                        "lat": -6.2,
                        "lon": 106.8,
                        "tags": {
                            "amenity": "pharmacy",
                            "name": "Community Pharmacy",
                            "phone": "+62 21 555 1111",
                            "opening_hours": "Mo-Su 08:00-21:00",
                        },
                    },
                    {
                        "type": "way",
                        "id": 222,
                        "center": {"lat": -6.3, "lon": 106.9},
                        "tags": {"leisure": "park", "name": "Big Park"},
                    },
                ],
            },
        )

    client = make_client(handler)
    results = fetch_places(
        client, lat=-6.2, lng=106.8, radius_m=1000,
        categories=["pharmacy", "park"], sleep=lambda s: None,
    )

    assert set(results.keys()) == {"pharmacy", "park"}
    pharmacy = results["pharmacy"][0]
    assert pharmacy.place_id == "111"
    assert pharmacy.source == "osm"
    assert pharmacy.name == "Community Pharmacy"
    assert pharmacy.category == "pharmacy"
    assert pharmacy.phone == "+62 21 555 1111"
    assert pharmacy.opening_hours == "Mo-Su 08:00-21:00"

    park = results["park"][0]
    assert park.lat == -6.3
    assert park.lng == 106.9
    assert park.category == "park"


def test_fetch_places_skips_elements_matching_no_requested_category():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "elements": [{
                    "type": "node", "id": 999, "lat": -6.2, "lon": 106.8,
                    "tags": {"amenity": "restaurant", "name": "Unrequested"},
                }],
            },
        )

    client = make_client(handler)
    results = fetch_places(
        client, lat=-6.2, lng=106.8, radius_m=1000,
        categories=["pharmacy"], sleep=lambda s: None,
    )

    assert results == {"pharmacy": []}


def test_fetch_places_retries_once_on_429_then_succeeds():
    responses = [httpx.Response(429), httpx.Response(200, json={"elements": []})]

    def handler(request):
        return responses.pop(0)

    client = make_client(handler)
    results = fetch_places(
        client, lat=-6.2, lng=106.8, radius_m=1000,
        categories=["hospital"], sleep=lambda s: None,
    )

    assert results == {"hospital": []}


def test_fetch_places_raises_after_retry_exhausted():
    def handler(request):
        return httpx.Response(429)

    client = make_client(handler)
    try:
        fetch_places(
            client, lat=-6.2, lng=106.8, radius_m=1000,
            categories=["hospital"], sleep=lambda s: None,
        )
        assert False, "expected OverpassError"
    except OverpassError:
        pass


def test_fetch_places_bank_atm_covers_both_tags_in_one_query():
    captured = {}

    def handler(request):
        # The Overpass query is sent as a form-encoded `data` field, per
        # standard Overpass API usage (`curl -d "data=<query>" ...`), so
        # decode the form body rather than substring-matching the raw
        # request content.
        captured["query"] = parse_qs(request.content.decode())["data"][0]
        return httpx.Response(200, json={"elements": []})

    client = make_client(handler)
    fetch_places(
        client, lat=-6.2, lng=106.8, radius_m=1000,
        categories=["bank_atm"], sleep=lambda s: None,
    )

    assert '"amenity"="bank"' in captured["query"]
    assert '"amenity"="atm"' in captured["query"]
