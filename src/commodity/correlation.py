"""
Honest correlation between commodity price movement and news volume.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

This replaces the fabricated statistics found in the audit (e.g. ``p_value =
1.0 - correlation_score``). Here the coefficient and p-value come from a REAL
test (scipy.stats pearson/spearman) computed over the dates where both a daily
price change and an article count exist. The result always carries:

  * the method used,
  * the actual sample size n,
  * the real two-sided p-value,
  * an explicit "correlation is not causation" caveat,

and when there are too few overlapping points to test, it says so rather than
inventing a number.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from scipy import stats

# Minimum overlapping (price-change, news-count) pairs to attempt a test.
_MIN_N = 4

_CAVEAT = (
    "Correlation does not imply causation. A relationship here only indicates that "
    "price changes and article volume moved together on the overlapping dates; it "
    "does not establish that one caused the other."
)


@dataclass
class CorrelationResult:
    method: str
    n: int
    coefficient: float | None = None
    p_value: float | None = None
    significant: bool | None = None  # p < alpha, only when computed
    alpha: float = 0.05
    insufficient_data: bool = False
    caveat: str = _CAVEAT
    overlapping_dates: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "n": self.n,
            "coefficient": self.coefficient,
            "p_value": self.p_value,
            "significant": self.significant,
            "alpha": self.alpha,
            "insufficient_data": self.insufficient_data,
            "caveat": self.caveat,
            "overlapping_dates": self.overlapping_dates,
        }


def _daily_price_changes(points: list[tuple[date, float]]) -> dict[date, float]:
    """Signed day-over-day price change keyed by the later date."""
    ordered = sorted(points, key=lambda p: p[0])
    changes: dict[date, float] = {}
    for (_d0, p0), (d1, p1) in zip(ordered, ordered[1:], strict=False):
        changes[d1] = p1 - p0
    return changes


def correlate_price_with_news(
    price_points: list[tuple[date, float]],
    article_dates: list[date],
    *,
    method: str = "pearson",
    alpha: float = 0.05,
) -> CorrelationResult:
    """Correlate daily price *change* with daily article count over shared dates.

    ``price_points`` is [(date, price), ...]; ``article_dates`` is the publish date
    of each relevant article (duplicates = higher volume that day).

    Thin list-input wrapper: it groups ``article_dates`` into per-day counts and delegates
    to :func:`correlate_price_with_counts`. A caller that can GROUP BY in SQL should build
    the ``{date: count}`` map directly and call that entry point instead of materialising
    one row per article.
    """
    return correlate_price_with_counts(
        price_points, Counter(article_dates), method=method, alpha=alpha
    )


def correlate_price_with_counts(
    price_points: list[tuple[date, float]],
    article_counts: Mapping[date, int],
    *,
    method: str = "pearson",
    alpha: float = 0.05,
) -> CorrelationResult:
    """Correlate daily price *change* with a per-day article COUNT map over shared dates.

    Byte-identical to :func:`correlate_price_with_news` (which is ``… (Counter(list))``) but
    takes the counts already grouped by day (``{date: count}``), so the caller can aggregate
    in SQL (``GROUP BY day``) instead of pulling one row per article through the codec.
    """
    if method not in ("pearson", "spearman"):
        raise ValueError("method must be 'pearson' or 'spearman'")

    changes = _daily_price_changes(price_points)
    counts = article_counts

    shared = sorted(set(changes) & set(counts))
    n = len(shared)
    if n < _MIN_N:
        return CorrelationResult(
            method=method,
            n=n,
            insufficient_data=True,
            alpha=alpha,
            overlapping_dates=[d.isoformat() for d in shared],
        )

    xs = [changes[d] for d in shared]
    ys = [float(counts[d]) for d in shared]

    # Constant input -> correlation undefined; report as insufficient rather than NaN.
    if len(set(xs)) < 2 or len(set(ys)) < 2:
        return CorrelationResult(
            method=method,
            n=n,
            insufficient_data=True,
            alpha=alpha,
            overlapping_dates=[d.isoformat() for d in shared],
        )

    if method == "pearson":
        coef, p = stats.pearsonr(xs, ys)
    else:
        coef, p = stats.spearmanr(xs, ys)

    return CorrelationResult(
        method=method,
        n=n,
        coefficient=float(coef),
        p_value=float(p),
        significant=bool(p < alpha),
        alpha=alpha,
        overlapping_dates=[d.isoformat() for d in shared],
    )
