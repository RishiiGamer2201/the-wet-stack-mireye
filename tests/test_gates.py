"""Verification gates and final decision states."""

from __future__ import annotations

from app.domain import (
    CandidateSite,
    CheckStatus,
    DecisionState,
    EquipmentConfiguration,
    EvidenceStatus,
    Quantity,
    RatingConditions,
    Requirement,
    SiteDimension,
    SiteObservation,
)
from app.engine import decisions, gates


def q(v, u):
    return Quantity(value=v, unit=u)


RATING = RatingConditions(
    entering_water_temp=q(12, "degC"),
    leaving_water_temp=q(6.7, "degC"),
    ambient_temp=q(35, "degC"),
    standard="AHRI 550/590",
)

SOURCED = {
    "weight": "ev1", "length": "ev2", "width": "ev3", "height": "ev4",
    "full_load_amps": "ev5", "mca": "ev6", "cooling_capacity": "ev7",
}


def cfg(**kw):
    base = dict(
        manufacturer="Northwind Thermal",
        model_number="NT-1100",
        equipment_type="air_cooled_chiller",
        circuits=2,
        weight=q(4850, "kg"),
        weight_basis="operating",
        length=q(6800, "mm"),
        width=q(2250, "mm"),
        height=q(2450, "mm"),
        full_load_amps=q(240, "A"),
        mca=q(265, "A"),
        cooling_capacity=q(1050, "kW"),
        rating_conditions=RATING,
        evidence_ids=dict(SOURCED),
    )
    base.update(kw)
    return EquipmentConfiguration(**base)


def site(resolution="parcel", lat=33.5, lon=-111.6):
    return CandidateSite(
        id="site1", project_id="p1", name="Rio Verde Mesa",
        latitude=lat, longitude=lon, geocode_resolution=resolution,
    )


def ambient(value, status=EvidenceStatus.SYNTHETIC):
    return {
        "ambient_design_db_c": SiteObservation(
            site_id="site1", project_id="p1", field_key="ambient_design_db_c",
            dimension=SiteDimension.HAZARDS_CLIMATE, value=value, unit="degC",
            status=status, confidence=0.7, evidence_id="ev_amb",
        )
    }


def by_key(checks, key):
    return next(c for c in checks if c.key == key)


# --- individual gates -------------------------------------------------------


def test_model_identity_open_when_model_missing():
    check = gates.gate_model_identity(cfg(model_number=None), cfg(model_number="VX-1150"))
    assert check.status == CheckStatus.OPEN


def test_model_identity_triggered_when_models_are_identical():
    check = gates.gate_model_identity(cfg(), cfg())
    assert check.status == CheckStatus.TRIGGERED
    assert "same identity" in check.detail


def test_same_data_type_triggers_on_operating_vs_dry_weight():
    check = gates.gate_same_data_type(cfg(weight_basis="operating"), cfg(weight_basis="dry"))
    assert check.status == CheckStatus.TRIGGERED
    assert "misstate" in check.detail


def test_same_data_type_open_when_basis_undeclared():
    assert gates.gate_same_data_type(cfg(weight_basis=None), cfg()).status == CheckStatus.OPEN


def test_configuration_comparability_triggers_on_circuit_count():
    check = gates.gate_configuration_comparability(cfg(circuits=2), cfg(circuits=3))
    assert check.status == CheckStatus.TRIGGERED


def test_unit_gate_triggers_on_dimensional_conflict():
    check = gates.gate_units(cfg(), cfg(weight=q(5290, "kW")))
    assert check.status == CheckStatus.TRIGGERED
    assert check.severity.value == "critical"


def test_rating_conditions_gap_is_detected():
    other = RatingConditions(
        entering_water_temp=q(12, "degC"),
        leaving_water_temp=q(6.7, "degC"),
        ambient_temp=q(46, "degC"),
        standard="AHRI 550/590",
    )
    check = gates.gate_rating_conditions(cfg(), cfg(rating_conditions=other))
    assert check.status == CheckStatus.TRIGGERED
    assert "Rating-condition gap" in check.detail


def test_rating_conditions_open_when_absent():
    check = gates.gate_rating_conditions(cfg(rating_conditions=None), cfg())
    assert check.status == CheckStatus.OPEN


def test_source_availability_open_for_unsourced_value():
    check = gates.gate_source_availability(cfg(), cfg(evidence_ids={}))
    assert check.status == CheckStatus.OPEN
    assert "proposed.weight" in check.detail


def test_site_compatibility_triggers_when_site_is_hotter_than_rating():
    check = gates.gate_site_compatibility(cfg(), site(), ambient(46))
    assert check.status == CheckStatus.TRIGGERED
    assert "re-rated" in check.detail


