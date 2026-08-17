"""Deterministic site scoring.

Formulas (all documented in `docs/scoring.md`):

    higher_better   n = clamp((v - bad) / (good - bad), 0, 1) * 100
    lower_better    n = clamp((bad - v) / (bad - good), 0, 1) * 100
    band            n = 100 inside [low, high], decaying linearly to 0 at
                        low - tolerance / high + tolerance
    categorical     n = table lookup; an unmapped category is *missing*, not 0

    dimension score = Σ(w_i · n_i) / Σ(w_i)   over metrics that have evidence
    coverage        = Σ(w_i evidenced) / Σ(w_i all)
    overall score   = Σ(W_d · score_d) / Σ(W_d)  over dimensions that scored
    coverage(site)  = Σ(W_d · coverage_d) / Σ(W_d)

Missing evidence never contributes a value. It lowers coverage and confidence,
and it is listed explicitly in `missing_fields`.
"""

from __future__ import annotations

from ..domain import (
    DimensionScore,
    EvidenceStatus,
    MetricScore,
    Project,
    RequirementFlag,
    RiskLevel,
    Severity,
    SiteDimension,
    SiteObservation,
    SiteScore,
)
from ..fields import (
    DEFAULT_DIMENSION_WEIGHTS,
    DIMENSION_FIELDS,
    DIMENSION_LABELS,
    FIELD_INDEX,
    FieldSpec,
)

USABLE = {
    EvidenceStatus.LIVE,
    EvidenceStatus.CACHED,
    EvidenceStatus.SYNTHETIC,
    EvidenceStatus.USER_CONFIRMED,
}

#: Evidence status -> multiplier applied to the metric's contribution to confidence.
STATUS_CONFIDENCE = {
    EvidenceStatus.LIVE: 1.0,
    EvidenceStatus.USER_CONFIRMED: 1.0,
    EvidenceStatus.CACHED: 0.9,
    EvidenceStatus.SYNTHETIC: 0.6,
    EvidenceStatus.STALE: 0.35,
    EvidenceStatus.MISSING: 0.0,
}


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def normalize(spec: FieldSpec, value: float | str | None) -> float | None:
    """Map a raw field value to 0–100 (higher is better). None means 'no score'."""
    if value is None:
        return None
    if spec.direction == "categorical":
        if not isinstance(value, str) or not spec.categories:
            return None
        return spec.categories.get(value)
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if spec.direction == "higher_better":
        assert spec.good is not None and spec.bad is not None
        return clamp((v - spec.bad) / (spec.good - spec.bad)) * 100
    if spec.direction == "lower_better":
        assert spec.good is not None and spec.bad is not None
        return clamp((spec.bad - v) / (spec.bad - spec.good)) * 100
    if spec.direction == "band":
        low, high = spec.band_low or 0.0, spec.band_high or 0.0
        tol = spec.band_tolerance or 1.0
        if low <= v <= high:
            return 100.0
        distance = (low - v) if v < low else (v - high)
        return clamp(1 - distance / tol) * 100
    return None


def _explain(spec: FieldSpec, value, normalized: float | None, status: EvidenceStatus) -> str:
    if status == EvidenceStatus.MISSING or normalized is None:
        return f"{spec.label}: no evidence available — excluded from the score."
    unit = f" {spec.unit}" if spec.unit and spec.unit != "dimensionless" else ""
    shown = value if isinstance(value, str) else f"{float(value):g}{unit}"
    if spec.direction == "higher_better":
        basis = f"target ≥ {spec.good:g}, poor at {spec.bad:g}"
    elif spec.direction == "lower_better":
        basis = f"target ≤ {spec.good:g}, poor at {spec.bad:g}"
    elif spec.direction == "band":
        basis = f"preferred band {spec.band_low:g}–{spec.band_high:g}"
    else:
        basis = "category scale"
    label = "" if status != EvidenceStatus.SYNTHETIC else " (synthetic demo value)"
    return f"{spec.label}: {shown} → {normalized:.0f}/100 ({basis}){label}."


