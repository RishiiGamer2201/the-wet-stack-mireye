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
    CountyLookup,
    EIAReliability,
    FEMANationalRiskIndex,
    PADUSProtectedAreas,
    PeeringDBFacilities,
    WaterQualityPortal,
    distance_to_rings_km,
    haversine_km,
    normalise_county,
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


# --- EIA-861 grid reliability ----------------------------------------------

# A square kilometre-ish box around a point, as PAD-US would return it.
def box(lat, lon, half_deg):
    return [
        [
            [lon - half_deg, lat - half_deg],
            [lon + half_deg, lat - half_deg],
            [lon + half_deg, lat + half_deg],
            [lon - half_deg, lat + half_deg],
            [lon - half_deg, lat - half_deg],
        ]
    ]


@pytest.fixture
def counties(tmp_path) -> CountyLookup:
    """Answers from a seeded cache; fetching is off so no test touches Census."""
    lookup = CountyLookup(path=tmp_path / "counties.json", allow_fetch=False)
    lookup._cache = {
        "39.016,-77.459": {"state": "VA", "county": "Loudoun", "fips": "51107"},
        "33.531,-111.632": {"state": "AZ", "county": "Maricopa", "fips": "04013"},
        "47.424,-120.310": {"state": "WA", "county": "Chelan", "fips": "53007"},
        "0.000,-160.000": None,
    }
    return lookup


@pytest.fixture
def eia(counties) -> EIAReliability:
    return EIAReliability(counties=counties)


def test_county_names_join_across_both_spellings():
    """Census says 'St. Louis city' and 'Doña Ana'; EIA says 'St Louis City' and
    'Dona Ana'. Without normalisation the join misses and real data looks absent."""
    assert normalise_county("St. Louis city") == normalise_county("St Louis City")
    assert normalise_county("Doña Ana") == normalise_county("Dona Ana")
    assert normalise_county("Loudoun County") == "LOUDOUN"
    assert normalise_county("East Baton Rouge Parish") == "EAST BATON ROUGE"


def test_the_bundled_reliability_table_is_real_eia_data(eia):
    payload = eia._load()
    assert "eia.gov" in payload["_url"]
    assert payload["utilities"] and payload["counties"]
    values = [u["saidi_without_med"] for u in payload["utilities"].values()]
    assert any(v is None for v in values), "'.' in the workbook means not reported"
    assert any(v and v > 100 for v in values), "and real outage minutes came through"
    # A handful of small municipal systems genuinely reported zero outage minutes.
    # That is a reported measurement, not a missing one — the two are different
    # values here and the loader must never collapse one into the other.
    assert all(v is None or v >= 0 for v in values)


def test_not_reported_is_none_and_never_zero(eia):
    """The whole rule in one assertion: '.' does not become 0.0."""
    from app.adapters.datasets import EIAReliability

    assert EIAReliability  # imported for clarity about what is under test
    payload = eia._load()
    reported_zero = [u for u in payload["utilities"].values() if u["saidi_without_med"] == 0.0]
    not_reported = [u for u in payload["utilities"].values() if u["saidi_without_med"] is None]
    assert reported_zero and not_reported, "both states must exist and be distinguishable"


def test_reliability_reports_the_worst_utility_in_the_county(eia):
    """Maricopa is served by several utilities whose SAIDI differs several-fold.
    A siting decision should not rest on the most flattering of them."""
    value = eia.values_for(33.5312, -111.6321)["grid_reliability_saidi_min"]
    payload = eia._load()
    served = [
        payload["utilities"][e]["saidi_without_med"]
        for e in payload["counties"]["AZ|MARICOPA"]
        if payload["utilities"][e]["saidi_without_med"] is not None
    ]
    assert value.value == max(served)
    assert value.unit == "minute"
    assert "utility(ies) reporting" in value.detail


def test_reliability_is_context_because_it_describes_a_territory_not_a_feeder(eia):
    value = eia.values_for(39.0164, -77.4590)["grid_reliability_saidi_min"]
    assert value.relation is EvidenceRelation.CONTEXTUAL_PROXY
    assert "feeder" in (value.relation_note or "")
    assert "Loudoun" in value.detail


def test_a_county_where_nobody_reported_stays_a_gap(eia):
    """Chelan County's utility filed the form without reliability figures. An
    absent number is not a good one."""
    assert eia.values_for(47.4235, -120.3103) == {}


