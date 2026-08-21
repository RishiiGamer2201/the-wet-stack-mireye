"""Public-dataset adapters.

Offline against a recorded PeeringDB fixture. The autouse network guard in
conftest means a real download inside a test fails loudly rather than quietly
depending on a third party.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from app.adapters.datasets import (
    PeeringDBFacilities,
    WaterQualityPortal,
    haversine_km,
    set_dataset_providers,
)
from app.domain import (
    CandidateSite,
    Evidence,
    EvidenceRelation,
    EvidenceStatus,
    SiteObservation,
    SourceType,
)
from app.services.sites import fetch_dataset_fields
from app.store import C, Store

FIXTURES = Path(__file__).parent / "fixtures" / "datasets"
FIXTURE = FIXTURES / "peeringdb_sample.json"
WQP_CSV = FIXTURES / "wqp_tds_sample.csv"

# Cascade Flats, the demo's leading candidate.
CASCADE = (47.4235, -120.3103)
# Ashburn, Virginia — the densest interconnection market in the US.
ASHBURN = (39.0164, -77.4590)


@pytest.fixture
def peeringdb() -> PeeringDBFacilities:
    return PeeringDBFacilities(path=FIXTURE)


@pytest.fixture(autouse=True)
def _only_this_provider(peeringdb):
    set_dataset_providers([peeringdb])
    yield
    set_dataset_providers(None)


def test_haversine_matches_a_known_distance():
    # New York to Los Angeles is ~3936 km great-circle.
    d = haversine_km(40.7128, -74.0060, 34.0522, -118.2437)
    assert math.isclose(d, 3936, rel_tol=0.01)
    assert haversine_km(*CASCADE, *CASCADE) == 0.0


def test_the_fixture_is_real_recorded_data():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert "peeringdb" in payload["_url"]
    assert payload["facilities"]
    for f in payload["facilities"]:
        assert f["latitude"] and f["longitude"]
        assert (f["ix_count"] or 0) > 0, "only exchange-hosting facilities belong here"


def test_a_dense_market_is_close_to_an_exchange(peeringdb):
    values = peeringdb.values_for(*ASHBURN)
    d = values["distance_to_ix_km"]
    assert d.value < 25, "Ashburn should be within a few km of an exchange"
    assert d.unit == "km"
    assert d.source_url.startswith("https://www.peeringdb.com/fac/")
    assert "CC-BY" in d.licence
    assert "internet exchange" in (d.detail or "")


def test_a_remote_site_is_further_but_still_measured(peeringdb):
    values = peeringdb.values_for(*CASCADE)
    if values:  # within MAX_USEFUL_KM of Seattle/Portland in the sample
        assert values["distance_to_ix_km"].value > 100


def test_a_location_with_nothing_nearby_returns_nothing_not_a_number(peeringdb):
    """Mid-Pacific. A distance here would score as though an exchange existed."""
    assert peeringdb.values_for(0.0, -160.0) == {}


def test_a_missing_download_degrades_quietly():
    provider = PeeringDBFacilities(path=Path("does-not-exist.json"))
    assert provider.available is False
    assert provider.values_for(*ASHBURN) == {}


def test_dataset_values_become_observations_scoring_can_read(store: Store, seeded):
    site = CandidateSite(
        project_id=seeded.id, name="Ashburn", latitude=ASHBURN[0], longitude=ASHBURN[1]
    )
    store.put(C.SITES, site, project_id=seeded.id)
    result = fetch_dataset_fields(store, seeded, site, ["distance_to_ix_km"])

    assert result["ok"] and result["evidence_ids"]
    observations = store.list(C.OBSERVATIONS, SiteObservation, project_id=seeded.id, parent_id=site.id)
    obs = next(o for o in observations if o.field_key == "distance_to_ix_km")
    assert obs.value is not None and obs.status != EvidenceStatus.MISSING

    from app.domain import Evidence

    evidence = store.list(C.EVIDENCE, Evidence, project_id=seeded.id, parent_id=site.id)
    ev = next(e for e in evidence if e.field_key == "distance_to_ix_km")
    assert ev.source.source_type == SourceType.EXTERNAL_DATASET
    assert ev.source.synthetic is False, "a public dataset is not synthetic data"
    assert ev.source.url and "Licence" in (ev.source.notes or "")


def test_a_site_without_coordinates_gets_nothing(store: Store, seeded):
    site = CandidateSite(project_id=seeded.id, name="Unlocated")
    result = fetch_dataset_fields(store, seeded, site, ["distance_to_ix_km"])
    assert result["evidence_ids"] == []


def test_latency_stays_an_open_gap_because_distance_is_not_latency():
    """Distance to an exchange does not answer round-trip latency; it depends on
    the route and the carrier. Serving one as the other is the wet-bulb mistake."""
    from app.fields import FIELD_INDEX

    assert FIELD_INDEX["latency_to_ix_ms"].provider_availability == "unavailable"
    assert FIELD_INDEX["distance_to_ix_km"].provider == "peeringdb"
    note = FIELD_INDEX["latency_to_ix_ms"].provider_note
    assert "cannot be derived from distance" in note


# --- Water Quality Portal --------------------------------------------------


@pytest.fixture
def wqp(tmp_path) -> WaterQualityPortal:
    """Reads a cache seeded from a real recorded response. Fetching is disabled,
    so a test can never reach the network or depend on the Portal being up."""
    provider = WaterQualityPortal(path=tmp_path / "wqp.json", allow_fetch=False)
    best = WaterQualityPortal._best_result(WQP_CSV.read_text(encoding="utf-8"))
    provider._cache = {
        provider._key(*CASCADE): {"result": best, "queried_at": "2026-08-21T00:00:00+00:00"}
    }
    return provider


def test_the_recorded_response_yields_the_most_recent_mgl_reading():
    best = WaterQualityPortal._best_result(WQP_CSV.read_text(encoding="utf-8"))
    assert best is not None
    assert best["value"] > 0
    assert best["station"], "the reading must name the station it came from"
    assert len(best["date"]) == 10


def test_non_mgl_units_and_censored_values_are_discarded():
    """'tons/ac ft' is the same sample in another unit and '<5' is a detection
    limit. Reading either as mg/L would invent a number."""
    csv_text = (
        "MonitoringLocationIdentifier,ActivityStartDate,ResultMeasureValue,"
        "ResultMeasure/MeasureUnitCode,MonitoringLocationName,OrganizationFormalName\n"
        "USGS-1,2024-01-01,0.48,tons/ac ft,Well A,USGS\n"
        "USGS-2,2023-01-01,<5,mg/l,Well B,USGS\n"
        "USGS-3,2022-01-01,188,mg/l,Well C,USGS\n"
    )
    best = WaterQualityPortal._best_result(csv_text)
    assert best["value"] == 188.0 and best["station"] == "USGS-3"


def test_tds_is_contextual_not_the_sites_own_water(wqp):
    value = wqp.values_for(*CASCADE)["water_quality_tds_mg_l"]
    assert value.relation is EvidenceRelation.CONTEXTUAL_PROXY
    assert value.unit == "mg/l"
    assert "not from this" in (value.relation_note or "")
    assert "mg/L sampled" in (value.detail or "")


def test_an_uncached_location_returns_nothing_when_fetching_is_off(wqp):
    assert wqp.values_for(0.0, -160.0) == {}


def test_a_proxy_is_recorded_as_evidence_but_never_becomes_an_observation(
    store: Store, seeded, wqp
):
    """The wet-bulb rule: a real, cited, *different* measurement is readable but
    cannot populate the concept, close its gap or move a score."""
    set_dataset_providers([wqp])
    site = CandidateSite(
        project_id=seeded.id, name="Cascade Flats", latitude=CASCADE[0], longitude=CASCADE[1]
    )
    store.put(C.SITES, site, project_id=seeded.id)

    result = fetch_dataset_fields(store, seeded, site, ["water_quality_tds_mg_l"])
    assert result["evidence_ids"], "the reading is worth showing"
    assert result["detail"]["fields"] == [], "but it populates no field"
    assert result["detail"]["context_only"] == 1
    assert "context only" in result["summary"]

    evidence = store.list(C.EVIDENCE, Evidence, project_id=seeded.id, parent_id=site.id)
    ev = next(e for e in evidence if e.field_key == "water_quality_tds_mg_l")
    assert ev.is_canonical is False
    assert ev.source.synthetic is False

    observations = store.list(
        C.OBSERVATIONS, SiteObservation, project_id=seeded.id, parent_id=site.id
    )
    assert not [o for o in observations if o.field_key == "water_quality_tds_mg_l"]


def test_an_old_reading_is_carried_at_lower_confidence(wqp):
    wqp._cache = {
        wqp._key(*CASCADE): {
            "result": {
                "value": 350.0,
                "date": "2006-07-18",
                "station": "USGS-1",
                "station_name": "Old Well",
                "organization": "USGS",
            },
            "queried_at": "2026-08-21T00:00:00+00:00",
        }
    }
    value = wqp.values_for(*CASCADE)["water_quality_tds_mg_l"]
    assert value.confidence == 0.5
    assert "years old" in value.detail