def score_dimension(
    dimension: SiteDimension,
    observations: dict[str, SiteObservation],
    weight: float,
) -> DimensionScore:
    metrics: list[MetricScore] = []
    weighted_sum = 0.0
    used_weight = 0.0
    total_weight = 0.0
    confidence_sum = 0.0

    for spec in DIMENSION_FIELDS[dimension]:
        total_weight += spec.weight
        obs = observations.get(spec.key)
        status = obs.status if obs else EvidenceStatus.MISSING
        raw = obs.value if obs and status in USABLE else None
        normalized = normalize(spec, raw) if raw is not None else None
        if normalized is not None:
            weighted_sum += normalized * spec.weight
            used_weight += spec.weight
            base_conf = obs.confidence if obs else 0.0
            confidence_sum += spec.weight * base_conf * STATUS_CONFIDENCE.get(status, 0.5)
        metrics.append(
            MetricScore(
                field_key=spec.key,
                label=spec.label,
                raw_value=raw if raw is not None else (obs.value if obs else None),
                unit=spec.unit,
                normalized=normalized,
                weight=spec.weight,
                status=status,
                evidence_id=obs.evidence_id if obs else None,
                explanation=_explain(spec, raw, normalized, status),
            )
        )

    score = weighted_sum / used_weight if used_weight else None
    coverage = used_weight / total_weight if total_weight else 0.0
    confidence = (confidence_sum / used_weight) if used_weight else 0.0
    confidence *= 0.4 + 0.6 * coverage

    scored = [m for m in metrics if m.normalized is not None]
    drivers = [m.explanation for m in sorted(scored, key=lambda m: -(m.normalized or 0))[:2]]
    concerns = [
        m.explanation for m in sorted(scored, key=lambda m: (m.normalized or 0)) if m.normalized < 55
    ][:3]
    return DimensionScore(
        dimension=dimension,
        score=score,
        weight=weight,
        coverage=coverage,
        confidence=round(confidence, 3),
        metrics=metrics,
        drivers=drivers,
        concerns=concerns,
    )


def check_requirements(
    project: Project, observations: dict[str, SiteObservation]
) -> list[RequirementFlag]:
    """Hard project targets evaluated against evidence. Missing evidence yields
    `passed = None` (unknown) — never an assumed pass."""
    t = project.targets
    rules: list[tuple[str, str, float | None, str, str]] = [
        ("Grid capacity", "min_grid_capacity_mw", t.min_grid_capacity_mw, "grid_capacity_mw", "ge"),
        (
            "Distance to substation",
            "max_distance_to_substation_km",
            t.max_distance_to_substation_km,
            "distance_to_substation_km",
            "le",
        ),
        (
            "Water stress",
            "max_water_stress_index",
            t.max_water_stress_index,
            "water_stress_index",
            "le",
        ),
        (
            "Permit lead time",
            "max_permit_lead_time_months",
            t.max_permit_lead_time_months,
            "permit_lead_time_months",
            "le",
        ),
        (
            "Soil bearing capacity",
            "min_bearing_capacity_kpa",
            t.min_bearing_capacity_kpa,
            "soil_bearing_capacity_kpa",
            "ge",
        ),
        ("Seismic PGA", "max_seismic_pga_g", t.max_seismic_pga_g, "seismic_pga_g", "le"),
        ("IX latency", "max_latency_to_ix_ms", t.max_latency_to_ix_ms, "latency_to_ix_ms", "le"),
    ]
    flags: list[RequirementFlag] = []
    for label, _attr, target, field_key, op in rules:
        if target is None:
            continue
        spec = FIELD_INDEX[field_key]
        unit = f" {spec.unit}" if spec.unit and spec.unit != "dimensionless" else ""
        obs = observations.get(field_key)
        if obs is None or obs.status not in USABLE or obs.value is None:
            flags.append(
                RequirementFlag(
                    requirement=label,
                    target=f"{'≥' if op == 'ge' else '≤'} {target:g}{unit}",
                    actual=None,
                    passed=None,
                    severity=Severity.HIGH,
                    explanation=f"{label} cannot be verified: no evidence for {field_key}.",
                )
            )
            continue
        value = float(obs.value)
        passed = value >= target if op == "ge" else value <= target
        margin = abs(value - target) / target * 100 if target else 0.0
        severity = (
            Severity.INFO if passed else (Severity.CRITICAL if margin > 25 else Severity.HIGH)
        )
        flags.append(
            RequirementFlag(
                requirement=label,
                target=f"{'≥' if op == 'ge' else '≤'} {target:g}{unit}",
                actual=f"{value:g}{unit}",
                passed=passed,
                severity=severity,
                explanation=(
                    f"{label} {value:g}{unit} "
                    f"{'meets' if passed else 'misses'} the project target "
                    f"({'≥' if op == 'ge' else '≤'} {target:g}{unit})"
                    + ("" if passed else f", off by {margin:.0f}%.")
                ),
            )
        )
    return flags


def risk_level(overall: float | None, coverage: float, flags: list[RequirementFlag]) -> RiskLevel:
    ladder = [RiskLevel.LOW, RiskLevel.MODERATE, RiskLevel.ELEVATED, RiskLevel.HIGH]
    if overall is None:
        return RiskLevel.HIGH
    idx = 0 if overall >= 75 else 1 if overall >= 62 else 2 if overall >= 48 else 3
    if coverage < 0.6:
        idx += 1
    idx += sum(1 for f in flags if f.passed is False and f.severity == Severity.CRITICAL)
    if any(f.passed is False for f in flags):
        idx += 1
    return ladder[min(idx, 3)]


