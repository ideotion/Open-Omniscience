"""Lunar-effects correlation framework — the honest "name the shape" instrument.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer concept (2026-06-12): let users TEST moon-effect beliefs against their OWN data
instead of asserting them. This correlates ANY stored daily series (a keyword's daily
mention count, a per-day figure) against the moon's illuminated fraction from the verified
local Meeus engine (:mod:`src.events.astronomy`) — and it does so HONESTLY:

  * NEVER a bare significant result. Screening many series against the moon WILL turn up
    spurious "hits" by chance, so a SCREEN corrects the whole family with Benjamini-Hochberg
    FDR (:mod:`src.stats.fdr`); a single correlation is reported with its p-value and the
    explicit note that one test is not a screen.
  * The p-value is a DETERMINISTIC CIRCULAR-SHIFT permutation test — no scipy, no RNG, and
    (unlike a naive shuffle or a normal-theory t-test) it PRESERVES the autocorrelation of
    BOTH series and asks only whether the OBSERVED phase alignment is special versus every
    rigid shift of the same lunar cycle. This is the standard, assumption-light test for a
    cyclic association and is honest for non-normal count data.
  * correlation != causation, stated on every result; a survivor is a SHAPE to investigate,
    never proof of a lunar effect.

There is no fabricated finding here: the null result ("nothing survived correction") is the
common, honest, and expected outcome.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class LunarCorrelation:
    """One series correlated against the moon's illuminated fraction.

    Fields (counts + statistics only, never a score):
      * ``term``            -- the series label (a keyword, or a caller-supplied name).
      * ``r``               -- Pearson correlation with the daily illuminated fraction.
      * ``n``               -- number of days in the (dense, contiguous) series.
      * ``p_value``         -- deterministic circular-shift permutation p-value (two-sided).
      * ``q_value``         -- BH-adjusted p-value across the screen (None for a single test).
      * ``survives``        -- did it survive the FDR correction at the screen's level?
      * ``active_days``     -- days with a non-zero value (the real signal density).
      * ``window``          -- (start_iso, end_iso) of the series.
    """

    term: str
    r: float
    n: int
    p_value: float
    q_value: float | None
    survives: bool | None
    active_days: int
    window: tuple[str, str]

    def to_dict(self) -> dict:
        return {
            "term": self.term,
            "r": round(self.r, 4),
            "n": self.n,
            "p_value": round(self.p_value, 5),
            "q_value": round(self.q_value, 5) if self.q_value is not None else None,
            "survives": self.survives,
            "active_days": self.active_days,
            "window": {"start": self.window[0], "end": self.window[1]},
        }


CORRELATION_CAVEAT = (
    "Correlation is NOT causation. This asks only whether a daily series lines up with the "
    "moon's illuminated fraction more than every rigid shift of the same lunar cycle would — "
    "a shape, never proof of a lunar effect. Screening many series WILL produce chance hits, "
    "so a screen is corrected for multiple testing (Benjamini-Hochberg FDR); a survivor is a "
    "prompt to investigate the confound (a real ~monthly driver — pay cycles, reporting "
    "cadence, weather seasons — can align with the lunar month), never a finding. The most "
    "common and honest outcome is that nothing survives."
)

LUNAR_METHOD = (
    "Pearson correlation of a dense daily series (missing days = 0) against the moon's "
    "illuminated fraction (Meeus ch.49 new moons; the synodic-age fraction). The p-value is "
    "a deterministic CIRCULAR-SHIFT permutation test: the fraction of the n rigid shifts of "
    "the lunar series whose |r| is at least the observed |r| — which preserves both series' "
    "autocorrelation and tests only the observed phase alignment. A screen corrects the "
    "family with Benjamini-Hochberg FDR. Statistics + counts only, no score."
)


def _pearson_centered(xc: list[float], lc: list[float], sx: float, sl: float) -> float:
    num = sum(a * b for a, b in zip(xc, lc, strict=True))
    return num / (sx * sl)


def circular_shift_test(x: list[float], moon: list[float]) -> tuple[float, float] | None:
    """(r, p) for a dense daily series ``x`` vs the aligned illuminated fraction ``moon``.

    ``r`` is Pearson; ``p`` is the fraction of the n circular shifts of ``moon`` whose |r|
    is >= the observed |r| (a two-sided, deterministic permutation p-value). Returns None if
    either series is constant (a correlation is undefined — no fabricated value). O(n^2),
    bounded by the caller's window.
    """
    n = len(x)
    if n < 3 or len(moon) != n:
        return None
    xbar = sum(x) / n
    lbar = sum(moon) / n
    xc = [v - xbar for v in x]
    lc = [v - lbar for v in moon]
    sx = math.sqrt(sum(v * v for v in xc))
    sl = math.sqrt(sum(v * v for v in lc))
    if sx <= 0.0 or sl <= 0.0:
        return None  # a constant series -> correlation undefined, never invented
    denom = sx * sl
    r_obs = sum(a * b for a, b in zip(xc, lc, strict=True)) / denom
    target = abs(r_obs) - 1e-12
    at_least = 0
    for s in range(n):
        num = sum(xc[i] * lc[(i - s) % n] for i in range(n))
        if abs(num / denom) >= target:
            at_least += 1
    return r_obs, at_least / n


def moon_fraction_by_day(start: date, end: date) -> dict[str, float]:
    """The moon's illuminated fraction per calendar day in ``[start, end]`` (inclusive),
    from the verified local astronomy engine. Keyed by ISO date string."""
    from src.events.astronomy import lunar_phase_series

    series = lunar_phase_series(start.isoformat(), end.isoformat())
    return {d["date"]: float(d["illuminated_fraction"]) for d in series["days"]}


def _dense_daily(points: dict[str, float], start: date, end: date) -> list[float]:
    """A contiguous daily series over ``[start, end]`` (missing day = 0.0)."""
    out: list[float] = []
    cur = start
    while cur <= end:
        out.append(float(points.get(cur.isoformat(), 0.0)))
        cur += timedelta(days=1)
    return out


def correlate_daily_series(
    name: str, daily: dict[str, float], *, min_active_days: int = 8, min_span_days: int = 45
) -> LunarCorrelation | None:
    """Correlate ANY daily series against the moon (a single, uncorrected test).

    ``daily`` maps ISO date -> value. The series is densified over its active span (missing
    days = 0) and correlated with the illuminated fraction. Returns None (honest skip, never
    a fabricated correlation) when there are too few active days, the span is too short, or a
    series is constant. ``q_value``/``survives`` are None (a single test is not a screen).
    """
    active = sorted(d for d, v in daily.items() if float(v) != 0.0)
    if len(active) < min_active_days:
        return None
    start = date.fromisoformat(active[0])
    end = date.fromisoformat(active[-1])
    n = (end - start).days + 1
    if n < min_span_days:
        return None
    x = _dense_daily(daily, start, end)
    moon_map = moon_fraction_by_day(start, end)
    moon = [moon_map.get((start + timedelta(days=i)).isoformat(), 0.0) for i in range(n)]
    res = circular_shift_test(x, moon)
    if res is None:
        return None
    r, p = res
    return LunarCorrelation(
        term=name, r=r, n=n, p_value=p, q_value=None, survives=None,
        active_days=len(active), window=(start.isoformat(), end.isoformat()),
    )


def _keyword_daily(session, term: str) -> dict[str, float]:
    """A keyword's daily mention-count series {iso date -> count} from the trend query."""
    from src.analytics.queries import trend

    t = trend(session, term, bucket="day")
    return {p["date"]: float(p["count"]) for p in t.get("points", [])}


