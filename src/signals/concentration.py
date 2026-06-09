"""
Concentration / inequality of a distribution — the Gini coefficient and top-N share.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A *pure* primitive (no DB, no network) that answers one measurable question: **how
unevenly is a quantity spread across a set of actors?** It is the same maths whether
the actors are media owners (FUTURE_DEVELOPMENTS §1 — "7 billionaires control ~90%"),
named people (§4 prominence-concentration), or sources contributing to one story.

It is a *descriptive measurement*, never a verdict: concentration is not by itself
good or bad, and the tool stops at the number + its method + its caveat. The human
judges what it means.

Definitions
-----------
* **Gini coefficient** — 0 = perfectly equal (every actor has the same amount),
  approaching 1 = one actor has everything. Computed by the standard sorted form
  ``G = (2 * Σ i·xᵢ) / (n · Σ xᵢ) − (n + 1) / n`` over values sorted ascending.
* **top-N share** — the fraction of the total held by the ``top_n`` largest actors
  (e.g. "the top 3 owners account for 0.82 of the coverage").

Both are exact, deterministic, and carry their own sample size; neither invents a
value when the input is too small or degenerate (all-equal / empty) — they say so.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_CAVEAT = (
    "Concentration is a descriptive measure of how unevenly a quantity is spread, "
    "not a judgement: a high value is not inherently good or bad. It reflects only "
    "the actors present in this sample — a skewed or incomplete sample skews the "
    "result. Read the breakdown and attribute for yourself."
)


@dataclass
class ConcentrationResult:
    """The concentration of one distribution, with method + caveat + n.

    ``shares`` is the per-label fraction of the total (descending), present only
    when labels were supplied — so a card can show *who* concentrates, not just a
    bare coefficient.
    """

    method: str
    n: int  # number of actors (non-empty buckets counted)
    total: float  # sum of all values
    gini: float | None = None  # None when undefined (n < 2 or total == 0)
    top_n: int = 0
    top_share: float | None = None  # fraction held by the top_n actors
    shares: list[dict] = field(default_factory=list)  # [{label, value, share}], descending
    caveat: str = _CAVEAT

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "n": self.n,
            "total": self.total,
            "gini": self.gini,
            "top_n": self.top_n,
            "top_share": self.top_share,
            "shares": self.shares,
            "caveat": self.caveat,
        }


def gini(values: list[float]) -> float | None:
    """Gini coefficient of ``values`` (each ≥ 0). ``None`` when undefined.

    Undefined (returns ``None``) for fewer than two values or a zero total, because
    inequality has no meaning there — we never fabricate a 0/NaN to fill the gap.
    """
    xs = sorted(float(v) for v in values if v is not None)
    n = len(xs)
    if n < 2:
        return None
    if any(x < 0 for x in xs):
        raise ValueError("gini is undefined for negative values")
    total = sum(xs)
    if total == 0:
        return None
    # Sorted form: G = (2 * Σ i·xᵢ) / (n · Σ xᵢ) − (n + 1) / n, i = 1..n ascending.
    weighted = sum(i * x for i, x in enumerate(xs, start=1))
    g = (2.0 * weighted) / (n * total) - (n + 1.0) / n
    # Clamp tiny floating-point excursions outside [0, 1].
    return max(0.0, min(1.0, g))


def top_share(values: list[float], top_n: int) -> float | None:
    """Fraction of the total held by the ``top_n`` largest values. ``None`` if empty."""
    xs = sorted((float(v) for v in values if v is not None), reverse=True)
    total = sum(xs)
    if not xs or total == 0:
        return None
    k = max(1, min(top_n, len(xs)))
    return sum(xs[:k]) / total


def concentration(
    counts: dict[str, float] | list[float],
    *,
    top_n: int = 3,
    method: str = "Gini coefficient + top-N share over actor totals",
) -> ConcentrationResult:
    """Measure how concentrated a distribution is.

    ``counts`` may be a ``{label: value}`` mapping (preferred — the breakdown then
    names *who* concentrates) or a bare list of values. Buckets with a value of 0
    (or ``None``) are dropped: an actor that contributed nothing is not an actor in
    this measurement.
    """
    if isinstance(counts, dict):
        items = [(str(k), float(v)) for k, v in counts.items() if v]
    else:
        items = [(None, float(v)) for v in counts if v]

    values = [v for _, v in items]
    n = len(values)
    total = sum(values)

    shares: list[dict] = []
    if total > 0 and any(label is not None for label, _ in items):
        for label, value in sorted(items, key=lambda kv: kv[1], reverse=True):
            shares.append({"label": label, "value": value, "share": value / total})

    return ConcentrationResult(
        method=method,
        n=n,
        total=total,
        gini=gini(values),
        top_n=max(1, min(top_n, n)) if n else 0,
        top_share=top_share(values, top_n),
        shares=shares,
    )
