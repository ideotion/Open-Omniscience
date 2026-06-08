"""
Tests for the pure concentration primitive (Gini + top-N share).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pins exact, hand-computed values on crafted distributions and the honest
"undefined → None" behaviour. These are property-style checks: no DB, no network.
"""

from __future__ import annotations

import math

import pytest

from src.signals import concentration, gini, top_share
from src.signals.concentration import ConcentrationResult


def test_gini_perfect_equality_is_zero():
    assert gini([1, 1, 1, 1]) == 0.0
    assert gini([7, 7, 7]) == 0.0


def test_gini_known_values():
    # Hand-computed by the sorted form: [1,2,3,4] -> 0.25 exactly.
    assert math.isclose(gini([1, 2, 3, 4]), 0.25, rel_tol=1e-9)
    # One actor holds everything among four -> 0.75.
    assert math.isclose(gini([0, 0, 0, 1]), 0.75, rel_tol=1e-9)


def test_gini_undefined_returns_none_not_a_fabricated_zero():
    assert gini([]) is None        # no actors
    assert gini([5]) is None       # a single actor has no inequality
    assert gini([0, 0, 0]) is None  # zero total


def test_gini_rejects_negative_values():
    with pytest.raises(ValueError):
        gini([1, -2, 3])


def test_top_share():
    assert math.isclose(top_share([1, 2, 3, 4], 1), 0.4, rel_tol=1e-9)
    assert math.isclose(top_share([1, 2, 3, 4], 2), 0.7, rel_tol=1e-9)
    assert top_share([], 3) is None
    # k is clamped to the available count.
    assert math.isclose(top_share([2, 2], 5), 1.0, rel_tol=1e-9)


def test_concentration_from_mapping_names_who_concentrates():
    res = concentration({"a": 4, "b": 3, "c": 2, "d": 1}, top_n=2)
    assert isinstance(res, ConcentrationResult)
    assert res.n == 4
    assert res.total == 10
    assert math.isclose(res.gini, 0.25, rel_tol=1e-9)
    assert math.isclose(res.top_share, 0.7, rel_tol=1e-9)
    # Shares descending, summing to 1, top label is the largest actor.
    assert res.shares[0]["label"] == "a"
    assert math.isclose(sum(s["share"] for s in res.shares), 1.0, rel_tol=1e-9)
    assert "method" in res.to_dict() and "caveat" in res.to_dict()


def test_concentration_drops_empty_buckets():
    # An actor that contributed nothing is not an actor in this measurement.
    res = concentration({"a": 5, "b": 0, "c": 0})
    assert res.n == 1
    assert res.gini is None  # a single real actor -> inequality undefined


def test_concentration_empty_is_honest():
    res = concentration({})
    assert res.n == 0 and res.total == 0
    assert res.gini is None and res.top_share is None and res.shares == []
