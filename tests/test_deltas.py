"""Deterministic equipment deltas."""

from __future__ import annotations

import pytest

from app.domain import (
    CheckStatus,
    EquipmentConfiguration,
    Quantity,
    RatingConditions,
    Severity,
    SupportPoint,
)
from app.engine import deltas


def q(value, unit):
    return Quantity(value=value, unit=unit)


def cfg(**kw) -> EquipmentConfiguration:
    base = dict(
        manufacturer="Northwind Thermal",
        model_number="NT-1100",
        equipment_type="air_cooled_chiller",
        circuits=2,
        weight=q(4850, "kg"),
        weight_basis="operating",
        length=q(6800, "mm"),
        width=q(2250, "mm"),
        height=q(2450, "mm"),
        voltage=q(480, "V"),
        phases=3,
        mca=q(265, "A"),
        refrigerant_type="R-134a",
        refrigerant_charge=q(210, "kg"),
        cooling_capacity=q(1050, "kW"),
        rating_conditions=RatingConditions(ambient_temp=q(35, "degC"), standard="AHRI 550/590"),
    )
    base.update(kw)
    return EquipmentConfiguration(**base)


def find(results, field):
    return next(r for r in results if r.field == field)


def test_weight_delta_is_exact_and_triggers_above_threshold():
    result = deltas.quantity_delta("weight", q(4850, "kg"), q(5290, "kg"))
    assert result.absolute_delta.value == pytest.approx(440.0)
    assert result.percent_delta == pytest.approx(9.072, rel=1e-3)
    assert result.status == CheckStatus.TRIGGERED
    assert result.direction == "increase"


def test_small_delta_closes():
    result = deltas.quantity_delta("weight", q(2400, "kg"), q(2460, "kg"))
    assert result.status == CheckStatus.CLOSED
    assert result.severity == Severity.LOW


def test_mixed_units_convert_before_comparing():
    result = deltas.quantity_delta("weight", q(4850, "kg"), q(5.29, "tonne"))
    assert result.percent_delta == pytest.approx(9.072, rel=1e-3)


def test_incompatible_units_trigger_rather_than_coerce():
    result = deltas.quantity_delta("weight", q(4850, "kg"), q(5290, "kW"))
    assert result.status == CheckStatus.TRIGGERED
    assert "different physical quantities" in result.explanation
    assert result.absolute_delta is None


def test_one_sided_missing_value_is_open_and_generates_a_gap():
    result = deltas.quantity_delta("weight", q(4850, "kg"), None)
    assert result.status == CheckStatus.OPEN
    assert "No substitute value has been assumed" in result.explanation
    gaps = deltas.gaps_from_deltas([result], "p1", "chg1")
    assert len(gaps) == 1 and gaps[0].field_key == "weight"


def test_both_sides_missing_is_skipped_not_open():
    result = deltas.quantity_delta("refrigerant_charge", None, None)
    assert result.status == CheckStatus.SKIPPED
    assert not deltas.gaps_from_deltas([result], "p1", "chg1")


def test_unknown_unit_is_open_not_a_silent_zero():
    result = deltas.quantity_delta("weight", q(1, "wibbles"), q(2, "kg"))
    assert result.status == CheckStatus.OPEN
    assert result.absolute_delta is None


def test_full_delta_set_for_a_real_substitution():
    old = cfg(support_points=[SupportPoint(point_id="P1", load=q(12.1, "kN"))])
    new = cfg(
        model_number="VX-1150",
        weight=q(5290, "kg"),
        support_points=[SupportPoint(point_id="P1", load=q(13.2, "kN"))],
        length=q(7100, "mm"),
        height=q(2600, "mm"),
        mca=q(297, "A"),
        refrigerant_charge=q(232, "kg"),
        cooling_capacity=q(1055, "kW"),
    )
    results = deltas.compute_deltas(old, new)
    assert find(results, "weight").status == CheckStatus.TRIGGERED
    assert find(results, "support_point_load_max").percent_delta == pytest.approx(9.09, rel=1e-2)
    assert find(results, "footprint_area").percent_delta == pytest.approx(4.41, rel=1e-2)
    assert find(results, "mca").status == CheckStatus.TRIGGERED
    assert find(results, "refrigerant_type").status == CheckStatus.CLOSED
    assert find(results, "cooling_capacity").status == CheckStatus.CLOSED  # 0.48% < 2%
    assert find(results, "voltage").direction == "unchanged"


def test_refrigerant_type_change_is_high_severity():
    result = deltas.categorical_delta("refrigerant_type", "R-134a", "R-1234ze")
    assert result.status == CheckStatus.TRIGGERED
    assert result.severity == Severity.HIGH


def test_structural_flag_is_coordination_only():
    old = cfg()
    new = cfg(weight=q(5290, "kg"))
    required, reasons = deltas.structural_coordination_required(deltas.compute_deltas(old, new))
    assert required and reasons
    assert not any("adequate" in r.lower() for r in reasons)


def test_weight_decrease_does_not_require_structural_coordination():
    old = cfg(weight=q(5290, "kg"))
    new = cfg(weight=q(4850, "kg"))
    required, _ = deltas.structural_coordination_required(deltas.compute_deltas(old, new))
    assert required is False
