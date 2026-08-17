"""Verification gate — the checks that must pass *before* a comparison is accepted.

Diagram §4A. Each gate is pure, deterministic and returns an
:class:`EngineeringCheck` with one of CLOSED / OPEN / TRIGGERED / SKIPPED:

    CLOSED     evaluated and satisfied
    OPEN       cannot be evaluated — evidence is missing (blocks the decision)
    TRIGGERED  evaluated and not satisfied — needs engineering judgement
    SKIPPED    not applicable to this case
"""

from __future__ import annotations

from ..domain import (
    CandidateSite,
    CheckStatus,
    EngineeringCheck,
    EquipmentConfiguration,
    EvidenceStatus,
    InformationGap,
    NextActionType,
    Quantity,
    Requirement,
    Severity,
    SiteObservation,
    SourceType,
)
from . import units

#: Location resolutions precise enough to attach site facts to an equipment decision.
ACCEPTABLE_RESOLUTIONS = {"rooftop", "parcel", "building"}
#: Rating-condition temperatures within this many kelvin are treated as the same point.
RATING_TOLERANCE_K = 0.15

COMPARED_FIELDS = [
    "weight",
    "length",
    "width",
    "height",
    "full_load_amps",
    "mca",
    "cooling_capacity",
]


def _check(key: str, name: str, status: CheckStatus, severity: Severity, detail: str, **kw):
    return EngineeringCheck(
        key=key, name=name, status=status, severity=severity, detail=detail, **kw
    )


def gate_model_identity(old: EquipmentConfiguration, new: EquipmentConfiguration):
    name = "Model identity"
    missing = [
        side
        for side, cfg in (("existing", old), ("proposed", new))
        if not cfg.model_number or not cfg.manufacturer
    ]
    if missing:
        return _check(
            "model_identity",
            name,
            CheckStatus.OPEN,
            Severity.HIGH,
            "Manufacturer and model number are required on both sides before any "
            f"comparison is accepted; missing for: {', '.join(missing)}.",
            expected="manufacturer + model number on both units",
            observed=f"missing on {', '.join(missing)}",
        )
    if (old.manufacturer, old.model_number) == (new.manufacturer, new.model_number):
        return _check(
            "model_identity",
            name,
            CheckStatus.TRIGGERED,
            Severity.MEDIUM,
            f"Existing and proposed units carry the same identity "
            f"({new.manufacturer} {new.model_number}); there is no substitution to analyse "
            "or the submittal references the wrong model.",
            expected="two distinct models",
            observed=f"{new.manufacturer} {new.model_number} on both sides",
        )
    return _check(
        "model_identity",
        name,
        CheckStatus.CLOSED,
        Severity.INFO,
        f"Comparing {old.manufacturer} {old.model_number} → "
        f"{new.manufacturer} {new.model_number}.",
        expected="two distinct models",
        observed=f"{old.model_number} vs {new.model_number}",
    )


def gate_same_data_type(old: EquipmentConfiguration, new: EquipmentConfiguration):
    name = "Same data type"
    if old.weight is None and new.weight is None:
        return _check(
            "same_data_type",
            name,
            CheckStatus.SKIPPED,
            Severity.INFO,
            "No weight supplied on either side — weight basis check not applicable.",
        )
    if not old.weight_basis or not new.weight_basis:
        return _check(
            "same_data_type",
            name,
            CheckStatus.OPEN,
            Severity.HIGH,
            "The basis of the stated weight (operating / dry / shipping) is not declared "
            "on both sides, so the two figures may not be the same quantity.",
            expected="declared weight basis on both units",
            observed=f"existing={old.weight_basis or 'undeclared'}, "
            f"proposed={new.weight_basis or 'undeclared'}",
        )
    if old.weight_basis != new.weight_basis:
        return _check(
            "same_data_type",
            name,
            CheckStatus.TRIGGERED,
            Severity.HIGH,
            f"Weight basis differs: existing is {old.weight_basis} weight, proposed is "
            f"{new.weight_basis} weight. Comparing them would misstate the delta.",
            expected="matching weight basis",
            observed=f"{old.weight_basis} vs {new.weight_basis}",
        )
    return _check(
        "same_data_type",
        name,
        CheckStatus.CLOSED,
        Severity.INFO,
        f"Both weights are stated on a {new.weight_basis} basis.",
        expected="matching weight basis",
        observed=new.weight_basis,
    )


