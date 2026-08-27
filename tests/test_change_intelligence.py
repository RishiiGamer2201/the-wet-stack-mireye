"""Test suite for AI-Powered Data Center Construction Change Intelligence Platform.

Validates:
1. Natural language requirement parsing -> Structured constraints
2. Equipment catalog recommendation engine & 9-dimension scoring
3. Deterministic Design Margins (structural, electrical, thermal, cooling, water, generator, transformer)
4. Cumulative multi-change cascade analysis
5. Cost & critical-path schedule impact estimation
6. Action package generation (RFIs, vendor evidence requests, review packages)
7. Full API endpoints & round-trip verification
"""

from __future__ import annotations

import pytest
from app.agent import change_orchestrator
from app.domain import (
    DecisionState,
    Discipline,
    Equipment,
    EquipmentChange,
    EquipmentConfiguration,
    MarginStatus,
    MarginType,
    Project,
    ProjectCapacities,
    Quantity,
    Requirement,
    StructuredConstraint,
    StructuredRequirementSet,
)
from app.engine import cascade as cascade_engine
from app.engine import catalog_engine
from app.engine import cost_schedule as cost_engine
from app.engine import margins as margins_engine
from app.store import C, Store


def test_natural_language_requirement_parsing():
    """Verify natural language prompts extract structured physics/electrical constraints."""
    prompt = "I need a water-cooled chiller with at least 1400 kW cooling capacity, COP above 6.0, 480V, and footprint under 18 m2."
    req_set = change_orchestrator.parse_natural_language_requirements(prompt, equipment_type="chiller")

    assert req_set.equipment_type == "chiller"
    params = {c.parameter: c for c in req_set.constraints}
    assert "cooling_capacity" in params
    assert params["cooling_capacity"].value >= 1400.0
    assert "cop" in params
    assert params["cop"].value >= 6.0
    assert "voltage" in params
    assert params["voltage"].value == 480.0
    assert "footprint" in params
    assert params["footprint"].value == 18.0


def test_catalog_search_and_deterministic_ranking():
    """Verify hard constraint filtering and multi-criteria scoring."""
    req_set = StructuredRequirementSet(
        project_id="test-p",
        equipment_type="chiller",
        constraints=[
            StructuredConstraint(parameter="cooling_capacity", operator=">=", value=1200.0, unit="kW", priority="mandatory"),
            StructuredConstraint(parameter="voltage", operator="==", value=480.0, unit="V", priority="mandatory"),
        ],
    )

    candidates = catalog_engine.search_and_rank_candidates("chiller", req_set, site_climate_db_c=36.0)
    assert len(candidates) > 0
    top = candidates[0]
    assert top.score > 0
    assert top.compatibility_status in ("COMPATIBLE", "CONDITIONALLY_COMPATIBLE")
    assert "capacity_margin" in top.score_breakdown
    assert "energy_efficiency" in top.score_breakdown
    assert "electrical_compatibility" in top.score_breakdown
    assert "climate_margin" in top.score_breakdown


def test_llm_can_explain_but_not_change_the_deterministic_shortlist(monkeypatch):
    class Explainer:
        available = True

        def complete(self, system, user, max_tokens=1000):
            assert "Do not calculate" in system
            assert '"ranked_candidates"' in user
            assert max_tokens == 900
            return "Review the fixed shortlist and obtain certified submittals."

    monkeypatch.setattr(change_orchestrator, "get_llm", lambda: Explainer())
    requirement_set = StructuredRequirementSet(
        project_id="llm-explanation-test",
        equipment_type="chiller",
        constraints=[
            StructuredConstraint(
                parameter="cooling_capacity",
                operator=">=",
                value=1200,
                unit="kW",
                priority="mandatory",
            )
        ],
    )
    result = change_orchestrator.generate_product_recommendations(
        project_id="llm-explanation-test",
        equipment_type="chiller",
        requirement_set=requirement_set,
        limit=5,
    )
    deterministic_ids = [
        candidate.id
        for candidate in catalog_engine.search_and_rank_candidates(
            "chiller", requirement_set, limit=5
        )
    ]
    assert [candidate.id for candidate in result.candidates] == deterministic_ids
    assert "LLM coordination note" in result.explanation_narrative
    assert "certified submittals" in result.explanation_narrative


