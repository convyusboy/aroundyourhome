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
