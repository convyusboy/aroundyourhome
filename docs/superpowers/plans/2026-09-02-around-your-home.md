# Around Your Home Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a locally-run FastAPI + MongoDB service (with a minimal static frontend) that, given a coordinate and radius, returns nearby places across 11 fixed categories, using Google Places as primary source and OpenStreetMap Overpass as fallback, with Mongo-backed TTL caching.

**Architecture:** A single FastAPI app exposes `GET /api/places`. A service layer checks Mongo for fresh cached coverage per category; for categories lacking fresh coverage it calls Google Places (falling back to Overpass on failure), normalizes results into a shared shape, and upserts them into Mongo. All matching cached docs within the radius are then distance-filtered/sorted in Python and returned. A static HTML/JS/Leaflet frontend is served by the same app.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, PyMongo (sync), httpx (sync client), pytest, mongomock (for DB tests), Leaflet.js (CDN) for the map. No async — this is a single-user local tool, so sync I/O run in FastAPI's threadpool is sufficient and much simpler to test.

**Spec:** `PRD.md` (repo root)

## Global Constraints

- Radius must be validated to 100–10000 meters; out-of-range → HTTP 400 (PRD 5.3, 5.7).
- Fixed v1 category list (PRD 5.4): `hospital`, `restaurant`, `pharmacy`, `school`, `bank_atm`, `place_of_worship`, `supermarket`, `gas_station`, `police`, `gym`, `park`. Unknown category in request → HTTP 400 (PRD 5.7).
- `gojek_link` is always `null` in v1 (PRD 3, 5.2, 7).
- Every stored place carries `source` (`"google"` or `"osm"`) and `fetched_at` (PRD 5.2, 5.6).
- Cache TTL default 14 days, overridable via `CACHE_TTL_DAYS` (PRD 5.6, 10).
- Default radius 1500m, overridable via `DEFAULT_RADIUS_M` (PRD 10).
- Mongo uniqueness/dedup key is `(source, place_id)` (PRD 5.6, 7).
- Freshness is tracked per `search_coverage` record (category + center +
  radius + fetched_at), not per cached place: a category is covered only if
  a fresh record's circle *contains* the requested circle
  (`distance(prev_center, requested_center) + requested_radius <=
  prev_radius`). A coverage record is written after every completed live
  fetch, including zero-result ones (PRD 5.6).
- Both providers batch categories into a single request per cold search
  (Google via `includedTypes`, Overpass via multiple query clauses), then
  attribute each result back to a v1 category post-hoc (PRD 5.5).
- Google failure/quota/invalid key → fall back to Overpass automatically, no request failure (PRD 5.7).
- Overpass rate-limited → one retry with backoff, then fall back to whatever cached/partial data exists; response includes `partial: true` when any category couldn't be freshly fetched (PRD 5.7).
- `lat`/`lng` missing or non-numeric → 422 (FastAPI param validation); numeric but out of `-90..90`/`-180..180` range → 400, same as out-of-range `radius` (PRD 5.7).
- Results are sorted ascending by `distance_m` (PRD 5.2).
- No auth, no user accounts, local docker-compose only (PRD 3).

---

### Task 1: Project scaffolding

**Files:**
- Create: `.gitignore`
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `.env.example`
- Create: `pyproject.toml`
- Create: `app/__init__.py`
- Create: `app/providers/__init__.py`
- Create: `app/services/__init__.py`
- Create: `app/routers/__init__.py`
- Create: `tests/__init__.py`

**Interfaces:**
- Produces: an importable `app` package with `app.providers`, `app.services`, `app.routers` subpackages, and a `pytest` setup where `import app...` works from `tests/` without path hacks.

This is a setup-only task (no code under test yet), so it skips the write-test/run-fail/implement/run-pass cycle.

- [ ] **Step 1: Initialize git**

```bash
git init
```

- [ ] **Step 2: Create `.gitignore`**

```
__pycache__/
*.pyc
.venv/
venv/
.env
.pytest_cache/
*.egg-info/
```

- [ ] **Step 3: Create `requirements.txt`**

```
fastapi>=0.110
uvicorn[standard]>=0.29
pymongo>=4.7
httpx>=0.27
python-dotenv>=1.0
```

- [ ] **Step 4: Create `requirements-dev.txt`**

```
-r requirements.txt
pytest>=7.4
mongomock>=4.1
```

- [ ] **Step 5: Create `.env.example`**

```
MONGO_URI=mongodb://localhost:27017
GOOGLE_PLACES_API_KEY=
CACHE_TTL_DAYS=14
DEFAULT_RADIUS_M=1500
```

- [ ] **Step 6: Create `pyproject.toml`**

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 7: Create empty package `__init__.py` files**

Create these four empty files (zero bytes each):
- `app/__init__.py`
- `app/providers/__init__.py`
- `app/services/__init__.py`
- `app/routers/__init__.py`
- `tests/__init__.py`

- [ ] **Step 8: Install dependencies and verify pytest runs with zero tests collected**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

Expected: `no tests ran` (exit code 5) — this confirms pytest config/imports are wired correctly before any test files exist.