def test_a_location_outside_the_us_returns_nothing(eia):
    assert eia.values_for(0.0, -160.0) == {}


# --- PAD-US protected areas -------------------------------------------------


def test_distance_to_a_polygon_is_zero_inside_it():
    rings = box(39.0, -77.0, 0.05)
    assert distance_to_rings_km(39.0, -77.0, rings) == 0.0


def test_distance_to_a_polygon_matches_the_haversine_to_its_edge():
    # A point 0.1 degrees west of a box that spans -77.05 to -76.95.
    rings = box(39.0, -77.0, 0.05)
    computed = distance_to_rings_km(39.0, -77.15, rings)
    expected = haversine_km(39.0, -77.15, 39.0, -77.05)
    assert computed == pytest.approx(expected, rel=0.02)


@pytest.fixture
def padus(tmp_path) -> PADUSProtectedAreas:
    return PADUSProtectedAreas(path=tmp_path / "padus.json", allow_fetch=False)


def test_a_cached_protected_area_is_reported_as_the_measurement(padus):
    padus._cache = {
        padus._key(*CASCADE): {
            "result": {
                "distance_km": 1.8,
                "unit_name": "WA State Parks Eastern",
                "designation": "SP",
                "manager": "SPR",
                "manager_type": "STAT",
                "gap_status": "3",
                "nearest_local": None,
            },
            "queried_at": "2026-08-22T00:00:00+00:00",
        }
    }
    value = padus.values_for(*CASCADE)["protected_area_distance_km"]
    # This is the measurement the concept asks for, unlike the Class I proxy it
    # replaces, so it is canonical.
    assert value.relation is EvidenceRelation.EXACT
    assert value.value == 1.8 and value.unit == "km"
    assert "WA State Parks Eastern" in value.detail
    assert "0.2 km" in value.detail, "the simplification error must be stated"


def test_being_inside_a_park_says_so_rather_than_reporting_a_small_number(padus):
    padus._cache = {
        padus._key(*CASCADE): {
            "result": {
                "distance_km": 0.0,
                "unit_name": "Yosemite National Park",
                "designation": "NP",
                "manager": "NPS",
                "manager_type": "FED",
                "gap_status": "1",
                "nearest_local": None,
            },
            "queried_at": "2026-08-22T00:00:00+00:00",
        }
    }
    value = padus.values_for(*CASCADE)["protected_area_distance_km"]
    assert value.value == 0.0
    assert "inside this protected area" in value.detail


def test_a_nearer_ball_field_is_excluded_but_never_hidden(padus):
    """A municipal diamond is a land-use neighbour, not an ecological
    constraint — but dropping it silently would be editing the evidence."""
    padus._cache = {
        padus._key(*CASCADE): {
            "result": {
                "distance_km": 5.65,
                "unit_name": "Broad Run Farms Open Space",
                "designation": "PCON",
                "manager": "UNK",
                "manager_type": "UNK",
                "gap_status": "3",
                "nearest_local": {"unit_name": "Chick Ford Field", "distance_km": 0.84},
            },
            "queried_at": "2026-08-22T00:00:00+00:00",
        }
    }
    value = padus.values_for(*CASCADE)["protected_area_distance_km"]
    assert value.value == 5.65
    assert "Chick Ford Field" in value.detail and "0.84" in value.detail
    assert "excluded as municipal recreation" in value.detail


def test_nothing_within_the_search_rings_reports_nothing(padus):
    padus._cache = {padus._key(*CASCADE): {"result": None, "queried_at": "2026-08-22T00:00:00+00:00"}}
    assert padus.values_for(*CASCADE) == {}


def test_recreation_designations_are_separated_from_conservation_land():
    """LCA is a Local Conservation Area and must stay in; LP is a Local Park."""
    assert "LP" in PADUSProtectedAreas.RECREATION_DESIGNATIONS
    assert "LCA" not in PADUSProtectedAreas.RECREATION_DESIGNATIONS
    assert "4" not in PADUSProtectedAreas.MEANINGFUL_GAP_STATUS


def test_all_providers_are_registered():
    from app.adapters.datasets import dataset_fields, get_dataset_providers

    set_dataset_providers(None)
    names = {p.name for p in get_dataset_providers()}
    assert names == {
        "peeringdb",
        "water_quality_portal",
        "eia_reliability",
        "padus",
        "fema_nri",
    }
    assert "protected_area_distance_km" in dataset_fields()
    assert "grid_reliability_saidi_min" in dataset_fields()
    assert "wildfire_risk_index" in dataset_fields()