def test_deterministic_design_margins():
    """Verify structural, electrical, and thermal design headroom calculations."""
    proposed_cfg = EquipmentConfiguration(
        manufacturer="Trane",
        model_number="CVHE-1400",
        weight=Quantity(value=7200.0, unit="kg"),
        weight_basis="operating",
        power_input=Quantity(value=230.0, unit="kW"),
        cooling_capacity=Quantity(value=1400.0, unit="kW"),
    )
    proposed_eq = Equipment(
        project_id="p1",
        tag="CH-01-PROP",
        name="Proposed Chiller",
        discipline=Discipline.MECHANICAL,
        configuration=proposed_cfg,
    )

    reqs = [
        Requirement(project_id="p1", field_key="max_weight", value=9000.0, unit="kg", label="Max Weight"),
        Requirement(project_id="p1", field_key="max_power_input", value=280.0, unit="kW", label="Max Feeder Power"),
        Requirement(project_id="p1", field_key="cooling_capacity", value=1250.0, unit="kW", label="Min Cooling Duty"),
    ]

    results = margins_engine.calculate_design_margins(proposed_eq, requirements=reqs, site_climate_db_c=36.0)
    struct_margin = next(m for m in results if m.margin_type == MarginType.STRUCTURAL)
    assert struct_margin.status == MarginStatus.WITHIN_MARGIN
    assert struct_margin.remaining_margin.value == 1800.0  # 9000 - 7200

    elec_margin = next(m for m in results if m.margin_type == MarginType.ELECTRICAL)
    assert elec_margin.status == MarginStatus.WITHIN_MARGIN
    assert elec_margin.remaining_margin.value == 50.0  # 280 - 230


def test_cumulative_cascade_analysis(store: Store):
    """Verify multi-change cumulative loading on power and structural capacities."""
    p = Project(id="cascade-proj", name="Cascade Test Facility")
    store.put(C.PROJECTS, p)

    # Equipment 1: Chiller (+30 kW, +800 kg)
    e1 = Equipment(
        project_id=p.id, tag="CH-1", name="Base Chiller",
        configuration=EquipmentConfiguration(power_input=Quantity(value=200, unit="kW"), weight=Quantity(value=6000, unit="kg")),
    )
    p1 = Equipment(
        project_id=p.id, tag="CH-1-PROP", name="Prop Chiller",
        configuration=EquipmentConfiguration(power_input=Quantity(value=230, unit="kW"), weight=Quantity(value=6800, unit="kg")),
    )
    store.put(C.EQUIPMENT, e1, project_id=p.id)
    store.put(C.EQUIPMENT, p1, project_id=p.id)

    chg1 = EquipmentChange(
        project_id=p.id, title="Chiller Sub", equipment_tag="CH-1",
        existing_equipment_id=e1.id, proposed_equipment_id=p1.id,
    )
    store.put(C.CHANGES, chg1, project_id=p.id)

    # The deltas are arithmetic on supplied values, so they are always available.
    summary = cascade_engine.evaluate_cascade_impact(p, [chg1], store)
    assert summary.cumulative_electrical_delta_kw == 30.0
    assert summary.cumulative_weight_delta_kg == 800.0

    # Headroom is a fraction of a capacity. With no capacities on the project it
    # cannot be computed, and "within limits" would be a claim about a building
    # nobody described.
    assert summary.collective_status == "NEEDS_INFORMATION"
    assert summary.transformer_headroom_pct is None
    assert summary.structural_headroom_pct is None
    assert summary.generator_headroom_pct is None
    assert any("Headroom not calculated" in line for line in summary.rationale)

    # Given the facility's stated capacities, the same change is measurable.
    caps = ProjectCapacities(
        structural_roof_capacity_kg=50_000.0,
        generator_capacity_kw=3_000.0,
        transformer_capacity_kva=2_500.0,
    )
    stated = cascade_engine.evaluate_cascade_impact(p, [chg1], store, capacities=caps)
    assert stated.collective_status == "WITHIN_FACILITY_LIMITS"
    assert stated.structural_headroom_pct == pytest.approx(98.4, abs=0.1)  # 800 of 50,000 kg
    assert stated.transformer_headroom_pct is not None


