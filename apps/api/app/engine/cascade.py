"""System-Level Cascade Impact Analysis Engine.

Calculates the cumulative facility-wide impact of multiple concurrent equipment changes:
Chiller + CRAH + Pump + UPS changes → Combined Electrical, Structural, Cooling, and Water Loading.
"""

from __future__ import annotations

import logging
from typing import Any

from ..domain import (
    CascadeChangeItem,
    CascadeImpactSummary,
    Equipment,
    EquipmentChange,
    Project,
    ProjectCapacities,
)
from ..store import C, Store
from . import units

log = logging.getLogger("cascade_engine")


def evaluate_cascade_impact(
    project: Project,
    changes: list[EquipmentChange],
    store: Store,
    capacities: ProjectCapacities | None = None,
) -> CascadeImpactSummary:
    """Aggregate cumulative deltas across multiple equipment substitutions."""
    evaluated_items: list[CascadeChangeItem] = []
    total_delta_kw = 0.0
    total_delta_weight_kg = 0.0
    total_delta_cooling_kw = 0.0
    total_delta_water_m3 = 0.0

    for change in changes:
        existing = store.get(C.EQUIPMENT, change.existing_equipment_id, Equipment)
        proposed = store.get(C.EQUIPMENT, change.proposed_equipment_id, Equipment)
        if not existing or not proposed:
            continue

        e_cfg = existing.configuration
        p_cfg = proposed.configuration

        # Power Delta
        d_pwr = 0.0
        if p_cfg.power_input and e_cfg.power_input:
            try:
                p_kw = units.to_canonical(p_cfg.power_input).value
                e_kw = units.to_canonical(e_cfg.power_input).value
                d_pwr = p_kw - e_kw
            except Exception:
                pass

        # Weight Delta
        d_wt = 0.0
        if p_cfg.weight and e_cfg.weight:
            try:
                p_kg = units.to_canonical(p_cfg.weight).value
                e_kg = units.to_canonical(e_cfg.weight).value
                d_wt = p_kg - e_kg
            except Exception:
                pass

        # Cooling Delta
        d_cool = 0.0
        if p_cfg.cooling_capacity and e_cfg.cooling_capacity:
            try:
                p_c = units.to_canonical(p_cfg.cooling_capacity).value
                e_c = units.to_canonical(e_cfg.cooling_capacity).value
                d_cool = p_c - e_c
            except Exception:
                pass

        # Water Delta (m3/yr estimate)
        d_water = (d_cool * 8760 * 0.70 * 1.45) / 1000.0 if d_cool != 0 else 0.0

        evaluated_items.append(
            CascadeChangeItem(
                change_id=change.id,
                equipment_tag=change.equipment_tag,
                title=change.title,
                equipment_type=p_cfg.equipment_type or "equipment",
                delta_power_kw=round(d_pwr, 1),
                delta_weight_kg=round(d_wt, 1),
                delta_cooling_kw=round(d_cool, 1),
                delta_water_m3_yr=round(d_water, 1),
            )
        )

        total_delta_kw += d_pwr
        total_delta_weight_kg += d_wt
        total_delta_cooling_kw += d_cool
        total_delta_water_m3 += d_water

    # Facility Capacity Headroom Checks
    caps = capacities or ProjectCapacities(
        structural_roof_capacity_kg=50000.0,
        substation_capacity_mw=10.0,
        generator_capacity_kw=3000.0,
        transformer_capacity_kva=2500.0,
    )

    rationale: list[str] = []
    collective_status = "WITHIN_FACILITY_LIMITS"

    # Transformer Headroom
    xfmr_kva = caps.transformer_capacity_kva or 2500.0
    added_kva = total_delta_kw / 0.95
    rem_xfmr_kva = xfmr_kva - added_kva
    xfmr_headroom_pct = (rem_xfmr_kva / xfmr_kva) * 100.0 if xfmr_kva > 0 else 100.0
    if added_kva > 0:
        rationale.append(f"Cumulative electrical addition of {total_delta_kw:+.1f} kW ({added_kva:.1f} kVA) consumes {((added_kva)/xfmr_kva)*100:.1f}% of transformer capacity.")
    if xfmr_headroom_pct < 10.0:
        collective_status = "FACILITY_LIMITS_EXCEEDED"
        rationale.append("CRITICAL: Combined electrical load change exceeds safe substation transformer headroom.")

    # Generator Headroom
    gen_kw = caps.generator_capacity_kw or 3000.0
    rem_gen_kw = gen_kw - total_delta_kw
    gen_headroom_pct = (rem_gen_kw / gen_kw) * 100.0 if gen_kw > 0 else 100.0

    # Structural Headroom
    roof_kg = caps.structural_roof_capacity_kg or 50000.0
    rem_roof_kg = roof_kg - total_delta_weight_kg
    struct_headroom_pct = (rem_roof_kg / roof_kg) * 100.0 if roof_kg > 0 else 100.0
    if total_delta_weight_kg > 0:
        rationale.append(f"Cumulative equipment weight delta is {total_delta_weight_kg:+.0f} kg across {len(evaluated_items)} substitutions.")
    if struct_headroom_pct < 5.0:
        collective_status = "FACILITY_LIMITS_EXCEEDED"
        rationale.append("CRITICAL: Combined equipment weight additions exceed structural roof capacity limit.")

    if not rationale:
        rationale.append("All cumulative multi-equipment changes remain well within facility headroom envelope.")

    return CascadeImpactSummary(
        project_id=project.id,
        evaluated_changes=evaluated_items,
        cumulative_electrical_delta_kw=round(total_delta_kw, 1),
        cumulative_weight_delta_kg=round(total_delta_weight_kg, 1),
        cumulative_cooling_delta_kw=round(total_delta_cooling_kw, 1),
        cumulative_water_delta_m3_yr=round(total_delta_water_m3, 1),
        transformer_headroom_pct=round(xfmr_headroom_pct, 1),
        generator_headroom_pct=round(gen_headroom_pct, 1),
        structural_headroom_pct=round(struct_headroom_pct, 1),
        collective_status=collective_status,
        rationale=rationale,
    )