def test_site_compatibility_closed_when_within_rating():
    assert gates.gate_site_compatibility(cfg(), site(), ambient(34)).status == CheckStatus.CLOSED


def test_site_compatibility_open_when_site_evidence_is_stale():
    check = gates.gate_site_compatibility(cfg(), site(), ambient(34, EvidenceStatus.STALE))
    assert check.status == CheckStatus.OPEN


def test_site_checks_skip_when_no_site_linked():
    assert gates.gate_site_compatibility(cfg(), None, {}).status == CheckStatus.SKIPPED
    assert gates.gate_coordinate_accuracy(None).status == CheckStatus.SKIPPED


def test_coordinate_accuracy_triggers_on_coarse_geocode():
    assert gates.gate_coordinate_accuracy(site("city")).status == CheckStatus.TRIGGERED
    assert gates.gate_coordinate_accuracy(site("parcel")).status == CheckStatus.CLOSED


def test_capacity_requirement_triggers_when_below_spec():
    req = Requirement(
        project_id="p1", label="Min capacity", field_key="cooling_capacity",
        value=1100, unit="kW", confirmed=True,
    )
    check = gates.gate_capacity_requirement(cfg(), [req])
    assert check.status == CheckStatus.TRIGGERED
    assert check.severity.value == "critical"


def test_capacity_requirement_open_without_a_requirement():
    assert gates.gate_capacity_requirement(cfg(), []).status == CheckStatus.OPEN


# --- gate suite + decision --------------------------------------------------


def test_full_gate_suite_all_closed_gives_first_pass_closed():
    req = Requirement(
        project_id="p1", label="Min capacity", field_key="cooling_capacity",
        value=1040, unit="kW", confirmed=True,
    )
    checks = gates.run_verification_gates(
        cfg(), cfg(model_number="VX-1150"), site=site(), observations=ambient(34), requirements=[req]
    )
    assert all(c.status in (CheckStatus.CLOSED, CheckStatus.SKIPPED) for c in checks), [
        (c.key, c.status) for c in checks
    ]
    state, rationale = decisions.decide(checks, [], [])
    assert state == DecisionState.FIRST_PASS_CHECKS_CLOSED
    assert rationale


def test_open_evidence_beats_triggered_and_yields_needs_information():
    checks = gates.run_verification_gates(
        cfg(evidence_ids={}), cfg(model_number="VX-1150", weight_basis=None), requirements=[]
    )
    gaps = gates.gaps_from_checks(checks, "p1", "chg1")
    assert gaps and all(g.blocking for g in gaps)
    state, _ = decisions.decide(checks, [], gaps)
    assert state == DecisionState.NEEDS_INFORMATION


def test_triggered_without_open_yields_engineer_review():
    req = Requirement(
        project_id="p1", label="Min capacity", field_key="cooling_capacity",
        value=1040, unit="kW", confirmed=True,
    )
    checks = gates.run_verification_gates(
        cfg(), cfg(model_number="VX-1150"), site=site(), observations=ambient(46), requirements=[req]
    )
    assert by_key(checks, "site_compatibility").status == CheckStatus.TRIGGERED
    state, rationale = decisions.decide(checks, [], [])
    assert state == DecisionState.ENGINEER_REVIEW
    assert any("TRIGGERED" in r for r in rationale)


def test_recommendation_always_carries_the_safety_caveat():
    rec = decisions.build_recommendation(
        DecisionState.ENGINEER_REVIEW, ["because"], [], [], 0.8
    )
    assert any("not professional engineering approval" in c for c in rec.caveats)
    assert "structural adequacy" in " ".join(rec.caveats)


def test_next_actions_match_the_decision_state():
    req_gap_checks = gates.run_verification_gates(cfg(evidence_ids={}), cfg(model_number="X"))
    gaps = gates.gaps_from_checks(req_gap_checks, "p1", "chg1")
    actions = decisions.build_next_actions(
        DecisionState.NEEDS_INFORMATION, "Swap", "CH-01", gaps, req_gap_checks, []
    )
    assert actions and all(a.body for a in actions)
    assert any(a.type.value in ("vendor_evidence_request", "rfi") for a in actions)


def test_decision_confidence_drops_with_open_checks_and_synthetic_evidence():
    closed = gates.run_verification_gates(
        cfg(), cfg(model_number="VX-1150"), site=site(), observations=ambient(34),
        requirements=[Requirement(project_id="p1", label="c", field_key="cooling_capacity",
                                  value=1040, unit="kW", confirmed=True)],
    )
    high = decisions.decision_confidence(closed, [], synthetic_share=0.0)
    low = decisions.decision_confidence(closed, [], synthetic_share=1.0)
    assert high > low
