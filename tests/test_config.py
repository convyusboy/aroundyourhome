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
