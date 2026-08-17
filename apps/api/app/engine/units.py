"""Unit handling built on Pint.

Every numeric comparison in the platform goes through here. Incompatible units
raise :class:`IncompatibleUnitsError` — they are never coerced, and never
silently dropped.
"""

from __future__ import annotations

from functools import lru_cache

from pint import UnitRegistry
from pint.errors import DimensionalityError, UndefinedUnitError

from ..domain import Quantity


class UnitError(ValueError):
    """Base class for unit problems surfaced to the verification gate."""


class UnknownUnitError(UnitError):
    pass


class IncompatibleUnitsError(UnitError):
    pass


@lru_cache
def registry() -> UnitRegistry:
    ureg = UnitRegistry()
    # Domain shorthand used in equipment schedules.
    ureg.define("refrigeration_ton = 3516.8528421 * watt = RT = ton_refrigeration")
    ureg.define("amp = ampere")
    return ureg


#: Unit every comparison of a given physical kind is normalised to before deltas.
CANONICAL: dict[str, str] = {
    "mass": "kilogram",
    "force": "kilonewton",
    "length": "millimeter",
    "area": "meter ** 2",
    "power": "kilowatt",
    "current": "ampere",
    "voltage": "volt",
    "temperature": "degC",
    "volumetric_flow": "liter / second",
    "pressure": "kilopascal",
    "sound": "decibel",
}


def parse(quantity: Quantity):
    """Quantity -> pint quantity. Raises UnknownUnitError on a bad unit string.

    Uses `Quantity(value, unit)` rather than `value * unit` so that offset units
    such as degC do not raise an ambiguous-operation error.
    """
    try:
        return registry().Quantity(quantity.value, quantity.unit)
    except (UndefinedUnitError, AttributeError, TypeError, ValueError) as exc:
        raise UnknownUnitError(f"unknown unit {quantity.unit!r}") from exc


def dimensionality(unit: str):
    try:
        return registry().Unit(unit).dimensionality
    except (UndefinedUnitError, AttributeError, TypeError, ValueError) as exc:
        raise UnknownUnitError(f"unknown unit {unit!r}") from exc


def compatible(a: Quantity, b: Quantity) -> bool:
    try:
        return dimensionality(a.unit) == dimensionality(b.unit)
    except UnknownUnitError:
        return False


def convert(quantity: Quantity, target_unit: str) -> Quantity:
    """Convert to `target_unit`, raising IncompatibleUnitsError across dimensions."""
    pq = parse(quantity)
    try:
        converted = pq.to(target_unit)
    except DimensionalityError as exc:
        raise IncompatibleUnitsError(
            f"cannot convert {quantity.unit!r} to {target_unit!r}: different physical quantities"
        ) from exc
    except (UndefinedUnitError, AttributeError, ValueError) as exc:
        raise UnknownUnitError(f"unknown target unit {target_unit!r}") from exc
    return Quantity(value=float(converted.magnitude), unit=target_unit)


def to_canonical(quantity: Quantity) -> Quantity:
    """Convert to the canonical unit for its dimensionality."""
    dim = dimensionality(quantity.unit)
    for _, unit in CANONICAL.items():
        try:
            if dimensionality(unit) == dim:
                return convert(quantity, unit)
        except UnknownUnitError:  # pragma: no cover - static table
            continue
    return quantity


def subtract(new: Quantity, old: Quantity) -> Quantity:
    """new - old, expressed in the canonical unit of the pair.

    Raises IncompatibleUnitsError when the two are not the same physical quantity.
    """
    # An unparseable unit is a *missing information* problem (UnknownUnitError);
    # a parseable but mismatched one is a comparison error (IncompatibleUnitsError).
    if dimensionality(new.unit) != dimensionality(old.unit):
        raise IncompatibleUnitsError(
            f"cannot subtract {old.unit!r} from {new.unit!r}: different physical quantities"
        )
    canonical = to_canonical(new)
    old_c = convert(old, canonical.unit)
    return Quantity(value=canonical.value - old_c.value, unit=canonical.unit)


def percent_change(new: Quantity, old: Quantity) -> float | None:
    """(new-old)/|old| * 100. None when the baseline is zero (undefined)."""
    delta = subtract(new, old)
    old_c = convert(old, delta.unit)
    if old_c.value == 0:
        return None
    return delta.value / abs(old_c.value) * 100.0


def fmt(quantity: Quantity | None, digits: int = 2) -> str:
    if quantity is None:
        return "—"
    return f"{round(quantity.value, digits):g} {quantity.unit}"