- [ ] **Step 9: Commit**

```bash
git add .gitignore requirements.txt requirements-dev.txt .env.example pyproject.toml app tests PRD.md
git commit -m "chore: project scaffolding"
```

---

### Task 2: Config module

**Files:**
- Create: `app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `app.config.Settings` (dataclass with fields `mongo_uri: str`, `google_places_api_key: str | None`, `cache_ttl_days: int`, `default_radius_m: int`) and `app.config.get_settings() -> Settings` (env-driven, `lru_cache`d).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from app.config import get_settings


def test_defaults_when_env_unset(monkeypatch):
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    monkeypatch.delenv("CACHE_TTL_DAYS", raising=False)
    monkeypatch.delenv("DEFAULT_RADIUS_M", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.mongo_uri == "mongodb://localhost:27017"
    assert settings.google_places_api_key is None
    assert settings.cache_ttl_days == 14
    assert settings.default_radius_m == 1500


def test_reads_overrides_from_env(monkeypatch):
    monkeypatch.setenv("MONGO_URI", "mongodb://example:27017")
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "key-123")
    monkeypatch.setenv("CACHE_TTL_DAYS", "7")
    monkeypatch.setenv("DEFAULT_RADIUS_M", "2000")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.mongo_uri == "mongodb://example:27017"
    assert settings.google_places_api_key == "key-123"
    assert settings.cache_ttl_days == 7
    assert settings.default_radius_m == 2000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/config.py
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional


@dataclass(frozen=True)
class Settings:
    mongo_uri: str
    google_places_api_key: Optional[str]
    cache_ttl_days: int
    default_radius_m: int


@lru_cache
def get_settings() -> Settings:
    return Settings(
        mongo_uri=os.environ.get("MONGO_URI", "mongodb://localhost:27017"),
        google_places_api_key=os.environ.get("GOOGLE_PLACES_API_KEY") or None,
        cache_ttl_days=int(os.environ.get("CACHE_TTL_DAYS", "14")),
        default_radius_m=int(os.environ.get("DEFAULT_RADIUS_M", "1500")),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: add env-driven settings module"
```

---

### Task 3: Geo utility

**Files:**
- Create: `app/geo.py`
- Test: `tests/test_geo.py`

**Interfaces:**
- Produces: `app.geo.haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float` — great-circle distance in meters.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_geo.py
from app.geo import haversine_m


def test_zero_distance_for_identical_points():
    assert haversine_m(-6.2, 106.8, -6.2, 106.8) == 0.0


def test_known_distance_jakarta_to_bandung_within_tolerance():
    # Monas (Jakarta) to Gedung Sate (Bandung), real-world distance ~115 km
    distance = haversine_m(-6.1754, 106.8272, -6.9024, 107.6186)
    assert 110_000 < distance < 120_000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_geo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.geo'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/geo.py
from math import atan2, cos, radians, sin, sqrt

EARTH_RADIUS_M = 6_371_000


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lng2 - lng1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * atan2(sqrt(a), sqrt(1 - a))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_geo.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add app/geo.py tests/test_geo.py
git commit -m "feat: add haversine distance utility"
```

---

### Task 4: Shared models

**Files:**
- Create: `app/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `app.models.CATEGORIES: list[str]` (the 11 fixed categories); `app.models.NormalizedPlace` dataclass with fields `place_id: str, source: str, name: str, category: str, lat: float, lng: float, phone: str | None = None, opening_hours: str | None = None, rating: float | None = None, raw: dict = {}` and method `to_mongo_doc(fetched_at: datetime) -> dict`; pydantic response models `LocationOut`, `PlaceOut`, `QueryEcho`, `PlacesResponse`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/models.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

CATEGORIES: list[str] = [
    "hospital", "restaurant", "pharmacy", "school", "bank_atm",
    "place_of_worship", "supermarket", "gas_station", "police",
    "gym", "park",
]


@dataclass
class NormalizedPlace:
    place_id: str
    source: str
    name: str
    category: str
    lat: float
    lng: float
    phone: Optional[str] = None
    opening_hours: Optional[str] = None
    rating: Optional[float] = None
    raw: dict = field(default_factory=dict)

    def to_mongo_doc(self, fetched_at: datetime) -> dict:
        return {
            "place_id": self.place_id,
            "source": self.source,
            "name": self.name,
            "category": self.category,
            "location": {"type": "Point", "coordinates": [self.lng, self.lat]},
            "phone": self.phone,
            "opening_hours": self.opening_hours,
            "rating": self.rating,
            "gojek_link": None,
            "fetched_at": fetched_at,
            "raw": self.raw,
        }


class LocationOut(BaseModel):
    lat: float
    lng: float


class PlaceOut(BaseModel):
    name: str
    category: str
    distance_m: int
    location: LocationOut
    phone: Optional[str] = None
    opening_hours: Optional[str] = None
    rating: Optional[float] = None
    gojek_link: Optional[str] = None
    source: str


class QueryEcho(BaseModel):
    lat: float
    lng: float
    radius: int
    categories: list[str]


