"""Equipment Catalog Recommendation & Scoring Engine.

Executes:
1. Hard Constraint Filtering (Mandatory requirements: e.g. capacity >= required, voltage == required, ambient >= site condition).
2. Deterministic Multi-Criteria Product Scoring (0 - 100 points).
3. Candidate Ranking with breakdown dimensions and explanation generation.
"""

from __future__ import annotations

import logging
from typing import Any

from ..adapters.equipment_specs import get_equipment_specs_adapter
from ..domain import (
    CandidateProduct,
    StructuredConstraint,
    StructuredRequirementSet,
)

log = logging.getLogger("catalog_engine")

DEFAULT_WEIGHTS = {
    "capacity_margin": 0.25,
    "energy_efficiency": 0.20,
    "electrical_compatibility": 0.15,
    "climate_margin": 0.10,
    "physical_compatibility": 0.10,
    "water_efficiency": 0.05,
    "cost": 0.05,
    "maintenance": 0.05,
    "project_compatibility": 0.05,
}


def search_and_rank_candidates(
    equipment_type: str,
    requirement_set: StructuredRequirementSet | None = None,
    custom_weights: dict[str, float] | None = None,
    site_climate_db_c: float | None = 35.0,
) -> list[CandidateProduct]:
    """Retrieve catalog models, filter by hard constraints, score, and rank."""
    adapter = get_equipment_specs_adapter()
    raw_models = adapter.list_models_by_type(equipment_type)
    if not raw_models:
        # Fallback to all models if type has no exact matches
        raw_models = adapter.list_models_by_type("all")

    weights = dict(DEFAULT_WEIGHTS)
    if custom_weights:
        weights.update(custom_weights)

    constraints = requirement_set.constraints if requirement_set else []
    candidates: list[CandidateProduct] = []

    for model in raw_models:
        candidate = evaluate_candidate_product(
            model=model,
            constraints=constraints,
            weights=weights,
            site_climate_db_c=site_climate_db_c,
        )
        candidates.append(candidate)

    # Sort descending by score; filter compatible and conditionally compatible first
    candidates.sort(
        key=lambda c: (
            0 if c.compatibility_status == "INCOMPATIBLE" else 1,
            c.score,
        ),
        reverse=True,
    )
    return candidates


