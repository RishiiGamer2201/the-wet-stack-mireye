"""Deterministic Design Margin Engine.

Calculates remaining project capacity and engineering design headroom across:
1. Structural Margin (Roof / Steel loading vs Equipment weight)
2. Electrical Margin (Substation / Switchboard / Feeder vs Equipment power & MCA)
3. Thermal / Climate Margin (Equipment max rated ambient vs Site peak dry-bulb temperature)
4. Cooling Margin (Central chilled water plant capacity vs Total facility heat load)
5. Water Margin (Municipal allocation vs Peak evaporative cooling consumption)
6. Generator Margin (Standby genset capacity vs Total facility emergency demand)
7. Transformer Margin (Substation transformer rating vs Total electrical demand)

All calculations are strictly deterministic with Pint unit conversions.
Missing baseline values yield NEEDS_INFORMATION; values are never guessed.
"""

from __future__ import annotations

import logging
from typing import Any

from ..domain import (
    CandidateSite,
    DesignMargin,
    Discipline,
    Equipment,
    EquipmentConfiguration,
    MarginStatus,
    MarginType,
    Quantity,
    Requirement,
)
from . import units

log = logging.getLogger("margins_engine")


def calculate_design_margins(
    proposed: Equipment,
    site: CandidateSite | None = None,
    requirements: list[Requirement] | None = None,
    observations: dict[str, Any] | None = None,
    site_climate_db_c: float | None = None,
) -> list[DesignMargin]:
    """Evaluate all applicable deterministic design margins for proposed equipment."""
    cfg = proposed.configuration
    reqs = requirements or []
    req_map = {r.field_key: r for r in reqs if r.field_key}
    margins: list[DesignMargin] = []

    # 1. Structural Margin
    margins.append(_eval_structural_margin(cfg, req_map))

    # 2. Electrical Margin
    margins.append(_eval_electrical_margin(cfg, req_map))

    # 3. Thermal / Climate Margin
    margins.append(_eval_thermal_margin(cfg, site, observations, site_climate_db_c))

    # 4. Cooling Capacity Margin
    margins.append(_eval_cooling_margin(cfg, req_map))

    # 5. Water Margin
    margins.append(_eval_water_margin(cfg, req_map))

    # 6. Generator Margin
    margins.append(_eval_generator_margin(cfg, req_map))

    # 7. Transformer Margin
    margins.append(_eval_transformer_margin(cfg, req_map))

    return margins


def _eval_structural_margin(
    cfg: EquipmentConfiguration, req_map: dict[str, Requirement]
) -> DesignMargin:
    req = req_map.get("max_weight") or req_map.get("weight") or req_map.get("roof_structural_capacity")
    if not cfg.weight or not req or req.value is None:
        return DesignMargin(
            margin_type=MarginType.STRUCTURAL,
            name="Structural Roof & Dunnage Margin",
            discipline=Discipline.STRUCTURAL,
            status=MarginStatus.NEEDS_INFORMATION,
            detail="Structural design capacity limit not specified in project requirements.",
        )

    try:
        cap_val = float(req.value)
        cap_unit = req.unit or "kg"
        cap_q = Quantity(value=cap_val, unit=cap_unit)
        
        cap_kg = units.to_canonical(cap_q).value
        prop_kg = units.to_canonical(cfg.weight).value
        rem_kg = cap_kg - prop_kg
        pct = (rem_kg / cap_kg) * 100.0 if cap_kg > 0 else 0.0

        if rem_kg < 0:
            status = MarginStatus.EXCEEDED
            detail = f"Proposed weight ({prop_kg:.0f} kg) exceeds structural capacity ({cap_kg:.0f} kg) by {abs(rem_kg):.0f} kg ({abs(pct):.1f}% overload)."
        elif pct < 10.0:
            status = MarginStatus.CRITICAL_MARGIN
            detail = f"Structural headroom is tight: {rem_kg:.0f} kg remaining ({pct:.1f}% margin)."
        else:
            status = MarginStatus.WITHIN_MARGIN
            detail = f"Safe structural margin: {rem_kg:.0f} kg remaining ({pct:.1f}% headroom)."

        return DesignMargin(
            margin_type=MarginType.STRUCTURAL,
            name="Structural Roof & Dunnage Margin",
            discipline=Discipline.STRUCTURAL,
            design_capacity=cap_q,
            proposed_demand=cfg.weight,
            remaining_margin=Quantity(value=round(rem_kg, 1), unit="kg"),
            margin_pct=round(pct, 1),
            status=status,
            detail=detail,
        )
    except Exception as e:
        log.warning("Structural margin evaluation failed: %s", e)
        return DesignMargin(
            margin_type=MarginType.STRUCTURAL,
            name="Structural Roof & Dunnage Margin",
            discipline=Discipline.STRUCTURAL,
            status=MarginStatus.NEEDS_INFORMATION,
            detail=f"Unit calculation error: {e}",
        )


