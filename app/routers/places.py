from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.ratelimit import enforce_rate_limit
from app.models import CATEGORIES, PlaceOut, PlacesResponse, QueryEcho
from app.services import places_service

router = APIRouter()


@router.get("/api/places", response_model=PlacesResponse, dependencies=[Depends(enforce_rate_limit)])
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
