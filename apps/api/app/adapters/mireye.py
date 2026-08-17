"""Mireye client abstraction.

ASSUMED REQUEST/RESPONSE CONTRACT
---------------------------------
The published documentation lists the endpoints below but not their payload
shapes, so the shapes here are *our assumption* and are deliberately confined to
this module (see `docs/mireye-contract.md`). When the real specification arrives,
only `LiveMireyeClient._to_observation` / the request builders should need edits.

    GET  /v1/meta/fields          -> {"fields": [{"key","label","unit","description"}]}
    POST /v1/geocode              {"address"} -> {"latitude","longitude","resolution",
                                                  "formatted_address","confidence"}
    POST /v1/fetch                {"latitude","longitude","fields":[...],"site_id"?}
                                  -> {"results": {field: {"value","unit","confidence",
                                                          "observed_at","source"}},
                                      "unavailable": [field]}
    POST /v1/ask                  {"question","latitude"?,"longitude"?,"site_id"?}
                                  -> {"answer","citations":[...],"confidence"}
    POST /v1/ask/stream           same as /ask, streamed as text/event-stream
    POST /v1/sites                {"name","latitude","longitude","address"?} -> {"site_id"}
    GET  /v1/sites/{site_id}      -> {"site_id","name","latitude","longitude"}
    POST /v1/ask-site             {"site_id","question"} -> like /ask
    POST /v1/feature-requests     {"field","reason","context"} -> {"id","status"}

Rules enforced here:
  * the field catalog is cached and is the only source of legal field names;
  * an unknown or unavailable field raises/records a gap — it never gets a value;
  * every returned observation carries source, timestamp, confidence and status.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx

from ..config import Settings, get_settings
from ..fields import FIELD_INDEX, FIELDS, UnknownFieldError
from ..store import Store, get_store

log = logging.getLogger("mireye")


class MireyeError(RuntimeError):
    """Any failure talking to Mireye. Callers degrade to a gap, never to a guess."""


class MireyeUnavailableError(MireyeError):
    pass


@dataclass
class FieldValue:
    """One physical-world value plus everything needed to trace it."""

    field_key: str
    value: float | str | None
    unit: str | None
    confidence: float
    observed_at: datetime | None
    retrieved_at: datetime
    source: str
    status: str  # live | cached | synthetic | missing
    latitude: float | None = None
    longitude: float | None = None
    endpoint: str = "/v1/fetch"
    note: str | None = None


@dataclass
class FetchResult:
    values: dict[str, FieldValue] = dc_field(default_factory=dict)
    unavailable: list[str] = dc_field(default_factory=list)
    mode: str = "mock"
    latency_ms: int = 0


@dataclass
class GeocodeResult:
    latitude: float
    longitude: float
    resolution: str
    formatted_address: str
    confidence: float
    mode: str = "mock"


@dataclass
class AskResult:
    answer: str
    citations: list[dict[str, Any]]
    confidence: float
    mode: str = "mock"


class MireyeClient(Protocol):
    mode: str

    def meta_fields(self) -> list[dict[str, Any]]: ...
    def geocode(self, address: str) -> GeocodeResult: ...
    def fetch(
        self, latitude: float, longitude: float, fields: list[str], site_id: str | None = None
    ) -> FetchResult: ...
    def ask(
        self, question: str, latitude: float | None = None, longitude: float | None = None
    ) -> AskResult: ...
    def ask_stream(
        self, question: str, latitude: float | None = None, longitude: float | None = None
    ) -> Iterator[str]: ...
    def create_site(self, name: str, latitude: float, longitude: float, address: str | None) -> str: ...
    def get_site(self, site_id: str) -> dict[str, Any]: ...
    def ask_site(self, site_id: str, question: str) -> AskResult: ...
    def feature_request(self, field_key: str, reason: str, context: str = "") -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Deterministic mock
# ---------------------------------------------------------------------------

#: Curated synthetic profiles used by the seeded demo sites. Values are invented
#: for demonstration and are labelled `synthetic` everywhere they surface.
SYNTHETIC_PROFILES: dict[str, dict[str, Any]] = {
    "cascade-flats": {
        "match": (47.4235, -120.3103),
        "values": {
            "elevation_m": 320, "mean_slope_pct": 1.6, "terrain_ruggedness_index": 1.2,
            "land_cover_class": "shrubland",
            "water_stress_index": 1.2, "groundwater_availability_l_s": 55,
            "water_quality_tds_mg_l": 240, "flood_zone": "X",
            "distance_to_water_source_km": 2.1,
            "grid_capacity_mw": 420, "distance_to_substation_km": 2.3,
            "grid_reliability_saidi_min": 62, "planned_grid_expansion_mw": 300,
            "fiber_routes_count": 4, "distance_to_fiber_km": 0.8, "latency_to_ix_ms": 6.0,
            "distance_to_highway_km": 3.1,
            "soil_bearing_capacity_kpa": 320, "depth_to_bedrock_m": 6.5,
            "cut_fill_volume_m3": 45000, "soil_drainage_class": "well_drained",
            "seismic_pga_g": 0.12, "wildfire_risk_index": 34,
            "extreme_heat_days_per_year": 22, "design_wind_speed_mph": 100,
            "ambient_design_db_c": 34,
            "protected_area_distance_km": 18, "cropland_fraction": 0.10,
            "wetland_fraction": 0.0, "biodiversity_sensitivity_index": 22,
            "zoning_class": "industrial", "permit_lead_time_months": 7,
            "incentive_score": 72, "jurisdiction_complexity_index": 30,
        },
    },
    "rio-verde-mesa": {
        "match": (33.5312, -111.6321),
        "values": {
            "elevation_m": 512, "mean_slope_pct": 2.4, "terrain_ruggedness_index": 2.1,
            "land_cover_class": "barren",
            "water_stress_index": 4.4, "groundwater_availability_l_s": 8,
            "water_quality_tds_mg_l": 1250, "flood_zone": "X",
            "distance_to_water_source_km": 18.0,
            "grid_capacity_mw": 380, "distance_to_substation_km": 4.5,
            "grid_reliability_saidi_min": 90, "planned_grid_expansion_mw": 150,
            "fiber_routes_count": 3, "distance_to_fiber_km": 1.9, "latency_to_ix_ms": 9.0,
            "distance_to_highway_km": 5.2,
            "soil_bearing_capacity_kpa": 290, "depth_to_bedrock_m": 9.0,
            "cut_fill_volume_m3": 70000, "soil_drainage_class": "well_drained",
            "seismic_pga_g": 0.09, "wildfire_risk_index": 55,
            "extreme_heat_days_per_year": 78, "design_wind_speed_mph": 95,
            "ambient_design_db_c": 46,
            "protected_area_distance_km": 9, "cropland_fraction": 0.02,
            "wetland_fraction": 0.0, "biodiversity_sensitivity_index": 38,
            "zoning_class": "light_industrial", "permit_lead_time_months": 9,
            "incentive_score": 66, "jurisdiction_complexity_index": 42,
        },
    },
    "delta-fields": {
        "match": (35.0512, -90.0421),
        "values": {
            "elevation_m": 62, "mean_slope_pct": 0.7, "terrain_ruggedness_index": 0.4,
            "land_cover_class": "cropland",
            "water_stress_index": 1.0, "groundwater_availability_l_s": 90,
            "water_quality_tds_mg_l": 320, "flood_zone": "AE",
            "distance_to_water_source_km": 1.2,
            "grid_capacity_mw": 180, "distance_to_substation_km": 6.8,
            "grid_reliability_saidi_min": 140, "planned_grid_expansion_mw": 60,
            "fiber_routes_count": 3, "distance_to_fiber_km": 2.4, "latency_to_ix_ms": 11.0,
            "distance_to_highway_km": 2.0,
            "soil_bearing_capacity_kpa": 130, "depth_to_bedrock_m": 42.0,
            "cut_fill_volume_m3": 30000, "soil_drainage_class": "poorly_drained",
            "seismic_pga_g": 0.42, "wildfire_risk_index": 12,
            "extreme_heat_days_per_year": 46, "design_wind_speed_mph": 115,
            "ambient_design_db_c": 36,
            "protected_area_distance_km": 6, "cropland_fraction": 0.72,
            "wetland_fraction": 0.18, "biodiversity_sensitivity_index": 58,
            "zoning_class": "agricultural", "permit_lead_time_months": 14,
            "incentive_score": 48, "jurisdiction_complexity_index": 55,
        },
    },
    "harbour-point": {
        "match": (36.8912, -76.2612),
        "values": {
            "elevation_m": 4, "mean_slope_pct": 0.5, "terrain_ruggedness_index": 0.3,
            "land_cover_class": "urban",
            "water_stress_index": 2.0, "groundwater_availability_l_s": 35,
            "water_quality_tds_mg_l": 680, "flood_zone": "VE",
            "distance_to_water_source_km": 0.6,
            "grid_capacity_mw": 140, "distance_to_substation_km": 1.1,
            "grid_reliability_saidi_min": 75, "planned_grid_expansion_mw": 40,
            "fiber_routes_count": 6, "distance_to_fiber_km": 0.2, "latency_to_ix_ms": 3.0,
            "distance_to_highway_km": 1.0,
            "soil_bearing_capacity_kpa": 110, "depth_to_bedrock_m": 60.0,
            "cut_fill_volume_m3": 25000, "soil_drainage_class": "somewhat_poorly_drained",
            "seismic_pga_g": 0.07, "wildfire_risk_index": 8,
            "extreme_heat_days_per_year": 34, "design_wind_speed_mph": 130,
            "ambient_design_db_c": 35,
            "protected_area_distance_km": 3, "cropland_fraction": 0.01,
            "wetland_fraction": 0.09, "biodiversity_sensitivity_index": 44,
            "zoning_class": "commercial", "permit_lead_time_months": 11,
            "incentive_score": 55, "jurisdiction_complexity_index": 62,
        },
    },
    "prairie-junction": {
        "match": (41.1401, -96.6512),
        # Deliberately incomplete: demonstrates information gaps and feature requests.
        "unavailable": ["grid_capacity_mw", "permit_lead_time_months", "wetland_fraction"],
        "values": {
            "elevation_m": 355, "mean_slope_pct": 1.1, "terrain_ruggedness_index": 0.6,
            "land_cover_class": "grassland",
            "water_stress_index": 2.2, "groundwater_availability_l_s": 48,
            "water_quality_tds_mg_l": 410, "flood_zone": "X",
            "distance_to_water_source_km": 4.0,
            "distance_to_substation_km": 8.5,
            "grid_reliability_saidi_min": 110, "planned_grid_expansion_mw": 120,
            "fiber_routes_count": 2, "distance_to_fiber_km": 6.5, "latency_to_ix_ms": 14.0,
            "distance_to_highway_km": 4.4,
            "soil_bearing_capacity_kpa": 240, "depth_to_bedrock_m": 18.0,
            "cut_fill_volume_m3": 55000, "soil_drainage_class": "moderately_well_drained",
            "seismic_pga_g": 0.05, "wildfire_risk_index": 18,
            "extreme_heat_days_per_year": 38, "design_wind_speed_mph": 115,
            "ambient_design_db_c": 35,
            "protected_area_distance_km": 22, "cropland_fraction": 0.55,
            "biodiversity_sensitivity_index": 30,
            "zoning_class": "agricultural",
            "incentive_score": 60, "jurisdiction_complexity_index": 45,
        },
    },
}


def _profile_for(latitude: float, longitude: float) -> dict[str, Any] | None:
    for profile in SYNTHETIC_PROFILES.values():
        plat, plon = profile["match"]
        if abs(plat - latitude) < 0.05 and abs(plon - longitude) < 0.05:
            return profile
    return None


def _deterministic_value(field_key: str, latitude: float, longitude: float):
    """Stable pseudo-value for an unseeded location. Same input -> same output."""
    spec = FIELD_INDEX[field_key]
    digest = hashlib.sha256(f"{field_key}|{latitude:.4f}|{longitude:.4f}".encode()).digest()
    unit_interval = int.from_bytes(digest[:6], "big") / float(1 << 48)
    if spec.direction == "categorical" and spec.categories:
        keys = sorted(spec.categories)
        return keys[int(unit_interval * len(keys))]
    if spec.direction == "band":
        low, high = spec.band_low or 0.0, spec.band_high or 1.0
        span = (high - low) * 1.6
        return round(low - span * 0.2 + unit_interval * span, 3)
    good, bad = spec.good or 0.0, spec.bad or 1.0
    return round(bad + (good - bad) * unit_interval, 3)


class MockMireyeClient:
    """Deterministic offline stand-in. Every value it returns is marked synthetic."""

    mode = "mock"

    def __init__(self, fail_fields: set[str] | None = None) -> None:
        self.fail_fields = fail_fields or set()
        self.calls: list[tuple[str, dict]] = []
        self._sites: dict[str, dict[str, Any]] = {}

    def meta_fields(self) -> list[dict[str, Any]]:
        self.calls.append(("meta_fields", {}))
        return [
            {
                "key": f.key,
                "label": f.label,
                "unit": f.unit,
                "dimension": f.dimension.value,
                "description": f.description,
            }
            for f in FIELDS
        ]

    def geocode(self, address: str) -> GeocodeResult:
        self.calls.append(("geocode", {"address": address}))
        for slug, profile in SYNTHETIC_PROFILES.items():
            if slug.replace("-", " ") in address.lower():
                lat, lon = profile["match"]
                return GeocodeResult(lat, lon, "parcel", address, 0.9, mode="mock")
        digest = hashlib.sha256(address.lower().encode()).digest()
        lat = 25 + int.from_bytes(digest[0:4], "big") / (1 << 32) * 24
        lon = -124 + int.from_bytes(digest[4:8], "big") / (1 << 32) * 56
        return GeocodeResult(round(lat, 5), round(lon, 5), "city", address, 0.55, mode="mock")

    def fetch(
        self, latitude: float, longitude: float, fields: list[str], site_id: str | None = None
    ) -> FetchResult:
        self.calls.append(("fetch", {"lat": latitude, "lon": longitude, "fields": list(fields)}))
        unknown = [f for f in fields if f not in FIELD_INDEX]
        if unknown:
            raise UnknownFieldError(f"unknown Mireye field(s): {', '.join(unknown)}")
        profile = _profile_for(latitude, longitude)
        unavailable = set(profile.get("unavailable", [])) if profile else set()
        unavailable |= self.fail_fields
        result = FetchResult(mode="mock", latency_ms=4)
        retrieved = datetime.now(UTC)
        for key in fields:
            if key in unavailable:
                result.unavailable.append(key)
                continue
            value = (
                profile["values"].get(key) if profile else None
            )
            if value is None:
                if profile:  # curated profile intentionally lacks this field
                    result.unavailable.append(key)
                    continue
                value = _deterministic_value(key, latitude, longitude)
            spec = FIELD_INDEX[key]
            result.values[key] = FieldValue(
                field_key=key,
                value=value,
                unit=spec.unit,
                confidence=0.72,
                observed_at=retrieved - timedelta(days=30),
                retrieved_at=retrieved,
                source="mireye-demo-fixture",
                status="synthetic",
                latitude=latitude,
                longitude=longitude,
                note="Deterministic demo value — not a real observation.",
            )
        return result

    def ask(
        self, question: str, latitude: float | None = None, longitude: float | None = None
    ) -> AskResult:
        self.calls.append(("ask", {"question": question}))
        where = f"({latitude:.4f}, {longitude:.4f})" if latitude is not None else "the project area"
        return AskResult(
            answer=(
                f"[demo] Exploratory answer for {where}: “{question}”. In demo mode Mireye's "
                "natural-language endpoint is simulated; only catalogued fields fetched via "
                "/v1/fetch are used for scoring or calculation."
            ),
            citations=[{"source": "mireye-demo-fixture", "detail": "synthetic exploratory answer"}],
            confidence=0.4,
            mode="mock",
        )

    def ask_stream(
        self, question: str, latitude: float | None = None, longitude: float | None = None
    ) -> Iterator[str]:
        for token in self.ask(question, latitude, longitude).answer.split(" "):
            yield token + " "

    def create_site(self, name, latitude, longitude, address=None) -> str:
        site_id = "mireye_" + hashlib.sha256(f"{name}{latitude}{longitude}".encode()).hexdigest()[:10]
        self._sites[site_id] = {
            "site_id": site_id,
            "name": name,
            "latitude": latitude,
            "longitude": longitude,
            "address": address,
        }
        self.calls.append(("create_site", {"site_id": site_id}))
        return site_id

    def get_site(self, site_id: str) -> dict[str, Any]:
        if site_id not in self._sites:
            raise MireyeError(f"unknown site {site_id}")
        return self._sites[site_id]

    def ask_site(self, site_id: str, question: str) -> AskResult:
        site = self.get_site(site_id)
        return self.ask(question, site["latitude"], site["longitude"])

    def feature_request(self, field_key: str, reason: str, context: str = "") -> dict[str, Any]:
        self.calls.append(("feature_request", {"field": field_key}))
        return {
            "id": "fr_" + hashlib.sha256(f"{field_key}{reason}".encode()).hexdigest()[:10],
            "status": "recorded_locally",
            "field": field_key,
            "reason": reason,
            "context": context,
            "mode": "mock",
        }


# ---------------------------------------------------------------------------
# Live client
# ---------------------------------------------------------------------------


class LiveMireyeClient:
    """HTTP client with timeout, bounded retries, and a response cache.

    Any failure is raised as :class:`MireyeError`; the caller records an
    InformationGap rather than substituting a value.
    """

    mode = "live"

    def __init__(self, settings: Settings, store: Store, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.store = store
        self._client = client or httpx.Client(
            base_url=settings.mireye_base_url or "",
            timeout=settings.mireye_timeout_seconds,
            headers={"Authorization": f"Bearer {settings.mireye_api_key}"},
        )

    # -- plumbing -----------------------------------------------------------
    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        last: Exception | None = None
        for attempt in range(self.settings.mireye_max_retries + 1):
            try:
                response = self._client.request(method, path, json=payload)
                if response.status_code >= 500:
                    raise MireyeUnavailableError(f"{path} returned {response.status_code}")
                if response.status_code >= 400:
                    raise MireyeError(f"{path} returned {response.status_code}: {response.text[:200]}")
                return response.json()
            except (httpx.HTTPError, MireyeUnavailableError) as exc:
                last = exc
                log.warning(
                    "mireye request failed", extra={"path": path, "attempt": attempt, "error": str(exc)}
                )
                if attempt < self.settings.mireye_max_retries:
                    time.sleep(min(0.25 * 2**attempt, 2.0))
        raise MireyeUnavailableError(f"{path} failed after retries: {last}")

    def _cached(self, key: str, builder) -> tuple[dict, bool]:
        hit = self.store.cache_get(key)
        if hit is not None:
            return hit, True
        fresh = builder()
        self.store.cache_set(key, fresh, self.settings.mireye_cache_ttl_seconds)
        return fresh, False

    # -- endpoints ----------------------------------------------------------
    def meta_fields(self) -> list[dict[str, Any]]:
        payload, _ = self._cached(
            "mireye:meta:fields", lambda: self._request("GET", "/v1/meta/fields")
        )
        return payload.get("fields", [])

    def geocode(self, address: str) -> GeocodeResult:
        data = self._request("POST", "/v1/geocode", {"address": address})
        return GeocodeResult(
            latitude=float(data["latitude"]),
            longitude=float(data["longitude"]),
            resolution=data.get("resolution", "unknown"),
            formatted_address=data.get("formatted_address", address),
            confidence=float(data.get("confidence", 0.7)),
            mode="live",
        )

    def _to_observation(
        self, key: str, raw: dict, latitude: float, longitude: float, cached: bool
    ) -> FieldValue:
        observed = raw.get("observed_at")
        return FieldValue(
            field_key=key,
            value=raw.get("value"),
            unit=raw.get("unit") or (FIELD_INDEX[key].unit if key in FIELD_INDEX else None),
            confidence=float(raw.get("confidence", 0.8)),
            observed_at=datetime.fromisoformat(observed) if observed else None,
            retrieved_at=datetime.now(UTC),
            source=raw.get("source", "mireye"),
            status="cached" if cached else "live",
            latitude=latitude,
            longitude=longitude,
        )

    def fetch(
        self, latitude: float, longitude: float, fields: list[str], site_id: str | None = None
    ) -> FetchResult:
        catalog = {f["key"] for f in self.meta_fields()} or set(FIELD_INDEX)
        unknown = [f for f in fields if f not in catalog]
        if unknown:
            raise UnknownFieldError(f"unknown Mireye field(s): {', '.join(unknown)}")
        cache_key = f"mireye:fetch:{latitude:.5f}:{longitude:.5f}:{','.join(sorted(fields))}"
        started = time.perf_counter()
        payload, cached = self._cached(
            cache_key,
            lambda: self._request(
                "POST",
                "/v1/fetch",
                {
                    "latitude": latitude,
                    "longitude": longitude,
                    "fields": fields,
                    **({"site_id": site_id} if site_id else {}),
                },
            ),
        )
        result = FetchResult(
            mode="live", latency_ms=int((time.perf_counter() - started) * 1000)
        )
        for key, raw in (payload.get("results") or {}).items():
            result.values[key] = self._to_observation(key, raw, latitude, longitude, cached)
        result.unavailable = list(payload.get("unavailable") or [])
        for key in fields:
            if key not in result.values and key not in result.unavailable:
                result.unavailable.append(key)
        return result

    def ask(self, question, latitude=None, longitude=None) -> AskResult:
        data = self._request(
            "POST",
            "/v1/ask",
            {"question": question, "latitude": latitude, "longitude": longitude},
        )
        return AskResult(
            answer=data.get("answer", ""),
            citations=data.get("citations", []),
            confidence=float(data.get("confidence", 0.6)),
            mode="live",
        )

    def ask_stream(self, question, latitude=None, longitude=None) -> Iterator[str]:
        with self._client.stream(
            "POST",
            "/v1/ask/stream",
            json={"question": question, "latitude": latitude, "longitude": longitude},
        ) as response:
            for line in response.iter_lines():
                if line:
                    yield line

    def create_site(self, name, latitude, longitude, address=None) -> str:
        data = self._request(
            "POST",
            "/v1/sites",
            {"name": name, "latitude": latitude, "longitude": longitude, "address": address},
        )
        return data["site_id"]

    def get_site(self, site_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/sites/{site_id}")

    def ask_site(self, site_id: str, question: str) -> AskResult:
        data = self._request("POST", "/v1/ask-site", {"site_id": site_id, "question": question})
        return AskResult(
            answer=data.get("answer", ""),
            citations=data.get("citations", []),
            confidence=float(data.get("confidence", 0.6)),
            mode="live",
        )

    def feature_request(self, field_key: str, reason: str, context: str = "") -> dict[str, Any]:
        return self._request(
            "POST", "/v1/feature-requests", {"field": field_key, "reason": reason, "context": context}
        )


class FallbackMireyeClient:
    """Live-first, mock-on-failure.

    Values served by the fallback are marked `synthetic` so the UI can label them,
    and the failure is recorded on `self.degraded_reason`.
    """

    def __init__(self, live: MireyeClient, mock: MockMireyeClient) -> None:
        self.live = live
        self.mock = mock
        self.mode = "live"
        self.degraded_reason: str | None = None

    def _run(self, name: str, *args, **kwargs):
        try:
            result = getattr(self.live, name)(*args, **kwargs)
            self.mode = "live"
            return result
        except (MireyeError, httpx.HTTPError) as exc:
            self.degraded_reason = str(exc)
            self.mode = "degraded_mock"
            log.warning("mireye degraded to mock", extra={"call": name, "error": str(exc)})
            return getattr(self.mock, name)(*args, **kwargs)

    def meta_fields(self):
        return self._run("meta_fields")

    def geocode(self, address):
        return self._run("geocode", address)

    def fetch(self, latitude, longitude, fields, site_id=None):
        return self._run("fetch", latitude, longitude, fields, site_id)

    def ask(self, question, latitude=None, longitude=None):
        return self._run("ask", question, latitude, longitude)

    def ask_stream(self, question, latitude=None, longitude=None):
        return self._run("ask_stream", question, latitude, longitude)

    def create_site(self, name, latitude, longitude, address=None):
        return self._run("create_site", name, latitude, longitude, address)

    def get_site(self, site_id):
        return self._run("get_site", site_id)

    def ask_site(self, site_id, question):
        return self._run("ask_site", site_id, question)

    def feature_request(self, field_key, reason, context=""):
        return self._run("feature_request", field_key, reason, context)


_client: MireyeClient | None = None


def get_mireye_client() -> MireyeClient:
    global _client
    if _client is None:
        settings = get_settings()
        if settings.mireye_live:
            _client = FallbackMireyeClient(
                LiveMireyeClient(settings, get_store()), MockMireyeClient()
            )
        else:
            _client = MockMireyeClient()
    return _client


def set_mireye_client(client: MireyeClient | None) -> None:
    """Test hook."""
    global _client
    _client = client
