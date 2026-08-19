"""Evidence-semantics and live-cost guardrails.

Two rules are enforced here, both offline against recorded fixtures.

**A contextual proxy is not a measurement.** Wet-bulb temperature, broadband
provider count and interconnection-queue capacity are each *related to* a
concept the scoring model needs, but none of them measures it. They may be
recorded, displayed and cited; they may never populate the value, close the gap,
satisfy a gate or move the score.

**Live provider calls cost money.** Nothing here touches the network, and the
budget that bounds a real investigation is exercised with a fake client.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from app.adapters.mireye import LiveMireyeClient, MockMireyeClient
from app.config import Settings
from app.domain import (
    CandidateSite,
    Evidence,
    EvidenceRelation,
    EvidenceStatus,
    InformationGap,
    Quantity,
    RatingConditions,
    SiteObservation,
)
from app.domain import EquipmentConfiguration as Config
from app.engine import gates, scoring
from app.fields import FIELD_INDEX
from app.services import sites as site_service
from app.services.evidence import record_fetch
from app.store import C, Store

FIXTURES = Path(__file__).parent / "fixtures" / "mireye"

#: Every concept whose provider mapping is a different measurement.
PROXY_CONCEPTS = ["ambient_design_db_c", "fiber_routes_count", "planned_grid_expansion_mw"]


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def live_client(store: Store, fields_payload: dict) -> LiveMireyeClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/meta/fields":
            return httpx.Response(200, json=fixture("meta_fields"))
        return httpx.Response(200, json=fields_payload)

    settings = Settings(
        mireye_base_url="https://api.mireye.test", mireye_api_key="k", mireye_max_retries=0
    )
    http = httpx.Client(base_url=settings.mireye_base_url, transport=httpx.MockTransport(handler))
    return LiveMireyeClient(settings, store, client=http)


def proxy_payload() -> dict:
    """A fetch response carrying only proxy readings, all non-null."""
    return {
        "lat": 47.4235,
        "lng": -120.3103,
        "fields": {
            "design_wet_bulb_temperature_0_4pct_degc": {
                "value": 20.7, "unit": "degC", "source": "NREL_NSRDB", "confidence": "medium",
                "fetched_at": "2026-08-17T19:13:50+00:00", "status": "ok",
            },
            "fiber_provider_count": {
                "value": 5, "unit": None, "source": "FCC_BDC", "confidence": "medium",
                "fetched_at": "2026-08-17T19:13:50+00:00", "status": "ok",
            },
            "nearest_proposed_generator_capacity_mw": {
                "value": 100.0, "unit": "MW", "source": "LBNL_QUEUES", "confidence": "medium",
                "fetched_at": "2026-08-17T19:13:50+00:00", "status": "ok",
            },
        },
    }


# ---------------------------------------------------------------------------
# Relation classification
# ---------------------------------------------------------------------------


def test_each_mapping_declares_how_it_relates_to_its_concept():
    expected = {
        "elevation_m": EvidenceRelation.EXACT,
        "seismic_pga_g": EvidenceRelation.EXACT,
        "mean_slope_pct": EvidenceRelation.UNIT_CONVERTED,
        "distance_to_substation_km": EvidenceRelation.UNIT_CONVERTED,
        "depth_to_bedrock_m": EvidenceRelation.UNIT_CONVERTED,
        "flood_zone": EvidenceRelation.CATEGORICAL_NORMALIZED,
        "soil_drainage_class": EvidenceRelation.CATEGORICAL_NORMALIZED,
        "ambient_design_db_c": EvidenceRelation.CONTEXTUAL_PROXY,
        "fiber_routes_count": EvidenceRelation.CONTEXTUAL_PROXY,
        "planned_grid_expansion_mw": EvidenceRelation.CONTEXTUAL_PROXY,
    }
    for key, relation in expected.items():
        assert FIELD_INDEX[key].relation == relation, key


def test_only_the_three_known_proxies_are_contextual():
    contextual = {k for k, s in FIELD_INDEX.items() if s.relation == EvidenceRelation.CONTEXTUAL_PROXY}
    assert contextual == set(PROXY_CONCEPTS)


def test_canonical_relations_may_populate_a_value_and_proxies_may_not():
    for relation in (
        EvidenceRelation.EXACT,
        EvidenceRelation.UNIT_CONVERTED,
        EvidenceRelation.CATEGORICAL_NORMALIZED,
    ):
        assert Evidence(claim="c", source=_src(), relation=relation).is_canonical
    assert not Evidence(claim="c", source=_src(), relation=EvidenceRelation.CONTEXTUAL_PROXY).is_canonical


def _src():
    from app.domain import EvidenceSource, SourceType

    return EvidenceSource(source_type=SourceType.MIREYE, source_id="x", source_name="x")


# ---------------------------------------------------------------------------
# A proxy is recorded, but never becomes the value
# ---------------------------------------------------------------------------


@pytest.fixture
def proxy_fetch(store: Store):
    site = CandidateSite(project_id="p1", name="Cascade Flats", latitude=47.4235, longitude=-120.3103)
    client = live_client(store, proxy_payload())
    result = client.fetch(47.4235, -120.3103, PROXY_CONCEPTS)
    return site, client, result


def test_proxy_readings_are_retrieved_and_kept(proxy_fetch):
    _, _, result = proxy_fetch
    assert set(result.values) == set(PROXY_CONCEPTS)
    for key in PROXY_CONCEPTS:
        assert result.values[key].relation == EvidenceRelation.CONTEXTUAL_PROXY
        assert result.values[key].value is not None


def test_a_proxy_never_produces_a_valued_observation(store: Store, proxy_fetch):
    site, client, result = proxy_fetch
    evidences, observations, gaps = record_fetch(store, client, "p1", site, result)

    # An observation is what scoring reads. The concept still gets one, but it
    # records the absence — value None, status MISSING — so the proxy reading
    # cannot leak into a score through the back door.
    assert {o.field_key for o in observations} == set(PROXY_CONCEPTS)
    for obs in observations:
        assert obs.value is None, f"{obs.field_key} must not carry the proxy's number"
        assert obs.status == EvidenceStatus.MISSING
        assert obs.confidence == 0.0

    recorded = {e.field_key for e in evidences if e.relation == EvidenceRelation.CONTEXTUAL_PROXY}
    assert recorded == set(PROXY_CONCEPTS), "the reading is still kept as evidence"
    for e in evidences:
        if e.relation == EvidenceRelation.CONTEXTUAL_PROXY:
            assert e.value is not None
            assert "CONTEXTUAL EVIDENCE" in e.source.notes
            assert e.relation_note


def test_a_proxy_does_not_close_its_information_gap(store: Store, proxy_fetch):
    site, client, result = proxy_fetch
    _, _, gaps = record_fetch(store, client, "p1", site, result)
    gapped = {g.field_key for g in gaps}
    assert set(PROXY_CONCEPTS) <= gapped
    wet = next(g for g in gaps if g.field_key == "ambient_design_db_c")
    assert "different quantity" in wet.description
    assert "design_wet_bulb_temperature_0_4pct_degc" in wet.description


def test_a_proxy_does_not_count_as_coverage_or_raise_the_score(store: Store, proxy_fetch):
    from app.domain import Project

    site, client, result = proxy_fetch
    record_fetch(store, client, "p1", site, result)
    observations = store.list(C.OBSERVATIONS, SiteObservation, project_id="p1", parent_id=site.id)
    usable = [o for o in observations if o.status != EvidenceStatus.MISSING]
    assert usable == []

    score = scoring.score_site(Project(id="p1", name="P"), site.id, site.name, observations)
    assert score.overall_score is None, "three proxies must not produce a score"
    assert score.evidence_coverage == 0.0
    for key in PROXY_CONCEPTS:
        assert key in score.missing_fields


# ---------------------------------------------------------------------------
# Rules 3-5: the specific substitutions that must never happen
# ---------------------------------------------------------------------------


def test_wet_bulb_never_satisfies_the_dry_bulb_compatibility_gate(store: Store, proxy_fetch):
    """Wet-bulb runs below dry-bulb, so accepting it here would pass a chiller
    that fails at real site conditions."""
    site, client, result = proxy_fetch
    record_fetch(store, client, "p1", site, result)
    observations = {
        o.field_key: o
        for o in store.list(C.OBSERVATIONS, SiteObservation, project_id="p1", parent_id=site.id)
        if o.status != EvidenceStatus.MISSING
    }
    proposed = Config(
        manufacturer="Vertex", model_number="VX-1150",
        cooling_capacity=Quantity(value=1055, unit="kW"),
        rating_conditions=RatingConditions(ambient_temp=Quantity(value=35, unit="degC")),
    )
    check = gates.gate_site_compatibility(proposed, site, observations)
    assert check.status.value == "OPEN"
    assert "not available" in check.detail or "not stated" in check.detail


def test_queue_capacity_never_substitutes_for_deliverable_grid_capacity(store: Store, proxy_fetch):
    from app.domain import Project, RequirementTargets

    site, client, result = proxy_fetch
    record_fetch(store, client, "p1", site, result)
    observations = store.list(C.OBSERVATIONS, SiteObservation, project_id="p1", parent_id=site.id)
    project = Project(id="p1", name="P", targets=RequirementTargets(min_grid_capacity_mw=200))
    score = scoring.score_site(project, site.id, site.name, observations)
    flag = next(f for f in score.requirement_flags if f.requirement == "Grid capacity")
    assert flag.passed is None, "queued generation cannot verify a load-capacity target"
    assert flag.actual is None
    # And the proxy is filed under planned expansion, which is also not scored.
    assert "planned_grid_expansion_mw" in score.missing_fields


def test_provider_count_is_never_presented_as_route_diversity(store: Store, proxy_fetch):
    site, client, result = proxy_fetch
    evidences, _, _ = record_fetch(store, client, "p1", site, result)
    fiber = next(e for e in evidences if e.field_key == "fiber_routes_count" and e.value is not None)
    assert fiber.relation == EvidenceRelation.CONTEXTUAL_PROXY
    assert "not physical route diversity" in fiber.relation_note
    assert "route survey" in fiber.relation_note


def test_proxy_explanations_name_the_actual_quantity():
    for key in PROXY_CONCEPTS:
        note = FIELD_INDEX[key].provider_note
        assert note.startswith("CONTEXTUAL ONLY"), key
        assert "Shown as" in note or "It is shown as" in note, f"{key} must say what it IS"


# ---------------------------------------------------------------------------
# Live-cost guardrails
# ---------------------------------------------------------------------------


class _CountingClient(MockMireyeClient):
    """A client that claims to be live, so the budget engages."""

    mode = "live"


def test_budget_does_not_bind_in_mock_mode():
    budget = site_service.LiveBudget(MockMireyeClient())
    assert budget.enforced is False
    for i in range(50):
        site = CandidateSite(project_id="p1", name=f"s{i}", latitude=1.0, longitude=1.0)
        assert budget.check(site) is None


def test_live_budget_caps_locations_and_records_a_gap(store: Store, seeded):
    settings = Settings(mireye_max_live_locations=2, mireye_max_live_fetches=99)
    budget = site_service.LiveBudget(_CountingClient(), settings)
    sites = store.list(C.SITES, CandidateSite, project_id=seeded.id)
    results = site_service._pass(store, _CountingClient(), seeded, sites, ["elevation_m"], budget)

    queried = [r for r in results if r["ok"]]
    skipped = [r for r in results if not r["ok"]]
    assert len(queried) == 2
    assert len(skipped) == len(sites) - 2
    assert "live location limit" in skipped[0]["summary"]

    gaps = store.list(C.GAPS, InformationGap, project_id=seeded.id)
    assert any("was not requested" in g.description for g in gaps), (
        "a site skipped for cost must be visible as a gap, not silently absent"
    )


def test_live_budget_caps_total_fetches(store: Store, seeded):
    settings = Settings(mireye_max_live_locations=99, mireye_max_live_fetches=1)
    budget = site_service.LiveBudget(_CountingClient(), settings)
    sites = store.list(C.SITES, CandidateSite, project_id=seeded.id)
    results = site_service._pass(store, _CountingClient(), seeded, sites, ["elevation_m"], budget)
    assert sum(1 for r in results if r["ok"]) == 1
    assert "live fetch limit" in [r for r in results if not r["ok"]][0]["summary"]


def test_parcel_fields_stay_out_of_a_live_request_by_default(store: Store):
    sent: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/meta/fields":
            return httpx.Response(200, json=fixture("meta_fields"))
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"lat": 1, "lng": 1, "fields": {}})

    settings = Settings(
        mireye_base_url="https://x.test",
        mireye_api_key="k",
        mireye_max_retries=0,
        mireye_include_parcel_fields=False,
    )
    assert settings.mireye_include_parcel_fields is False
    http = httpx.Client(base_url="https://x.test", transport=httpx.MockTransport(handler))
    client = LiveMireyeClient(settings, store, client=http)
    result = client.fetch(1.0, 1.0, ["elevation_m", "wetland_fraction", "zoning_class"])

    assert "parcel_zoning" not in sent["fields"]
    assert "wetland_fraction_of_parcel" not in sent["fields"]
    assert {"wetland_fraction", "zoning_class"} <= set(result.unavailable)


def test_repeat_fetches_reuse_the_cache_instead_of_billing_again(store: Store):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/meta/fields":
            return httpx.Response(200, json=fixture("meta_fields"))
        calls["n"] += 1
        return httpx.Response(200, json=fixture("fetch_cascade_flats"))

    settings = Settings(mireye_base_url="https://x.test", mireye_api_key="k", mireye_max_retries=0)
    http = httpx.Client(base_url="https://x.test", transport=httpx.MockTransport(handler))
    client = LiveMireyeClient(settings, store, client=http)
    for _ in range(4):
        client.fetch(47.4235, -120.3103, ["elevation_m"])
    assert calls["n"] == 1


def test_site_scoring_never_calls_ask(store: Store, seeded):
    """/ask is exploratory and separately billed; it must stay on the explicit
    endpoint and out of the scoring path."""

    class NoAsk(MockMireyeClient):
        def ask(self, *a, **kw):
            raise AssertionError("site scoring must not call /v1/ask")

        def ask_stream(self, *a, **kw):
            raise AssertionError("site scoring must not call /v1/ask/stream")

    sites = store.list(C.SITES, CandidateSite, project_id=seeded.id)
    site_service.broad_pass(store, NoAsk(), seeded, sites)
    site_service.deep_pass(store, NoAsk(), seeded, sites[:1])
