"""Redis cache adapter for Mireye API physical world data and coordinate lookups.

Workflow:
1. When coordinates (lat, lon) or addresses are queried, check Redis cache first.
2. If present in cache -> return cached data immediately (status: cached, 0 API credit cost).
3. If not in cache -> call Mireye API (/v1/fetch, /v1/geocode).
4. After API task completion -> save all response fields and coordinate objects into Redis cache with TTL.
5. Durable fallback: If standalone Redis server is unavailable, writes to persistent local redis_cache.json.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from ..config import Settings, get_settings

log = logging.getLogger("rediscache")

try:
    import redis
    REDIS_INSTALLED = True
except ImportError:
    redis = None  # type: ignore
    REDIS_INSTALLED = False


class RedisCacheManager:
    """Manages Redis caching with dual-mode support (Live Redis Server + Persistent Local Cache File)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._lock = threading.RLock()
        self._redis_client: Any = None
        self._redis_connected = False
        self._file_cache: dict[str, dict[str, Any]] = {}
        self._file_path = self.settings.redis_path

        # Initialize local file cache storage
        self._init_file_cache()

        # Attempt live Redis connection
        self._init_redis_client()

    def _init_file_cache(self) -> None:
        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            if self._file_path.exists():
                data = json.loads(self._file_path.read_text(encoding="utf-8"))
                now = time.time()
                # Clean up expired items
                self._file_cache = {
                    k: v for k, v in data.items() if v.get("expires_at", float("inf")) > now
                }
            else:
                self._file_cache = {}
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not load local redis cache file", extra={"error": str(exc)})
            self._file_cache = {}

    def _flush_file_cache(self) -> None:
        try:
            with self._lock:
                now = time.time()
                valid = {k: v for k, v in self._file_cache.items() if v.get("expires_at", float("inf")) > now}
                self._file_path.write_text(json.dumps(valid, indent=2, default=str), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not flush local redis cache file", extra={"error": str(exc)})

    def _init_redis_client(self) -> None:
        if not REDIS_INSTALLED or not redis:
            log.info("Redis package not installed or disabled; using persistent file cache fallback")
            return

        try:
            if self.settings.redis_url:
                self._redis_client = redis.from_url(self.settings.redis_url, decode_responses=True)
            else:
                self._redis_client = redis.Redis(
                    host=self.settings.redis_host,
                    port=self.settings.redis_port,
                    db=self.settings.redis_db,
                    password=self.settings.redis_password,
                    decode_responses=True,
                    socket_timeout=2.0,
                    socket_connect_timeout=2.0,
                )
            # Test ping
            self._redis_client.ping()
            self._redis_connected = True
            log.info("Connected to live Redis cache server", extra={"host": self.settings.redis_host, "port": self.settings.redis_port})
        except Exception as exc:  # noqa: BLE001
            self._redis_connected = False
            self._redis_client = None
            log.info("Live Redis server not reachable, using durable local redis_cache.json", extra={"reason": str(exc)})

    @property
    def is_live_redis(self) -> bool:
        return self._redis_connected and self._redis_client is not None

    @property
    def mode(self) -> str:
        return "redis_live" if self.is_live_redis else "redis_file_persistent"

    # -- Core Cache Operations ----------------------------------------------

    def get(self, key: str) -> dict | list | None:
        """Retrieve key from Redis or file fallback. Returns None if missing/expired."""
        # 1. Try Live Redis
        if self.is_live_redis:
            try:
                val = self._redis_client.get(key)
                if val is not None:
                    return json.loads(val)
            except Exception as exc:  # noqa: BLE001
                log.warning("Redis get error, falling back to local cache", extra={"error": str(exc)})

        # 2. Try Local File Cache
        with self._lock:
            entry = self._file_cache.get(key)
            if entry:
                if entry.get("expires_at", float("inf")) > time.time():
                    return entry.get("payload")
                del self._file_cache[key]
        return None

    def set(self, key: str, payload: Any, ttl_seconds: int | None = None) -> None:
        """Store key in Redis and local persistent cache with TTL."""
        ttl = ttl_seconds if ttl_seconds is not None else self.settings.redis_ttl_seconds
        payload_json = json.dumps(payload, default=str)

        # 1. Set in Live Redis
        if self.is_live_redis:
            try:
                self._redis_client.setex(key, ttl, payload_json)
            except Exception as exc:  # noqa: BLE001
                log.warning("Redis set error", extra={"error": str(exc)})

        # 2. Save in Local File Cache
        with self._lock:
            self._file_cache[key] = {
                "payload": payload,
                "expires_at": time.time() + ttl,
                "cached_at": time.time(),
            }
            self._flush_file_cache()

    def delete(self, key: str) -> None:
        if self.is_live_redis:
            try:
                self._redis_client.delete(key)
            except Exception:  # noqa: BLE001
                pass
        with self._lock:
            self._file_cache.pop(key, None)
            self._flush_file_cache()

    def clear(self) -> None:
        if self.is_live_redis:
            try:
                self._redis_client.flushdb()
            except Exception:  # noqa: BLE001
                pass
        with self._lock:
            self._file_cache.clear()
            self._flush_file_cache()

    # -- Coordinate & Mireye Fetch Helpers ----------------------------------

    def coord_key(self, lat: float, lon: float) -> str:
        """Canonical Redis key for coordinate location profile."""
        return f"mireye:coord:{lat:.5f}:{lon:.5f}"

    def fetch_key(self, lat: float, lon: float, provider_names: list[str]) -> str:
        """Canonical Redis key for specific coordinate field fetch."""
        fields_str = ",".join(sorted(provider_names))
        return f"mireye:fetch:{lat:.5f}:{lon:.5f}:{fields_str}"

    def geocode_key(self, address: str) -> str:
        """Canonical Redis key for address geocode."""
        norm_addr = address.strip().lower()
        return f"mireye:geocode:{norm_addr}"

    def get_cached_coordinates_fetch(
        self, lat: float, lon: float, provider_names: list[str]
    ) -> tuple[dict[str, Any] | None, list[str]]:
        """
        Checks Redis for coordinates data.
        Returns (cached_fields_map, list_of_fields_missing_from_cache).
        """
        # Check specific fetch key first
        exact_key = self.fetch_key(lat, lon, provider_names)
        cached_payload = self.get(exact_key)
        if cached_payload and isinstance(cached_payload, dict) and "fields" in cached_payload:
            return cached_payload, []

        # Check aggregate coordinate profile
        coord_key = self.coord_key(lat, lon)
        loc_profile = self.get(coord_key)
        if loc_profile and isinstance(loc_profile, dict) and "fields" in loc_profile:
            cached_fields = loc_profile["fields"]
            missing = [name for name in provider_names if name not in cached_fields]
            if not missing:
                # All requested fields are present in the cached coordinate profile!
                return {
                    "lat": lat,
                    "lng": lon,
                    "fetched_at": loc_profile.get("fetched_at"),
                    "fields": {k: cached_fields[k] for k in provider_names if k in cached_fields},
                }, []
            return None, missing

        return None, provider_names

    def set_cached_coordinates_fetch(
        self, lat: float, lon: float, provider_names: list[str], payload: dict[str, Any], ttl_seconds: int | None = None
    ) -> None:
        """Caches fetch response under both exact query key and aggregate coordinate profile."""
        ttl = ttl_seconds if ttl_seconds is not None else self.settings.redis_ttl_seconds

        # 1. Cache exact fetch key
        exact_key = self.fetch_key(lat, lon, provider_names)
        self.set(exact_key, payload, ttl_seconds=ttl)

        # 2. Update aggregate coordinate profile
        coord_key = self.coord_key(lat, lon)
        existing = self.get(coord_key) or {"lat": lat, "lng": lon, "fields": {}}
        if isinstance(existing, dict):
            fields_map = existing.setdefault("fields", {})
            new_fields = payload.get("fields", {})
            if isinstance(new_fields, dict):
                fields_map.update(new_fields)
            existing["fetched_at"] = payload.get("fetched_at")
            self.set(coord_key, existing, ttl_seconds=ttl)

    def get_cached_geocode(self, address: str) -> dict[str, Any] | None:
        key = self.geocode_key(address)
        return self.get(key)

    def set_cached_geocode(self, address: str, payload: dict[str, Any], ttl_seconds: int | None = None) -> None:
        key = self.geocode_key(address)
        ttl = ttl_seconds or (86400 * 30)  # 30 days for geocodes
        self.set(key, payload, ttl_seconds=ttl)


_redis_cache_instance: RedisCacheManager | None = None


def get_redis_cache() -> RedisCacheManager:
    global _redis_cache_instance
    if _redis_cache_instance is None:
        _redis_cache_instance = RedisCacheManager()
    return _redis_cache_instance


def set_redis_cache(manager: RedisCacheManager | None) -> None:
    global _redis_cache_instance
    _redis_cache_instance = manager