def gate_configuration_comparability(old: EquipmentConfiguration, new: EquipmentConfiguration):
    name = "Configuration comparability"
    diffs = []
    if old.equipment_type and new.equipment_type and old.equipment_type != new.equipment_type:
        diffs.append(f"equipment type {old.equipment_type} → {new.equipment_type}")
    if old.circuits and new.circuits and old.circuits != new.circuits:
        diffs.append(f"refrigeration circuits {old.circuits} → {new.circuits}")
    if (
        old.configuration_code
        and new.configuration_code
        and old.configuration_code != new.configuration_code
    ):
        diffs.append(f"configuration code {old.configuration_code} → {new.configuration_code}")
    if not (old.equipment_type and new.equipment_type):
        return _check(
            "configuration_comparability",
            name,
            CheckStatus.OPEN,
            Severity.MEDIUM,
            "Equipment type is not declared on both sides; comparability cannot be established.",
            expected="declared equipment type on both units",
            observed=f"existing={old.equipment_type or 'undeclared'}, "
            f"proposed={new.equipment_type or 'undeclared'}",
        )
    if diffs:
        return _check(
            "configuration_comparability",
            name,
            CheckStatus.TRIGGERED,
            Severity.HIGH,
            "Configurations are not directly comparable: " + "; ".join(diffs) + ".",
            expected="matching configuration",
            observed="; ".join(diffs),
        )
    return _check(
        "configuration_comparability",
        name,
        CheckStatus.CLOSED,
        Severity.INFO,
        f"Both units are {new.equipment_type}"
        + (f" with {new.circuits} circuits" if new.circuits else "")
        + ".",
    )


def gate_units(old: EquipmentConfiguration, new: EquipmentConfiguration):
    name = "Unit compatibility & conversion"
    problems: list[str] = []
    compared = 0
    for field in COMPARED_FIELDS:
        a, b = getattr(old, field), getattr(new, field)
        if not isinstance(a, Quantity) or not isinstance(b, Quantity):
            continue
        compared += 1
        try:
            units.subtract(b, a)
        except units.UnitError as exc:
            problems.append(f"{field}: {exc}")
    if compared == 0:
        return _check(
            "unit_compatibility",
            name,
            CheckStatus.SKIPPED,
            Severity.INFO,
            "No field is populated on both sides, so no unit conversion is required yet.",
        )
    if problems:
        return _check(
            "unit_compatibility",
            name,
            CheckStatus.TRIGGERED,
            Severity.CRITICAL,
            "Values are not dimensionally comparable: " + "; ".join(problems),
            expected="dimensionally compatible units on both sides",
            observed="; ".join(problems),
        )
    return _check(
        "unit_compatibility",
        name,
        CheckStatus.CLOSED,
        Severity.INFO,
        f"{compared} paired value(s) converted to canonical units without a dimensional conflict.",
    )


def gate_rating_conditions(old: EquipmentConfiguration, new: EquipmentConfiguration):
    name = "Rating / operating conditions"
    if not old.cooling_capacity and not new.cooling_capacity:
        return _check(
            "rating_conditions",
            name,
            CheckStatus.SKIPPED,
            Severity.INFO,
            "No performance rating supplied, so rating conditions are not applicable.",
        )
    if not old.rating_conditions or not new.rating_conditions:
        return _check(
            "rating_conditions",
            name,
            CheckStatus.OPEN,
            Severity.HIGH,
            "Capacity is stated without the rating conditions on both sides. Capacity "
            "figures at different conditions cannot be subtracted.",
            expected="rating conditions declared for both capacities",
            observed=f"existing={'present' if old.rating_conditions else 'absent'}, "
            f"proposed={'present' if new.rating_conditions else 'absent'}",
        )
    diffs: list[str] = []
    for field in (
        "entering_water_temp",
        "leaving_water_temp",
        "ambient_temp",
        "condenser_water_flow",
    ):
        a = getattr(old.rating_conditions, field)
        b = getattr(new.rating_conditions, field)
        if a is None and b is None:
            continue
        if a is None or b is None:
            diffs.append(f"{field} stated on only one side")
            continue
        try:
            if "temp" in field:
                delta = abs(units.convert(b, "kelvin").value - units.convert(a, "kelvin").value)
                if delta > RATING_TOLERANCE_K:
                    diffs.append(f"{field} {units.fmt(a)} → {units.fmt(b)}")
            else:
                pct = units.percent_change(b, a)
                if pct is not None and abs(pct) > 1.0:
                    diffs.append(f"{field} {units.fmt(a)} → {units.fmt(b)} ({pct:+.1f}%)")
        except units.UnitError as exc:
            diffs.append(f"{field}: {exc}")
    if old.rating_conditions.standard != new.rating_conditions.standard:
        diffs.append(
            f"rating standard {old.rating_conditions.standard} → {new.rating_conditions.standard}"
        )
    if diffs:
        return _check(
            "rating_conditions",
            name,
            CheckStatus.TRIGGERED,
            Severity.HIGH,
            "Rating-condition gap — the two capacities are not stated at the same point: "
            + "; ".join(diffs)
            + ". A corrected performance point is required before the capacity delta is valid.",
            expected="identical rating conditions",
            observed="; ".join(diffs),
        )
    return _check(
        "rating_conditions",
        name,
        CheckStatus.CLOSED,
        Severity.INFO,
        f"Both capacities are rated at the same conditions "
        f"({new.rating_conditions.standard or 'stated conditions'}).",
    )


