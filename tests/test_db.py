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
