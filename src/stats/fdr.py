"""Benjamini-Hochberg false-discovery-rate control (the multiple-testing spine).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. Several analytics screen MANY hypotheses at once -- one keyword's daily
count against the lunar phase, every source-vs-topic pair, each day of a manipulation
scan. Screening m tests at a fixed alpha produces ~alpha*m false positives BY
CONSTRUCTION: at alpha=0.05, testing 100 unrelated series yields ~5 "significant" hits that
mean nothing. Reporting a bare significant p-value from such a screen is exactly the
fabricated finding the project forbids. The Benjamini-Hochberg (1995) procedure controls
the expected proportion of false discoveries among the rejections (the FDR) at a chosen
level q, so a screen can report "these survived multiple-testing correction" honestly.

This module is PURE and textbook -- no dependency, no I/O, no state -- and is the shared
correction any screening analytic runs before it surfaces a result. It computes a
DISCLOSURE (which hypotheses survive at level q, and the adjusted p-values), never a
composite score.

Definitions (Benjamini & Hochberg 1995, "Controlling the false discovery rate"):
  * Order the m p-values ascending: p(1) <= ... <= p(m).
  * The BH cutoff is the largest k with p(k) <= (k/m)*q; reject hypotheses 1..k.
  * The BH-adjusted p-value (q-value) of the i-th ordered test is
    min over j>=i of (m/j)*p(j), capped at 1 -- the step-up. A hypothesis is rejected at
    level q iff its adjusted p-value <= q, which is equivalent to the cutoff rule above.

Assumption: BH controls FDR at q under independence or positive dependence of the tests.
When tests can be arbitrarily (negatively) dependent, the conservative BH-Yekutieli
variant (``dependency="arbitrary"``) divides q by the harmonic number H(m); it always
holds but rejects fewer. Callers state which they use.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


class FdrError(ValueError):
    """Raised for an invalid p-value (outside [0, 1], NaN) or an invalid level q."""


@dataclass(frozen=True)
class FdrResult:
    """The outcome of a BH correction over a set of p-values.

    Fields:
      * ``q``          -- the FDR level the correction targeted.
      * ``m``          -- number of tests (hypotheses) corrected together.
      * ``rejected``   -- ORIGINAL indices (into the input list) of the surviving
                          hypotheses, ascending. The honest "these are real at FDR q".
      * ``n_rejected`` -- ``len(rejected)``.
      * ``threshold``  -- the largest raw p-value that was rejected (the BH cutoff), or
                          ``None`` when nothing survives -- so a caller can say "p had to be
                          <= X to survive". Never fabricated when empty.
      * ``adjusted``   -- the BH-adjusted p-values (q-values) in the INPUT order; a
                          hypothesis is rejected iff ``adjusted[i] <= q``.
      * ``dependency`` -- ``"independent"`` (standard BH) or ``"arbitrary"`` (BH-Yekutieli).
      * ``method``     -- one constant sentence naming the procedure.

    A disclosure, never a score: it says which findings survive multiple-testing control
    and by how much, and ranks nothing across incommensurable dimensions.
    """

    q: float
    m: int
    rejected: tuple[int, ...]
    n_rejected: int
    threshold: float | None
    adjusted: tuple[float, ...]
    dependency: str
    method: str


def _validated(pvalues) -> list[float]:
    out: list[float] = []
    for i, p in enumerate(pvalues):
        try:
            pv = float(p)
        except (TypeError, ValueError) as exc:
            raise FdrError(f"p-value at index {i} is not a number: {p!r}") from exc
        if math.isnan(pv) or math.isinf(pv):
            raise FdrError(f"p-value at index {i} is not finite: {pv}")
        if pv < 0.0 or pv > 1.0:
            raise FdrError(f"p-value at index {i} is outside [0, 1]: {pv}")
        out.append(pv)
    return out


def bh_adjusted(pvalues, *, dependency: str = "independent") -> list[float]:
    """The BH-adjusted p-values (q-values) in the INPUT order (the step-up, capped at 1).

    A hypothesis is significant at FDR level q iff its adjusted value is ``<= q``. Empty
    input returns ``[]``. ``dependency="arbitrary"`` applies the BH-Yekutieli correction
    factor (scales p by the harmonic number H(m)) for arbitrarily-dependent tests.
    """
    p = _validated(pvalues)
    m = len(p)
    if m == 0:
        return []
    if dependency not in ("independent", "arbitrary"):
        raise FdrError(f"dependency must be 'independent' or 'arbitrary', got {dependency!r}")
    factor = _harmonic(m) if dependency == "arbitrary" else 1.0

    order = sorted(range(m), key=lambda i: p[i])  # ascending, stable
    adj_sorted = [0.0] * m
    prev = 1.0
    # Step-up: walk the ordered p-values from largest to smallest, keep the running min.
    for pos in range(m - 1, -1, -1):
        rank = pos + 1  # 1-based rank of this ordered p-value
        val = p[order[pos]] * m * factor / rank
        prev = min(prev, val)
        adj_sorted[pos] = min(prev, 1.0)
    adjusted = [0.0] * m
    for pos, orig in enumerate(order):
        adjusted[orig] = adj_sorted[pos]
    return adjusted


def benjamini_hochberg(
    pvalues, q: float = 0.05, *, dependency: str = "independent"
) -> FdrResult:
    """Control the false-discovery rate at level ``q`` over ``pvalues`` (BH 1995).

    Returns an :class:`FdrResult` naming the surviving hypotheses (by original index), the
    BH cutoff, and the adjusted p-values. Pure; validates every p-value is a finite number
    in [0, 1] and ``0 < q <= 1`` (raises :class:`FdrError` otherwise). Empty input yields an
    empty, honest result (nothing rejected, no threshold). Counts + probabilities only,
    never a score.
    """
    if not (0.0 < float(q) <= 1.0):
        raise FdrError(f"q must be in (0, 1], got {q}")
    p = _validated(pvalues)
    m = len(p)
    method = (
        "Benjamini-Hochberg step-up FDR control at level q; a hypothesis survives iff its "
        "BH-adjusted p-value <= q (equivalently p(k) <= (k/m)*q at the largest such k)."
    )
    if dependency == "arbitrary":
        method += " BH-Yekutieli variant (q scaled by the harmonic number) for arbitrary dependence."
    if m == 0:
        return FdrResult(
            q=float(q), m=0, rejected=(), n_rejected=0, threshold=None,
            adjusted=(), dependency=dependency, method=method,
        )

    adjusted = bh_adjusted(p, dependency=dependency)
    rejected = tuple(sorted(i for i in range(m) if adjusted[i] <= q))
    threshold = max((p[i] for i in rejected), default=None)
    return FdrResult(
        q=float(q),
        m=m,
        rejected=rejected,
        n_rejected=len(rejected),
        threshold=threshold,
        adjusted=tuple(adjusted),
        dependency=dependency,
        method=method,
    )


def _harmonic(m: int) -> float:
    """H(m) = sum_{i=1..m} 1/i -- the BH-Yekutieli correction factor for arbitrary
    dependence (Benjamini & Yekutieli 2001)."""
    return sum(1.0 / i for i in range(1, m + 1))