def test_cascade_will_not_report_within_limits_on_an_unknown_structure(store: Store):
    """A stated electrical capacity does not license a structural verdict."""
    p = Project(id="partial-caps", name="Partly Described Facility")
    store.put(C.PROJECTS, p)
    existing = Equipment(
        project_id=p.id, tag="CH-9", name="Existing",
        configuration=EquipmentConfiguration(weight=Quantity(value=6000, unit="kg")),
    )
    proposed = Equipment(
        project_id=p.id, tag="CH-9", name="Proposed",
        configuration=EquipmentConfiguration(weight=Quantity(value=9000, unit="kg")),
    )
    store.put(C.EQUIPMENT, existing, project_id=p.id)
    store.put(C.EQUIPMENT, proposed, project_id=p.id)
    change = EquipmentChange(
        project_id=p.id, title="Heavier chiller", equipment_tag="CH-9",
        existing_equipment_id=existing.id, proposed_equipment_id=proposed.id,
    )
    store.put(C.CHANGES, change, project_id=p.id)

    summary = cascade_engine.evaluate_cascade_impact(
        p, [change], store, capacities=ProjectCapacities(transformer_capacity_kva=2_500.0)
    )
    assert summary.transformer_headroom_pct is not None
    assert summary.structural_headroom_pct is None
    assert summary.collective_status == "NEEDS_INFORMATION"
    assert any("structural roof allowance" in line for line in summary.rationale)


def test_cost_and_schedule_impact():
    """Verify deterministic energy OPEX and schedule delay calculations."""
    e = Equipment(
        project_id="p", tag="CH-01", name="Old",
        configuration=EquipmentConfiguration(equipment_type="chiller", power_input=Quantity(value=250, unit="kW")),
    )
    p = Equipment(
        project_id="p", tag="CH-01", name="New",
        configuration=EquipmentConfiguration(equipment_type="chiller", power_input=Quantity(value=210, unit="kW")),
    )
    chg = EquipmentChange(
        project_id="p", title="Chiller Efficiency Upgrade", equipment_tag="CH-01",
        existing_equipment_id=e.id, proposed_equipment_id=p.id,
    )

    impact = cost_engine.estimate_cost_schedule_impact(chg, e, p)
    assert impact.total_annual_opex_delta_usd is not None
    assert impact.total_annual_opex_delta_usd < 0
    assert impact.on_critical_path is True


def test_action_package_rfi_generation(store: Store):
    """Verify formal markdown RFI generation with required coordination checklist."""
    e = Equipment(
        project_id="p", tag="CH-01", name="Old",
        configuration=EquipmentConfiguration(weight=Quantity(value=6000, unit="kg")),
    )
    p = Equipment(
        project_id="p", tag="CH-01", name="New",
        configuration=EquipmentConfiguration(weight=Quantity(value=7000, unit="kg")),
    )
    chg = EquipmentChange(
        project_id="p", title="York YZ Chiller Submittal", equipment_tag="CH-01",
        existing_equipment_id=e.id, proposed_equipment_id=p.id,
    )
    from app.domain import Investigation, Workflow
    inv = Investigation(
        project_id="p", workflow=Workflow.DURING_CONSTRUCTION, subject_id=chg.id,
        question="Analyze change", decision_state=DecisionState.ENGINEER_REVIEW,
    )

    rfi = change_orchestrator.generate_action_package(chg, inv, action_type="rfi")
    assert rfi.action_type == "rfi"
    assert "Request for Information" in rfi.body_markdown
    assert "York YZ Chiller Submittal" in rfi.body_markdown
    assert len(rfi.requested_items) > 0


def test_during_construction_extended_api_endpoints(api):
    """Verify HTTP API contracts for the extended change intelligence workflow."""
    # Seed demo project first
    res = api.post("/api/admin/seed")
    assert res.status_code == 200
    p_id = res.json()["project_id"]

    # 1. Parse Requirements
    parse_res = api.post(
        f"/api/projects/{p_id}/requirements/parse",
        json={"prompt": "Chiller >= 1200 kW, COP >= 6.0, 480V"},
    )
    assert parse_res.status_code == 200
    req_json = parse_res.json()
    assert req_json["equipment_type"] == "chiller"
    assert len(req_json["constraints"]) >= 3

    # 2. Search Recommendations
    rec_res = api.post(
        f"/api/projects/{p_id}/recommendations/search",
        json={"equipment_type": "chiller", "constraints": req_json["constraints"]},
    )
    assert rec_res.status_code == 200
    rec_json = rec_res.json()
    assert len(rec_json["candidates"]) > 0
    top_cand = rec_json["candidates"][0]

    # 3. Apply Recommendation as Change Case
    apply_res = api.post(
        f"/api/projects/{p_id}/recommendations/apply-change",
        json={
            "equipment_tag": "CH-01",
            "candidate_product_id": top_cand["id"],
            "title": f"Sub: {top_cand['model_number']}",
        },
    )
    assert apply_res.status_code == 200
    inv_json = apply_res.json()
    assert inv_json["status"] == "completed"
    chg_id = inv_json["subject_id"]

    # 4. Fetch Design Margins
    mrn_res = api.get(f"/api/projects/{p_id}/changes/{chg_id}/margins")
    assert mrn_res.status_code == 200
    mrn_json = mrn_res.json()
    assert len(mrn_json) >= 5

    # 5. Fetch Decision Lineage
    lin_res = api.get(f"/api/projects/{p_id}/changes/{chg_id}/lineage")
    assert lin_res.status_code == 200
    assert len(lin_res.json()) >= 1

    # 6. Fetch Cost & Schedule Impact
    cost_res = api.get(f"/api/projects/{p_id}/changes/{chg_id}/cost-schedule")
    assert cost_res.status_code == 200
    assert "schedule_delay_days" in cost_res.json()

    # 7. Run Cascade Analysis
    casc_res = api.post(f"/api/projects/{p_id}/cascade-analysis", json={})
    assert casc_res.status_code == 200
    casc_json = casc_res.json()
    assert "cumulative_electrical_delta_kw" in casc_json

    # 8. Generate Action Package (RFI)
    act_res = api.post(
        f"/api/projects/{p_id}/actions/generate",
        json={"change_id": chg_id, "action_type": "rfi"},
    )
    assert act_res.status_code == 200
    act_json = act_res.json()
    assert "Request for Information" in act_json["body_markdown"]


