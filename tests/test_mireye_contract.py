"""Contract tests for the real Mireye REST API.

Every expectation here is taken from a recorded response in
`tests/fixtures/mireye/`, captured from https://api.mireye.com. They are the
reason the adapter looks the way it does: the previously *assumed* payload
shapes were wrong on five separate points, and each one is pinned below.

No test in this file performs a network call. The opt-in live test lives in
`test_mireye_live.py`.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import httpx
import pytest
from app.adapters.mireye import (
    LiveMireyeClient,
    MireyeContractError,
    MireyeError,
    MockMireyeClient,
)
from app.config import Settings
from app.domain import EvidenceRelation
from app.fields import FIELD_INDEX, provider_fields, to_internal
from app.store import Store

FIXTURES = Path(__file__).parent / "fixtures" / "mireye"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def client(handler, store: Store | None = None) -> LiveMireyeClient:
    """A LiveMireyeClient wired to a scripted transport — no sockets involved."""
    settings = Settings(
        mireye_base_url="https://api.mireye.test",
        mireye_api_key="test-key",
        mireye_max_retries=0,
    )
    transport = httpx.MockTransport(handler)
    http = httpx.Client(base_url=settings.mireye_base_url, transport=transport)
    return LiveMireyeClient(settings, store or Store(":memory:"), client=http)


def json_route(routes: dict[str, dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        body = routes.get(request.url.path)
        if body is None:
            return httpx.Response(404, json={"detail": "not found"})
        return httpx.Response(200, json=body)

    return handler


# ---------------------------------------------------------------------------
# 1. Catalog: entries are identified by `name`, not `key`
# ---------------------------------------------------------------------------


def test_catalog_entries_are_identified_by_name():
    meta = fixture("meta_fields")
    assert all("name" in f for f in meta["fields"])
    assert not any("key" in f for f in meta["fields"]), "the real catalog has no 'key'"
    assert len(meta["fields"]) == 306


def test_client_reads_the_catalog_by_name():
    c = client(json_route({"/v1/meta/fields": fixture("meta_fields")}))
    names = c.catalog_names()
    assert len(names) == 306
    assert "elevation" in names and "slope_degrees" in names
    assert "elevation_m" not in names, "our internal name is not a provider name"


# ---------------------------------------------------------------------------
# 2. Geocode: lat/lng/accuracy/normalized_address
# ---------------------------------------------------------------------------


def test_geocode_reads_the_real_response_shape():
    c = client(json_route({"/v1/geocode": fixture("geocode")}))
    result = c.geocode("1400 Grant Rd, East Wenatchee, WA")
    assert result.latitude == pytest.approx(47.405845)
    assert result.longitude == pytest.approx(-120.265701)
    assert result.formatted_address == "1400 Grant Rd, East Wenatchee, WA 98802"
    assert result.resolution == "range_interpolation"
    assert 0.0 <= result.confidence <= 1.0
    assert result.mode == "live"


def test_geocode_missing_coordinates_is_a_contract_error_not_a_crash():
    c = client(json_route({"/v1/geocode": {"normalized_address": "somewhere"}}))
    with pytest.raises(MireyeContractError):
        c.geocode("somewhere")


# ---------------------------------------------------------------------------
# 3. Fetch request: lat+lng OR address, never both
# ---------------------------------------------------------------------------


def test_fetch_sends_lat_lng_never_latitude_longitude():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/meta/fields":
            return httpx.Response(200, json=fixture("meta_fields"))
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=fixture("fetch_cascade_flats"))

    client(handler).fetch(47.4235, -120.3103, ["elevation_m"])
    assert seen["lat"] == 47.4235 and seen["lng"] == -120.3103
    assert "latitude" not in seen and "longitude" not in seen
    assert "address" not in seen, "coordinates and address must never be sent together"


def test_fetch_by_address_sends_no_coordinates():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/meta/fields":
            return httpx.Response(200, json=fixture("meta_fields"))
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=fixture("fetch_cascade_flats"))

    client(handler).fetch_by_address("1400 Grant Rd, East Wenatchee, WA", ["elevation_m"])
    assert seen["address"] == "1400 Grant Rd, East Wenatchee, WA"
    assert "lat" not in seen and "lng" not in seen


def test_fetch_translates_internal_names_to_provider_names():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/meta/fields":
            return httpx.Response(200, json=fixture("meta_fields"))
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=fixture("fetch_cascade_flats"))

    client(handler).fetch(47.4235, -120.3103, ["elevation_m", "mean_slope_pct", "flood_zone"])
    assert set(seen["fields"]) == {"elevation", "slope_degrees", "fema_flood_zone"}


# ---------------------------------------------------------------------------
# 4. Fetch response: values live under `fields`, confidence is a string
# ---------------------------------------------------------------------------


def test_fetch_reads_values_from_the_fields_envelope():
    c = client(
        json_route(
            {
                "/v1/meta/fields": fixture("meta_fields"),
                "/v1/fetch": fixture("fetch_cascade_flats"),
            }
        )
    )
    result = c.fetch(47.4235, -120.3103, ["elevation_m", "mean_slope_pct", "flood_zone"])

    assert result.mode == "live"
    elevation = result.values["elevation_m"]
    assert elevation.value == pytest.approx(203.6425018310547)
    assert elevation.unit == "m"
    assert elevation.status == "live"
    # Provenance keeps what the provider actually said.
    assert elevation.provider_field == "elevation"
    assert elevation.provider_value == pytest.approx(203.6425018310547)
    assert elevation.provider_unit == "meters"
    assert elevation.provider_confidence == "medium"
    assert elevation.source == "USGS_3DEP_COG"
    assert elevation.observed_at is not None


def test_string_confidence_becomes_a_number_without_crashing():
    c = client(
        json_route(
            {
                "/v1/meta/fields": fixture("meta_fields"),
                "/v1/fetch": fixture("fetch_cascade_flats"),
            }
        )
    )
    value = c.fetch(47.4235, -120.3103, ["elevation_m"]).values["elevation_m"]
    assert isinstance(value.confidence, float)
    assert 0.0 < value.confidence < 1.0
    assert value.provider_confidence == "medium"


def test_unparseable_confidence_is_a_contract_error():
    payload = json.loads(json.dumps(fixture("fetch_cascade_flats")))
    payload["fields"]["elevation"]["confidence"] = {"unexpected": "object"}
    c = client(json_route({"/v1/meta/fields": fixture("meta_fields"), "/v1/fetch": payload}))
    with pytest.raises(MireyeContractError):
        c.fetch(47.4235, -120.3103, ["elevation_m"])


def test_null_provider_value_becomes_unavailable_not_zero():
    c = client(
        json_route(
            {
                "/v1/meta/fields": fixture("meta_fields"),
                "/v1/fetch": fixture("fetch_cascade_flats"),
            }
        )
    )
    result = c.fetch(47.4235, -120.3103, ["elevation_m", "flood_zone"])
    assert "flood_zone" in result.unavailable
    assert "flood_zone" not in result.values
    assert result.values["elevation_m"].value != 0


def test_a_field_the_provider_omits_entirely_is_unavailable():
    payload = json.loads(json.dumps(fixture("fetch_cascade_flats")))
    del payload["fields"]["slope_degrees"]
    c = client(json_route({"/v1/meta/fields": fixture("meta_fields"), "/v1/fetch": payload}))
    result = c.fetch(47.4235, -120.3103, ["elevation_m", "mean_slope_pct"])
    assert "mean_slope_pct" in result.unavailable


def test_malformed_envelope_is_a_contract_error_so_fallback_can_catch_it():
    c = client(
        json_route({"/v1/meta/fields": fixture("meta_fields"), "/v1/fetch": {"totally": "wrong"}})
    )
    with pytest.raises(MireyeContractError):
        c.fetch(47.4235, -120.3103, ["elevation_m"])


def test_contract_error_is_a_mireye_error():
    assert issubclass(MireyeContractError, MireyeError)


# ---------------------------------------------------------------------------
# 5. Ask: no citations array in the real response
# ---------------------------------------------------------------------------


def test_ask_reads_the_real_response_shape():
    c = client(json_route({"/v1/ask": fixture("ask")}))
    answer = c.ask("What is the terrain like here?", 47.4235, -120.3103)
    assert "gently rolling" in answer.answer
    assert answer.citations == []  # the real API returns none; we must not invent any
    assert answer.mode == "live"


# ---------------------------------------------------------------------------
# Unit conversion at the provider boundary
# ---------------------------------------------------------------------------


def test_slope_degrees_converts_to_percent_by_tangent():
    assert to_internal("mean_slope_pct", 2.4269587993621826) == pytest.approx(
        math.tan(math.radians(2.4269587993621826)) * 100
    )
    assert to_internal("mean_slope_pct", 0.0) == 0.0
    assert to_internal("mean_slope_pct", 45.0) == pytest.approx(100.0)


def test_metre_distances_convert_to_kilometres():
    assert to_internal("distance_to_substation_km", 2300.0) == pytest.approx(2.3)
    assert to_internal("distance_to_highway_km", 0.0) == 0.0


def test_centimetre_depth_converts_to_metres():
    assert to_internal("depth_to_bedrock_m", 650.0) == pytest.approx(6.5)


def test_identity_mappings_are_untouched():
    assert to_internal("elevation_m", 203.64) == pytest.approx(203.64)
    assert to_internal("seismic_pga_g", 0.12) == pytest.approx(0.12)


def test_categorical_values_are_normalised_to_our_vocabulary():
    assert to_internal("soil_drainage_class", "Well drained") == "well_drained"
    assert to_internal("soil_drainage_class", "Moderately well drained") == "moderately_well_drained"
    assert to_internal("flood_zone", "AE") == "AE"


def test_null_converts_to_null_never_zero():
    for key in ("mean_slope_pct", "distance_to_substation_km", "depth_to_bedrock_m", "flood_zone"):
        assert to_internal(key, None) is None


# ---------------------------------------------------------------------------
# Concept mapping
# ---------------------------------------------------------------------------

#: Named in the task, and each verified present in the recorded 306-field catalog.
REQUIRED_PROVIDER_FIELDS = {
    "elevation",
    "slope_degrees",
    "fema_flood_zone",
    "nearest_substation_distance_m",
    "seismic_pga_2pct_50yr_g",
    "wetland_fraction_of_parcel",
    "parcel_zoning",
    "design_wet_bulb_temperature_0_4pct_degc",
}


def test_every_required_provider_field_is_mapped():
    mapped = {s.provider_field for s in FIELD_INDEX.values() if s.provider_field}
    assert REQUIRED_PROVIDER_FIELDS <= mapped


def test_no_mapping_invents_a_field_absent_from_the_catalog():
    catalog = {f["name"] for f in fixture("meta_fields")["fields"]}
    for spec in FIELD_INDEX.values():
        if spec.provider_field:
            assert spec.provider_field in catalog, f"{spec.key} -> {spec.provider_field} is not real"


def test_concepts_without_a_provider_equivalent_are_declared_unavailable():
    for key in (
        "grid_capacity_mw",
        "latency_to_ix_ms",
        "permit_lead_time_months",
        "incentive_score",
        "jurisdiction_complexity_index",
        "water_stress_index",
    ):
        spec = FIELD_INDEX[key]
        assert spec.provider_field is None
        assert spec.provider_availability == "unavailable"


def test_billed_parcel_fields_are_mapped_but_excluded_from_the_default_request():
    for key in ("wetland_fraction", "zoning_class"):
        spec = FIELD_INDEX[key]
        assert spec.provider_field is not None
        assert spec.provider_availability == "billed_extra"
    requested = set(provider_fields(FIELD_INDEX))
    assert "parcel_zoning" not in requested
    assert "wetland_fraction_of_parcel" not in requested


def test_semantic_proxy_mappings_are_labelled():
    spec = FIELD_INDEX["ambient_design_db_c"]
    assert spec.provider_field == "design_wet_bulb_temperature_0_4pct_degc"
    assert spec.provider_availability == "proxy"
    assert spec.provider_note and "wet-bulb" in spec.provider_note.lower()
    assert spec.relation == EvidenceRelation.CONTEXTUAL_PROXY


# ---------------------------------------------------------------------------
# Mock parity: the offline path must be unaffected
# ---------------------------------------------------------------------------


def test_mock_still_speaks_internal_field_names():
    result = MockMireyeClient().fetch(47.4235, -120.3103, ["elevation_m", "flood_zone"])
    assert result.values["elevation_m"].status == "synthetic"
    assert result.mode == "mock"
