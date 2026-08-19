"""Test Redis cache adapter for Mireye coordinate data and geocoding."""

from __future__ import annotations

import pytest
from app.adapters.rediscache import RedisCacheManager


@pytest.fixture
def cache(tmp_path):
    cache_file = tmp_path / "test_redis_cache.json"
    manager = RedisCacheManager()
    manager._file_path = cache_file
    manager._file_cache = {}
    manager._redis_connected = False
    manager._redis_client = None
    return manager


def test_coordinate_cache_miss_then_hit(cache):
    lat, lon = 33.4484, -112.0740
    fields = ["mean_slope_pct", "grid_capacity_mw", "ambient_design_db_c"]

    # 1. First check: should be a cache miss
    cached_payload, missing = cache.get_cached_coordinates_fetch(lat, lon, fields)
    assert cached_payload is None
    assert missing == fields

    # 2. Add details to Redis cache after fetch
    fetch_payload = {
        "lat": lat,
        "lng": lon,
        "fetched_at": "2026-08-19T20:00:00Z",
        "fields": {
            "mean_slope_pct": {"value": 2.1, "unit": "percent", "status": "live"},
            "grid_capacity_mw": {"value": 350.0, "unit": "MW", "status": "live"},
            "ambient_design_db_c": {"value": 42.5, "unit": "degC", "status": "live"},
        },
    }
    cache.set_cached_coordinates_fetch(lat, lon, fields, fetch_payload, ttl_seconds=3600)

    # 3. Second check with same coordinates: should be a direct cache hit
    hit_payload, missing_after = cache.get_cached_coordinates_fetch(lat, lon, fields)
    assert hit_payload is not None
    assert len(missing_after) == 0
    assert hit_payload["fields"]["grid_capacity_mw"]["value"] == 350.0
    assert hit_payload["fields"]["ambient_design_db_c"]["value"] == 42.5


def test_geocode_cache_miss_then_hit(cache):
    address = "1000 Hyperscale Way, Phoenix, AZ"

    # 1. Miss
    assert cache.get_cached_geocode(address) is None

    # 2. Set after geocoding
    geo_data = {
        "lat": 33.4500,
        "lng": -112.0800,
        "accuracy_type": "rooftop",
        "normalized_address": "1000 Hyperscale Way, Phoenix, AZ 85001",
    }
    cache.set_cached_geocode(address, geo_data)

    # 3. Hit
    hit = cache.get_cached_geocode(address)
    assert hit is not None
    assert hit["lat"] == 33.4500
    assert hit["accuracy_type"] == "rooftop"


def test_coordinate_partial_fields_cache(cache):
    lat, lon = 34.0522, -118.2437

    # Cache subset of fields
    cache.set_cached_coordinates_fetch(
        lat,
        lon,
        ["elevation_m"],
        {
            "lat": lat,
            "lng": lon,
            "fields": {"elevation_m": {"value": 85.0, "unit": "m"}},
        },
    )

    # Query with subset -> hit
    hit, missing = cache.get_cached_coordinates_fetch(lat, lon, ["elevation_m"])
    assert hit is not None
    assert missing == []

    # Query with extra field -> returns missing field list so only missing is requested
    hit2, missing2 = cache.get_cached_coordinates_fetch(lat, lon, ["elevation_m", "flood_zone_risk"])
    assert hit2 is None
    assert "flood_zone_risk" in missing2