def test_construction_plan_sizes_equipment_and_reports_power_costs(api):
    """The simplified During Construction flow is site-scoped and fully deterministic."""
    seed_res = api.post("/api/admin/seed")
    project_id = seed_res.json()["project_id"]
    site = api.get(f"/api/projects/{project_id}").json()["sites"][0]

    response = api.post(
        f"/api/projects/{project_id}/construction-plan",
        json={
            "site_id": site["id"],
            "it_load_mw": 12,
            "redundancy": "N+1",
            "target_pue": 1.3,
            "utilization_pct": 75,
            "electricity_rate_usd_kwh": 0.10,
            "budget_usd": 100_000_000,
            "cooling_strategy": "hybrid_economizer",
        },
    )

    assert response.status_code == 200
    plan = response.json()
    assert plan["site"]["id"] == site["id"]
    assert plan["totals"]["peak_facility_power_kw"] == 15_600
    assert plan["totals"]["annual_energy_kwh"] == 15_600 * 8760 * 0.75
    assert plan["totals"]["annual_energy_cost_usd"] == 15_600 * 8760 * 0.75 * 0.10
    assert plan["totals"]["plan_cost_low_usd"] > 0
    assert plan["totals"]["plan_cost_high_usd"] > plan["totals"]["plan_cost_low_usd"]
    assert plan["totals"]["budget_status"] == "WITHIN_RANGE"

    schedule = {item["category"]: item for item in plan["equipment_schedule"]}
    assert {"transformer", "ups", "generator", "chiller", "crah", "cooling_tower", "pdu"} <= set(schedule)
    assert "heat_exchanger" in schedule
    assert all(item["quantity"] >= 2 for item in schedule.values())
    assert all(item["synthetic_cost"] is True for item in schedule.values())
    assert len(plan["work_packages"]) == 5
    assert any("synthetic planning ranges" in warning for warning in plan["warnings"])


def test_construction_plan_rejects_a_site_from_another_project(api):
    seed_res = api.post("/api/admin/seed")
    project_id = seed_res.json()["project_id"]
    other = api.post(
        "/api/projects",
        json={"name": "Other construction project"},
    ).json()

    site = api.get(f"/api/projects/{project_id}").json()["sites"][0]
    response = api.post(
        f"/api/projects/{other['id']}/construction-plan",
        json={"site_id": site["id"], "it_load_mw": 5},
    )
    assert response.status_code == 404


def test_us_construction_dataset_has_nationwide_labelled_coverage(api):
    coverage = api.get("/api/construction-data/coverage")
    assert coverage.status_code == 200
    body = coverage.json()
    assert body["state_profile_count"] == 51
    assert body["equipment_model_count"] >= 600
    assert len(body["equipment_categories"]) == 11
    assert body["synthetic_equipment"] is True
    assert len(body["prototype_scenarios"]) >= 10
    assert "certified manufacturer" in body["catalog_disclaimer"]
    assert body["real_data_sources"][0]["name"].startswith("U.S. EIA")