# --- FEMA National Risk Index -----------------------------------------------


@pytest.fixture
def tracts(tmp_path) -> CountyLookup:
    lookup = CountyLookup(path=tmp_path / "tracts.json", allow_fetch=False)
    lookup._cache = {
        # Ashburn VA — FEMA rates this tract Very Low.
        "39.016,-77.459": {
            "state": "VA",
            "county": "Loudoun",
            "fips": "51107",
            "tract_fips": "51107611006",
            "tract": "6110.06",
        },
        # Rio Verde Mesa AZ — Very High, next to Tonto National Forest.
        "33.531,-111.632": {
            "state": "AZ",
            "county": "Maricopa",
            "fips": "04013",
            "tract_fips": "04013010102",
            "tract": "101.02",
        },
        # A point the geocoder placed in no US county at all.
        "0.000,-160.000": None,
        # An entry cached before tracts were requested: no tract_fips key.
        "1.000,-1.000": {"state": "XX", "county": "Nowhere", "fips": "99999"},
    }
    return lookup


@pytest.fixture
def nri(tracts) -> FEMANationalRiskIndex:
    return FEMANationalRiskIndex(counties=tracts)


def test_the_bundled_nri_table_is_real_fema_data(nri):
    payload = nri._load()
    assert "fema.gov" in payload["_url"]
    assert len(payload["tracts"]) > 80_000, "the national table covers every US tract"
    assert "WFIR_RISKS" in payload["_field"]


def test_wildfire_score_comes_with_femas_own_rating(nri):
    value = nri.values_for(39.0164, -77.4590)["wildfire_risk_index"]
    assert value.relation is EvidenceRelation.EXACT
    assert 0 <= value.value <= 100
    assert "Very Low" in value.detail
    assert "Loudoun County" in value.detail
    assert "non-linear" in value.detail, "the scale caveat travels with the value"


def test_a_high_risk_tract_scores_zero_and_a_low_risk_one_scores_full(nri):
    """The point of re-anchoring the thresholds. On the old evenly-spread 10/80
    ramp, Ashburn's Very Low tract scored 70/100 rather than 100, because a
    'Very Low' NRI score is a number in the 20s-60s, not in the single digits."""
    from app.engine.scoring import normalize
    from app.fields import FIELD_INDEX

    spec = FIELD_INDEX["wildfire_risk_index"]
    low = nri.values_for(39.0164, -77.4590)["wildfire_risk_index"]
    high = nri.values_for(33.5312, -111.6321)["wildfire_risk_index"]

    assert low.value < high.value
    assert normalize(spec, low.value) == 100.0
    assert normalize(spec, high.value) == 0.0
    # And the thresholds are FEMA's published class boundaries, not round numbers.
    assert spec.good == 68.65 and spec.bad == 96.26


def test_the_thresholds_match_the_boundaries_recorded_with_the_data(nri):
    """If a future NRI version moves its class boundaries, this fails rather
    than silently scoring against the old ones."""
    from app.fields import FIELD_INDEX

    bounds = nri._load()["_rating_bounds"]
    spec = FIELD_INDEX["wildfire_risk_index"]
    assert spec.good == bounds["Very Low"][1]
    assert spec.bad == bounds["Relatively High"][0]


def test_a_tract_outside_the_index_is_absent_not_zero(nri):
    """Zero here would read as 'no wildfire risk', which is the opposite of
    'we do not know'."""
    nri._counties._cache["12.000,-12.000"] = {
        "state": "ZZ",
        "county": "Unknown",
        "fips": "00000",
        "tract_fips": "00000000000",
        "tract": "0",
    }
    assert nri.values_for(12.0, -12.0) == {}


def test_a_point_outside_the_us_returns_nothing(nri):
    assert nri.values_for(0.0, -160.0) == {}


def test_a_cache_entry_predating_tracts_is_refetched_when_it_can_be(tracts, nri):
    """A cache written before tracts were requested has county data but no
    tract. With fetching on it is re-fetched rather than trusted; with fetching
    off the county half is still served, because it is still correct — and the
    wildfire lookup reports nothing rather than guessing a tract."""
    stale = tracts.county_for(1.0, -1.0)
    assert stale is not None and "tract_fips" not in stale
    assert stale["county"] == "Nowhere", "the county half is still usable"
    assert nri.values_for(1.0, -1.0) == {}, "but no tract means no wildfire score"
