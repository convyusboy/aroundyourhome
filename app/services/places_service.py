import logging
from datetime import datetime, timezone

from app import db
from app.config import Settings
from app.geo import haversine_m
from app.providers import google_places, osm_overpass

logger = logging.getLogger(__name__)


def search_places(
    collection,
    coverage_collection,
    http_client,
    settings: Settings,
    lat: float,
    lng: float,
    radius_m: int,
    categories: list[str],
) -> tuple[list[dict], bool]:
    partial = False
    now = datetime.now(timezone.utc)

    missing = [
        category for category in categories
        if not db.has_fresh_coverage(
            coverage_collection, lat, lng, radius_m, category,
            settings.cache_ttl_days, now=now,
        )
    ]

    if not missing:
        logger.info("cache hit: all %d categories fresh", len(categories))
    else:
        logger.info("cache miss: fetching %s (%d cached)", missing, len(categories) - len(missing))
        fetched_by_category: dict[str, list] = {}

        if settings.google_places_api_key:
            try:
                fetched_by_category = google_places.fetch_places(
                    http_client, settings.google_places_api_key,
                    lat, lng, radius_m, missing,
                )
            except google_places.GooglePlacesError as exc:
                logger.warning("google places failed, falling back to osm: %s", exc)
                fetched_by_category = {}

        remaining = [c for c in missing if c not in fetched_by_category]
        if remaining:
            try:
                fetched_by_category.update(
                    osm_overpass.fetch_places(http_client, lat, lng, radius_m, remaining)
                )
            except osm_overpass.OverpassError as exc:
                logger.warning("overpass failed, returning partial results: %s", exc)
                partial = True

        for category, places in fetched_by_category.items():
            logger.info("fetched %d %s places", len(places), category)
            db.upsert_places(collection, places, fetched_at=now)
            db.record_coverage(coverage_collection, lat, lng, radius_m, category, fetched_at=now)

    docs = db.find_places_in_radius(collection, lat, lng, radius_m, categories)

    results = []
    for doc in docs:
        doc_lng, doc_lat = doc["location"]["coordinates"]
        distance_m = round(haversine_m(lat, lng, doc_lat, doc_lng))
        results.append({
            "name": doc["name"],
            "category": doc["category"],
            "distance_m": distance_m,
            "location": {"lat": doc_lat, "lng": doc_lng},
            "phone": doc.get("phone"),
            "opening_hours": doc.get("opening_hours"),
            "rating": doc.get("rating"),
            "gojek_link": doc.get("gojek_link"),
            "source": doc["source"],
        })

    results.sort(key=lambda r: r["distance_m"])
    return results, partial
