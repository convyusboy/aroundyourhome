from datetime import datetime, timezone

from app.models import CATEGORIES, NormalizedPlace, PlaceOut, PlacesResponse, QueryEcho


def test_categories_is_the_fixed_v1_list():
    assert CATEGORIES == [
        "hospital", "restaurant", "pharmacy", "school", "bank_atm",
        "place_of_worship", "supermarket", "gas_station", "police",
        "gym", "park",
    ]


def test_normalized_place_to_mongo_doc_shape():
    place = NormalizedPlace(
        place_id="abc123",
        source="google",
        name="City Hospital",
        category="hospital",
        lat=-6.2,
        lng=106.8,
        phone="+62 21 555 0000",
        opening_hours="Mon-Sun 24 hours",
        rating=4.5,
        raw={"foo": "bar"},
    )
    fetched_at = datetime(2026, 9, 1, tzinfo=timezone.utc)

    doc = place.to_mongo_doc(fetched_at)

    assert doc == {
        "place_id": "abc123",
        "source": "google",
        "name": "City Hospital",
        "category": "hospital",
        "location": {"type": "Point", "coordinates": [106.8, -6.2]},
        "phone": "+62 21 555 0000",
        "opening_hours": "Mon-Sun 24 hours",
        "rating": 4.5,
        "gojek_link": None,
        "fetched_at": fetched_at,
        "raw": {"foo": "bar"},
    }


def test_places_response_serializes_with_defaults():
    response = PlacesResponse(
        query=QueryEcho(lat=-6.2, lng=106.8, radius=1500, categories=["hospital"]),
        partial=False,
        results=[
            PlaceOut(
                name="City Hospital",
                category="hospital",
                distance_m=320,
                location={"lat": -6.2, "lng": 106.8},
                source="google",
            )
        ],
    )

    payload = response.model_dump()

    assert payload["partial"] is False
    assert payload["results"][0]["gojek_link"] is None
    assert payload["results"][0]["phone"] is None