def _eval_electrical_margin(
    cfg: EquipmentConfiguration, req_map: dict[str, Requirement]
) -> DesignMargin:
    req = req_map.get("max_power_input") or req_map.get("feeder_capacity_kw") or req_map.get("power_input")
    demand = cfg.power_input
    if not demand or not req or req.value is None:
        return DesignMargin(
            margin_type=MarginType.ELECTRICAL,
            name="Electrical Feeder & Distribution Margin",
            discipline=Discipline.ELECTRICAL,
            status=MarginStatus.NEEDS_INFORMATION,
            detail="Electrical feeder capacity baseline not specified in project requirements.",
        )

    try:
        cap_val = float(req.value)
        cap_unit = req.unit or "kW"
        cap_q = Quantity(value=cap_val, unit=cap_unit)

        cap_kw = units.to_canonical(cap_q).value
        prop_kw = units.to_canonical(demand).value
        rem_kw = cap_kw - prop_kw
        pct = (rem_kw / cap_kw) * 100.0 if cap_kw > 0 else 0.0

        if rem_kw < 0:
            status = MarginStatus.EXCEEDED
            detail = f"Proposed power demand ({prop_kw:.1f} kW) exceeds feeder limit ({cap_kw:.1f} kW) by {abs(rem_kw):.1f} kW."
        elif pct < 10.0:
            status = MarginStatus.CRITICAL_MARGIN
            detail = f"Electrical feeder margin is narrow: {rem_kw:.1f} kW remaining ({pct:.1f}% margin)."
        else:
            status = MarginStatus.WITHIN_MARGIN
            detail = f"Healthy electrical capacity: {rem_kw:.1f} kW remaining ({pct:.1f}% margin)."

        return DesignMargin(
            margin_type=MarginType.ELECTRICAL,
            name="Electrical Feeder & Distribution Margin",
            discipline=Discipline.ELECTRICAL,
            design_capacity=cap_q,
            proposed_demand=demand,
            remaining_margin=Quantity(value=round(rem_kw, 1), unit="kW"),
            margin_pct=round(pct, 1),
            status=status,
            detail=detail,
        )
    except Exception as e:
        return DesignMargin(
            margin_type=MarginType.ELECTRICAL,
            name="Electrical Feeder & Distribution Margin",
            discipline=Discipline.ELECTRICAL,
            status=MarginStatus.NEEDS_INFORMATION,
            detail=f"Unit calculation error: {e}",
        )


def _eval_thermal_margin(
    cfg: EquipmentConfiguration,
    site: CandidateSite | None,
    observations: dict[str, Any] | None,
    site_climate_db_c: float | None = None,
) -> DesignMargin:
    # Check equipment ambient rating
    eq_max_c = None
    if cfg.rating_conditions and cfg.rating_conditions.ambient_temp:
        try:
            eq_max_c = units.to_canonical(cfg.rating_conditions.ambient_temp).value
        except Exception:
            pass

    # Check site design peak dry bulb
    site_db_c = site_climate_db_c
    if site_db_c is None and observations and "ambient_design_db_c" in observations:
        obs = observations["ambient_design_db_c"]
        val = getattr(obs, "value", obs) if obs else None
        if val is not None:
            try:
                site_db_c = float(val)
            except Exception:
                pass

    if eq_max_c is None or site_db_c is None:
        return DesignMargin(
            margin_type=MarginType.THERMAL,
            name="Site Climate & Thermal Derating Margin",
            discipline=Discipline.MECHANICAL,
            status=MarginStatus.NEEDS_INFORMATION,
            detail="Requires equipment maximum ambient rating and site peak design dry-bulb temperature.",
        )

    margin_deg = eq_max_c - site_db_c
    if margin_deg < 0:
        status = MarginStatus.EXCEEDED
        detail = f"Site design temperature ({site_db_c:.1f}°C) exceeds equipment rated maximum ({eq_max_c:.1f}°C) by {abs(margin_deg):.1f}°C. Unit will trip or derate."
    elif margin_deg < 3.0:
        status = MarginStatus.CRITICAL_MARGIN
        detail = f"Climate headroom is narrow: {margin_deg:.1f}°C buffer above site peak summer dry-bulb."
    else:
        status = MarginStatus.WITHIN_MARGIN
        detail = f"Robust climate margin: {margin_deg:.1f}°C buffer above site peak design dry-bulb ({site_db_c:.1f}°C)."

    return DesignMargin(
        margin_type=MarginType.THERMAL,
        name="Site Climate & Thermal Derating Margin",
        discipline=Discipline.MECHANICAL,
        design_capacity=Quantity(value=round(eq_max_c, 1), unit="degC"),
        proposed_demand=Quantity(value=round(site_db_c, 1), unit="degC"),
        remaining_margin=Quantity(value=round(margin_deg, 1), unit="delta_degC"),
        margin_pct=round(margin_deg, 1),
        status=status,
        detail=detail,
    )


