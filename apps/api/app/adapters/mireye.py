"""Mireye client abstraction.

OBSERVED REQUEST/RESPONSE CONTRACT
----------------------------------
These shapes are recorded from the live service at https://api.mireye.com, not
assumed. The fixtures behind them are in `tests/fixtures/mireye/` and are pinned
by `tests/test_mireye_contract.py`.

    GET  /v1/meta/fields  -> {"billing", "fields": [{"name","unit","type","layer",
                              "nullable","null_meaning","source","presets", ...}],
                              "presets", "us_envelope", "version"}
                             NOTE: entries are identified by `name`. There is no `key`.

    POST /v1/geocode      {"address"}
                          -> {"lat","lng","accuracy","accuracy_type","match_type",
                              "normalized_address","provider","source"}

    POST /v1/fetch        {"lat","lng","fields":[...]}  OR  {"address","fields":[...]}
                          Sending coordinates *and* an address is rejected with 422.
                          -> {"lat","lng","fetched_at",
                              "fields": {name: {"value","unit","source","source_url",
                                                "confidence","fetched_at",
                                                "dataset_vintage","ttl_seconds",
                                                "notes","status"}}}
                             NOTE: there is no `results` map and no `unavailable`
                             list. An absent value is `value: null`, and
                             `confidence` is a word such as "medium".

    POST /v1/ask          {"question","lat"?,"lng"?}
                          -> {"lat","lng","question","answered_at","answer"}
                             NOTE: no citations array.

    POST /v1/ask/stream   same as /ask, streamed
    POST /v1/feature-requests  {"field","reason","context"} -> {"id","status"}

The `/v1/sites` endpoints are documented by Mireye but unused here and remain
unverified; they are marked as such in `docs/mireye-contract.md`.

Rules enforced here:
  * the live catalog is the only source of legal provider field names;
  * our internal concept names are translated to provider names on the way out
    and back on the way in — the two vocabularies never mix;
  * a null or omitted provider value becomes MISSING, never a zero;
  * a response that does not match the shapes above raises MireyeContractError,
    so the fallback client degrades instead of the request dying on a KeyError;
  * every observation keeps the provider's own field, value, unit, confidence
    word, source and timestamp alongside the converted value.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from ..config import Settings, get_settings
from ..domain import EvidenceRelation
from ..fields import CONVERSIONS, FIELD_INDEX, FIELDS, UnknownFieldError, to_internal
from ..store import Store, get_store
from .rediscache import get_redis_cache

UTC = timezone.utc

log = logging.getLogger("mireye")


# ---------------------------------------------------------------------------
# Typed provider payloads
#
# These mirror the responses recorded in tests/fixtures/mireye/, captured from
# https://api.mireye.com. Validation failures become MireyeContractError so the
# fallback client can degrade instead of the request dying on a KeyError.
# ---------------------------------------------------------------------------


class ProviderPayload(BaseModel):
    # Mireye adds attributes over time; unknown ones are kept, not rejected.
    model_config = ConfigDict(extra="allow")


class GeocodeResponse(ProviderPayload):
    lat: float
    lng: float
    accuracy: float | None = None
    accuracy_type: str | None = None
    match_type: str | None = None
    normalized_address: str | None = None
    provider: str | None = None
    source: str | None = None


class ProviderField(ProviderPayload):
    """One field inside a /v1/fetch response's `fields` map."""

    value: float | int | str | bool | None = None
    unit: str | None = None
    source: str | None = None
    source_url: str | None = None
    confidence: Any = None  # a word such as "medium", occasionally a number
    fetched_at: datetime | None = None
    dataset_vintage: str | None = None
    ttl_seconds: int | None = None
    notes: str | None = None
    status: str | None = None


class FetchResponse(ProviderPayload):
    lat: float | None = None
    lng: float | None = None
    fetched_at: datetime | None = None
    # The assumed contract called this `results` and paired it with an
    # `unavailable` list. Neither exists: absence is a null value in here.
    # Required: the live API always returns it, so a response without one is a
    # drifted contract rather than an empty result.
    fields: dict[str, ProviderField]


class AskResponse(ProviderPayload):
    answer: str = ""
    question: str | None = None
    lat: float | None = None
    lng: float | None = None
    answered_at: datetime | None = None


class MireyeError(RuntimeError):
    """Any failure talking to Mireye. Callers degrade to a gap, never to a guess."""


class MireyeUnavailableError(MireyeError):
    pass


