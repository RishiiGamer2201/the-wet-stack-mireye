"""Deterministic site decision gates and transparent first-pass business case."""

from __future__ import annotations

from ..domain import (
    CandidateSite,
    DecisionGate,
    Project,
    SiteDecisionReadiness,
    SiteObservation,
    SiteScore,
)
from ..schemas import SiteBusinessCaseRequest, SiteBusinessCaseResponse


def decision_readiness(
    project: Project,
    site: CandidateSite,
    observations: list[SiteObservation],
    score: SiteScore | None = None,
) -> SiteDecisionReadiness:
    required_mw = project.targets.min_grid_capacity_mw or project.targets.it_load_mw
    by_key = {item.field_key: item for item in observations if item.value is not None}
    power_context: list[str] = []
    for key, label in (
        ("distance_to_substation_km", "Nearest substation distance"),
        ("planned_grid_expansion_mw", "Nearby interconnection-queue activity"),
        ("grid_capacity_mw", "Unconfirmed capacity observation"),
    ):
        obs = by_key.get(key)
        if obs is not None:
            power_context.append(f"{label}: {obs.value} {obs.unit or ''}".strip())

    confirmed = site.utility_confirmed_capacity_mw
    if confirmed is not None and required_mw is not None and confirmed < required_mw:
        power_status = "FAILED"
        power_action = "Select another site or obtain a revised utility service commitment."
    elif confirmed is not None and required_mw is not None:
        power_status = "CONFIRMED"
        power_action = "Carry the utility reference into formal electrical due diligence."
    else:
        power_status = "NEEDS_CONFIRMATION"
        power_action = "Obtain a written large-load service study or utility capacity commitment."

    approval = site.government_approval_status
    if approval == "approved":
        approval_status = "CONFIRMED"
        approval_action = "Validate approval conditions and maintain the permit register."
    elif approval == "rejected":
        approval_status = "FAILED"
        approval_action = "Resolve the rejection or remove this site from consideration."
    else:
        approval_status = "NEEDS_CONFIRMATION"
        approval_action = "Meet the AHJ and document zoning, entitlement, and permit outcomes."

    gates = [
        DecisionGate(
            key="power_serviceability",
            label="Deliverable power",
            status=power_status,
            requirement=(f"At least {required_mw:g} MW" if required_mw is not None else "Project MW requirement must be defined"),
            confirmed_value=(f"{confirmed:g} MW" if confirmed is not None else None),
            screening_context=power_context,
            authority="Serving electric utility / grid operator",
            reference=site.utility_confirmation_reference,
            next_action=power_action,
        ),
        DecisionGate(
            key="government_approval",
            label="Government approval pathway",
            status=approval_status,
            requirement="Zoning, entitlement, environmental, and construction approvals",
            confirmed_value=approval.replace("_", " ").title() if approval else None,
            screening_context=["Parcel zoning and public permit data are screening context only."],
            authority="Authority having jurisdiction (AHJ)",
            reference=site.government_approval_reference,
            next_action=approval_action,
        ),
    ]
    statuses = {gate.status for gate in gates}
    decision_status = "BLOCKED" if "FAILED" in statuses else (
        "READY_FOR_DUE_DILIGENCE" if statuses == {"CONFIRMED"} else "CONDITIONAL"
    )
    return SiteDecisionReadiness(
        project_id=project.id,
        site_id=site.id,
        site_name=site.name,
        decision_status=decision_status,
        gates=gates,
        business_context_score=score.overall_score if score else None,
        business_context_rank=score.rank if score else None,
        disclaimer="Mireye and public datasets provide screening context. Only the serving utility and the relevant authorities can close these gates.",
    )


def build_business_case(
    project: Project,
    site: CandidateSite,
    request: SiteBusinessCaseRequest,
    us_profile: dict | None,
) -> SiteBusinessCaseResponse:
    it_load_mw = request.it_load_mw or project.targets.it_load_mw
    if it_load_mw is None:
        raise ValueError("Set the project IT load or provide it_load_mw for this business case")
    rate = request.electricity_rate_usd_kwh
    rate_source = "User-supplied electricity tariff"
    if rate is None and us_profile is not None:
        rate = float(us_profile["commercial_electricity_rate_usd_kwh"])
        rate_source = "U.S. EIA 2024 state commercial-sector average"
    if rate is None:
        raise ValueError("Enter an electricity tariff; this site could not be matched to a U.S. state profile")

    facility_mw = it_load_mw * request.target_pue
    annual_energy_kwh = facility_mw * 1000 * 8760 * (request.utilization_pct / 100)
    annual_energy_cost = annual_energy_kwh * rate
    regional_index = float(us_profile.get("construction_cost_index", 1.0)) if us_profile else 1.0
    # Broad prototype benchmark range, explicitly not a quote or project estimate.
    capex_low = facility_mw * 8_000_000 * regional_index
    capex_high = facility_mw * 15_000_000 * regional_index
    additions = sum(value or 0 for value in (
        request.land_cost_usd,
        request.utility_interconnection_cost_usd,
        request.taxes_and_fees_usd,
    )) - (request.incentives_usd or 0)
    annual_other = request.annual_staffing_network_cost_usd or 0
    operating = request.years * (annual_energy_cost + annual_other)
    missing = []
    if request.land_cost_usd is None:
        missing.append("land acquisition")
    if request.utility_interconnection_cost_usd is None:
        missing.append("utility interconnection and network upgrades")
    if request.annual_staffing_network_cost_usd is None:
        missing.append("annual staffing and network operations")
    if request.taxes_and_fees_usd is None:
        missing.append("taxes and permitting fees")
    if request.incentives_usd is None:
        missing.append("negotiated incentives")
    return SiteBusinessCaseResponse(
        project_id=project.id,
        site_id=site.id,
        site_name=site.name,
        annual_energy_kwh=round(annual_energy_kwh, 2),
        annual_energy_cost_usd=round(annual_energy_cost, 2),
        estimated_facility_capex_low_usd=round(capex_low, 2),
        estimated_facility_capex_high_usd=round(capex_high, 2),
        known_additional_capex_usd=round(additions, 2),
        ten_year_known_cost_low_usd=round(capex_low + additions + operating, 2),
        ten_year_known_cost_high_usd=round(capex_high + additions + operating, 2),
        years=request.years,
        inputs={
            "it_load_mw": it_load_mw, "facility_load_mw": facility_mw,
            "target_pue": request.target_pue, "utilization_pct": request.utilization_pct,
            "electricity_rate_usd_kwh": rate,
        },
        sources=[rate_source, "Synthetic prototype facility CAPEX benchmark: USD 8M-15M per facility MW", "User-supplied cost inputs where provided"],
        missing_cost_items=missing,
        estimate_class="Prototype screening range; not a vendor quote or AACE-class estimate",
        disclaimer="The total excludes every item listed as missing. Utility upgrade cost must come from the serving utility.",
    )