def _eval_cooling_margin(
    cfg: EquipmentConfiguration, req_map: dict[str, Requirement]
) -> DesignMargin:
    req = req_map.get("cooling_capacity") or req_map.get("min_cooling_capacity")
    cap = cfg.cooling_capacity
    if not cap or not req or req.value is None:
        return DesignMargin(
            margin_type=MarginType.COOLING,
            name="Cooling Plant Capacity Margin",
            discipline=Discipline.MECHANICAL,
            status=MarginStatus.NEEDS_INFORMATION,
            detail="Design cooling requirement baseline not specified.",
        )

    try:
        req_val = float(req.value)
        req_unit = req.unit or "kW"
        req_q = Quantity(value=req_val, unit=req_unit)

        req_kw = units.to_canonical(req_q).value
        prop_kw = units.to_canonical(cap).value
        rem_kw = prop_kw - req_kw
        pct = (rem_kw / req_kw) * 100.0 if req_kw > 0 else 0.0

        if rem_kw < 0:
            status = MarginStatus.EXCEEDED
            detail = f"Proposed cooling ({prop_kw:.1f} kW) fails minimum requirement ({req_kw:.1f} kW) by {abs(rem_kw):.1f} kW."
        else:
            status = MarginStatus.WITHIN_MARGIN
            detail = f"Delivers {rem_kw:.1f} kW excess cooling capacity ({pct:+.1f}% above design minimum)."

        return DesignMargin(
            margin_type=MarginType.COOLING,
            name="Cooling Plant Capacity Margin",
            discipline=Discipline.MECHANICAL,
            design_capacity=cap,
            proposed_demand=req_q,
            remaining_margin=Quantity(value=round(rem_kw, 1), unit="kW"),
            margin_pct=round(pct, 1),
            status=status,
            detail=detail,
        )
    except Exception as e:
        return DesignMargin(
            margin_type=MarginType.COOLING,
            name="Cooling Plant Capacity Margin",
            discipline=Discipline.MECHANICAL,
            status=MarginStatus.NEEDS_INFORMATION,
            detail=f"Unit calculation error: {e}",
        )


def _eval_water_margin(
    cfg: EquipmentConfiguration, req_map: dict[str, Requirement]
) -> DesignMargin:
    req = req_map.get("max_water_consumption_m3_yr") or req_map.get("water_allocation")
    if not req or req.value is None or not cfg.cooling_capacity:
        return DesignMargin(
            margin_type=MarginType.WATER,
            name="Municipal Water Allocation Margin",
            discipline=Discipline.MECHANICAL,
            status=MarginStatus.NEEDS_INFORMATION,
            detail="Municipal water allocation baseline not provided in project constraints.",
        )

    try:
        cap_kw = units.to_canonical(cfg.cooling_capacity).value
        # Estimated annual water m3 based on 1.45 L/kWh at 70% load factor
        annual_water_m3 = (cap_kw * 8760 * 0.70 * 1.45) / 1000.0
        alloc_m3 = float(req.value)
        rem_m3 = alloc_m3 - annual_water_m3
        pct = (rem_m3 / alloc_m3) * 100.0 if alloc_m3 > 0 else 0.0

        if rem_m3 < 0:
            status = MarginStatus.EXCEEDED
            detail = f"Estimated water demand ({annual_water_m3:.0f} m³/yr) exceeds municipal allocation ({alloc_m3:.0f} m³/yr)."
        else:
            status = MarginStatus.WITHIN_MARGIN
            detail = f"Water demand within allocation: {rem_m3:.0f} m³/yr remaining buffer ({pct:.1f}% margin)."

        return DesignMargin(
            margin_type=MarginType.WATER,
            name="Municipal Water Allocation Margin",
            discipline=Discipline.MECHANICAL,
            design_capacity=Quantity(value=alloc_m3, unit="m3/yr"),
            proposed_demand=Quantity(value=round(annual_water_m3, 0), unit="m3/yr"),
            remaining_margin=Quantity(value=round(rem_m3, 0), unit="m3/yr"),
            margin_pct=round(pct, 1),
            status=status,
            detail=detail,
        )
    except Exception as e:
        return DesignMargin(
            margin_type=MarginType.WATER,
            name="Municipal Water Allocation Margin",
            discipline=Discipline.MECHANICAL,
            status=MarginStatus.NEEDS_INFORMATION,
            detail=f"Error evaluating water margin: {e}",
        )