def gate_source_availability(old: EquipmentConfiguration, new: EquipmentConfiguration):
    name = "Source availability for every value"
    unsourced: list[str] = []
    for field in COMPARED_FIELDS + ["refrigerant_charge", "power_input"]:
        for side, cfg in (("existing", old), ("proposed", new)):
            if getattr(cfg, field) is not None and field not in cfg.evidence_ids:
                unsourced.append(f"{side}.{field}")
    if unsourced:
        return _check(
            "source_availability",
            name,
            CheckStatus.OPEN,
            Severity.HIGH,
            "These values have no traceable source document and cannot be accepted: "
            + ", ".join(unsourced)
            + ".",
            expected="every compared value cites a document or dataset",
            observed=f"{len(unsourced)} unsourced value(s)",
        )
    return _check(
        "source_availability",
        name,
        CheckStatus.CLOSED,
        Severity.INFO,
        "Every compared value cites a source document.",
    )


def gate_site_compatibility(
    new: EquipmentConfiguration,
    site: CandidateSite | None,
    observations: dict[str, SiteObservation],
):
    name = "Site / rating-condition compatibility"
    if site is None:
        return _check(
            "site_compatibility",
            name,
            CheckStatus.SKIPPED,
            Severity.INFO,
            "No site is linked to this change, so site conditions are not applicable.",
        )
    rated = new.rating_conditions.ambient_temp if new.rating_conditions else None
    obs = observations.get("ambient_design_db_c")
    usable = obs and obs.status not in (EvidenceStatus.MISSING, EvidenceStatus.STALE)
    if rated is None or not usable:
        return _check(
            "site_compatibility",
            name,
            CheckStatus.OPEN,
            Severity.HIGH,
            "Cannot compare the proposed unit's rated ambient temperature with the site "
            "design dry-bulb: "
            + ("rated ambient not stated. " if rated is None else "")
            + ("site ambient design temperature is not available. " if not usable else ""),
            expected="rated ambient ≥ site design dry-bulb",
            observed=f"rated={units.fmt(rated) if rated else 'unknown'}, "
            f"site={obs.value if obs else 'unknown'}",
        )
    site_temp = units.convert(Quantity(value=float(obs.value), unit="degC"), "kelvin").value
    rated_k = units.convert(rated, "kelvin").value
    if site_temp > rated_k:
        return _check(
            "site_compatibility",
            name,
            CheckStatus.TRIGGERED,
            Severity.HIGH,
            f"Site design dry-bulb ({obs.value} degC) exceeds the proposed unit's rated "
            f"ambient ({units.fmt(rated)}). Capacity must be re-rated at site conditions "
            "before the substitution can be accepted.",
            expected="rated ambient ≥ site design dry-bulb",
            observed=f"site {obs.value} degC vs rated {units.fmt(rated)}",
            evidence_ids=[obs.evidence_id] if obs.evidence_id else [],
        )
    return _check(
        "site_compatibility",
        name,
        CheckStatus.CLOSED,
        Severity.INFO,
        f"Rated ambient {units.fmt(rated)} covers the site design dry-bulb "
        f"of {obs.value} degC.",
        evidence_ids=[obs.evidence_id] if obs.evidence_id else [],
    )


def gate_coordinate_accuracy(site: CandidateSite | None):
    name = "Coordinate / location accuracy"
    if site is None:
        return _check(
            "coordinate_accuracy",
            name,
            CheckStatus.SKIPPED,
            Severity.INFO,
            "No site is linked to this change.",
        )
    if site.latitude is None or site.longitude is None:
        return _check(
            "coordinate_accuracy",
            name,
            CheckStatus.OPEN,
            Severity.MEDIUM,
            f"Site {site.name} has no resolved coordinates, so site-dependent facts cannot "
            "be attached to this change.",
            expected="resolved coordinates",
            observed="none",
        )
    resolution = (site.geocode_resolution or "unknown").lower()
    if resolution not in ACCEPTABLE_RESOLUTIONS:
        return _check(
            "coordinate_accuracy",
            name,
            CheckStatus.TRIGGERED,
            Severity.MEDIUM,
            f"Coordinates for {site.name} resolve only to '{resolution}' precision. Site "
            "facts fetched at this precision may not describe the actual parcel.",
            expected=f"one of {sorted(ACCEPTABLE_RESOLUTIONS)}",
            observed=resolution,
        )
    return _check(
        "coordinate_accuracy",
        name,
        CheckStatus.CLOSED,
        Severity.INFO,
        f"{site.name} resolves to {resolution} precision "
        f"({site.latitude:.5f}, {site.longitude:.5f}).",
    )


