"""Site scoring, ranking, missing-data handling and what-if behaviour."""

from __future__ import annotations

import pytest

from app.domain import (
    EvidenceStatus,
    Project,
    RequirementTargets,
    SiteDimension,
    SiteObservation,
)
from app.engine import scoring
from app.fields import DEFAULT_DIMENSION_WEIGHTS, FIELD_INDEX, spec


def obs(field_key, value, status=EvidenceStatus.SYNTHETIC, confidence=0.8):
    fs = FIELD_INDEX[field_key]
    return SiteObservation(
        site_id="s1",
        project_id="p1",
        field_key=field_key,
        dimension=fs.dimension,
        value=value,
        unit=fs.unit,
        status=status,
        confidence=confidence,
        evidence_id=f"ev_{field_key}",
    )


@pytest.fixture
def project():
    return Project(
        id="p1",
        name="Test",
        targets=RequirementTargets(min_grid_capacity_mw=200, max_water_stress_index=3.5),
        dimension_weights=dict(DEFAULT_DIMENSION_WEIGHTS),
    )


def test_normalize_higher_better_clamps():
    fs = spec("grid_capacity_mw")
    assert scoring.normalize(fs, 400) == 100
    assert scoring.normalize(fs, 10) == 0
    assert scoring.normalize(fs, 160) == pytest.approx((160 - 20) / (300 - 20) * 100)


def test_normalize_lower_better_and_band():
    assert scoring.normalize(spec("mean_slope_pct"), 1.0) == 100
    assert scoring.normalize(spec("mean_slope_pct"), 20) == 0
    assert scoring.normalize(spec("elevation_m"), 300) == 100
    assert scoring.normalize(spec("elevation_m"), 0) == pytest.approx((1 - 40 / 400) * 100)


def test_normalize_categorical_unknown_value_is_missing_not_zero():
    assert scoring.normalize(spec("zoning_class"), "industrial") == 100
    assert scoring.normalize(spec("zoning_class"), "lunar_colony") is None


def test_missing_evidence_lowers_coverage_but_never_invents_a_value():
    dimension = scoring.score_dimension(
        SiteDimension.POWER,
        {"grid_capacity_mw": obs("grid_capacity_mw", 300)},
        weight=2.0,
    )
    assert dimension.score == 100
    assert dimension.coverage < 1.0
    missing = [m for m in dimension.metrics if m.status == EvidenceStatus.MISSING]
    assert missing and all(m.normalized is None and m.raw_value is None for m in missing)


def test_site_with_no_evidence_scores_none_and_ranks_last(project):
    good = scoring.score_site(project, "s1", "Good", [obs("grid_capacity_mw", 400)])
    empty = scoring.score_site(project, "s2", "Empty", [])
    ranked = scoring.rank([empty, good])
    assert ranked[0].site_id == "s1" and ranked[0].rank == 1
    assert ranked[1].overall_score is None and ranked[1].rank is None


def test_requirement_flag_unknown_when_evidence_missing(project):
    score = scoring.score_site(project, "s1", "S", [obs("water_stress_index", 1.0)])
    grid = next(f for f in score.requirement_flags if f.requirement == "Grid capacity")
    assert grid.passed is None and grid.actual is None
    assert "cannot be verified" in grid.explanation


def test_requirement_flag_fails_and_escalates_risk(project):
    observations = [obs("grid_capacity_mw", 60), obs("water_stress_index", 4.9)]
    score = scoring.score_site(project, "s1", "S", observations)
    failed = [f for f in score.requirement_flags if f.passed is False]
    assert len(failed) == 2
    assert score.risk_level.value in ("elevated", "high")


def test_weight_change_reorders_ranking(project):
    power_site = [obs("grid_capacity_mw", 400), obs("water_stress_index", 4.5)]
    water_site = [obs("grid_capacity_mw", 120), obs("water_stress_index", 0.5)]
    power_heavy = {d: 0.1 for d in SiteDimension} | {SiteDimension.POWER: 5.0}
    water_heavy = {d: 0.1 for d in SiteDimension} | {SiteDimension.WATER: 5.0}

    a = scoring.rank(
        [
            scoring.score_site(project, "s1", "PowerSite", power_site, power_heavy),
            scoring.score_site(project, "s2", "WaterSite", water_site, power_heavy),
        ]
    )
    b = scoring.rank(
        [
            scoring.score_site(project, "s1", "PowerSite", power_site, water_heavy),
            scoring.score_site(project, "s2", "WaterSite", water_site, water_heavy),
        ]
    )
    assert a[0].site_name == "PowerSite"
    assert b[0].site_name == "WaterSite"


def test_compare_explains_the_gap(project):
    a = scoring.score_site(project, "s1", "A", [obs("grid_capacity_mw", 400)])
    b = scoring.score_site(project, "s2", "B", [obs("grid_capacity_mw", 60)])
    text = scoring.compare(a, b, dict(DEFAULT_DIMENSION_WEIGHTS))
    assert "ranks above" in text and "Power & grid" in text


def test_stale_evidence_reduces_confidence_but_keeps_score(project):
    fresh = scoring.score_site(project, "s1", "S", [obs("grid_capacity_mw", 400)])
    stale = scoring.score_site(
        project, "s1", "S", [obs("grid_capacity_mw", 400, status=EvidenceStatus.STALE)]
    )
    assert stale.overall_score is None  # STALE is not usable evidence
    assert fresh.overall_score == 100
    assert stale.confidence < fresh.confidence


def test_user_confirmed_evidence_scores_at_full_confidence(project):
    confirmed = scoring.score_site(
        project,
        "s1",
        "S",
        [obs("grid_capacity_mw", 400, status=EvidenceStatus.USER_CONFIRMED, confidence=0.95)],
    )
    synthetic = scoring.score_site(project, "s1", "S", [obs("grid_capacity_mw", 400)])
    assert confirmed.confidence > synthetic.confidence