def _eval_generator_margin(
    cfg: EquipmentConfiguration, req_map: dict[str, Requirement]
) -> DesignMargin:
    req = req_map.get("generator_capacity_kw") or req_map.get("standby_emergency_kw")
    if not req or req.value is None or not cfg.power_input:
        return DesignMargin(
            margin_type=MarginType.GENERATOR,
            name="Emergency Generator Standby Margin",
            discipline=Discipline.ELECTRICAL,
            status=MarginStatus.NEEDS_INFORMATION,
            detail="Emergency generator standby headroom baseline not specified.",
        )

    try:
        gen_kw = float(req.value)
        prop_kw = units.to_canonical(cfg.power_input).value
        rem_kw = gen_kw - prop_kw
        pct = (rem_kw / gen_kw) * 100.0 if gen_kw > 0 else 0.0

        if rem_kw < 0:
            status = MarginStatus.EXCEEDED
            detail = f"Equipment power ({prop_kw:.1f} kW) exceeds emergency generator capacity ({gen_kw:.1f} kW)."
        elif pct < 15.0:
            status = MarginStatus.CRITICAL_MARGIN
            detail = f"Generator headroom is narrow: {rem_kw:.1f} kW ({pct:.1f}% margin)."
        else:
            status = MarginStatus.WITHIN_MARGIN
            detail = f"Generator standby headroom is healthy: {rem_kw:.1f} kW ({pct:.1f}% margin)."

        return DesignMargin(
            margin_type=MarginType.GENERATOR,
            name="Emergency Generator Standby Margin",
            discipline=Discipline.ELECTRICAL,
            design_capacity=Quantity(value=gen_kw, unit="kW"),
            proposed_demand=cfg.power_input,
            remaining_margin=Quantity(value=round(rem_kw, 1), unit="kW"),
            margin_pct=round(pct, 1),
            status=status,
            detail=detail,
        )
    except Exception as e:
        return DesignMargin(
            margin_type=MarginType.GENERATOR,
            name="Emergency Generator Standby Margin",
            discipline=Discipline.ELECTRICAL,
            status=MarginStatus.NEEDS_INFORMATION,
            detail=f"Error evaluating generator margin: {e}",
        )


def _eval_transformer_margin(
    cfg: EquipmentConfiguration, req_map: dict[str, Requirement]
) -> DesignMargin:
    req = req_map.get("transformer_capacity_kva") or req_map.get("substation_transformer_kva")
    if not req or req.value is None or not cfg.power_input:
        return DesignMargin(
            margin_type=MarginType.TRANSFORMER,
            name="Substation Transformer Loading Margin",
            discipline=Discipline.ELECTRICAL,
            status=MarginStatus.NEEDS_INFORMATION,
            detail="Substation transformer capacity baseline not specified.",
        )

    try:
        xfmr_kva = float(req.value)
        # Approximate kVA from kW assuming 0.95 power factor
        prop_kw = units.to_canonical(cfg.power_input).value
        prop_kva = prop_kw / 0.95
        rem_kva = xfmr_kva - prop_kva
        pct = (rem_kva / xfmr_kva) * 100.0 if xfmr_kva > 0 else 0.0

        if rem_kva < 0:
            status = MarginStatus.EXCEEDED
            detail = f"Equipment demand ({prop_kva:.1f} kVA) exceeds transformer rating ({xfmr_kva:.1f} kVA)."
        elif pct < 15.0:
            status = MarginStatus.CRITICAL_MARGIN
            detail = f"Transformer loading headroom is tight: {rem_kva:.1f} kVA ({pct:.1f}% margin)."
        else:
            status = MarginStatus.WITHIN_MARGIN
            detail = f"Transformer capacity is adequate: {rem_kva:.1f} kVA ({pct:.1f}% margin)."

        return DesignMargin(
            margin_type=MarginType.TRANSFORMER,
            name="Substation Transformer Loading Margin",
            discipline=Discipline.ELECTRICAL,
            design_capacity=Quantity(value=xfmr_kva, unit="kVA"),
            proposed_demand=Quantity(value=round(prop_kva, 1), unit="kVA"),
            remaining_margin=Quantity(value=round(rem_kva, 1), unit="kVA"),
            margin_pct=round(pct, 1),
            status=status,
            detail=detail,
        )
    except Exception as e:
        return DesignMargin(
            margin_type=MarginType.TRANSFORMER,
            name="Substation Transformer Loading Margin",
            discipline=Discipline.ELECTRICAL,
            status=MarginStatus.NEEDS_INFORMATION,
            detail=f"Error evaluating transformer margin: {e}",
        )