def score_site(
    project: Project,
    site_id: str,
    site_name: str,
    observations: list[SiteObservation],
    weights: dict[SiteDimension, float] | None = None,
) -> SiteScore:
    weights = weights or project.dimension_weights or DEFAULT_DIMENSION_WEIGHTS
    by_key = {o.field_key: o for o in observations}

    dimensions = [
        score_dimension(dim, by_key, weights.get(dim, DEFAULT_DIMENSION_WEIGHTS[dim]))
        for dim in SiteDimension
    ]

    total_w = sum(d.weight for d in dimensions)
    scored = [d for d in dimensions if d.score is not None]
    scored_w = sum(d.weight for d in scored)
    overall = sum(d.score * d.weight for d in scored) / scored_w if scored_w else None
    coverage = sum(d.coverage * d.weight for d in dimensions) / total_w if total_w else 0.0
    confidence = sum(d.confidence * d.weight for d in dimensions) / total_w if total_w else 0.0

    flags = check_requirements(project, by_key)
    missing = [
        m.field_key for d in dimensions for m in d.metrics if m.status == EvidenceStatus.MISSING
    ]
    synthetic = sum(
        1 for d in dimensions for m in d.metrics if m.status == EvidenceStatus.SYNTHETIC
    )

    best = max(scored, key=lambda d: d.score) if scored else None
    worst = min(scored, key=lambda d: d.score) if scored else None
    parts = []
    if overall is not None:
        parts.append(f"Overall {overall:.1f}/100 from {len(scored)} evidenced dimensions.")
    if best:
        parts.append(f"Strongest: {DIMENSION_LABELS[best.dimension]} ({best.score:.0f}).")
    if worst and worst is not best:
        parts.append(f"Weakest: {DIMENSION_LABELS[worst.dimension]} ({worst.score:.0f}).")
    if missing:
        parts.append(f"{len(missing)} field(s) missing evidence.")
    failed = [f.requirement for f in flags if f.passed is False]
    if failed:
        parts.append("Fails project target(s): " + ", ".join(failed) + ".")

    return SiteScore(
        site_id=site_id,
        site_name=site_name,
        overall_score=round(overall, 2) if overall is not None else None,
        evidence_coverage=round(coverage, 3),
        confidence=round(confidence, 3),
        risk_level=risk_level(overall, coverage, flags),
        dimensions=dimensions,
        requirement_flags=flags,
        missing_fields=missing,
        synthetic_field_count=synthetic,
        summary=" ".join(parts),
    )


def rank(scores: list[SiteScore]) -> list[SiteScore]:
    """Sort by overall score, tie-broken by confidence then coverage. Sites with
    no score at all rank last and keep `rank = None`."""
    scorable = [s for s in scores if s.overall_score is not None]
    unscored = [s for s in scores if s.overall_score is None]
    scorable.sort(key=lambda s: (-s.overall_score, -s.confidence, -s.evidence_coverage))
    for i, s in enumerate(scorable, start=1):
        s.rank = i
    for s in unscored:
        s.rank = None
    return scorable + unscored


def compare(a: SiteScore, b: SiteScore, weights: dict[SiteDimension, float]) -> str:
    """Explain, in weighted-contribution terms, why `a` ranks above `b`."""
    if a.overall_score is None or b.overall_score is None:
        return f"{a.site_name} cannot be compared to {b.site_name}: one has no scored dimension."
    total_w = sum(weights.values())
    diffs: list[tuple[float, str]] = []
    bmap = {d.dimension: d for d in b.dimensions}
    for d in a.dimensions:
        other = bmap.get(d.dimension)
        if not other or d.score is None or other.score is None:
            continue
        contribution = (d.score - other.score) * weights.get(d.dimension, 1.0) / total_w
        if abs(contribution) >= 0.5:
            diffs.append((contribution, DIMENSION_LABELS[d.dimension]))
    diffs.sort(key=lambda x: -abs(x[0]))
    lead = f"{a.site_name} ({a.overall_score:.1f}) ranks above {b.site_name} ({b.overall_score:.1f})"
    if not diffs:
        return lead + " on aggregate; no single dimension dominates the gap."
    top = "; ".join(
        f"{name} {'+' if c > 0 else ''}{c:.1f} pts weighted" for c, name in diffs[:3]
    )
    return f"{lead}. Largest weighted contributions: {top}."
