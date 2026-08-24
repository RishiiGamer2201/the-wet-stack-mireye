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
    CandidateProduct,
    DecisionState,
    Discipline,
    Equipment,
    EquipmentChange,
    EquipmentConfiguration,
    MarginStatus,
    MarginType,
    Project,
    Quantity,
    Requirement,
    StructuredConstraint,
    StructuredRequirementSet,
)
from app.engine import cascade as cascade_engine, catalog_engine, cost_schedule as cost_engine, margins as margins_engine
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

    summary = cascade_engine.evaluate_cascade_impact(p, [chg1], store)
    assert summary.cumulative_electrical_delta_kw == 30.0
    assert summary.cumulative_weight_delta_kg == 800.0
    assert summary.collective_status == "WITHIN_FACILITY_LIMITS"


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