def test_construction_plan_uses_eia_state_rate_when_override_is_blank(api):
    project = api.post("/api/projects", json={"name": "Virginia construction plan"}).json()
    site_response = api.post(
        f"/api/projects/{project['id']}/sites",
        json={
            "name": "Ashburn campus",
            "address": "Ashburn, VA",
            "latitude": 39.0438,
            "longitude": -77.4874,
        },
    )
    assert site_response.status_code == 201
    plan_response = api.post(
        f"/api/projects/{project['id']}/construction-plan",
        json={"site_id": site_response.json()["id"], "it_load_mw": 24},
    )
    assert plan_response.status_code == 200
    basis = plan_response.json()["design_basis"]
    assert basis["state_code"] == "VA"
    assert basis["electricity_rate_usd_kwh"] > 0
    assert basis["electricity_rate_source"].startswith("U.S. EIA 2024")
    assert basis["regional_cost_index"] != 1.0


def test_construction_plan_does_not_use_a_distant_climate_station(api):
    project = api.post("/api/projects", json={"name": "Remote climate test"}).json()
    site = api.post(
        f"/api/projects/{project['id']}/sites",
        json={
            "name": "Northern site",
            "address": "New York",
            "latitude": 42.761,
            "longitude": -82.607,
        },
    ).json()
    response = api.post(
        f"/api/projects/{project['id']}/construction-plan",
        json={"site_id": site["id"], "it_load_mw": 10},
    )
    assert response.status_code == 200
    plan = response.json()
    assert "ambient_design_db_c" not in {
        constraint["field_key"] for constraint in plan["site_constraints"]
    }
    assert any("No nearby climate-station" in warning for warning in plan["warnings"])


def test_catalog_rejects_missing_mandatory_values_and_unknown_categories():
    model = {"id": "partial", "model_number": "PARTIAL", "equipment_type": "chiller"}
    constraint = StructuredConstraint(
        parameter="cooling_capacity",
        operator=">=",
        value=1200,
        unit="kW",
        priority="mandatory",
    )
    candidate = catalog_engine.evaluate_candidate_product(
        model,
        [constraint],
        catalog_engine.DEFAULT_WEIGHTS,
    )
    assert candidate.compatibility_status == "INCOMPATIBLE"
    assert any("not specified" in failure for failure in candidate.failed_constraints)
    assert catalog_engine.search_and_rank_candidates("category-that-does-not-exist") == []


@pytest.mark.parametrize(
    ("prompt", "equipment_type", "parameter", "expected"),
    [
        ("Need a 2.5 MVA transformer", "transformer", "kva_rating", 2500),
        ("Replace with a 1200 kW UPS", "ups", "power_capacity", 1200),
        ("Need a pump rated for 90 L/s", "pump", "flow_rate", 90),
        ("Use 4000 amp switchgear", "switchgear", "bus_current", 4000),
    ],
)
def test_requirement_parser_handles_multiple_equipment_categories(
    prompt, equipment_type, parameter, expected
):
    parsed = change_orchestrator.parse_natural_language_requirements(
        prompt,
        equipment_type=equipment_type,
    )
    matching = [item for item in parsed.constraints if item.parameter == parameter]
    assert matching
    assert matching[0].value == expected


def test_recommendation_can_create_a_new_change_and_blocks_cross_project_update(api, store):
    seeded = api.post("/api/admin/seed").json()
    project_id = seeded["project_id"]
    search = api.post(
        f"/api/projects/{project_id}/recommendations/search",
        json={
            "equipment_type": "transformer",
            "constraints": [
                {
                    "parameter": "kva_rating",
                    "operator": ">=",
                    "value": 2500,
                    "unit": "kVA",
                    "priority": "mandatory",
                }
            ],
        },
    )
    assert search.status_code == 200
    candidate = search.json()["top_recommendation"]
    assert candidate is not None

    applied = api.post(
        f"/api/projects/{project_id}/recommendations/apply-change",
        json={
            "equipment_tag": "TX-NEW",
            "candidate_product_id": candidate["id"],
        },
    )
    assert applied.status_code == 200
    change_id = applied.json()["subject_id"]
    change = store.get(C.CHANGES, change_id, EquipmentChange)
    proposed = store.get(C.EQUIPMENT, change.proposed_equipment_id, Equipment)
    assert change.synthetic is True
    assert proposed.synthetic is True
    assert proposed.discipline == Discipline.ELECTRICAL

    other = api.post("/api/projects", json={"name": "Unrelated project"}).json()
    blocked = api.post(
        f"/api/projects/{other['id']}/recommendations/apply-change",
        json={
            "equipment_tag": "TX-NEW",
            "candidate_product_id": candidate["id"],
            "existing_change_id": change_id,
        },
    )
    assert blocked.status_code == 422
    assert "this project" in blocked.json()["detail"]
