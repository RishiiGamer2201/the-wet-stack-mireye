"""Opt-in live test against the real Mireye API. Skipped by default.

    RUN_MIREYE_LIVE_TESTS=1 python -m pytest tests/test_mireye_live.py -q -s

WARNING — THIS SPENDS CREDITS ON YOUR MIREYE ACCOUNT.
Mireye bills 1 credit per field per location. This module deliberately keeps the
cost to a handful of credits:

  * one location only (Cascade Flats, the demo's leading candidate);
  * three ordinary fields;
  * nothing from the `parcel_record` group, which costs 300 credits per location;
  * the catalog is free and unauthenticated, so it is not counted.

Everything else about the contract is pinned offline by `test_mireye_contract.py`
against recorded fixtures. This test exists to catch the provider changing its
contract underneath us, not to exercise logic.
"""

from __future__ import annotations

import os

import pytest
from app.adapters.mireye import LiveMireyeClient
from app.config import Settings
from app.fields import FIELD_INDEX
from app.store import Store

LIVE = os.getenv("RUN_MIREYE_LIVE_TESTS") == "1"

pytestmark = pytest.mark.skipif(
    not LIVE,
    reason="live Mireye test is opt-in and consumes credits; set RUN_MIREYE_LIVE_TESTS=1",
)

#: ONE location, always. Cascade Flats, the demo's leading candidate. There is no
#: sweep here and no loop over sites: a second location doubles the bill and adds
#: nothing, because this test checks the contract, not the data.
LAT, LNG = 47.4235, -120.3103
LOCATIONS = 1
#: 3 credits. Deliberately small, and none is in the parcel_record group.
FIELDS = ["elevation_m", "mean_slope_pct", "flood_zone"]


@pytest.fixture(scope="module")
def live_client() -> LiveMireyeClient:
    settings = Settings()
    if not settings.mireye_live:
        pytest.skip("MIREYE_BASE_URL / MIREYE_API_KEY are not configured")
    assert not settings.mireye_include_parcel_fields, (
        "MIREYE_INCLUDE_PARCEL_FIELDS is on — the parcel_record group bills 300 "
        "credits per location. Refusing to run the live test with it enabled."
    )
    print(
        f"\n*** LIVE MIREYE TEST ***"
        f"\n  target      : {settings.mireye_base_url}"
        f"\n  locations   : {LOCATIONS} ({LAT}, {LNG})"
        f"\n  fields      : {FIELDS}"
        f"\n  parcel group: excluded"
        f"\n  estimated   : ~{LOCATIONS * len(FIELDS)} credits ***"
    )
    # A real store so the response cache is shared across the tests below and
    # the second call costs nothing.
    return LiveMireyeClient(settings, Store(":memory:"))


def test_live_catalog_still_identifies_fields_by_name(live_client):
    """Free: /v1/meta/fields needs no authentication and bills nothing."""
    names = live_client.catalog_names()
    assert len(names) > 250
    assert "elevation" in names


def test_every_mapping_still_exists_in_the_live_catalog(live_client):
    """The mapping is only valid while the provider still has these fields."""
    names = live_client.catalog_names()
    for spec in FIELD_INDEX.values():
        if spec.provider_field:
            assert spec.provider_field in names, f"{spec.key} -> {spec.provider_field} disappeared"


def test_live_fetch_returns_converted_values_with_provenance(live_client):
    """~3 credits: one location, three ordinary fields."""
    result = live_client.fetch(LAT, LNG, FIELDS)
    assert result.mode == "live"

    elevation = result.values["elevation_m"]
    assert elevation.status in ("live", "cached")
    assert 0 < elevation.value < 5000
    assert elevation.unit == "m"
    assert elevation.provider_field == "elevation"
    assert elevation.provider_unit == "meters"
    assert elevation.provider_value == pytest.approx(elevation.value)

    slope = result.values["mean_slope_pct"]
    assert slope.provider_field == "slope_degrees"
    assert slope.provider_unit == "degrees"
    # Converted, so the stored value must differ from the provider's reading.
    assert slope.value != slope.provider_value
    assert 0 <= slope.value < 100

    print(
        f"\n  elevation  {elevation.provider_value} m -> {elevation.value} m"
        f"\n  slope      {slope.provider_value} deg -> {slope.value:.4f} %"
        f"\n  unavailable: {result.unavailable}"
    )


def test_live_null_field_is_reported_unavailable_not_zero(live_client):
    """Served from the cache populated above — no additional credits."""
    result = live_client.fetch(LAT, LNG, FIELDS)
    # Cascade Flats sits outside any NFHL flood polygon, so FEMA returns null.
    assert "flood_zone" in result.unavailable
    assert "flood_zone" not in result.values
