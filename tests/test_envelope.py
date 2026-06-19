"""
Tests for the honesty envelope (Slice 1 of the data-architecture build).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

from src.analytics.envelope import (
    BASIS_ESTIMATED,
    BASIS_EXACT,
    Envelope,
    now_iso,
)
from src.briefing.card import CardSchemaError, assert_no_score_fields


def test_exact_and_estimated_constructors_and_dict():
    e = Envelope.exact(42, as_of="2026-06-19T00:00:00+00:00", method="counter", n=7)
    assert e.basis == BASIS_EXACT
    assert e.is_exact()
    assert e.to_dict() == {
        "value": 42,
        "basis": "exact",
        "as_of": "2026-06-19T00:00:00+00:00",
        "method": "counter",
        "n": 7,
    }

    est = Envelope.estimated(
        [{"term": "x"}], as_of="2026-06-19T00:00:00+00:00", method="live GROUP BY"
    )
    assert est.basis == BASIS_ESTIMATED
    assert not est.is_exact()
    assert est.to_dict()["n"] is None


def test_basis_is_validated():
    with pytest.raises(ValueError):
        Envelope(value=1, basis="great", as_of=now_iso(), method="m")


def test_as_of_is_required_never_fabricated():
    # An honesty envelope with an empty/invented freshness time is forbidden.
    for bad in ("", "   ", None):
        with pytest.raises(ValueError):
            Envelope(value=1, basis="exact", as_of=bad, method="m")  # type: ignore[arg-type]


def test_method_is_required():
    with pytest.raises(ValueError):
        Envelope(value=1, basis="exact", as_of=now_iso(), method="")


def test_now_iso_is_a_real_utc_timestamp():
    s = now_iso()
    # ISO-8601 with a UTC offset, parseable back to an aware datetime.
    from datetime import datetime

    dt = datetime.fromisoformat(s)
    assert dt.tzinfo is not None


def test_basis_is_a_disclosure_not_a_score():
    # The §6 no-composite-score guard must pass on the Envelope (basis is NOT a
    # banned field name) — the same guard that protects the Card.
    assert_no_score_fields(Envelope)  # does not raise


def test_a_score_shaped_field_would_be_rejected_by_the_same_guard():
    # Non-vacuous: prove the guard the envelope relies on actually bites.
    import dataclasses

    @dataclasses.dataclass
    class _Bad:
        trust_score: float = 0.0

    with pytest.raises(CardSchemaError):
        assert_no_score_fields(_Bad)
