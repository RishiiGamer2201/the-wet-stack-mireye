"""Deterministic Cost & Schedule Impact Estimation Engine.

Computes:
1. CAPEX impact (Equipment price delta baseline)
2. OPEX / Energy & Water impact ($/yr based on local industrial kWh / m3 utility rates)
3. Construction Schedule & Lead Time impact (Days of delay, critical-path check)

Strict Rule: If cost data is absent, flag as NEEDS_INFORMATION rather than fabricating costs.
"""

from __future__ import annotations

import logging

from ..domain import (
    CostScheduleImpact,
    DeltaResult,
    Equipment,
    EquipmentChange,
)
from . import units

log = logging.getLogger("cost_schedule")

# Benchmark utility rates for industrial data centers
ELECTRICITY_RATE_PER_KWH = 0.085  # $0.085 / kWh
WATER_RATE_PER_M3 = 2.40          # $2.40 / m3


def estimate_cost_schedule_impact(
    change: EquipmentChange,
    existing: Equipment,
    proposed: Equipment,
    deltas: list[DeltaResult] | None = None,
) -> CostScheduleImpact:
    """Calculate deterministic energy OPEX and construction schedule delta."""
    e_cfg = existing.configuration
    p_cfg = proposed.configuration

    # 1. Energy Delta ($/year)
    energy_delta_usd = None
    if p_cfg.power_input and e_cfg.power_input:
        try:
            p_kw = units.to_canonical(p_cfg.power_input).value
            e_kw = units.to_canonical(e_cfg.power_input).value
            delta_kw = p_kw - e_kw
            # Annual kWh difference assuming 8760 hours/yr and 70% average load factor
            annual_kwh_delta = delta_kw * 8760 * 0.70
            energy_delta_usd = round(annual_kwh_delta * ELECTRICITY_RATE_PER_KWH, 2)
        except Exception:
            pass

    # 2. Water Delta ($/year)
    water_delta_usd = None
    if p_cfg.cooling_capacity and e_cfg.cooling_capacity:
        try:
            p_c = units.to_canonical(p_cfg.cooling_capacity).value
            e_c = units.to_canonical(e_cfg.cooling_capacity).value
            d_cool = p_c - e_c
            annual_m3 = (d_cool * 8760 * 0.70 * 1.45) / 1000.0
            water_delta_usd = round(annual_m3 * WATER_RATE_PER_M3, 2)
        except Exception:
            pass

    # Total OPEX delta
    total_opex_delta = None
    if energy_delta_usd is not None or water_delta_usd is not None:
        total_opex_delta = round((energy_delta_usd or 0.0) + (water_delta_usd or 0.0), 2)

    # 3. Schedule & Lead Time Impact
    # Major equipment substitutions on long-lead items (generators, chillers, switchgear) require re-engineering & FAT
    eq_type = (p_cfg.equipment_type or "").lower()
    lead_time_weeks = 16
    delay_days = 0
    on_critical_path = False

    if any(t in eq_type for t in ["chiller", "generator", "transformer", "switchgear"]):
        lead_time_weeks = 28
        on_critical_path = True
        # If there are electrical or structural deltas triggered, add re-engineering buffer
        triggered_count = sum(1 for d in (deltas or []) if d.status.value == "TRIGGERED")
        if triggered_count > 0:
            delay_days = 14 + (triggered_count * 7)  # Coordination & submittal resubmission cycle
        else:
            delay_days = 0
    elif "ups" in eq_type or "crah" in eq_type or "cooling_tower" in eq_type:
        lead_time_weeks = 20
        on_critical_path = True
        delay_days = 7 if (deltas and any(d.status.value == "TRIGGERED" for d in deltas)) else 0
    else:
        lead_time_weeks = 12
        delay_days = 0

    explanation = []
    if total_opex_delta is not None:
        if total_opex_delta > 0:
            explanation.append(f"Operating expense will increase by approximately ${total_opex_delta:,.0f}/yr due to higher electrical/cooling demand.")
        elif total_opex_delta < 0:
            explanation.append(f"Operating expense will decrease by approximately ${abs(total_opex_delta):,.0f}/yr due to improved equipment efficiency.")
        else:
            explanation.append("Operating expense remains neutral.")

    if delay_days > 0:
        explanation.append(f"Potential schedule delay of ~{delay_days} days for structural/electrical coordination and submittal resubmission.")
    else:
        explanation.append("No critical-path schedule delay projected if submittal is expedited.")

    return CostScheduleImpact(
        change_id=change.id,
        equipment_tag=change.equipment_tag,
        capex_delta_usd=None,  # Vendor quotation required
        annual_energy_delta_usd=energy_delta_usd,
        annual_water_delta_usd=water_delta_usd,
        total_annual_opex_delta_usd=total_opex_delta,
        schedule_delay_days=delay_days,
        on_critical_path=on_critical_path,
        lead_time_weeks=lead_time_weeks,
        status="ESTIMATED" if total_opex_delta is not None else "NEEDS_INFORMATION",
        explanation=" ".join(explanation),
    )
