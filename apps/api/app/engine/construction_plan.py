"""Deterministic first-pass equipment and utility plan for a selected site.

The engine sizes bundled reference equipment from user-supplied requirements. It
does not ask an LLM to invent loads, quantities, prices, or engineering limits.
Equipment prices come from a clearly labelled synthetic benchmark table and stay
as ranges until a user supplies vendor quotations.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from ..adapters.equipment_specs import ClimateStation, get_equipment_specs_adapter
from ..domain import CandidateSite, Project, SiteObservation
from ..schemas import (
    ConstructionPlanItem,
    ConstructionPlanRequest,
    ConstructionPlanResponse,
    ConstructionPlanTotals,
    ConstructionWorkPackage,
    SitePlanningConstraint,
)

_DATASET_DIR = Path(__file__).resolve().parent.parent / "data" / "datasets"
_COST_PATH = _DATASET_DIR / "construction_cost_benchmarks.json"

_CATEGORY_LABELS = {
    "transformer": "Substation transformer",
    "switchgear": "Medium-voltage switchgear",
    "ups": "UPS power block",
    "pdu": "Power distribution unit",
    "generator": "Standby generator",
    "chiller": "Water-cooled chiller",
    "crah": "Computer-room air handler",
    "cooling_tower": "Cooling tower",
    "pump": "Chilled/condenser-water pump",
    "heat_exchanger": "Waterside economizer",
}

_SITE_FIELDS = {
    "ambient_design_db_c": "Ambient design dry-bulb",
    "water_stress_index": "Water stress index",
    "flood_zone": "Flood zone",
    "seismic_pga_g": "Seismic PGA",
    "design_wind_speed_mph": "Design wind speed",
    "bearing_capacity_kpa": "Soil bearing capacity",
    "distance_to_substation_km": "Distance to substation",
    "grid_capacity_mw": "Available grid capacity",
}


def _load_cost_benchmarks() -> dict[str, Any]:
    with _COST_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _rated_duty(model: dict[str, Any]) -> tuple[float | None, str | None]:
    for key, unit in (
        ("cooling_capacity_kw", "kW cooling"),
        ("thermal_capacity_kw", "kW thermal"),
        ("power_capacity_kw", "kW"),
        ("standby_rating_kw", "kW standby"),
        ("kva_rating", "kVA"),
        ("flow_rate_l_s", "L/s"),
    ):
        if model.get(key) is not None:
            return float(model[key]), unit
    if model.get("bus_continuous_amps") and model.get("voltage_v"):
        kva = math.sqrt(3) * float(model["bus_continuous_amps"]) * float(model["voltage_v"]) / 1000
        return round(kva, 1), "kVA"
    return None, None


def _model_capacity_kw(model: dict[str, Any], equipment_type: str) -> float:
    if equipment_type == "transformer":
        return float(model.get("kva_rating", 0)) * 0.9
    if equipment_type == "switchgear":
        duty, _ = _rated_duty(model)
        return float(duty or 0) * 0.9
    for key in (
        "power_capacity_kw",
        "standby_rating_kw",
        "cooling_capacity_kw",
        "thermal_capacity_kw",
    ):
        if model.get(key):
            return float(model[key])
    return 0.0


def _pick_model(equipment_type: str) -> dict[str, Any]:
    models = get_equipment_specs_adapter().list_models_by_type(equipment_type)
    if not models:
        raise ValueError(f"No bundled reference model is available for {equipment_type}")
    return max(models, key=lambda model: _model_capacity_kw(model, equipment_type))


def _with_redundancy(base_quantity: int, redundancy: str) -> int:
    base = max(1, base_quantity)
    if redundancy == "2N":
        return base * 2
    if redundancy == "N+1":
        return base + 1
    return base


def _quantity_for(
    equipment_type: str,
    model: dict[str, Any],
    it_power_kw: float,
    facility_power_kw: float,
    cooling_duty_kw: float,
    redundancy: str,
    chiller_base_quantity: int,
) -> int:
    capacity = _model_capacity_kw(model, equipment_type)
    if equipment_type in {"ups", "pdu"}:
        base = math.ceil(it_power_kw / max(capacity, 1))
    elif equipment_type in {"transformer", "generator", "switchgear"}:
        base = math.ceil(facility_power_kw / max(capacity, 1))
    elif equipment_type in {"chiller", "crah", "cooling_tower", "heat_exchanger"}:
        base = math.ceil(cooling_duty_kw / max(capacity, 1))
    elif equipment_type == "pump":
        base = chiller_base_quantity
    else:
        base = 1
    return _with_redundancy(base, redundancy)


def _site_constraints(
    observations: list[SiteObservation],
    station: ClimateStation | None,
    us_profile: dict[str, Any] | None,
) -> list[SitePlanningConstraint]:
    by_field = {obs.field_key: obs for obs in observations if obs.value is not None}
    constraints: list[SitePlanningConstraint] = []
    if station is not None:
        constraints.append(
            SitePlanningConstraint(
                field_key="ambient_design_db_c",
                label="ASHRAE cooling design dry-bulb",
                value=station.cooling_db_0_4_pct_degc,
                unit="degC",
                status="external_dataset",
                source=f"Bundled prototype climate-station snapshot: {station.name}, {station.distance_km:.1f} km away",
            )
        )
    if us_profile is not None:
        constraints.append(
            SitePlanningConstraint(
                field_key="commercial_electricity_rate_usd_kwh",
                label="State commercial electricity price",
                value=us_profile["commercial_electricity_rate_usd_kwh"],
                unit="USD/kWh",
                status="external_dataset",
                source="U.S. EIA 2024 Table 4 state commercial-sector average",
            )
        )
    for field_key, label in _SITE_FIELDS.items():
        if field_key == "ambient_design_db_c" and station is not None:
            continue
        obs = by_field.get(field_key)
        if obs is None:
            continue
        constraints.append(
            SitePlanningConstraint(
                field_key=field_key,
                label=label,
                value=obs.value,
                unit=obs.unit,
                status=obs.status.value,
                source="Stored Mireye or public-dataset site evidence",
            )
        )
    return constraints


def build_construction_plan(
    project: Project,
    site: CandidateSite,
    request: ConstructionPlanRequest,
    observations: list[SiteObservation],
    station: ClimateStation | None,
    us_profile: dict[str, Any] | None = None,
) -> ConstructionPlanResponse:
    """Size a site equipment schedule and calculate first-pass energy and cost ranges."""
    cost_data = _load_cost_benchmarks()
    cost_rows = cost_data["equipment_types"]
    regional_cost_index = float(us_profile.get("construction_cost_index", 1.0)) if us_profile else 1.0
    lead_time_multiplier = float(us_profile.get("lead_time_multiplier", 1.0)) if us_profile else 1.0
    if request.electricity_rate_usd_kwh is not None:
        electricity_rate = request.electricity_rate_usd_kwh
        electricity_rate_source = "User-supplied tariff"
    elif us_profile is not None:
        electricity_rate = float(us_profile["commercial_electricity_rate_usd_kwh"])
        electricity_rate_source = "U.S. EIA 2024 state commercial-sector average"
    else:
        electricity_rate = 0.085
        electricity_rate_source = "Synthetic fallback planning assumption"

    it_power_kw = request.it_load_mw * 1000.0
    facility_power_kw = it_power_kw * request.target_pue
    facility_overhead_kw = facility_power_kw - it_power_kw
    cooling_duty_kw = it_power_kw * 1.10

    chiller_model = _pick_model("chiller")
    chiller_capacity = _model_capacity_kw(chiller_model, "chiller")
    chiller_base_quantity = max(1, math.ceil(cooling_duty_kw / max(chiller_capacity, 1)))

    equipment_types = [
        "transformer",
        "switchgear",
        "ups",
        "pdu",
        "generator",
        "chiller",
        "crah",
        "cooling_tower",
        "pump",
    ]
    if request.cooling_strategy == "hybrid_economizer":
        equipment_types.append("heat_exchanger")

    schedule: list[ConstructionPlanItem] = []
    for equipment_type in equipment_types:
        model = chiller_model if equipment_type == "chiller" else _pick_model(equipment_type)
        quantity = _quantity_for(
            equipment_type,
            model,
            it_power_kw,
            facility_power_kw,
            cooling_duty_kw,
            request.redundancy,
            chiller_base_quantity,
        )
        cost = cost_rows[equipment_type]
        duty, duty_unit = _rated_duty(model)
        # Power-train catalog records describe throughput/rating, not an
        # additional site load. Only plant auxiliaries are summed here.
        input_kw = (
            float(model["power_input_kw"])
            if model.get("power_input_kw") is not None
            and equipment_type not in {"transformer", "switchgear", "ups", "pdu", "generator"}
            else None
        )
        schedule.append(
            ConstructionPlanItem(
                category=equipment_type,
                label=_CATEGORY_LABELS[equipment_type],
                model_id=model["id"],
                model_number=model.get("model_number", model["id"]),
                manufacturer=model.get("manufacturer", "Open reference benchmark"),
                quantity=quantity,
                duty_per_unit=duty,
                duty_unit=duty_unit,
                power_input_per_unit_kw=input_kw,
                connected_power_kw=round((input_kw or 0.0) * quantity, 1),
                estimated_cost_low_usd=round(float(cost["installed_cost_low_usd"]) * quantity * regional_cost_index, 2),
                estimated_cost_high_usd=round(float(cost["installed_cost_high_usd"]) * quantity * regional_cost_index, 2),
                cost_basis=f"{cost['basis']}; regional prototype index {regional_cost_index:.3f}",
                lead_time_weeks=max(1, round(int(cost["lead_time_weeks"]) * lead_time_multiplier)),
                description=model.get("description", "Bundled open equipment reference model."),
                source=model.get("source", "Mireye synthetic USA prototype equipment catalog"),
                synthetic_cost=True,
            )
        )

    equipment_low = sum(item.estimated_cost_low_usd for item in schedule)
    equipment_high = sum(item.estimated_cost_high_usd for item in schedule)
    contingency_factor = 1.0 + request.contingency_pct / 100.0
    plan_low = equipment_low * contingency_factor
    plan_high = equipment_high * contingency_factor

    annual_energy_kwh = (
        facility_power_kw
        * request.annual_operating_hours
        * request.utilization_pct
        / 100.0
    )
    annual_energy_cost = annual_energy_kwh * electricity_rate
    water = get_equipment_specs_adapter().calculate_water_consumption_estimate(
        cooling_capacity_kw=cooling_duty_kw,
        cooling_type=request.cooling_strategy,
        cop=float(chiller_model.get("cop", 5.5)),
    )
    annual_water_m3 = (
        cooling_duty_kw
        * request.annual_operating_hours
        * request.utilization_pct
        / 100.0
        * water["wue_l_per_kwh_thermal"]
        / 1000.0
    )

    if request.budget_usd is None:
        budget_status = "NOT_PROVIDED"
    elif request.budget_usd >= plan_low:
        budget_status = "WITHIN_RANGE"
    else:
        budget_status = "BELOW_RANGE"

    constraints = _site_constraints(observations, station, us_profile)
    warnings = [
        "Equipment prices are synthetic planning ranges, not quotations. Replace them with vendor bids before procurement.",
        "The cost range covers the listed installed equipment plus contingency; it excludes land, utility interconnection, shell, taxes, financing, and owner costs.",
        "Equipment quantities are a deterministic concept plan. The engineer of record must validate short-circuit duty, hydraulics, controls, structural loads, and code compliance.",
        "Cooling equipment is sized at 110% of the requested IT load as a concept-stage heat-rejection allowance; replace it with the mechanical design load before procurement.",
    ]
    if station is None:
        warnings.append("No nearby climate-station record was available; climate derating requires engineer confirmation.")
    if request.electricity_rate_usd_kwh is None and us_profile is None:
        warnings.append(
            "The site could not be matched to a U.S. state, so annual energy cost uses a synthetic $0.085/kWh fallback. Enter the project tariff before comparison."
        )
    if not constraints:
        warnings.append("No stored site measurements were available. Run the site investigation before using this plan for comparison.")
    if request.requirements_note:
        warnings.append("Free-text requirements are recorded for the reviewer but do not change numeric sizing unless entered in a structured field.")

    work_packages = [
        ConstructionWorkPackage(
            sequence=1,
            name="Validate site and design basis",
            scope="Confirm survey, geotechnical, flood, seismic, utility, water and climate inputs for the selected site.",
        ),
        ConstructionWorkPackage(
            sequence=2,
            name="Enable civil and utility works",
            scope="Coordinate grading, drainage, equipment pads, underground utilities and the utility interconnection path.",
            depends_on=["Validate site and design basis"],
        ),
        ConstructionWorkPackage(
            sequence=3,
            name="Install power train",
            scope="Procure and install switchgear, transformers, generators, UPS blocks and PDUs to the selected redundancy basis.",
            depends_on=["Enable civil and utility works"],
        ),
        ConstructionWorkPackage(
            sequence=4,
            name="Install cooling train",
            scope="Procure and install chillers, CRAHs, towers, pumps and economizer equipment shown in the schedule.",
            depends_on=["Enable civil and utility works"],
        ),
        ConstructionWorkPackage(
            sequence=5,
            name="Integrate controls and commission",
            scope="Complete controls point-to-point checks, functional performance tests, load-bank testing and turnover evidence.",
            depends_on=["Install power train", "Install cooling train"],
        ),
    ]

    return ConstructionPlanResponse(
        project_id=project.id,
        site=site,
        design_basis={
            "it_load_mw": request.it_load_mw,
            "redundancy": request.redundancy,
            "target_pue": request.target_pue,
            "utilization_pct": request.utilization_pct,
            "annual_operating_hours": request.annual_operating_hours,
            "electricity_rate_usd_kwh": electricity_rate,
            "electricity_rate_source": electricity_rate_source,
            "state_code": us_profile.get("state_code") if us_profile else None,
            "regional_cost_index": regional_cost_index,
            "lead_time_multiplier": lead_time_multiplier,
            "cooling_strategy": request.cooling_strategy,
            "voltage_v": request.voltage_v,
            "cooling_duty_kw": round(cooling_duty_kw, 1),
            "requirements_note": request.requirements_note,
        },
        site_constraints=constraints,
        equipment_schedule=schedule,
        work_packages=work_packages,
        totals=ConstructionPlanTotals(
            peak_facility_power_kw=round(facility_power_kw, 1),
            it_power_kw=round(it_power_kw, 1),
            facility_overhead_kw=round(facility_overhead_kw, 1),
            annual_energy_kwh=round(annual_energy_kwh, 1),
            annual_energy_cost_usd=round(annual_energy_cost, 2),
            annual_water_m3=round(annual_water_m3, 1),
            equipment_cost_low_usd=round(equipment_low, 2),
            equipment_cost_high_usd=round(equipment_high, 2),
            contingency_pct=request.contingency_pct,
            plan_cost_low_usd=round(plan_low, 2),
            plan_cost_high_usd=round(plan_high, 2),
            budget_usd=request.budget_usd,
            budget_status=budget_status,
        ),
        warnings=warnings,
        data_sources=[
            "Mireye synthetic USA prototype equipment catalog v3.0 (generated, not manufacturer-certified)",
            "Bundled 7-station prototype climate snapshot (verify against NOAA or project design criteria)",
            f"Mireye synthetic construction-cost benchmark v{cost_data['version']} ({cost_data['price_year']} USD)",
            *(
                ["U.S. EIA 2024 Table 4 commercial electricity price; synthetic regional cost and lead-time multipliers"]
                if us_profile
                else []
            ),
        ],
    )