def correlate_keyword(
    session, term: str, *, min_active_days: int = 8, min_span_days: int = 45
) -> LunarCorrelation | None:
    """Correlate ONE keyword's daily mention series against the moon (a single, uncorrected
    test). The public single-term entry point; returns None on an untestable series."""
    return correlate_daily_series(
        term, _keyword_daily(session, term),
        min_active_days=min_active_days, min_span_days=min_span_days,
    )


def lunar_screen(
    session,
    *,
    terms: list[str] | None = None,
    limit: int = 40,
    fdr_q: float = 0.05,
    min_active_days: int = 8,
    min_span_days: int = 45,
) -> dict:
    """Screen many keyword daily series against the moon, corrected for multiple testing.

    Without ``terms`` it screens the top ``limit`` most-mentioned keywords. Each series is
    correlated (a single circular-shift test); the whole family of p-values is then corrected
    with Benjamini-Hochberg FDR at ``fdr_q``, and each result carries its BH-adjusted q-value
    and whether it survives. NEVER a bare significant result — the correction is the point.
    Returns a self-describing payload; the honest common outcome is zero survivors.
    """
    from src.stats.fdr import benjamini_hochberg

    if terms is None:
        from src.analytics.queries import top_terms

        top = top_terms(session, limit=max(1, int(limit)))
        terms = [row.get("term") or row.get("normalized") for row in top.get("terms", [])]
        terms = [t for t in terms if t]

    tested: list[LunarCorrelation] = []
    skipped = 0
    for term in terms:
        daily = _keyword_daily(session, term)
        corr = correlate_daily_series(
            term, daily, min_active_days=min_active_days, min_span_days=min_span_days
        )
        if corr is None:
            skipped += 1
            continue
        tested.append(corr)

    results: list[dict] = []
    survivors = 0
    if tested:
        fdr = benjamini_hochberg([c.p_value for c in tested], q=fdr_q)
        rejected = set(fdr.rejected)
        for i, c in enumerate(tested):
            survives = i in rejected
            survivors += 1 if survives else 0
            results.append(
                LunarCorrelation(
                    term=c.term, r=c.r, n=c.n, p_value=c.p_value, q_value=fdr.adjusted[i],
                    survives=survives, active_days=c.active_days, window=c.window,
                ).to_dict()
            )
        results.sort(key=lambda d: d["p_value"])

    return {
        "results": results,
        "tested": len(tested),
        "skipped": skipped,
        "survivors": survivors,
        "fdr_q": fdr_q,
        "variable": "illuminated_fraction",
        "method": LUNAR_METHOD,
        "caveat": CORRELATION_CAVEAT,
        "note": (
            "No series survived the multiple-testing correction — the honest, expected result."
            if tested and survivors == 0
            else ("Screened the keyword series you asked for." if tested
                  else "No series had enough active days to test.")
        ),
    }