def evaluate_candidate_product(
    model: dict[str, Any],
    constraints: list[StructuredConstraint],
    weights: dict[str, float],
    site_climate_db_c: float | None = 35.0,
) -> CandidateProduct:
    """Evaluate one model against constraints and score across 9 dimensions."""
    passed: list[str] = []
    failed: list[str] = []
    warnings: list[str] = []

    # 1. Hard Constraints Filtering
    for c in constraints:
        is_pass, reason = _check_constraint(model, c)
        if is_pass:
            passed.append(f"{c.parameter} {c.operator} {c.value} ({reason})")
        else:
            failed.append(f"{c.parameter} {c.operator} {c.value}: {reason}")
            if c.priority == "mandatory":
                warnings.append(f"Failed mandatory constraint: {c.parameter} {c.operator} {c.value}")

    # Check site climate compatibility if available
    max_ambient = model.get("max_ambient_degc", 45.0)
    if site_climate_db_c and max_ambient < site_climate_db_c:
        failed.append(f"Rated max ambient ({max_ambient}°C) is below site design condition ({site_climate_db_c}°C)")
        warnings.append(f"Thermal derate risk: Max ambient {max_ambient}°C < Site design {site_climate_db_c}°C")

    # Determine status
    if any("Failed mandatory" in w for w in warnings):
        status = "INCOMPATIBLE"
    elif failed:
        status = "CONDITIONALLY_COMPATIBLE"
    else:
        status = "COMPATIBLE"

    # 2. Multi-Criteria Scoring (0 - 100)
    scores: dict[str, float] = {}

    # Capacity Margin (25%). A catalog entry that states no capacity is not
    # scored on capacity; assuming one ranks an unspecified product against a
    # described one.
    cooling_kw = (
        model.get("cooling_capacity_kw")
        or model.get("thermal_capacity_kw")
        or model.get("standby_rating_kw")
    )
    req_cap = _find_constraint_val(
        constraints, ["cooling_capacity", "capacity", "power_capacity_kw"], default=None
    )
    if cooling_kw and req_cap:
        cap_ratio = cooling_kw / max(req_cap, 1.0)
        scores["capacity_margin"] = min(100.0, max(0.0, 70.0 + (cap_ratio - 1.0) * 100.0))
    elif not cooling_kw:
        warnings.append(
            f"{model.get('model_number', 'This model')} publishes no rated capacity, "
            "so capacity margin was not scored."
        )

    # Energy Efficiency / COP (20%)
    cop = model.get("cop")
    eff_pct = model.get("efficiency_pct")
    if cop:
        scores["energy_efficiency"] = min(100.0, max(40.0, (cop / 7.0) * 100.0))
    elif eff_pct:
        scores["energy_efficiency"] = min(100.0, max(50.0, eff_pct))
    else:
        scores["energy_efficiency"] = 75.0

    # Electrical Compatibility (15%)
    req_volt = _find_constraint_val(constraints, ["voltage", "voltage_v"], default=480)
    mod_volt = model.get("voltage_v") or 480
    scores["electrical_compatibility"] = 100.0 if mod_volt == req_volt else 0.0

    # Climate Margin (10%). The site's ambient design dry-bulb is a measurement
    # of the user's site. Substituting a plausible one moves every candidate's
    # ranking on a number nobody supplied.
    if site_climate_db_c is not None:
        amb_margin = max_ambient - site_climate_db_c
        scores["climate_margin"] = min(100.0, max(0.0, 50.0 + amb_margin * 5.0))
    else:
        warnings.append(
            "Site ambient design dry-bulb is not known, so climate margin was not "
            "scored. Supply it to rank candidates on high-ambient derating."
        )

    # Physical Compatibility / Weight / Footprint (10%)
    length = model.get("length_mm", 4000) / 1000.0
    width = model.get("width_mm", 2000) / 1000.0
    area = length * width
    req_area = _find_constraint_val(constraints, ["footprint", "area", "footprint_area"], default=20.0)
    scores["physical_compatibility"] = 100.0 if area <= req_area else max(0.0, 100.0 - (area - req_area) * 10.0)

    # Water Efficiency (5%)
    wue = model.get("wue_l_per_kwh", 1.45)
    scores["water_efficiency"] = min(100.0, max(50.0, (1.8 - wue) * 100.0 + 50.0))

    # Cost / OPEX (5%)
    scores["cost"] = 85.0

    # Maintenance (5%)
    scores["maintenance"] = 90.0 if "Magnetic Bearing" in model.get("model_number", "") or "EC fan" in model.get("description", "") else 80.0

    # Project Compatibility (5%)
    scores["project_compatibility"] = 95.0 if status == "COMPATIBLE" else (65.0 if status == "CONDITIONALLY_COMPATIBLE" else 20.0)

    # Compute the weighted score over the criteria that were actually scored, and
    # renormalise. Filling an unscored criterion with a neutral 70 would let a
    # product with unknown capacity out-rank one that simply scores badly.
    scored_weight = sum(weights.get(k, 0.1) for k in scores)
    if scored_weight > 0:
        total_score = sum(scores[k] * weights.get(k, 0.1) for k in scores) / scored_weight
    else:
        total_score = 0.0
    total_score = round(min(100.0, max(0.0, total_score)), 1)

    # Build Narrative Explanation
    explanation_parts = []
    explanation_parts.append(f"{model.get('model_number', model.get('id', 'Model'))} scored {total_score}/100.")
    if status == "COMPATIBLE":
        explanation_parts.append("Meets all mandatory criteria with positive design margins.")
    elif status == "CONDITIONALLY_COMPATIBLE":
        explanation_parts.append(f"Passes core duties but flagged {len(failed)} non-blocking constraint(s).")
    else:
        explanation_parts.append("Incompatible with mandatory project targets.")

    return CandidateProduct(
        id=model.get("id", model.get("model_number", "unknown")),
        model_number=model.get("model_number", model.get("id", "Unknown Model")),
        manufacturer=model.get("manufacturer", "Industry Benchmark"),
        equipment_type=model.get("equipment_type", "equipment"),
        specs=model,
        score=total_score,
        score_breakdown={k: round(v, 1) for k, v in scores.items()},
        passed_constraints=passed,
        failed_constraints=failed,
        compatibility_status=status,
        explanation=" ".join(explanation_parts),
        warnings=warnings,
        reference_source=model.get("source", "RacksDB & LBNL Open Equipment Benchmark"),
    )


def _check_constraint(model: dict[str, Any], c: StructuredConstraint) -> tuple[bool, str]:
    """Check single constraint against model dictionary."""
    field_aliases = {
        "cooling_capacity": ["cooling_capacity_kw", "thermal_capacity_kw", "capacity_kw"],
        "cop": ["cop", "efficiency_cop"],
        "voltage": ["voltage_v", "voltage"],
        "weight": ["weight_kg", "weight"],
        "power_input": ["power_input_kw", "power_kw"],
        "max_ambient": ["max_ambient_degc", "ambient_rating_c"],
        "footprint": ["footprint_m2", "length_mm", "width_mm"],
    }

    aliases = field_aliases.get(c.parameter.lower(), [c.parameter.lower()])
    model_val = None
    for a in aliases:
        if a in model:
            model_val = model[a]
            break

    if model_val is None:
        if c.parameter.lower() == "footprint":
            if "length_mm" in model and "width_mm" in model:
                model_val = (model["length_mm"] * model["width_mm"]) / 1_000_000.0

    if model_val is None:
        return True, "Value not specified in catalog (unconstrained)"

    try:
        req_val = float(c.value)
        mod_num = float(model_val)
        if c.operator == ">=":
            return mod_num >= req_val, f"actual {mod_num} >= target {req_val}"
        elif c.operator == "<=":
            return mod_num <= req_val, f"actual {mod_num} <= target {req_val}"
        elif c.operator in ("==", "="):
            return mod_num == req_val, f"actual {mod_num} == target {req_val}"
        elif c.operator == ">":
            return mod_num > req_val, f"actual {mod_num} > target {req_val}"
        elif c.operator == "<":
            return mod_num < req_val, f"actual {mod_num} < target {req_val}"
    except (ValueError, TypeError):
        # Categorical match
        if c.operator in ("==", "="):
            match = str(model_val).lower() == str(c.value).lower()
            return match, f"actual {model_val} vs target {c.value}"

    return True, "Passed"


def _find_constraint_val(
    constraints: list[StructuredConstraint], params: list[str], default: float | None
) -> float | None:
    for c in constraints:
        if c.parameter.lower() in params:
            try:
                return float(c.value)
            except Exception:
                pass
    return default