class MireyeContractError(MireyeError):
    """The service answered, but not in the shape this adapter understands.

    Raised for response-validation, missing-key, invalid-type and
    confidence-parsing failures — the specific, expected ways a provider
    contract drifts. It derives from MireyeError so FallbackMireyeClient
    degrades gracefully, and it is deliberately narrow: an unrelated
    programming bug must still surface as itself.
    """


#: Mireye reports confidence as a word. Scoring needs a number, and the word is
#: kept alongside it so the original is never lost.
#: Mireye's `parcel_record` billing group: 300 credits per location instead of 1
#: per field. Named here so a request can be costed before it is sent.
PARCEL_RECORD_FIELDS = frozenset(
    {"wetland_fraction_of_parcel", "parcel_zoning", "parcel_area_m2", "parcel_apn",
     "parcel_address", "parcel_boundary_geojson", "parcel_geometry_wkt",
     "parcel_data_source", "developable_acres_proxy",
     "onsite_solar_potential_mwac_low", "onsite_solar_potential_mwac_high"}
)

CONFIDENCE_WORDS: dict[str, float] = {
    "very_high": 0.95, "very high": 0.95,
    "high": 0.85,
    "medium": 0.65, "moderate": 0.65,
    "low": 0.4,
    "very_low": 0.2, "very low": 0.2,
    "unknown": 0.3,
}


def parse_confidence(raw: Any, default: float = 0.6) -> float:
    """Accept the word form, the numeric form, or nothing.

    Anything else is a contract change, not a value to guess at.
    """
    if raw is None:
        return default
    if isinstance(raw, bool):
        raise MireyeContractError(f"confidence must be a number or a word, got {raw!r}")
    if isinstance(raw, (int, float)):
        value = float(raw)
        return value / 100.0 if value > 1.0 else value
    if isinstance(raw, str):
        word = raw.strip().lower()
        if word in CONFIDENCE_WORDS:
            return CONFIDENCE_WORDS[word]
        try:
            return parse_confidence(float(word), default)
        except ValueError as exc:
            raise MireyeContractError(f"unrecognised confidence {raw!r}") from exc
    raise MireyeContractError(f"confidence has unexpected type {type(raw).__name__}")


@dataclass
class FieldValue:
    """One physical-world value plus everything needed to trace it.

    `value`/`unit` are what scoring uses; every `provider_*` attribute is what
    Mireye actually said, kept so a converted number can always be audited back
    to its source.
    """

    field_key: str
    value: float | str | None
    unit: str | None
    confidence: float
    observed_at: datetime | None
    retrieved_at: datetime
    source: str
    status: str  # live | cached | synthetic | fallback | missing
    latitude: float | None = None
    longitude: float | None = None
    endpoint: str = "/v1/fetch"
    note: str | None = None
    #: How this reading relates to the concept. CONTEXTUAL_PROXY values are
    #: recorded and displayed but never populate the concept's canonical value.
    relation: EvidenceRelation = EvidenceRelation.EXACT
    # -- provenance from the provider, pre-conversion ------------------------
    provider_field: str | None = None
    provider_value: float | str | None = None
    provider_unit: str | None = None
    provider_confidence: str | None = None
    provider_source_url: str | None = None
    provider_dataset_vintage: str | None = None


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


#: /v1/ask writes prose rather than returning a stored field, so it takes tens of
#: seconds. Sharing /fetch's timeout made every question look like an outage.
ASK_TIMEOUT_SECONDS = 90.0