class PlacesResponse(BaseModel):
    query: QueryEcho
    partial: bool
    results: list[PlaceOut]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add app/models.py tests/test_models.py
git commit -m "feat: add normalized place and API response models"
```

---

### Task 5: Database layer

**Files:**
- Create: `app/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `app.geo.haversine_m` (Task 3), `app.models.NormalizedPlace` (Task 4).
- Produces: `app.db.get_client(mongo_uri: str) -> MongoClient`; `app.db.get_collection(client) -> Collection`; `app.db.get_coverage_collection(client) -> Collection`; `app.db.ensure_indexes(collection) -> None`; `app.db.ensure_coverage_indexes(collection) -> None`; `app.db.upsert_places(collection, places: list[NormalizedPlace], fetched_at: datetime) -> None`; `app.db.record_coverage(collection, lat, lng, radius_m, category, fetched_at) -> None`; `app.db.has_fresh_coverage(collection, lat, lng, radius_m, category, ttl_days, now=None) -> bool`; `app.db.find_places_in_radius(collection, lat, lng, radius_m, categories: list[str]) -> list[dict]`.

Notes on design:
- Rather than relying on MongoDB geospatial query operators (which have inconsistent support in `mongomock`), radius filtering is done in Python using `haversine_m` after a plain equality/range query. This keeps the dataset-scale assumption (a personal tool's local cache) simple and fully testable without a real MongoDB. The `2dsphere` index is still created per the spec's architecture section for future-proofing, even though current queries don't require it.
- Freshness is tracked in a separate `search_coverage` collection, not by checking whether a cached place exists nearby (PRD 5.6). A category is covered for a request only if a fresh coverage record's previously-queried circle *contains* the requested circle: `distance(prev_center, requested_center) + requested_radius <= prev_radius`. This is what prevents a bug where a category fetched once with a small radius gets wrongly treated as "covered" when later requested with a much larger radius around the same point — a single nearby cached place would otherwise satisfy a naive "does a matching doc exist in range" check even though the wider area was never queried.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db.py
from datetime import datetime, timedelta, timezone

import mongomock

from app.db import (
    ensure_indexes,
    find_places_in_radius,
    has_fresh_coverage,
    record_coverage,
    upsert_places,
)
from app.models import NormalizedPlace


def make_collection():
    client = mongomock.MongoClient()
    return client["aroundyourhome"]["places"]


def make_coverage_collection():
    client = mongomock.MongoClient()
    return client["aroundyourhome"]["search_coverage"]


def test_ensure_indexes_does_not_raise():
    ensure_indexes(make_collection())


def test_upsert_and_find_places_in_radius():
    collection = make_collection()
    place = NormalizedPlace(
        place_id="p1", source="google", name="Test Hospital",
        category="hospital", lat=-6.2000, lng=106.8166,
    )
    upsert_places(collection, [place], fetched_at=datetime.now(timezone.utc))

    results = find_places_in_radius(collection, -6.2000, 106.8166, 500, ["hospital"])

    assert len(results) == 1
    assert results[0]["name"] == "Test Hospital"


def test_find_places_in_radius_excludes_far_places():
    collection = make_collection()
    far_place = NormalizedPlace(
        place_id="p2", source="google", name="Far Hospital",
        category="hospital", lat=-6.3000, lng=106.9000,
    )
    upsert_places(collection, [far_place], fetched_at=datetime.now(timezone.utc))

    results = find_places_in_radius(collection, -6.2000, 106.8166, 500, ["hospital"])

    assert results == []


def test_find_places_in_radius_excludes_other_categories():
    collection = make_collection()
    place = NormalizedPlace(
        place_id="p3", source="google", name="Corner Store",
        category="supermarket", lat=-6.2000, lng=106.8166,
    )
    upsert_places(collection, [place], fetched_at=datetime.now(timezone.utc))

    results = find_places_in_radius(collection, -6.2000, 106.8166, 500, ["hospital"])

    assert results == []


def test_upsert_is_idempotent_dedup_by_source_and_place_id():
    collection = make_collection()
    original = NormalizedPlace(
        place_id="p7", source="google", name="Original Name",
        category="bank_atm", lat=-6.2000, lng=106.8166,
    )
    upsert_places(collection, [original], fetched_at=datetime.now(timezone.utc))
    updated = NormalizedPlace(
        place_id="p7", source="google", name="Updated Name",
        category="bank_atm", lat=-6.2000, lng=106.8166,
    )
    upsert_places(collection, [updated], fetched_at=datetime.now(timezone.utc))

    assert collection.count_documents({}) == 1
    assert collection.find_one({"place_id": "p7"})["name"] == "Updated Name"


def test_has_fresh_coverage_true_when_same_circle_recorded():
    coverage = make_coverage_collection()
    record_coverage(
        coverage, -6.2000, 106.8166, 500, "pharmacy", fetched_at=datetime.now(timezone.utc)
    )

    assert has_fresh_coverage(
        coverage, -6.2000, 106.8166, 500, "pharmacy", ttl_days=14
    ) is True


def test_has_fresh_coverage_true_with_no_places_at_all():
    # Recording coverage for a search that found zero results still counts
    # as covered — there being no `places` documents must not matter here.
    coverage = make_coverage_collection()
    record_coverage(
        coverage, -6.2000, 106.8166, 500, "pharmacy", fetched_at=datetime.now(timezone.utc)
    )

    assert has_fresh_coverage(
        coverage, -6.2000, 106.8166, 500, "pharmacy", ttl_days=14
    ) is True


def test_has_fresh_coverage_false_when_expired():
    coverage = make_coverage_collection()
    old_fetch = datetime.now(timezone.utc) - timedelta(days=20)
    record_coverage(coverage, -6.2000, 106.8166, 500, "pharmacy", fetched_at=old_fetch)

    assert has_fresh_coverage(
        coverage, -6.2000, 106.8166, 500, "pharmacy", ttl_days=14
    ) is False


def test_has_fresh_coverage_false_when_out_of_radius():
    coverage = make_coverage_collection()
    record_coverage(
        coverage, -6.3000, 106.9000, 500, "pharmacy", fetched_at=datetime.now(timezone.utc)
    )

    assert has_fresh_coverage(
        coverage, -6.2000, 106.8166, 500, "pharmacy", ttl_days=14
    ) is False


def test_has_fresh_coverage_false_when_requested_radius_exceeds_covered_radius():
    # Regression test for the radius-widening bug: a 200m fetch must not be
    # treated as covering a later 5000m request around the same point.
    coverage = make_coverage_collection()
    record_coverage(
        coverage, -6.2000, 106.8166, 200, "hospital", fetched_at=datetime.now(timezone.utc)
    )

    assert has_fresh_coverage(
        coverage, -6.2000, 106.8166, 5000, "hospital", ttl_days=14
    ) is False


def test_has_fresh_coverage_true_when_requested_circle_is_contained():
    coverage = make_coverage_collection()
    record_coverage(
        coverage, -6.2000, 106.8166, 5000, "hospital", fetched_at=datetime.now(timezone.utc)
    )

    assert has_fresh_coverage(
        coverage, -6.2000, 106.8166, 200, "hospital", ttl_days=14
    ) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.db'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/db.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py -v`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
git add app/db.py tests/test_db.py
git commit -m "feat: add mongo db layer with coverage-based cache and radius filtering"
```

---

### Task 6: Google Places provider

**Files:**
- Create: `app/providers/google_places.py`
- Test: `tests/test_providers_google.py`

**Interfaces:**
- Consumes: `app.models.NormalizedPlace` (Task 4).
- Produces: `app.providers.google_places.fetch_places(client: httpx.Client, api_key: str, lat: float, lng: float, radius_m: int, categories: list[str]) -> dict[str, list[NormalizedPlace]]`; `app.providers.google_places.GooglePlacesError` exception; `app.providers.google_places.CATEGORY_TO_GOOGLE_TYPES: dict[str, list[str]]`.

Notes:
- Targets Google's current **Places API (New)** `searchNearby` endpoint
  (`POST https://places.googleapis.com/v1/places:searchNearby` with
  `X-Goog-Api-Key`/`X-Goog-FieldMask` headers), not the frozen Legacy
  Nearby Search GET endpoint (PRD 5.5) — Google froze Legacy in March 2025
  and recommends the new API for new development.
