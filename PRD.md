# PRD: Around Your Home

**Status:** Draft for review
**Owner:** Ridho (personal project)
**Date:** 2026-08-19

## 1. Summary

A personal tool that, given a coordinate (the user's current location or any
specific lat/lng), finds nearby points of interest — hospitals, restaurants,
pharmacies, schools, banks/ATMs, places of worship, supermarkets, gas
stations, police stations, gyms, parks — within an adjustable search radius.
Results (name, phone number, opening hours, rating, category, and a
placeholder for a future Gojek link) are persisted to MongoDB, which also
serves as a TTL-based cache so repeat searches over the same area don't
re-hit external APIs. A minimal web UI lets the user enter or detect a
coordinate, pick a radius and categories, and see results as a list plus a
map.

## 2. Goals

- Given any coordinate + radius, return nearby places across a fixed set of
  categories with useful contact/hours detail.
- Avoid redundant external API calls by caching fetched place data in Mongo
  with a configurable expiry.
- Keep the whole thing simple to run locally: one backend service, one
  database, no auth, no extra infrastructure.

## 3. Non-goals (v1)

- No user accounts, auth, or multi-tenant hosting — this is a personal,
  locally-run tool.
- No real Gojek/GoFood merchant link resolution — the field exists in the
  data model (`gojek_link`) but is left `null` in v1. Revisit if/when a real
  integration path exists.
- No production deployment (cloud hosting, HTTPS, CI/CD) — out of scope for
  v1; the design should not preclude it later, but nothing here builds it.
- No push notifications, favorites, search history UI, or user preferences
  beyond the current search form.

## 4. Users & use case

Single user (Ridho), run locally. Primary use case: "What's around this
address/location, and how do I contact it?" — e.g. checking the nearest
hospital and its phone number, or restaurants within walking distance.

## 5. Functional requirements

### 5.1 Input

- Coordinate: either the browser's current geolocation, or a manually
  entered lat/lng.
- Radius: adjustable, 100m–10km, default 1.5km.
- Categories: multi-select from the fixed v1 list (section 5.4); default is
  all categories selected.

### 5.2 Output

For each place found:
- Name
- Category
- Coordinates
- Distance from the search coordinate
- Phone number (if available from provider)
- Opening hours (if available from provider)
- Rating (if available)
- `gojek_link` (always `null` in v1 — reserved field)
- `source` — which provider the data came from (`google` or `osm`), so the
  UI can show provenance for partial/fallback results

Results are sorted ascending by `distance_m` (nearest first).

### 5.3 Search radius

User-adjustable per request via the UI/query param, not a fixed global
setting. Backend validates it's within 100m–10km and rejects out-of-range
values with a 400 error.

### 5.4 Categories (v1 fixed list)

`hospital`, `restaurant`, `pharmacy`, `school`, `bank_atm`,
`place_of_worship`, `supermarket`, `gas_station`, `police`, `gym`, `park`

### 5.5 Data sources

- **Primary:** Google Places API (New) — `POST places:searchNearby`. (The
  older "Nearby Search (Legacy)" GET endpoint was frozen by Google in March
  2025 with no further feature updates and is not recommended for new
  development, so v1 targets the current API directly.) Requires a Google
  Cloud API key, provided via environment variable, with "Places API (New)"
  enabled on the project.
  - Up to 50 place types can be requested via `includedTypes` in a single
    call, so one cold search across all categories lacking fresh coverage
    costs a single Google request, not one per category.
  - Unlike the legacy endpoint, phone number, opening hours, and rating are
    all obtainable directly on this call via the response field mask
    (`X-Goog-FieldMask`) — no separate Place Details call is needed. These
    richer fields are billed under Google's "Enterprise" SKU tier, pricier
    per-request than the basic tier; acceptable for a personal, low-volume
    tool but worth monitoring if usage grows.
  - Each returned place carries its own `types` array; since one request
    can cover multiple v1 categories at once, results are attributed back
    to whichever v1 category's type set intersects the place's `types`.