class LiveMireyeClient:
    """HTTP client with timeout, bounded retries, and a response cache.

    Any failure is raised as :class:`MireyeError`; the caller records an
    InformationGap rather than substituting a value.
    """

    mode = "live"

    def __init__(
        self,
        settings: Settings,
        store: Store,
        client: httpx.Client | None = None,
        redis_cache: Any = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self._is_memory = str(getattr(store, "path", "")) == ":memory:"
        self.redis_cache = redis_cache or (None if self._is_memory else get_redis_cache())
        self._client = client or httpx.Client(
            base_url=settings.mireye_base_url or "",
            timeout=settings.mireye_timeout_seconds,
            headers={"Authorization": f"Bearer {settings.mireye_api_key}"},
        )

    # -- plumbing -----------------------------------------------------------
    def _request(
        self, method: str, path: str, payload: dict | None = None, timeout: float | None = None
    ) -> dict:
        last: Exception | None = None
        for attempt in range(self.settings.mireye_max_retries + 1):
            try:
                response = self._client.request(method, path, json=payload, timeout=timeout)
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
        hit = None
        if self.redis_cache:
            hit = self.redis_cache.get(key)
        if hit is None:
            hit = self.store.cache_get(key)
        if hit is not None:
            return hit, True
        fresh = builder()
        if self.redis_cache:
            self.redis_cache.set(key, fresh, self.settings.mireye_cache_ttl_seconds)
        self.store.cache_set(key, fresh, self.settings.mireye_cache_ttl_seconds)
        return fresh, False

    # -- endpoints ----------------------------------------------------------
    def meta_fields(self) -> list[dict[str, Any]]:
        payload, _ = self._cached(
            "mireye:meta:fields", lambda: self._request("GET", "/v1/meta/fields")
        )
        fields = payload.get("fields")
        if not isinstance(fields, list):
            raise MireyeContractError("/v1/meta/fields did not return a 'fields' list")
        return fields

    def catalog_names(self) -> set[str]:
        """Provider field names, from the catalog's `name` attribute.

        The assumed contract read `key`; the real catalog has no such attribute.
        """
        names = {f.get("name") for f in self.meta_fields() if isinstance(f, dict)}
        names.discard(None)
        if not names:
            raise MireyeContractError("catalog entries carry no 'name'")
        return names

    def geocode(self, address: str) -> GeocodeResult:
        if self.redis_cache:
            cached_data = self.redis_cache.get_cached_geocode(address)
            if cached_data is not None:
                try:
                    payload = GeocodeResponse.model_validate(cached_data)
                    return GeocodeResult(
                        latitude=payload.lat,
                        longitude=payload.lng,
                        resolution=payload.accuracy_type or payload.match_type or "unknown",
                        formatted_address=payload.normalized_address or address,
                        confidence=parse_confidence(payload.accuracy, default=0.7),
                        mode="cached",
                    )
                except Exception:  # noqa: BLE001
                    pass

        data = self._request("POST", "/v1/geocode", {"address": address})
        try:
            payload = GeocodeResponse.model_validate(data)
        except ValidationError as exc:
            raise MireyeContractError(f"/v1/geocode response did not validate: {exc}") from exc

        # Save into Redis cache after task completion
        if self.redis_cache:
            self.redis_cache.set_cached_geocode(address, data)

        return GeocodeResult(
            latitude=payload.lat,
            longitude=payload.lng,
            resolution=payload.accuracy_type or payload.match_type or "unknown",
            formatted_address=payload.normalized_address or address,
            confidence=parse_confidence(payload.accuracy, default=0.7),
            mode="live",
        )

    def _to_observation(
        self,
        internal_key: str,
        provider_field: str,
        raw: ProviderField,
        latitude: float | None,
        longitude: float | None,
        cached: bool,
    ) -> FieldValue:
        spec = FIELD_INDEX[internal_key]
        try:
            value = to_internal(internal_key, raw.value)
        except (TypeError, ValueError, KeyError) as exc:
            raise MireyeContractError(
                f"{provider_field}: cannot convert {raw.value!r} for {internal_key}: {exc}"
            ) from exc
        note = spec.provider_note
        if spec.conversion != "identity":
            conversion = CONVERSIONS[spec.conversion][0]
            note = f"Converted {raw.value} {raw.unit or ''} ({conversion}). {note or ''}".strip()
        return FieldValue(
            field_key=internal_key,
            value=value,
            unit=spec.internal_unit,
            confidence=parse_confidence(raw.confidence),
            observed_at=raw.fetched_at,
            retrieved_at=datetime.now(UTC),
            source=raw.source or "mireye",
            status="cached" if cached else "live",
            latitude=latitude,
            longitude=longitude,
            note=note,
            relation=spec.relation,
            provider_field=provider_field,
            provider_value=raw.value,
            provider_unit=raw.unit,
            provider_confidence=raw.confidence if isinstance(raw.confidence, str) else None,
            provider_source_url=raw.source_url,
            provider_dataset_vintage=raw.dataset_vintage,
        )

    def _read_fetch(
        self,
        payload: dict,
        requested: list[str],
        latitude: float | None,
        longitude: float | None,
        cached: bool,
        started: float,
    ) -> FetchResult:
        try:
            response = FetchResponse.model_validate(payload)
        except ValidationError as exc:
            raise MireyeContractError(f"/v1/fetch response did not validate: {exc}") from exc

        result = FetchResult(mode="live", latency_ms=int((time.perf_counter() - started) * 1000))
        for internal_key in requested:
            spec = FIELD_INDEX[internal_key]
            provider_field = spec.provider_field
            raw = response.fields.get(provider_field) if provider_field else None
            # A null value is a real absence the provider is telling us about,
            # and an omitted field is one it never answered. Both are missing —
            # neither is a zero.
            if raw is None or raw.value is None:
                result.unavailable.append(internal_key)
                continue
            result.values[internal_key] = self._to_observation(
                internal_key,
                provider_field,
                raw,
                latitude if latitude is not None else response.lat,
                longitude if longitude is not None else response.lng,
                cached,
            )
        return result

    def _partition(self, fields: list[str]) -> tuple[list[str], list[str], list[str]]:
        """Split requested concepts into (requestable, provider names, skipped).

        Skipped covers both concepts Mireye has no field for and the ones in its
        300-credit parcel_record group when those are not enabled. Either way the
        caller turns them into InformationGaps rather than values.
        """
        unknown = [f for f in fields if f not in FIELD_INDEX]
        if unknown:
            raise UnknownFieldError(f"unknown Mireye field(s): {', '.join(unknown)}")
        allowed = {"mapped", "proxy"}
        if self.settings.mireye_include_parcel_fields:
            allowed.add("billed_extra")
        requestable = [f for f in fields if FIELD_INDEX[f].provider_availability in allowed]
        skipped = [f for f in fields if f not in requestable]
        return requestable, [FIELD_INDEX[f].provider_field for f in requestable], skipped

    def _log_plan(self, provider_names: list[str], where: str) -> None:
        """State what is about to be billed, before it is billed.

        Field names and a coordinate only — never the key, never a header.
        """
        billed = sorted(set(provider_names) & PARCEL_RECORD_FIELDS)
        log.info(
            "mireye fetch planned",
            extra={
                "location": where,
                "field_count": len(provider_names),
                "fields": sorted(provider_names),
                "billed_extra_group": billed,
                "estimated_credits": len(provider_names) - len(billed) + 300 * len(billed),
            },
        )

    def fetch(
        self, latitude: float, longitude: float, fields: list[str], site_id: str | None = None
    ) -> FetchResult:
        mapped, provider_names, unmapped = self._partition(fields)
        if not provider_names:
            return FetchResult(mode="live", unavailable=list(unmapped))

        catalog = self.catalog_names()
        missing = [n for n in provider_names if n not in catalog]
        if missing:
            raise MireyeContractError(
                f"mapped field(s) absent from the live catalog: {', '.join(missing)}"
            )

        started = time.perf_counter()
        cache_key = f"mireye:fetch:{latitude:.5f}:{longitude:.5f}:{','.join(sorted(provider_names))}"

        # 1. First check Redis cache (or store cache) for coordinates
        cached_payload = None
        if self.redis_cache:
            cached_payload, missing_from_cache = self.redis_cache.get_cached_coordinates_fetch(
                latitude, longitude, provider_names
            )
            if missing_from_cache:
                cached_payload = None
        if cached_payload is None:
            cached_payload = self.store.cache_get(cache_key)

        if cached_payload is not None:
            log.info(
                "Mireye coordinates fetch served from cache",
                extra={"lat": latitude, "lon": longitude, "fields_count": len(provider_names)},
            )
            result = self._read_fetch(cached_payload, mapped, latitude, longitude, cached=True, started=started)
            result.unavailable.extend(unmapped)
            return result

        # 2. Cache miss -> call live Mireye API
        self._log_plan(provider_names, f"{latitude:.5f},{longitude:.5f}")
        payload = self._request(
            "POST", "/v1/fetch", {"lat": latitude, "lng": longitude, "fields": provider_names}
        )

        # 3. Add details to Redis cache upon task completion
        if self.redis_cache:
            self.redis_cache.set_cached_coordinates_fetch(latitude, longitude, provider_names, payload)
        self.store.cache_set(cache_key, payload, self.settings.mireye_cache_ttl_seconds)

        result = self._read_fetch(payload, mapped, latitude, longitude, cached=False, started=started)
        result.unavailable.extend(unmapped)
        return result

    def fetch_by_address(self, address: str, fields: list[str]) -> FetchResult:
        """Let Mireye resolve the address server-side with Redis cache verification."""
        mapped, provider_names, unmapped = self._partition(fields)
        if not provider_names:
            return FetchResult(mode="live", unavailable=list(unmapped))

        cache_key = f"mireye:fetch:addr:{address.strip().lower()}:{','.join(sorted(provider_names))}"
        started = time.perf_counter()

        # Check cache first
        hit = None
        if self.redis_cache:
            hit = self.redis_cache.get(cache_key)
        if hit is None:
            hit = self.store.cache_get(cache_key)
        if hit is not None and isinstance(hit, dict):
            result = self._read_fetch(hit, mapped, None, None, cached=True, started=started)
            result.unavailable.extend(unmapped)
            return result

        # Fetch from API
        payload = self._request("POST", "/v1/fetch", {"address": address, "fields": provider_names})

        # Save to Redis & store cache
        if self.redis_cache:
            self.redis_cache.set(cache_key, payload, ttl_seconds=self.settings.mireye_cache_ttl_seconds)
        self.store.cache_set(cache_key, payload, self.settings.mireye_cache_ttl_seconds)

        result = self._read_fetch(payload, mapped, None, None, cached=False, started=started)
        result.unavailable.extend(unmapped)
        return result

    def ask(self, question, latitude=None, longitude=None) -> AskResult:
        # /v1/ask rejects a body with neither coordinates nor an address (HTTP
        # 422). Failing here keeps the reason legible instead of surfacing as a
        # provider error that silently degrades to the local stand-in.
        if latitude is None or longitude is None:
            raise MireyeError(
                "/v1/ask needs a location: pass a site with resolved coordinates, "
                "or geocode an address first."
            )
        body: dict[str, Any] = {"question": question, "lat": latitude, "lng": longitude}
        data = self._request("POST", "/v1/ask", body, timeout=ASK_TIMEOUT_SECONDS)
        try:
            payload = AskResponse.model_validate(data)
        except ValidationError as exc:
            raise MireyeContractError(f"/v1/ask response did not validate: {exc}") from exc
        return AskResult(
            answer=payload.answer,
            # The real response carries no citations. Returning an empty list is
            # honest; inventing one would put unsourced text next to sourced data.
            citations=[],
            confidence=0.6,
            mode="live",
        )

    def ask_stream(self, question, latitude=None, longitude=None) -> Iterator[str]:
        if latitude is None or longitude is None:
            raise MireyeError("/v1/ask/stream needs a location, same as /v1/ask.")
        body: dict[str, Any] = {"question": question, "lat": latitude, "lng": longitude}
        with self._client.stream(
            "POST", "/v1/ask/stream", json=body, timeout=ASK_TIMEOUT_SECONDS
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
        """Record a gap — at most once per field, and locally by default.

        A site investigation re-runs freely and every run finds the same unmapped
        concepts, so the first submission is remembered and replayed rather than
        re-sent. The remote call is off unless MIREYE_ENABLE_FEATURE_REQUESTS is
        set: unlike /fetch and /geocode, this endpoint's payload has never been
        verified against the live service, so posting to it would be guesswork
        against someone else's API.
        """
        cache_key = f"mireye:feature-request:{field_key}"
        existing = self.store.cache_get(cache_key)
        if existing is not None:
            return {**existing, "deduplicated": True}
        if not self.settings.mireye_enable_feature_requests:
            payload = {
                "id": "local_" + hashlib.sha256(field_key.encode()).hexdigest()[:10],
                "status": "recorded_locally",
                "field": field_key,
                "reason": reason,
                "note": "Not sent: /v1/feature-requests has an unverified contract. "
                "Set MIREYE_ENABLE_FEATURE_REQUESTS=true once it is confirmed.",
            }
            self.store.cache_set(cache_key, payload, 30 * 24 * 3600)
            return payload
        payload = self._request(
            "POST", "/v1/feature-requests", {"field": field_key, "reason": reason, "context": context}
        )
        # Long TTL: the point is to avoid resubmitting the same gap for the life
        # of the deployment, not to cache a value.
        self.store.cache_set(cache_key, payload, 30 * 24 * 3600)
        return payload


class FallbackMireyeClient:
    """Live-first, local-on-failure.

    Values served by the fallback are marked `fallback`, never `live` and never
    `synthetic`: they came from the deterministic local stand-in *because a
    configured live service failed*, and the UI has to be able to say so. The
    failure is recorded on `self.degraded_reason`.
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
            # MireyeContractError lands here too, so a drifted provider contract
            # degrades instead of failing the investigation. Anything that is not
            # a Mireye/transport problem is a bug and is left to propagate.
            self.degraded_reason = f"{type(exc).__name__}: {exc}"
            self.mode = "degraded_fallback"
            log.warning(
                "mireye degraded to local fallback",
                extra={"call": name, "error": str(exc), "kind": type(exc).__name__},
            )
            result = getattr(self.mock, name)(*args, **kwargs)
            return self._relabel(result)

    @staticmethod
    def _relabel(result):
        """Mark stand-in values `fallback`, so they can never read as live data."""
        if isinstance(result, FetchResult):
            for value in result.values.values():
                value.status = "fallback"
                value.note = (
                    "Live Mireye was configured but unavailable; this is a deterministic "
                    "local stand-in, not an observation."
                )
        elif isinstance(result, AskResult):
            # `mock` reads as "this deployment has no credentials". It does, and
            # they failed, which is a different thing and the UI must say which.
            result.mode = "degraded_fallback"
        return result

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