def gate_capacity_requirement(new: EquipmentConfiguration, requirements: list[Requirement]):
    """Compare the proposed capacity with the confirmed project requirement."""
    name = "Capacity vs project requirement"
    req = next(
        (
            r
            for r in requirements
            if r.field_key == "cooling_capacity" and r.value is not None and r.unit
        ),
        None,
    )
    if req is None:
        return _check(
            "capacity_requirement",
            name,
            CheckStatus.OPEN,
            Severity.MEDIUM,
            "No confirmed cooling-capacity requirement was extracted from the project "
            "specification, so the proposed unit cannot be checked against it.",
            expected="a specified minimum capacity",
            observed="none extracted",
        )
    if new.cooling_capacity is None:
        return _check(
            "capacity_requirement",
            name,
            CheckStatus.OPEN,
            Severity.HIGH,
            "The proposed unit's rated capacity was not supplied.",
            expected=f"≥ {req.value} {req.unit}",
            observed="unknown",
        )
    required = Quantity(value=float(req.value), unit=req.unit)
    try:
        margin = units.percent_change(new.cooling_capacity, required)
    except units.UnitError as exc:
        return _check(
            "capacity_requirement",
            name,
            CheckStatus.TRIGGERED,
            Severity.HIGH,
            f"Capacity requirement cannot be compared: {exc}",
        )
    confirmed = " (engineer-confirmed)" if req.confirmed else " (extracted, unconfirmed)"
    if margin is not None and margin < 0:
        return _check(
            "capacity_requirement",
            name,
            CheckStatus.TRIGGERED,
            Severity.CRITICAL,
            f"Proposed capacity {units.fmt(new.cooling_capacity)} is {abs(margin):.1f}% below "
            f"the specified {units.fmt(required)}{confirmed}.",
            expected=f"≥ {units.fmt(required)}",
            observed=units.fmt(new.cooling_capacity),
            evidence_ids=[req.evidence_id] if req.evidence_id else [],
        )
    return _check(
        "capacity_requirement",
        name,
        CheckStatus.CLOSED,
        Severity.INFO,
        f"Proposed capacity {units.fmt(new.cooling_capacity)} meets the specified "
        f"{units.fmt(required)}{confirmed} ({margin:+.1f}%).",
        evidence_ids=[req.evidence_id] if req.evidence_id else [],
    )


def run_verification_gates(
    old: EquipmentConfiguration,
    new: EquipmentConfiguration,
    *,
    site: CandidateSite | None = None,
    observations: dict[str, SiteObservation] | None = None,
    requirements: list[Requirement] | None = None,
) -> list[EngineeringCheck]:
    observations = observations or {}
    requirements = requirements or []
    return [
        gate_model_identity(old, new),
        gate_same_data_type(old, new),
        gate_configuration_comparability(old, new),
        gate_units(old, new),
        gate_rating_conditions(old, new),
        gate_source_availability(old, new),
        gate_site_compatibility(new, site, observations),
        gate_coordinate_accuracy(site),
        gate_capacity_requirement(new, requirements),
    ]


def gaps_from_checks(
    checks: list[EngineeringCheck], project_id: str, subject_id: str
) -> list[InformationGap]:
    source_by_key = {
        "model_identity": SourceType.PROJECT_DOCUMENT,
        "same_data_type": SourceType.MANUFACTURER_DOCUMENT,
        "configuration_comparability": SourceType.MANUFACTURER_DOCUMENT,
        "rating_conditions": SourceType.MANUFACTURER_DOCUMENT,
        "source_availability": SourceType.MANUFACTURER_DOCUMENT,
        "site_compatibility": SourceType.MIREYE,
        "coordinate_accuracy": SourceType.MIREYE,
        "capacity_requirement": SourceType.PROJECT_DOCUMENT,
    }
    action_by_source = {
        SourceType.MANUFACTURER_DOCUMENT: NextActionType.VENDOR_EVIDENCE_REQUEST,
        SourceType.PROJECT_DOCUMENT: NextActionType.RFI,
        SourceType.MIREYE: NextActionType.CLARIFICATION_REQUEST,
    }
    gaps: list[InformationGap] = []
    for check in checks:
        if check.status != CheckStatus.OPEN:
            continue
        source = source_by_key.get(check.key, SourceType.PROJECT_DOCUMENT)
        gap = InformationGap(
            project_id=project_id,
            subject_id=subject_id,
            field_key=check.key,
            description=check.detail,
            why_it_matters=f"The '{check.name}' verification gate cannot be closed without it.",
            expected_source=source,
            suggested_action=action_by_source.get(source, NextActionType.RFI),
            severity=check.severity,
        )
        check.gap_ids.append(gap.id)
        gaps.append(gap)
    return gaps
