from datetime import datetime, timedelta, timezone
from typing import Optional

from pymongo import ASCENDING, MongoClient
from pymongo.collection import Collection

from app.geo import haversine_m
from app.models import NormalizedPlace

DB_NAME = "aroundyourhome"
COLLECTION_NAME = "places"
COVERAGE_COLLECTION_NAME = "search_coverage"


def get_client(mongo_uri: str) -> MongoClient:
    return MongoClient(mongo_uri)


def get_collection(client: MongoClient) -> Collection:
    return client[DB_NAME][COLLECTION_NAME]


def get_coverage_collection(client: MongoClient) -> Collection:
    return client[DB_NAME][COVERAGE_COLLECTION_NAME]


def ensure_indexes(collection: Collection) -> None:
    collection.create_index([("location", "2dsphere")])
    collection.create_index([("category", ASCENDING)])
    collection.create_index([("fetched_at", ASCENDING)])
    collection.create_index(
        [("source", ASCENDING), ("place_id", ASCENDING)], unique=True
    )


def ensure_coverage_indexes(collection: Collection) -> None:
    collection.create_index([("category", ASCENDING)])
    collection.create_index([("fetched_at", ASCENDING)])


def upsert_places(
    collection: Collection, places: list[NormalizedPlace], fetched_at: datetime
) -> None:
    for place in places:
        doc = place.to_mongo_doc(fetched_at)
        collection.update_one(
            {"source": place.source, "place_id": place.place_id},
            {"$set": doc},
            upsert=True,
        )


def _within_radius(doc: dict, lat: float, lng: float, radius_m: float) -> bool:
    doc_lng, doc_lat = doc["location"]["coordinates"]
    return haversine_m(lat, lng, doc_lat, doc_lng) <= radius_m


def record_coverage(
    collection: Collection,
    lat: float,
    lng: float,
    radius_m: float,
    category: str,
    fetched_at: datetime,
) -> None:
    collection.insert_one({
        "category": category,
        "center": {"type": "Point", "coordinates": [lng, lat]},
        "radius_m": radius_m,
        "fetched_at": fetched_at,
    })


def has_fresh_coverage(
    collection: Collection,
    lat: float,
    lng: float,
    radius_m: float,
    category: str,
    ttl_days: int,
    now: Optional[datetime] = None,
) -> bool:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=ttl_days)
    cursor = collection.find({"category": category, "fetched_at": {"$gte": cutoff}})
    for doc in cursor:
        prev_lng, prev_lat = doc["center"]["coordinates"]
        gap = haversine_m(lat, lng, prev_lat, prev_lng)
        if gap + radius_m <= doc["radius_m"]:
            return True
    return False


def find_places_in_radius(
    collection: Collection,
    lat: float,
    lng: float,
    radius_m: float,
    categories: list[str],
) -> list[dict]:
    cursor = collection.find({"category": {"$in": categories}})
    return [doc for doc in cursor if _within_radius(doc, lat, lng, radius_m)]
