"""System-Level Cascade Impact Analysis Engine.

Calculates the cumulative facility-wide impact of multiple concurrent equipment changes:
Chiller + CRAH + Pump + UPS changes → Combined Electrical, Structural, Cooling, and Water Loading.
"""

from __future__ import annotations

import logging

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

    # Facility capacity headroom. Headroom is a fraction of a capacity, so it can
    # only be computed where that capacity is known. Nothing in the application
    # populates ProjectCapacities today, which is exactly why this must report
    # the absence rather than substitute a plausible building.
    caps = capacities or ProjectCapacities()

    rationale: list[str] = []
    collective_status = "WITHIN_FACILITY_LIMITS"
    unknown: list[str] = []

    def headroom(capacity: float | None, consumed: float, label: str) -> float | None:
        """Percent of capacity left, or None when the capacity is not known."""
        if capacity is None or capacity <= 0:
            unknown.append(label)
            return None
        return ((capacity - consumed) / capacity) * 100.0

    # Transformer
    added_kva = total_delta_kw / 0.95
    xfmr_headroom_pct = headroom(
        caps.transformer_capacity_kva, added_kva, "transformer capacity (kVA)"
    )
    if added_kva > 0:
        consumed = (
            f" ({added_kva / caps.transformer_capacity_kva * 100:.1f}% of transformer capacity)"
            if xfmr_headroom_pct is not None
            else ""
        )
        rationale.append(
            f"Cumulative electrical addition of {total_delta_kw:+.1f} kW "
            f"({added_kva:.1f} kVA){consumed}."
        )
    if xfmr_headroom_pct is not None and xfmr_headroom_pct < 10.0:
        collective_status = "FACILITY_LIMITS_EXCEEDED"
        rationale.append(
            "CRITICAL: Combined electrical load change exceeds safe substation transformer headroom."
        )

    # Generator
    gen_headroom_pct = headroom(
        caps.generator_capacity_kw, total_delta_kw, "generator capacity (kW)"
    )

    # Structure. This one is never a claim of adequacy: it reports how much of a
    # stated allowance the added weight consumes, and a structural engineer
    # decides what that means.
    struct_headroom_pct = headroom(
        caps.structural_roof_capacity_kg, total_delta_weight_kg, "structural roof allowance (kg)"
    )
    if total_delta_weight_kg > 0:
        rationale.append(
            f"Cumulative equipment weight delta is {total_delta_weight_kg:+.0f} kg "
            f"across {len(evaluated_items)} substitutions."
        )
    if struct_headroom_pct is not None and struct_headroom_pct < 5.0:
        collective_status = "FACILITY_LIMITS_EXCEEDED"
        rationale.append(
            "Combined equipment weight additions exceed the stated structural roof "
            "allowance. Structural review required; this is not an adequacy assessment."
        )

    if unknown:
        # An unknown capacity cannot be reported as being within limits.
        if collective_status != "FACILITY_LIMITS_EXCEEDED":
            collective_status = "NEEDS_INFORMATION"
        rationale.append(
            "Headroom not calculated for: "
            + ", ".join(unknown)
            + ". Supply the facility's stated capacities before relying on any "
            "cumulative limit check."
        )

    if not rationale:
        rationale.append("No cumulative electrical, weight, cooling or water delta was found.")

    return CascadeImpactSummary(
        project_id=project.id,
        evaluated_changes=evaluated_items,
        cumulative_electrical_delta_kw=round(total_delta_kw, 1),
        cumulative_weight_delta_kg=round(total_delta_weight_kg, 1),
        cumulative_cooling_delta_kw=round(total_delta_cooling_kw, 1),
        cumulative_water_delta_m3_yr=round(total_delta_water_m3, 1),
        transformer_headroom_pct=None if xfmr_headroom_pct is None else round(xfmr_headroom_pct, 1),
        generator_headroom_pct=None if gen_headroom_pct is None else round(gen_headroom_pct, 1),
        structural_headroom_pct=None if struct_headroom_pct is None else round(struct_headroom_pct, 1),
        collective_status=collective_status,
        rationale=rationale,
    )