- One call batches every category in `categories` via `includedTypes`
  (up to 50 allowed); results are attributed back to a v1 category by
  matching each place's `types` array against `CATEGORY_TO_GOOGLE_TYPES`.
- This call is all-or-nothing: if the request fails, the caller (Task 8)
  falls back to Overpass for *every* requested category, not just the
  one(s) that individually failed. That's an acceptable trade-off — a
  Google failure (bad key, quota, network) is virtually always
  request-wide, not category-specific — and batching removes what would
  otherwise be up to 11 sequential Google calls per cold search.
- Phone, opening hours, and rating are requested directly via the field
  mask — no separate Place Details call needed (unlike the Legacy API,
  which never returned phone at all).
- The exact Google Place Types (New) strings in `CATEGORY_TO_GOOGLE_TYPES`
  should be double-checked against Google's current Place Types reference
  table while implementing this task — the New API's type taxonomy differs
  slightly from Legacy's (tracked in PRD 12).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_providers_google.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_providers_google.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.providers.google_places'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/providers/google_places.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_providers_google.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add app/providers/google_places.py tests/test_providers_google.py
git commit -m "feat: add batched google places (new) searchNearby provider"
```

---

### Task 7: OSM Overpass provider

**Files:**
- Create: `app/providers/osm_overpass.py`
- Test: `tests/test_providers_osm.py`

**Interfaces:**
- Consumes: `app.models.NormalizedPlace` (Task 4).
- Produces: `app.providers.osm_overpass.fetch_places(client: httpx.Client, lat: float, lng: float, radius_m: int, categories: list[str], max_retries: int = 1, sleep=time.sleep) -> dict[str, list[NormalizedPlace]]`; `app.providers.osm_overpass.OverpassError` exception; `app.providers.osm_overpass.CATEGORY_TO_OSM_TAGS: dict[str, list[tuple[str, str]]]`.

Note: like the Google provider (Task 6), this batches every category
needing a live fetch into a single Overpass query (one tag clause per
category), instead of one HTTP request per category — a cold search across
all 11 categories costs one Overpass request, not up to 11, which also
reduces exposure to Overpass's public-instance rate limiting. Each returned
element's OSM tags are matched back to a v1 category via
`CATEGORY_TO_OSM_TAGS`; elements matching no requested category's tags are
dropped.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_providers_osm.py
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


def test_fetch_places_raises_overpass_error_on_network_failure():
    # A connection-level failure (DNS, timeout, TLS handshake, ...) must be
    # wrapped as OverpassError so callers can catch one exception type,
    # instead of an unhandled httpx.TransportError crashing the request.
    def handler(request):
        raise httpx.ConnectTimeout("connect timed out")

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_providers_osm.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.providers.osm_overpass'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/providers/osm_overpass.py
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
        try:
            response = client.post(OVERPASS_URL, data={"data": query})
        except httpx.HTTPError as exc:
            raise OverpassError(f"Overpass API request failed: {exc}") from exc
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_providers_osm.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add app/providers/osm_overpass.py tests/test_providers_osm.py
git commit -m "feat: add batched OSM overpass fallback provider with retry"
```

