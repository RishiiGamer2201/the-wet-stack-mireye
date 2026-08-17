"""Deterministic equipment delta calculation.

Only values that survive the verification gate reach this module. Every delta is
computed in a canonical unit via Pint; a missing value produces an OPEN delta and
an InformationGap, never an assumed number.

Thresholds are in `THRESHOLDS` and documented in `docs/engineering-rules.md`.
"""

from __future__ import annotations

from ..domain import (
    CheckStatus,
    DeltaResult,
    EquipmentConfiguration,
    InformationGap,
    NextActionType,
    Quantity,
    Severity,
    SourceType,
)
from . import units

#: percent-change magnitude above which a delta is TRIGGERED / escalated.
THRESHOLDS: dict[str, tuple[float, float]] = {
    # field:            (trigger %, critical %)
    "weight": (5.0, 15.0),
    "support_point_load_max": (5.0, 15.0),
    "dimension": (2.0, 10.0),
    "footprint_area": (3.0, 12.0),
    "electrical_current": (0.0, 10.0),
    "power_input": (5.0, 15.0),
    "refrigerant_charge": (10.0, 30.0),
    "cooling_capacity": (2.0, 10.0),
}

_LABELS = {
    "weight": "Operating weight",
    "support_point_load_max": "Max support-point load",
    "length": "Length",
    "width": "Width",
    "height": "Height",
    "footprint_area": "Footprint area",
    "full_load_amps": "Full load amps",
    "mca": "Minimum circuit ampacity",
    "mocp": "Max overcurrent protection",
    "power_input": "Electrical power input",
    "voltage": "Supply voltage",
    "phases": "Supply phases",
    "refrigerant_type": "Refrigerant type",
    "refrigerant_charge": "Refrigerant charge",
    "cooling_capacity": "Cooling capacity",
}


def _severity(pct: float | None, key: str) -> tuple[Severity, CheckStatus, str]:
    trigger, critical = THRESHOLDS.get(key, (5.0, 15.0))
    if pct is None:
        return Severity.MEDIUM, CheckStatus.OPEN, "baseline is zero — percent change undefined"
    mag = abs(pct)
    if mag > critical:
        return (
            Severity.CRITICAL,
            CheckStatus.TRIGGERED,
            f"|Δ| {mag:.1f}% exceeds the {critical:g}% critical threshold",
        )
    if mag > trigger:
        return (
            Severity.HIGH,
            CheckStatus.TRIGGERED,
            f"|Δ| {mag:.1f}% exceeds the {trigger:g}% coordination threshold",
        )
    if mag > 0:
        return Severity.LOW, CheckStatus.CLOSED, f"|Δ| {mag:.1f}% within the {trigger:g}% threshold"
    return Severity.INFO, CheckStatus.CLOSED, "no change"


def _missing(field: str, old: Quantity | None, new: Quantity | None) -> DeltaResult:
    """Both sides absent -> not applicable (SKIPPED). One side absent -> OPEN gap."""
    label = _LABELS.get(field, field)
    if old is None and new is None:
        return DeltaResult(
            field=field,
            label=label,
            old_value=None,
            new_value=None,
            status=CheckStatus.SKIPPED,
            severity=Severity.INFO,
            direction="unknown",
            explanation=f"{label} is not stated for either unit, so it is not part of this change.",
        )
    which = "existing" if old is None else "proposed"
    return DeltaResult(
        field=field,
        label=label,
        old_value=old,
        new_value=new,
        status=CheckStatus.OPEN,
        severity=Severity.MEDIUM,
        direction="unknown",
        explanation=(
            f"{label} cannot be compared: no value supplied for the {which} equipment. "
            "No substitute value has been assumed."
        ),
    )


def quantity_delta(
    field: str,
    old: Quantity | None,
    new: Quantity | None,
    *,
    threshold_key: str | None = None,
    evidence_ids: list[str] | None = None,
) -> DeltaResult:
    """One deterministic delta between two quantities."""
    label = _LABELS.get(field, field)
    if old is None or new is None:
        return _missing(field, old, new)
    try:
        abs_delta = units.subtract(new, old)
        pct = units.percent_change(new, old)
    except units.IncompatibleUnitsError as exc:
        return DeltaResult(
            field=field,
            label=label,
            old_value=old,
            new_value=new,
            status=CheckStatus.TRIGGERED,
            severity=Severity.HIGH,
            direction="unknown",
            explanation=f"{label} cannot be compared: {exc}",
            evidence_ids=evidence_ids or [],
        )
    except units.UnknownUnitError as exc:
        return DeltaResult(
            field=field,
            label=label,
            old_value=old,
            new_value=new,
            status=CheckStatus.OPEN,
            severity=Severity.MEDIUM,
            direction="unknown",
            explanation=f"{label} cannot be compared: {exc}",
            evidence_ids=evidence_ids or [],
        )

    severity, status, note = _severity(pct, threshold_key or field)
    direction = (
        "unchanged"
        if abs_delta.value == 0
        else ("increase" if abs_delta.value > 0 else "decrease")
    )
    pct_txt = f"{pct:+.1f}%" if pct is not None else "n/a"
    return DeltaResult(
        field=field,
        label=label,
        old_value=old,
        new_value=new,
        absolute_delta=abs_delta,
        percent_delta=round(pct, 3) if pct is not None else None,
        direction=direction,
        severity=severity,
        status=status,
        threshold_note=note,
        explanation=(
            f"{label}: {units.fmt(old)} → {units.fmt(new)} "
            f"({units.fmt(abs_delta)}, {pct_txt}); {note}."
        ),
        evidence_ids=evidence_ids or [],
    )


