"""
Closed-form uncertainty intervals for card signals (evidence-tiered cards).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer-ruled (2026-06-10, the clinical-phases discussion): where the math is
actually defined — counts, proportions, rates — cards carry a real 95% interval,
computed in closed form (no scipy, so the core install has them too). Two honest
boundaries, stated wherever these numbers surface:

- The corpus is an observational, self-selected sample (the operator chose the
  sources). An interval describes uncertainty *within your corpus*, never the world.
- Heuristics (tone, near-duplicate clusters) get NO interval — dressing a
  heuristic in a CI would fake rigor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_Z95 = 1.959963984540054  # standard normal 97.5th percentile (two-sided 95%)


@dataclass(frozen=True)
class Interval:
    low: float
    high: float
    method: str

    def fmt(self, *, prefix: str = "", digits: int = 2) -> str:
        return f"{prefix}{round(self.low, digits)} – {prefix}{round(self.high, digits)}"


def wilson_interval(k: int, n: int) -> Interval | None:
    """Wilson score 95% interval for a proportion ``k/n`` (closed form).

    Preferred over the naive Wald interval because it behaves at small n and
    near 0/1 — exactly the young-corpus regime the cards must be honest in.
    Returns None when undefined (n == 0 or k out of range).
    """
    if n <= 0 or k < 0 or k > n:
        return None
    z2 = _Z95 * _Z95
    p = k / n
    denom = 1 + z2 / n
    centre = p + z2 / (2 * n)
    spread = _Z95 * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return Interval(
        low=max(0.0, (centre - spread) / denom),
        high=min(1.0, (centre + spread) / denom),
        method="Wilson score 95% CI",
    )


def rate_ratio_interval(
    recent: int, prior: int, *, window_days: float, baseline_days: float
) -> Interval | None:
    """Katz log-method 95% interval for the rate ratio (recent vs prior period).

    RR = (recent/window) / (prior/baseline); CI = exp(ln RR ± z·√(1/recent + 1/prior)).
    Returns None when undefined (either count is zero — a brand-new term has no
    prior rate to compare against; the card must SAY that instead of inventing one).
    """
    if recent <= 0 or prior <= 0 or window_days <= 0 or baseline_days <= 0:
        return None
    rr = (recent / window_days) / (prior / baseline_days)
    se = math.sqrt(1.0 / recent + 1.0 / prior)
    return Interval(
        low=rr * math.exp(-_Z95 * se),
        high=rr * math.exp(_Z95 * se),
        method="Katz log-method 95% CI on the rate ratio",
    )