---

### Task 8: Places service (orchestration)

**Files:**
- Create: `app/services/places_service.py`
- Test: `tests/test_places_service.py`

**Interfaces:**
- Consumes: `app.db.has_fresh_coverage`, `app.db.record_coverage`, `app.db.upsert_places`, `app.db.find_places_in_radius` (Task 5); `app.providers.google_places.fetch_places`/`GooglePlacesError` (Task 6); `app.providers.osm_overpass.fetch_places`/`OverpassError` (Task 7); `app.geo.haversine_m` (Task 3); `app.config.Settings` (Task 2).
- Produces: `app.services.places_service.search_places(collection, coverage_collection, http_client, settings, lat, lng, radius_m, categories: list[str]) -> tuple[list[dict], bool]` — returns `(results, partial)` where each result dict matches the shape consumed by `PlaceOut(**result)`.

Orchestration, given `categories` still lacking fresh coverage (`missing`):
1. If a Google API key is configured, make one batched Google call for all
   of `missing`. On success this returns an entry (possibly an empty list)
   for every category in `missing` — all of those are considered covered
   by Google, even the empty ones (PRD 5.6's "coverage even on zero
   results"). On `GooglePlacesError`, none of `missing` is considered
   covered by Google.
2. Whatever remains uncovered after step 1 (no Google key, or Google
   failed, or Google didn't cover a category) is fetched from Overpass in
   one batched call. On `OverpassError`, `partial` is set `True` and none
   of the remaining categories get a coverage record.
3. For every category that ended up with a successful fetch (Google or
   Overpass), upsert its places (if any) and write one `search_coverage`
   record for the requested `(lat, lng, radius_m)`.
4. Read back everything within radius/category from `places` (cached +
   freshly fetched) and return it distance-sorted.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_places_service.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_places_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.places_service'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/services/places_service.py
from datetime import datetime, timezone

from app import db
from app.config import Settings
from app.geo import haversine_m
from app.providers import google_places, osm_overpass


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

    if missing:
        fetched_by_category: dict[str, list] = {}

        if settings.google_places_api_key:
            try:
                fetched_by_category = google_places.fetch_places(
                    http_client, settings.google_places_api_key,
                    lat, lng, radius_m, missing,
                )
            except google_places.GooglePlacesError:
                fetched_by_category = {}

        remaining = [c for c in missing if c not in fetched_by_category]
        if remaining:
            try:
                fetched_by_category.update(
                    osm_overpass.fetch_places(http_client, lat, lng, radius_m, remaining)
                )
            except osm_overpass.OverpassError:
                partial = True

        for category, places in fetched_by_category.items():
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_places_service.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add app/services/places_service.py tests/test_places_service.py
git commit -m "feat: add places service orchestrating coverage cache, batched providers, and fallback"
```

---

### Task 9: API router

**Files:**
- Create: `app/routers/places.py`
- Test: `tests/test_places_router.py`

**Interfaces:**
- Consumes: `app.models.CATEGORIES`, `PlacesResponse`, `QueryEcho`, `PlaceOut` (Task 4); `app.services.places_service.search_places` (Task 8). Reads `request.app.state.settings`, `request.app.state.collection`, `request.app.state.coverage_collection`, `request.app.state.http_client` (set up in Task 10).
- Produces: `app.routers.places.router` (a `fastapi.APIRouter`) exposing `GET /api/places`.

Validation order (PRD 5.7): `lat`/`lng` missing or non-numeric fail FastAPI's
own `Query(...)` type coercion → 422, before this handler body runs at all.
Everything else (`lat`/`lng` out of geographic range, out-of-range
`radius`, unknown `categories`) is checked in the handler → 400.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_places_router.py
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
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
    assert len(captured["categories"]) == 11


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_places_router.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.routers.places'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/routers/places.py
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from app.models import CATEGORIES, PlaceOut, PlacesResponse, QueryEcho
from app.services import places_service

router = APIRouter()


@router.get("/api/places", response_model=PlacesResponse)
def get_places(
    request: Request,
    lat: float = Query(...),
    lng: float = Query(...),
    radius: Optional[int] = Query(None),
    categories: Optional[str] = Query(None),
):
    settings = request.app.state.settings
    collection = request.app.state.collection
    coverage_collection = request.app.state.coverage_collection
    http_client = request.app.state.http_client

    if not (-90 <= lat <= 90):
        raise HTTPException(status_code=400, detail="lat must be between -90 and 90")
    if not (-180 <= lng <= 180):
        raise HTTPException(status_code=400, detail="lng must be between -180 and 180")

    radius_m = radius if radius is not None else settings.default_radius_m
    if not (100 <= radius_m <= 10000):
        raise HTTPException(
            status_code=400, detail="radius must be between 100 and 10000 meters"
        )

    if categories:
        category_list = [c.strip() for c in categories.split(",") if c.strip()]
    else:
        category_list = list(CATEGORIES)

    unknown = [c for c in category_list if c not in CATEGORIES]
    if unknown:
        raise HTTPException(
            status_code=400, detail=f"unknown categories: {', '.join(unknown)}"
        )

    results, partial = places_service.search_places(
        collection, coverage_collection, http_client, settings, lat, lng, radius_m, category_list
    )

    return PlacesResponse(
        query=QueryEcho(lat=lat, lng=lng, radius=radius_m, categories=category_list),
        partial=partial,
        results=[PlaceOut(**r) for r in results],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_places_router.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add app/routers/places.py tests/test_places_router.py
git commit -m "feat: add GET /api/places endpoint with input validation"
```

---

### Task 10: FastAPI app wiring and health check

**Files:**
- Create: `app/main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `app.config.get_settings` (Task 2); `app.db.get_client`, `get_collection`, `get_coverage_collection`, `ensure_indexes`, `ensure_coverage_indexes` (Task 5); `app.routers.places.router` (Task 9).
- Produces: `app.main.app` (the `FastAPI` instance), `GET /health`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_main.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/main.py
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import db
from app.config import get_settings
from app.routers.places import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    client = db.get_client(settings.mongo_uri)
    collection = db.get_collection(client)
    coverage_collection = db.get_coverage_collection(client)
    db.ensure_indexes(collection)
    db.ensure_coverage_indexes(coverage_collection)

    app.state.settings = settings
    app.state.mongo_client = client
    app.state.collection = collection
    app.state.coverage_collection = coverage_collection
    # Must exceed the Overpass query's own [timeout:25] budget (see
    # app/providers/osm_overpass.py) or the client aborts a legitimately
    # slow-but-successful Overpass response before the server would.
    app.state.http_client = httpx.Client(timeout=30.0)

    yield

    app.state.http_client.close()
    client.close()


app = FastAPI(title="Around Your Home", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
def health():
    try:
        app.state.collection.estimated_document_count()
        mongo_ok = True
    except Exception:
        mongo_ok = False
    return {"status": "ok" if mongo_ok else "degraded", "mongo": mongo_ok}


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main.py -v`
Expected: PASS (2 passed) — requires `frontend/index.html` to exist for `StaticFiles` mount not to error at import time; a placeholder is created in this step if Task 11 hasn't run yet.

If `frontend/` doesn't exist yet, create a minimal placeholder before running the test:

```bash
mkdir -p frontend
echo '<!doctype html><html><body>placeholder</body></html>' > frontend/index.html
```

(Task 11 replaces this file with the real UI.)

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_main.py frontend/index.html
git commit -m "feat: wire FastAPI app with lifespan, health check, and static frontend mount"
```

---

### Task 11: Frontend UI

**Files:**
- Modify: `frontend/index.html` (replace placeholder)
- Create: `frontend/app.js`
- Create: `frontend/style.css`
- Test: `tests/test_frontend.py`

**Interfaces:**
- Consumes: `GET /api/places` (Task 9) as the only backend contract; no other app module.
- Produces: a browser page served at `/` with a coordinate/radius/category form, a results list, and a Leaflet map.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_frontend.py
import mongomock
from fastapi.testclient import TestClient

from app import main


def test_index_page_serves_expected_markup(monkeypatch):
    monkeypatch.setattr(main.db, "get_client", lambda uri: mongomock.MongoClient())

    with TestClient(main.app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "id=\"search-form\"" in response.text
    assert "leaflet" in response.text.lower()


def test_app_js_is_served(monkeypatch):
    monkeypatch.setattr(main.db, "get_client", lambda uri: mongomock.MongoClient())

    with TestClient(main.app) as client:
        response = client.get("/app.js")

    assert response.status_code == 200
    assert "/api/places" in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_frontend.py -v`
Expected: FAIL — placeholder `index.html` lacks `id="search-form"` and Leaflet, and `/app.js` doesn't exist (404).

- [ ] **Step 3: Write minimal implementation**

```html
<!-- frontend/index.html -->
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Around Your Home</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <link rel="stylesheet" href="/style.css" />
</head>
<body>
  <h1>Around Your Home</h1>
  <form id="search-form">
    <label>Lat <input id="lat" type="number" step="any" required /></label>
    <label>Lng <input id="lng" type="number" step="any" required /></label>
    <button type="button" id="use-location">Use my location</button>
    <label>Radius (m) <input id="radius" type="number" min="100" max="10000" value="1500" /></label>
    <fieldset id="categories">
      <legend>Categories</legend>
    </fieldset>
    <button type="submit">Search</button>
  </form>
  <div id="map"></div>
  <ul id="results"></ul>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="/app.js"></script>
</body>
</html>
```

```css
/* frontend/style.css */
body {
  font-family: system-ui, sans-serif;
  max-width: 900px;
  margin: 0 auto;
  padding: 1rem;
}

#map {
  height: 400px;
  margin: 1rem 0;
}

#results {
  list-style: none;
  padding: 0;
}

#results li {
  border-bottom: 1px solid #ddd;
  padding: 0.5rem 0;
}
```

```javascript
// frontend/app.js
const CATEGORIES = [
  "hospital", "restaurant", "pharmacy", "school", "bank_atm",
  "place_of_worship", "supermarket", "gas_station", "police", "gym", "park",
];

const categoriesFieldset = document.getElementById("categories");
for (const category of CATEGORIES) {
  const label = document.createElement("label");
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.value = category;
  checkbox.checked = true;
  label.appendChild(checkbox);
  label.append(" " + category);
  categoriesFieldset.appendChild(label);
  categoriesFieldset.appendChild(document.createElement("br"));
}

const map = L.map("map").setView([-6.2, 106.8], 14);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

let markers = [];

document.getElementById("use-location").addEventListener("click", () => {
  navigator.geolocation.getCurrentPosition((position) => {
    document.getElementById("lat").value = position.coords.latitude;
    document.getElementById("lng").value = position.coords.longitude;
  });
});

document.getElementById("search-form").addEventListener("submit", async (event) => {
  event.preventDefault();

  const lat = document.getElementById("lat").value;
  const lng = document.getElementById("lng").value;
  const radius = document.getElementById("radius").value;
  const selected = Array.from(
    categoriesFieldset.querySelectorAll("input:checked")
  ).map((input) => input.value);

  const params = new URLSearchParams({ lat, lng, radius, categories: selected.join(",") });
  const response = await fetch(`/api/places?${params}`);
  const data = await response.json();

  markers.forEach((marker) => map.removeLayer(marker));
  markers = [];

  const resultsList = document.getElementById("results");
  resultsList.innerHTML = "";

  for (const place of data.results) {
    const item = document.createElement("li");
    item.textContent = `${place.name} (${place.category}) - ${place.distance_m}m` +
      (place.phone ? ` - ${place.phone}` : "");
    resultsList.appendChild(item);

    const marker = L.marker([place.location.lat, place.location.lng])
      .addTo(map)
      .bindPopup(place.name);
    markers.push(marker);
  }

  map.setView([parseFloat(lat), parseFloat(lng)], 14);
});
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_frontend.py -v`
Expected: PASS (2 passed)

Manual check (not automated): run `uvicorn app.main:app --reload`, open `http://localhost:8000/`, click "Use my location" or type a coordinate, submit, and confirm the results list and map markers populate.

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html frontend/app.js frontend/style.css tests/test_frontend.py
git commit -m "feat: add search form, results list, and leaflet map frontend"
```

---

### Task 12: Docker Compose, Dockerfile, and README

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `README.md`

**Interfaces:**
- Consumes: nothing new — packages the app built in Tasks 1–11 for `docker-compose up`.
- Produces: a runnable local stack (`mongo` + `app` services).

This task has no unit test (it's infra/docs); its "test cycle" is the manual verification in Step 3.

- [ ] **Step 1: Create `Dockerfile`**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY frontend ./frontend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Create `docker-compose.yml`**

```yaml
services:
  mongo:
    image: mongo:7
    ports:
      - "27017:27017"
    volumes:
      - mongo_data:/data/db

  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      MONGO_URI: mongodb://mongo:27017
      GOOGLE_PLACES_API_KEY: ${GOOGLE_PLACES_API_KEY:-}
      CACHE_TTL_DAYS: ${CACHE_TTL_DAYS:-14}
      DEFAULT_RADIUS_M: ${DEFAULT_RADIUS_M:-1500}
    depends_on:
      - mongo

volumes:
  mongo_data:
```

- [ ] **Step 3: Create `README.md` and manually verify the full stack**

```markdown
# Around Your Home

Local tool: given a coordinate and radius, find nearby hospitals, restaurants,
pharmacies, and other points of interest, cached in MongoDB. See `PRD.md` for
the full spec.

## Run locally

    cp .env.example .env
    # edit .env and set GOOGLE_PLACES_API_KEY if you have one (optional —
    # falls back to OpenStreetMap Overpass if omitted)
    docker-compose up --build

Then open http://localhost:8000/

## Run tests

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements-dev.txt
    pytest
```

Manual verification (run once, confirm each item):

```bash
docker-compose up --build
```

- [x] Open `http://localhost:8000/health` — returns `{"status": "ok", "mongo": true}`
- [x] Open `http://localhost:8000/` — form, map, and category checkboxes render
- [x] Enter a real coordinate, submit — results list populates with markers on the map
- [x] Check container logs (`docker-compose logs app`) — confirm a second identical search within the TTL window does not log a new outbound call to Google/Overpass (cache hit)
- [x] Submit with `radius=50` via `curl "http://localhost:8000/api/places?lat=-6.2&lng=106.8&radius=50"` — returns HTTP 400
- [x] Submit with `categories=not_a_category` — returns HTTP 400

- [ ] **Step 4: Run the full automated test suite one more time**

```bash
pytest -v
```

Expected: all tests from Tasks 2–11 pass (46 passed).

- [ ] **Step 5: Commit**

```bash
git add Dockerfile docker-compose.yml README.md
git commit -m "chore: add Dockerfile, docker-compose, and README"
```

---

## Post-plan notes (documented deviations from a literal PRD reading)

- **Radius filtering implementation:** done in Python via `haversine_m` rather than Mongo geospatial operators, to keep `mongomock` test coverage reliable (Task 5 note). The `2dsphere` index is still created per PRD's architecture section.
- **Google Place Types (New) strings:** `CATEGORY_TO_GOOGLE_TYPES` in Task 6 uses the same type strings as the old plan's Legacy mapping; these should be verified against Google's current Place Types (New) reference table while implementing Task 6, since the New API's taxonomy differs slightly from Legacy's (tracked in PRD 12).
- **Coverage-record granularity:** `search_coverage` records the exact `(category, center, radius_m)` that was queried; "fresh" means a past record's circle *contains* the requested circle (Task 5). A request whose circle is only partially covered by past records (e.g. straddling two previous searches, neither of which alone contains it) is treated as not covered and re-fetched in full — simpler than computing partial/union coverage, and safe (never under-fetches), at the cost of occasionally re-fetching an area that was, in aggregate, already covered by more than one prior search.
- **Provider network-failure handling (Tasks 6 & 7):** both `fetch_places` implementations wrap the outbound HTTP call itself in `try/except httpx.HTTPError`, converting a connection-level failure (timeout, DNS, TLS handshake) into `GooglePlacesError`/`OverpassError`. This wasn't in the original mocked-response test suite — every test used `httpx.MockTransport`, which never raises a transport error, only ever returns a `Response` object — so the gap only surfaced during a live manual run against docker-compose, where Overpass was genuinely unreachable and the missing wrapper caused an unhandled `httpx.ConnectTimeout` to propagate all the way to a 500, instead of degrading to `partial: true` per PRD 5.7. Fixed in both providers with a regression test each (`..._raises_..._error_on_network_failure`) that simulates the handler raising instead of returning.
- **Shared HTTP client timeout (Task 10):** the Overpass query built in Task 7 embeds `[timeout:25]`, telling the Overpass server it may take up to 25s to answer — but the shared `httpx.Client` in `app/main.py`'s lifespan was originally configured with `timeout=10.0`. A real batched query across all 11 categories in a dense area legitimately took ~30s and was aborted client-side before the (successful) server response arrived, silently producing zero results with `partial: true` instead of real data. Found via a live manual run with real Overpass data, not caught by the mocked test suite (which never waits on real latency). Fixed by raising the client timeout to `30.0`, comfortably above the query's own budget.
- **Overpass way/relation coverage and User-Agent (Tasks 7 & 10):** the query originally matched only `node` elements, silently missing places mapped as building/area outlines — in a live Jakarta run (1.5km, all categories) ways outnumbered nodes for hospitals, schools, parks, and places of worship (110 ways vs 5 nodes). The query now uses `nwr[...]` with `out center`, and `place_id` is prefixed with the OSM element type (`node/123`, `way/123`) because OSM ids are only unique per type. Places cached before this change keep their bare ids and will appear duplicated until the cache is cleared. Separately, Overpass began rejecting the default `python-httpx` User-Agent with HTTP 406, so the shared client now sends an identifying `aroundyourhome/0.1` User-Agent. Live query time with ways included: ~16s.
- **Overpass mirror fallback (Task 7):** live runs showed the public `overpass-api.de` instance intermittently returning HTTP 504 under load, and one retry against the same server wasn't enough. `fetch_places` now cycles through `OVERPASS_URLS` (main instance, then `overpass.private.coffee`); 429/502/503/504 or a transport error moves to the next mirror, and a full pass over all mirrors costs one retry round (backoff `2**round` seconds). Other statuses (e.g. 400) fail immediately. Worst case is bounded by mirrors × rounds × the 30s client timeout. `overpass.kumi.systems` was tried and timed out, so it is not listed.
