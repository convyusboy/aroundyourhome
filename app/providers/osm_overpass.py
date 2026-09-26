import time as time_module
from typing import Optional

import httpx

from app.models import NormalizedPlace

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

CATEGORY_TO_OSM_TAGS: dict[str, list[tuple[str, str]]] = {
    "hospital": [("amenity", "hospital")],
    "restaurant": [("amenity", "restaurant")],
    "pharmacy": [("amenity", "pharmacy")],
    "school": [("amenity", "school")],
    "bank_atm": [("amenity", "bank"), ("amenity", "atm")],
    "place_of_worship": [("amenity", "place_of_worship")],
    "supermarket": [("shop", "supermarket")],
    "gas_station": [("amenity", "fuel")],
    "police": [("amenity", "police")],
    "gym": [("leisure", "fitness_centre")],
    "park": [("leisure", "park")],
}

OSM_TAG_TO_CATEGORY: dict[tuple[str, str], str] = {
    tag: category
    for category, tags in CATEGORY_TO_OSM_TAGS.items()
    for tag in tags
}


class OverpassError(Exception):
    pass


def _build_query(lat: float, lng: float, radius_m: int, tags: list[tuple[str, str]]) -> str:
    clauses = "".join(
        f'node["{key}"="{value}"](around:{radius_m},{lat},{lng});'
        for key, value in tags
    )
    return f"[out:json][timeout:25];({clauses});out center;"


def _category_for(tags: dict, requested: list[str]) -> Optional[str]:
    for key, value in tags.items():
        category = OSM_TAG_TO_CATEGORY.get((key, value))
        if category in requested:
            return category
    return None


def fetch_places(
    client: httpx.Client,
    lat: float,
    lng: float,
    radius_m: int,
    categories: list[str],
    max_retries: int = 1,
    sleep=time_module.sleep,
) -> dict[str, list[NormalizedPlace]]:
    all_tags = [tag for category in categories for tag in CATEGORY_TO_OSM_TAGS[category]]
    query = _build_query(lat, lng, radius_m, all_tags)

    attempt = 0
    while True:
        response = client.post(OVERPASS_URL, data={"data": query})
        if response.status_code == 200:
            break
        if response.status_code in (429, 504) and attempt < max_retries:
            attempt += 1
            sleep(2 ** attempt)
            continue
        raise OverpassError(f"Overpass API error: HTTP {response.status_code}")

    data = response.json()
    results: dict[str, list[NormalizedPlace]] = {category: [] for category in categories}

    for element in data.get("elements", []):
        tags = element.get("tags", {})
        category = _category_for(tags, categories)
        if category is None:
            continue

        lat_value = element.get("lat", (element.get("center") or {}).get("lat"))
        lng_value = element.get("lon", (element.get("center") or {}).get("lon"))
        if lat_value is None or lng_value is None:
            continue

        results[category].append(
            NormalizedPlace(
                place_id=str(element["id"]),
                source="osm",
                name=tags.get("name", "Unnamed"),
                category=category,
                lat=lat_value,
                lng=lng_value,
                phone=tags.get("phone") or tags.get("contact:phone"),
                opening_hours=tags.get("opening_hours"),
                rating=None,
                raw=element,
            )
        )

    return results