- **Fallback:** OpenStreetMap Overpass API — used when Google returns no
  usable result for a category (error, quota exceeded, invalid key). No API
  key required.
  - All categories needing a live fetch are combined into a single Overpass
    query (one clause per category's tag), so a cold search costs one
    Overpass request regardless of how many categories are missing.
  - Each returned element's OSM tags are matched back to the v1 category
    whose tag mapping it satisfies.
- Both providers' responses are normalized into the same internal place
  shape before storage.

### 5.6 Caching & persistence

MongoDB is both the permanent store and the cache. Two collections are
used:

- **`places`** — individual point-of-interest documents, keyed by
  `(source, place_id)` for dedup/upsert. Search results are read from here.
- **`search_coverage`** — a log of which (category, area) combinations have
  actually been fetched from a live provider: `category`, a center point,
  the radius that was queried, and `fetched_at`.

Freshness is a property of *coverage*, not of individual places: a category
is considered "cached" for a given search request only if a past
`search_coverage` record for that category, still within the TTL window
(default 14 days, overridable via `CACHE_TTL_DAYS`), fully contains the
requested circle — i.e. `distance(prev_center, requested_center) +
requested_radius <= prev_radius`. This is deliberately stricter than "a
matching place exists nearby": if a category was previously fetched with a
200m radius and the same category is later requested with a 5km radius
around the same point, that is **not** treated as covered, even though a
cached place from the earlier fetch still falls inside 5km — the wider
area was never actually queried against a provider, and returning only the
narrow-radius cached point would silently under-report results.

On a search request, the service checks `search_coverage` per requested
category; only categories lacking sufficient coverage trigger a live
provider call. A `search_coverage` record is written after every live
fetch that completes (Google or Overpass), **including when a provider
returns zero results** — an empty result for a category is still
meaningful coverage (that area/category has no places), and re-querying it
every request would defeat the point of caching. Freshly fetched places
are upserted into `places` before the response is returned.

### 5.7 Error handling

- Google API failure/quota exceeded/invalid key → log a warning, fall back
  to Overpass automatically. Response marks affected places'
  `source: "osm"` (or returns cached data with no `source` change if cache
  covers it).
- Overpass rate-limited → one retry with backoff; if it still fails, return
  whatever cached/partial results exist rather than failing the whole
  request. The response includes a `partial: true` flag when any category
  couldn't be freshly fetched.
- Invalid input:
  - Missing or non-numeric `lat`/`lng` → HTTP 422 (FastAPI's standard
    request-validation response for a query param that fails its declared
    type).
  - Numeric but geographically invalid `lat`/`lng` (outside `-90..90` /
    `-180..180`), out-of-range `radius` (outside 100–10000m), or an unknown
    category → HTTP 400 with a descriptive error message.

## 6. Architecture

Single FastAPI service (Python) + MongoDB, run via `docker-compose`. The
same app serves a minimal static-HTML/JS frontend — no separate frontend
build/deploy.

```
Browser (index.html + app.js, Leaflet map)
        |
        v
FastAPI app (GET /api/places?lat&lng&radius&categories)
        |
        v
places_service: check Mongo cache -> call provider(s) for gaps -> upsert -> return
        |                                  |
        v                                  v
   MongoDB (places +                  Google Places API (New)
   search_coverage collections)       OpenStreetMap Overpass API (fallback)
```

Provider calls are batched: one request per provider per cold search covers
every category still lacking fresh coverage, rather than one request per
category (see 5.5).

### Components

- `app/routers/places.py` — the `GET /api/places` endpoint; parses/validates
  query params, delegates to the service, returns the response.
- `app/services/places_service.py` — orchestration: coverage lookup, gap
  detection, batched provider calls, upsert, coverage recording,
  distance-sort, partial-result flagging.
- `app/providers/google_places.py` — Google Places API (New) `searchNearby`
  adapter; batches categories via `includedTypes`, attributes results back
  to v1 categories via each place's `types`, normalizes to the internal
  place shape.
- `app/providers/osm_overpass.py` — Overpass API adapter; batches categories
  into a single query, attributes results back via OSM tags, same
  normalized shape.
- `app/db.py` — Mongo client setup, index creation (2dsphere on `location`,
  index on `category`, index on `fetched_at` for `places`; index on
  `category`/`fetched_at` for `search_coverage`).
- `app/models.py` — Pydantic schemas for the request, response, and place
  document.
- `app/config.py` — environment-driven settings (Mongo URI, Google API key,
  cache TTL, default radius).
- `frontend/index.html`, `frontend/app.js` — search form (coordinate entry
  or "use my location", radius input, category checkboxes), results list,
  Leaflet map with markers.
- `tests/` — unit tests for cache/TTL logic and provider normalization
  (mocked HTTP responses), plus geo-query/upsert tests against a test Mongo
  instance.

## 7. Data model

`places` collection:

```jsonc
{
  "_id": ObjectId,
  "place_id": "string",        // provider's native ID
  "source": "google" | "osm",
  "name": "string",
  "category": "hospital" | "restaurant" | ... ,
  "location": { "type": "Point", "coordinates": [lng, lat] }, // GeoJSON, 2dsphere indexed
  "phone": "string | null",
  "opening_hours": "string | null",   // human-readable, provider-dependent format
  "rating": "number | null",
  "gojek_link": null,                // reserved for future use
  "fetched_at": ISODate,
  "raw": { /* original provider payload, for debugging/future re-parsing */ }
}
```

Uniqueness: `(source, place_id)` compound unique index for upsert dedup.

`search_coverage` collection:

```jsonc
{
  "_id": ObjectId,
  "category": "hospital" | "restaurant" | ... ,
  "center": { "type": "Point", "coordinates": [lng, lat] }, // GeoJSON
  "radius_m": "number",     // radius actually queried against the provider
  "fetched_at": ISODate
}
```

No uniqueness constraint — multiple overlapping coverage records for the
same category can coexist; a request is covered if *any* fresh record's
circle contains the requested circle (see 5.6).

## 8. API

`GET /api/places`

Query params:
- `lat` (float, required)
- `lng` (float, required)
- `radius` (int, meters, optional, default 1500, range 100–10000)
- `categories` (comma-separated list, optional, default = all v1 categories)

Response:
```jsonc
{
  "query": { "lat": ..., "lng": ..., "radius": ..., "categories": [...] },
  "partial": false,
  "results": [
    {
      "name": "...", "category": "hospital", "distance_m": 320,
      "location": { "lat": ..., "lng": ... },
      "phone": "...", "opening_hours": "...", "rating": 4.5,
      "gojek_link": null, "source": "google"
    }
  ]
}
```

`GET /health` — basic liveness check (Mongo connectivity).

## 9. Project structure

```
projects/aroundyourhome/
  README.md
  .env.example
  docker-compose.yml
  requirements.txt
  app/
    main.py
    config.py
    db.py
    models.py
    providers/
      google_places.py
      osm_overpass.py
    services/
      places_service.py
    routers/
      places.py
  frontend/
    index.html
    app.js
    style.css
  tests/
    test_places_service.py
    test_providers.py
```

## 10. Configuration (env vars)

- `MONGO_URI` — default `mongodb://localhost:27017`
- `GOOGLE_PLACES_API_KEY` — required for the primary provider; if unset,
  the service runs OSM-only and logs a startup warning
- `CACHE_TTL_DAYS` — default `14`
- `DEFAULT_RADIUS_M` — default `1500`

## 11. Testing plan

- Unit tests: TTL/cache-freshness decision logic; Google/Overpass response
  normalization (mocked HTTP, no live calls in CI); radius/category input
  validation.
- Integration tests: geospatial query correctness and upsert/dedup behavior
  against a real or `mongomock` Mongo instance.
- Manual: run via `docker-compose up`, exercise the web UI with a real
  coordinate, confirm phone/hours/rating populate and a repeat search
  within the TTL window doesn't re-call external providers (verify via
  logs).

## 12. Open questions / future work

- Real Gojek/GoFood merchant link resolution, once/if a viable source
  exists.
- Deployment beyond local docker-compose, if this ever needs to be shared.
- Additional categories or provider sources if the fixed v1 list proves
  insufficient.
- Google Place Types (New) taxonomy differs slightly from the Legacy API's
  types — the exact type string for each v1 category (`school`, `gym`, etc.)
  needs confirming against Google's current Place Types (New) reference
  table during implementation.
- Monitor actual Google billing once running — the phone/hours/rating
  fields requested via field mask fall under the pricier "Enterprise" SKU
  tier; fine at personal-tool volume, but worth checking if usage grows.