def _max_support_load(cfg: EquipmentConfiguration) -> Quantity | None:
    if not cfg.support_points:
        return None
    try:
        canonical = [units.to_canonical(p.load) for p in cfg.support_points]
    except units.UnitError:
        return None
    return max(canonical, key=lambda q: q.value)


def _footprint(cfg: EquipmentConfiguration) -> Quantity | None:
    if not (cfg.length and cfg.width):
        return None
    try:
        length = units.convert(cfg.length, "meter")
        width = units.convert(cfg.width, "meter")
    except units.UnitError:
        return None
    return Quantity(value=round(length.value * width.value, 4), unit="m ** 2")


def categorical_delta(field: str, old: str | None, new: str | None) -> DeltaResult:
    label = _LABELS.get(field, field)
    if old is None and new is None:
        return DeltaResult(
            field=field,
            label=label,
            old_value=None,
            new_value=None,
            status=CheckStatus.SKIPPED,
            severity=Severity.INFO,
            direction="unknown",
            explanation=f"{label} is not stated for either unit, so it is not part of this change.",
        )
    if old is None or new is None:
        which = "existing" if old is None else "proposed"
        return DeltaResult(
            field=field,
            label=label,
            old_value=old,
            new_value=new,
            status=CheckStatus.OPEN,
            severity=Severity.MEDIUM,
            direction="unknown",
            explanation=f"{label} not stated for the {which} equipment.",
        )
    if old == new:
        return DeltaResult(
            field=field,
            label=label,
            old_value=old,
            new_value=new,
            status=CheckStatus.CLOSED,
            severity=Severity.INFO,
            direction="unchanged",
            explanation=f"{label} unchanged ({old}).",
        )
    severity = Severity.HIGH if field in ("refrigerant_type", "voltage", "phases") else Severity.MEDIUM
    return DeltaResult(
        field=field,
        label=label,
        old_value=old,
        new_value=new,
        status=CheckStatus.TRIGGERED,
        severity=severity,
        direction="changed",
        explanation=f"{label} changed: {old} → {new}.",
    )


def compute_deltas(
    old: EquipmentConfiguration, new: EquipmentConfiguration
) -> list[DeltaResult]:
    """The full deterministic delta set for an equipment substitution."""
    results: list[DeltaResult] = []

    def ev(field: str) -> list[str]:
        return [i for i in (old.evidence_ids.get(field), new.evidence_ids.get(field)) if i]

    results.append(quantity_delta("weight", old.weight, new.weight, evidence_ids=ev("weight")))
    results.append(
        quantity_delta(
            "support_point_load_max",
            _max_support_load(old),
            _max_support_load(new),
            evidence_ids=ev("support_points"),
        )
    )
    for dim in ("length", "width", "height"):
        results.append(
            quantity_delta(
                dim,
                getattr(old, dim),
                getattr(new, dim),
                threshold_key="dimension",
                evidence_ids=ev(dim),
            )
        )
    results.append(
        quantity_delta(
            "footprint_area",
            _footprint(old),
            _footprint(new),
            threshold_key="footprint_area",
        )
    )
    results.append(
        categorical_delta(
            "voltage",
            units.fmt(old.voltage) if old.voltage else None,
            units.fmt(new.voltage) if new.voltage else None,
        )
    )
    results.append(
        categorical_delta(
            "phases",
            str(old.phases) if old.phases is not None else None,
            str(new.phases) if new.phases is not None else None,
        )
    )
    for field in ("full_load_amps", "mca", "mocp"):
        results.append(
            quantity_delta(
                field,
                getattr(old, field),
                getattr(new, field),
                threshold_key="electrical_current",
                evidence_ids=ev(field),
            )
        )
    results.append(
        quantity_delta(
            "power_input", old.power_input, new.power_input, evidence_ids=ev("power_input")
        )
    )
    results.append(
        categorical_delta("refrigerant_type", old.refrigerant_type, new.refrigerant_type)
    )
    results.append(
        quantity_delta(
            "refrigerant_charge",
            old.refrigerant_charge,
            new.refrigerant_charge,
            evidence_ids=ev("refrigerant_charge"),
        )
    )
    results.append(
        quantity_delta(
            "cooling_capacity",
            old.cooling_capacity,
            new.cooling_capacity,
            evidence_ids=ev("cooling_capacity"),
        )
    )
    return results


def gaps_from_deltas(
    deltas: list[DeltaResult], project_id: str, subject_id: str
) -> list[InformationGap]:
    """Every OPEN delta becomes an explicit, trackable information gap."""
    gaps: list[InformationGap] = []
    for d in deltas:
        if d.status != CheckStatus.OPEN:
            continue
        gaps.append(
            InformationGap(
                project_id=project_id,
                subject_id=subject_id,
                field_key=d.field,
                description=f"{d.label} is not available for both the existing and proposed unit.",
                why_it_matters=(
                    f"{d.label} is required to compute the substitution delta; without it the "
                    "comparison cannot be closed."
                ),
                expected_source=SourceType.MANUFACTURER_DOCUMENT,
                suggested_action=NextActionType.VENDOR_EVIDENCE_REQUEST,
                severity=d.severity,
            )
        )
    return gaps


def structural_coordination_required(deltas: list[DeltaResult]) -> tuple[bool, list[str]]:
    """Flag structural coordination — never structural adequacy."""
    reasons = [
        d.explanation
        for d in deltas
        if d.field in ("weight", "support_point_load_max")
        and d.status == CheckStatus.TRIGGERED
        and d.direction == "increase"
    ]
    return bool(reasons), reasons
