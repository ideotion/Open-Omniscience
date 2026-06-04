"""
Correct mass-based price-unit conversion.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Fixes the previous normalization bug (P1-9): the old code multiplied by 35.274
(avoirdupois ounces per kg) in the wrong direction, producing prices off by
~1000x. Here every unit is defined by its size in kilograms, and a price in
``currency/from_unit`` is converted to ``currency/to_unit`` by the ratio of unit
sizes -- which is exact and self-checking.

Currency is NOT converted: we do not invent FX rates. Convert only within one
currency; cross-currency comparison must use an explicit, dated FX rate (future
work), never a hardcoded guess.
"""

from __future__ import annotations

# Size of each mass unit expressed in kilograms.
_KG_PER_UNIT: dict[str, float] = {
    "kg": 1.0,
    "g": 0.001,
    "mg": 1e-6,
    "t": 1000.0,            # metric tonne
    "tonne": 1000.0,
    "lb": 0.45359237,       # avoirdupois pound
    "oz": 0.028349523125,   # avoirdupois ounce
    "ozt": 0.0311034768,    # troy ounce
}


class UnitError(ValueError):
    """Raised for an unknown mass unit."""


def known_units() -> list[str]:
    return sorted(_KG_PER_UNIT)


def convert_price(value: float, from_unit: str, to_unit: str) -> float:
    """Convert a price expressed per ``from_unit`` to per ``to_unit``.

    A price is currency/mass. price_per_kg = value / kg_per(from_unit); then
    price_per_to = price_per_kg * kg_per(to_unit). Equivalently:

        value * kg_per(to_unit) / kg_per(from_unit)

    Example: 100 USD/g  ->  USD/kg  = 100 * 1 / 0.001 = 100000 USD/kg (correct:
    a kilogram costs 1000x a gram), NOT 100/35.274.
    """
    fu, tu = from_unit.lower(), to_unit.lower()
    if fu not in _KG_PER_UNIT:
        raise UnitError(f"unknown source unit: {from_unit!r} (known: {known_units()})")
    if tu not in _KG_PER_UNIT:
        raise UnitError(f"unknown target unit: {to_unit!r} (known: {known_units()})")
    return value * _KG_PER_UNIT[tu] / _KG_PER_UNIT[fu]
