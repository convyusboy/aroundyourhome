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
