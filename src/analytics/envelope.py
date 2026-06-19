"""
The honesty envelope for maintained / derived aggregates.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A *maintained aggregate* (a denormalised counter, a derived columnar roll-up) is
fast precisely because it is NOT recomputed from the raw rows on every read. That
speed buys a small honesty debt: the value can briefly lag the canonical store
(an unreconciled cascade-delete, an in-flight reconcile, a cold derived cache).
The envelope pays that debt in the open — every maintained aggregate the app
serves carries ``{value, basis, as_of, method, n}`` so the reader always knows
*how fresh / how trustworthy* the number is (maintainer ruling 2026-06-19,
"performance must not depend on hiding data").

``basis`` is a **disclosure, not a score**
------------------------------------------
``basis`` says only whether the value was *verified exact* (``"exact"``) or is a
*maintained best-effort that may have drifted* (``"estimated"``). It ranks
nothing, blends nothing, and judges no source — so it does not trip the §6
no-composite-score ban: :func:`src.briefing.card.assert_no_score_fields` is run
on :class:`Envelope` at import time (and in the test) exactly as it is on the
Card, and ``basis`` is not a banned field name.

``as_of`` is **real, never fabricated**
---------------------------------------
The helper REQUIRES a real timestamp from the caller — the moment the value was
last proven correct (a reconcile time) or computed live (``now_iso()``). It is
never defaulted to "now" behind the caller's back; an empty ``as_of`` raises,
because an honesty envelope with an invented freshness time would be the very
dishonesty it exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.briefing.card import assert_no_score_fields

# The only two values ``basis`` may take. A disclosure of *verification state*,
# never a quality/trust grade (see module docstring + the import-time guard).
BASIS_EXACT = "exact"
BASIS_ESTIMATED = "estimated"
_BASES: frozenset[str] = frozenset({BASIS_EXACT, BASIS_ESTIMATED})


def now_iso() -> str:
    """A real UTC timestamp for a value computed *now* (e.g. a live query).

    The one sanctioned source of ``as_of`` for a freshly-computed aggregate;
    counter/derived reads pass their own reconcile watermark instead.
    """
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Envelope:
    """A maintained aggregate wrapped with its honesty disclosure.

    Fields:
      * ``value``  — the aggregate itself (a number, a list of rows, a dict).
      * ``basis``  — ``"exact"`` (verified against the canonical store) or
                     ``"estimated"`` (maintained best-effort, may have drifted).
                     A disclosure, not a score.
      * ``as_of``  — ISO-8601 instant the value was last *known* correct (a
                     reconcile time) or computed (``now_iso()``). Never invented.
      * ``method`` — one constant sentence: how the number is produced.
      * ``n``      — sample size behind the value, when defined.
    """

    value: Any
    basis: str
    as_of: str
    method: str
    n: int | None = None

    def __post_init__(self) -> None:
        if self.basis not in _BASES:
            raise ValueError(
                f"unknown basis {self.basis!r}; use {BASIS_EXACT!r} or {BASIS_ESTIMATED!r}"
            )
        # as_of must be a real timestamp the caller supplied — never fabricated.
        if not isinstance(self.as_of, str) or not self.as_of.strip():
            raise ValueError(
                "as_of is required and must be a real timestamp (a reconcile time "
                "or now_iso()), never fabricated or left empty"
            )
        if not isinstance(self.method, str) or not self.method.strip():
            raise ValueError("method is required (one constant sentence)")

    @classmethod
    def exact(cls, value: Any, *, as_of: str, method: str, n: int | None = None) -> Envelope:
        """Wrap a value that was VERIFIED against the canonical store at ``as_of``."""
        return cls(value=value, basis=BASIS_EXACT, as_of=as_of, method=method, n=n)

    @classmethod
    def estimated(cls, value: Any, *, as_of: str, method: str, n: int | None = None) -> Envelope:
        """Wrap a MAINTAINED value that may have drifted since ``as_of`` (honest)."""
        return cls(value=value, basis=BASIS_ESTIMATED, as_of=as_of, method=method, n=n)

    def is_exact(self) -> bool:
        return self.basis == BASIS_EXACT

    def to_dict(self) -> dict:
        """The serialization convention shared by every maintained aggregate."""
        return {
            "value": self.value,
            "basis": self.basis,
            "as_of": self.as_of,
            "method": self.method,
            "n": self.n,
        }


# Enforce the §6 no-composite-score ban on the envelope's own field names the
# moment this module is imported (not only under test) — `basis` is a disclosure
# and must stay one. A contributor who renamed a field to "...score" would fail here.
assert_no_score_fields(Envelope)
