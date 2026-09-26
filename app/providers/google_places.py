from typing import Optional

import httpx

from app.models import NormalizedPlace

SEARCH_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"

FIELD_MASK = (
    "places.id,places.displayName,places.location,places.types,"
    "places.rating,places.nationalPhoneNumber,"
    "places.regularOpeningHours.weekdayDescriptions"
)

CATEGORY_TO_GOOGLE_TYPES: dict[str, list[str]] = {
    "hospital": ["hospital"],
    "restaurant": ["restaurant"],
    "pharmacy": ["pharmacy"],
    "school": ["school"],
    "bank_atm": ["bank", "atm"],
    "place_of_worship": ["place_of_worship"],
    "supermarket": ["supermarket"],
    "gas_station": ["gas_station"],
    "police": ["police"],
    "gym": ["gym"],
    "park": ["park"],
}

GOOGLE_TYPE_TO_CATEGORY: dict[str, str] = {
    google_type: category
    for category, google_types in CATEGORY_TO_GOOGLE_TYPES.items()
    for google_type in google_types
}


class GooglePlacesError(Exception):
    pass


def _category_for(place_types: list[str], requested: list[str]) -> Optional[str]:
    for place_type in place_types:
        category = GOOGLE_TYPE_TO_CATEGORY.get(place_type)
        if category in requested:
            return category
    return None


def fetch_places(
    client: httpx.Client,
    api_key: str,
    lat: float,
    lng: float,
    radius_m: int,
    categories: list[str],
) -> dict[str, list[NormalizedPlace]]:
    included_types = sorted({
        google_type
        for category in categories
        for google_type in CATEGORY_TO_GOOGLE_TYPES[category]
    })

    try:
        response = client.post(
            SEARCH_NEARBY_URL,
            headers={"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELD_MASK},
            json={
                "includedTypes": included_types,
                "maxResultCount": 20,
                "locationRestriction": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lng},
                        "radius": radius_m,
                    }
                },
            },
        )
    except httpx.HTTPError as exc:
        raise GooglePlacesError(f"Google Places API request failed: {exc}") from exc

    if response.status_code != 200:
        raise GooglePlacesError(
            f"Google Places API error: HTTP {response.status_code} {response.text}"
        )

    data = response.json()
    results: dict[str, list[NormalizedPlace]] = {category: [] for category in categories}

    for result in data.get("places", []):
        category = _category_for(result.get("types", []), categories)
        if category is None:
            continue

        location = result["location"]
        weekday_descriptions = (
            (result.get("regularOpeningHours") or {}).get("weekdayDescriptions")
        )
        results[category].append(
            NormalizedPlace(
                place_id=result["id"],
                source="google",
                name=(result.get("displayName") or {}).get("text", ""),
                category=category,
                lat=location["latitude"],
                lng=location["longitude"],
                phone=result.get("nationalPhoneNumber"),
                opening_hours=(
                    ", ".join(weekday_descriptions) if weekday_descriptions else None
                ),
                rating=result.get("rating"),
                raw=result,
            )
        )

    return results
