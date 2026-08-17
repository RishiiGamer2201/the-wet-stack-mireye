"""Unit conversion is the foundation of every delta — it is tested first."""

from __future__ import annotations

import pytest
from app.domain import Quantity
from app.engine import units


def q(value, unit):
    return Quantity(value=value, unit=unit)


def test_convert_mass():
    assert units.convert(q(1000, "kg"), "tonne").value == pytest.approx(1.0)
    assert units.convert(q(2205, "lb"), "kg").value == pytest.approx(1000.2, rel=1e-3)


def test_convert_length_and_power():
    assert units.convert(q(6800, "mm"), "m").value == pytest.approx(6.8)
    assert units.convert(q(1, "refrigeration_ton"), "kW").value == pytest.approx(3.5168, rel=1e-3)


def test_temperature_uses_offset_scale_correctly():
    assert units.convert(q(35, "degC"), "kelvin").value == pytest.approx(308.15)
    assert units.convert(q(95, "degF"), "degC").value == pytest.approx(35.0, rel=1e-6)


def test_incompatible_units_raise_and_are_never_coerced():
    with pytest.raises(units.IncompatibleUnitsError):
        units.convert(q(100, "kg"), "kW")
    with pytest.raises(units.IncompatibleUnitsError):
        units.subtract(q(10, "A"), q(10, "kg"))


def test_unknown_unit_raises():
    with pytest.raises(units.UnknownUnitError):
        units.convert(q(1, "flurbles"), "kg")


def test_subtract_normalises_to_canonical_unit():
    delta = units.subtract(q(5290, "kg"), q(4.85, "tonne"))
    assert delta.unit == "kilogram"
    assert delta.value == pytest.approx(440.0)


def test_percent_change_and_zero_baseline():
    assert units.percent_change(q(5290, "kg"), q(4850, "kg")) == pytest.approx(9.072, rel=1e-3)
    assert units.percent_change(q(5, "kg"), q(0, "kg")) is None


def test_compatible_is_false_for_unknown_units():
    assert units.compatible(q(1, "kg"), q(1, "lb")) is True
    assert units.compatible(q(1, "kg"), q(1, "nonsense")) is False


def test_to_canonical_maps_each_dimension():
    assert units.to_canonical(q(2, "tonne")).unit == "kilogram"
    assert units.to_canonical(q(1, "inch")).unit == "millimeter"
    assert units.to_canonical(q(1, "hp")).unit == "kilowatt"
