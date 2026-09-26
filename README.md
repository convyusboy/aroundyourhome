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
