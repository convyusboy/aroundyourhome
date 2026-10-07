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
    rate_limit_per_min: int = 0


@lru_cache
def get_settings() -> Settings:
    return Settings(
        mongo_uri=os.environ.get("MONGO_URI", "mongodb://localhost:27017"),
        google_places_api_key=os.environ.get("GOOGLE_PLACES_API_KEY") or None,
        cache_ttl_days=int(os.environ.get("CACHE_TTL_DAYS", "14")),
        default_radius_m=int(os.environ.get("DEFAULT_RADIUS_M", "1500")),
        rate_limit_per_min=int(os.environ.get("RATE_LIMIT_PER_MIN", "0")),
    )
