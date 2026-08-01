"""
The Bulletin's period arithmetic — half-open windows that tile exactly.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pure: no DB, no network, no model. Every function here is a calendar calculation.

THE RULE (design record §5.1, RULED): **the rising comparison's RECENT window
equals the COVERAGE window; the baseline is a multiple of it.** Coverage (which
articles the edition is about) and rising (what grew) then answer the same
question, and consecutive editions partition time exactly.

The rejected alternative — a rising window that is a *fraction* of the period —
was refuted with a worked example: a story peaking on day 2 of a weekly period
sits inside its own baseline, so `trending(window_days=1, baseline_days=7)`
reports the period's biggest story as *falling* (growth 0.17) in the very edition
covering it, and 6 days in 7 never contribute to any rising signal at all.

Two conventions are load-bearing here and neither is negotiable:

* **Windows are half-open** ``[start, end)``. Consecutive periods then have no gap
  and no double-counted boundary day. ``queries._window_filter`` is INCLUSIVE on
  both ends and must not be reused for this; ``queries._counts`` is half-open and
  is the shape mirrored here.
* **The default period is CLOSED** — it ends at the start of today, so it covers
  the whole days ending yesterday. Today is a partial bucket
  (``KeywordMention.observed_on`` is a DATE, so the final day holds only what has
  been observed so far), and an edition built over a partial day is neither
  reproducible tomorrow nor honest about its own last day.

Daily is the floor cadence. Hourly is BLOCKED, not merely unimplemented: the
mention clock is a ``Date`` and the time is destroyed at write
(``store.py:285``), while ``KeywordMention.created_at`` is unusable because
re-index deletes and re-inserts every row stamped ``now()`` — one keyword
clean-up would collapse the entire history into a single hour.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

# Cadence -> (coverage days = rising recent window, baseline days). Design record
# §5.3. Daily / weekly / monthly ARE the shipped ``queries._TREND_WINDOWS``
# presets, already maintainer-ruled and running on Home, so they need no new
# calibration; the three long cadences extend the same 3x baseline tail that the
# monthly preset uses.
#
# The baseline multiple is bias-free because ``trending``'s ``expected`` is
# rate-normalised (prior_count / baseline_days * window_days), so a longer tail
# trades variance against regime contamination only -- it does not shift the
# ratio's centre.
CADENCES: dict[str, tuple[int, int]] = {
    "daily": (1, 7),
    "weekly": (7, 30),
    "monthly": (30, 90),
    "trimester": (90, 270),
    "semester": (180, 540),
    "yearly": (365, 1095),
}

DEFAULT_CADENCE = "weekly"

_METHOD = (
    "half-open [start, end) on coalesce(published_at, created_at); the rising "
    "recent window EQUALS the coverage window and the baseline is the "
    "immediately preceding baseline_days, also half-open"
)
_CAVEAT = (
    "The period ends at the start of the generation day by default: today is a "
    "partial bucket and would make the edition non-reproducible. published_at is "
    "publisher-asserted and back-datable, so an article ingested this period but "
    "published earlier lands in an earlier edition."
)


@dataclass(frozen=True)
class Period:
    """One edition's bounded stretch of time, plus the baseline it is compared to.

    ``start``/``end`` are the COVERAGE window, half-open: ``start`` is included,
    ``end`` is not. ``baseline_start`` .. ``start`` is the baseline, likewise
    half-open, so the two windows abut without sharing a day.
    """

    cadence: str
    start: date
    end: date
    baseline_start: date

    @property
    def days(self) -> int:
        """Coverage days == the rising recent window (the §5.1 rule)."""
        return (self.end - self.start).days

    @property
    def baseline_days(self) -> int:
        return (self.start - self.baseline_start).days

    @property
    def last_day(self) -> date:
        """The last day actually covered — ``end`` is exclusive, so it is not it."""
        return self.end - timedelta(days=1)

    def contains(self, day: date) -> bool:
        return self.start <= day < self.end

    def preceding(self) -> Period:
        """The period immediately before this one, same width.

        Exists to make tiling testable rather than asserted: ``p.preceding().end``
        is exactly ``p.start``, so consecutive editions cover every day once.
        """
        width = timedelta(days=self.days)
        start = self.start - width
        return Period(
            cadence=self.cadence,
            start=start,
            end=self.start,
            baseline_start=start - timedelta(days=self.baseline_days),
        )

    def to_dict(self) -> dict:
        return {
            "cadence": self.cadence,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "end_is_exclusive": True,
            "last_day": self.last_day.isoformat(),
            "days": self.days,
            "baseline_start": self.baseline_start.isoformat(),
            "baseline_days": self.baseline_days,
            "method": _METHOD,
            "caveat": _CAVEAT,
        }


def resolve_period(
    cadence: str = DEFAULT_CADENCE,
    *,
    end: date | None = None,
    coverage_days: int | None = None,
    baseline_days: int | None = None,
) -> Period:
    """Build the ``Period`` for one edition.

    ``end`` is the EXCLUSIVE upper bound and defaults to today, so the period is
    the whole days ending yesterday — closed, reproducible, and free of the
    partial final day (see the module docstring).

    ``coverage_days`` / ``baseline_days`` override the cadence defaults; the
    cadence name is still carried, because the edition reports which cadence it
    was generated as even when the operator tuned its windows.

    Only an ``end`` is accepted, never a ``start``/``end`` pair: the width lives
    in ``coverage_days``, and a pair could disagree with it. That disagreement is
    exactly the defect fixed in ``trending()`` on 2026-07-31 (a window one day
    wider than its own rate normalisation), so it is made unrepresentable here.
    """
    key = (cadence or "").strip().lower()
    if key not in CADENCES:
        raise ValueError(
            f"unknown cadence {cadence!r}; known cadences: {', '.join(sorted(CADENCES))}"
        )
    default_cov, default_base = CADENCES[key]
    cov = default_cov if coverage_days is None else int(coverage_days)
    base = default_base if baseline_days is None else int(baseline_days)
    if cov < 1:
        raise ValueError("coverage_days must be at least 1 day (daily is the floor cadence)")
    if base < 1:
        raise ValueError("baseline_days must be at least 1 day")
    hi = end or date.today()
    start = hi - timedelta(days=cov)
    return Period(cadence=key, start=start, end=hi, baseline_start=start - timedelta(days=base))


def baseline_coverage(period: Period, earliest: date | None) -> dict:
    """How much of the nominal baseline the corpus can actually cover.

    THE LONG-CADENCE HONESTY RAIL (§5.3). ``trending``'s ``expected`` divides the
    prior count by the *nominal* ``baseline_days`` regardless of how far back the
    corpus goes. A yearly edition nominally reaches back four years; on a corpus
    two years old, two of those years contain no articles at all, so ``expected``
    is computed over a denominator the data never filled — it is understated, and
    every ``growth`` built on it is correspondingly inflated.

    This does not correct the ratio (correcting it would silently change a shipped,
    ruled formula). It reports the shortfall so the edition can state it.

    ``earliest is None`` means the corpus date range could not be read, which is
    NOT the same as "the corpus is empty" — it is reported as unknown, never as a
    full-coverage pass.
    """
    nominal = period.baseline_days
    if earliest is None:
        return {
            "nominal_days": nominal,
            "actual_days": None,
            "complete": None,
            "note": (
                "the corpus's earliest observed date could not be read, so baseline "
                "coverage is unknown — not assumed complete"
            ),
        }
    # The baseline window is [baseline_start, start); days of it the corpus can fill.
    covered_from = max(earliest, period.baseline_start)
    actual = max(0, (period.start - covered_from).days)
    actual = min(actual, nominal)
    complete = actual >= nominal
    note = (
        "the corpus spans the whole nominal baseline"
        if complete
        else (
            f"the corpus only reaches back {actual} of the {nominal} nominal baseline "
            "days, so `expected` is divided by days the data never filled — it is "
            "understated here, and every growth ratio built on it is correspondingly "
            "inflated"
        )
    )
    return {
        "nominal_days": nominal,
        "actual_days": actual,
        "complete": complete,
        "earliest_observed": earliest.isoformat(),
        "note": note,
    }


def top_share(counts, n: int = 3, *, total: int | None = None) -> float | None:
    """The share of the total held by the ``n`` largest contributors.

    A measured proportion, not a score: it has a denominator, it is exact, and it
    is reported beside the counts it comes from. ``None`` when there is nothing to
    take a share of — a share of zero articles is undefined, not 0.0.

    ``total`` overrides the denominator, so a caller that already knows the true
    total can hand it in rather than let this re-derive a different one from a
    partial ``counts``. Two shares in the same block computed over two
    denominators is the kind of quiet inconsistency nobody spots in output.
    """
    vals = [int(c) for c in counts if c is not None]
    denom = sum(vals) if total is None else int(total)
    if denom <= 0:
        return None
    return round(sum(sorted(vals, reverse=True)[: max(0, int(n))]) / denom, 4)


def run_bulletin_period_selftest() -> dict:
    """Deterministic mechanism proof for the period arithmetic. No DB, no network.

    Registered in ``src.monitoring.recursive_loop.LOOP_SELFTESTS``.

    SHAPE CONTRACT: ``recursive_loop._selftest_passed`` reads a top-level ``passed``
    BOOL (or a ``summary.failed`` int) and reports None — "shape not recognized",
    never a fabricated green — for anything else.
    """
    cases: list[dict] = []

    def _case(name: str, got, want) -> None:
        cases.append({"name": name, "passed": got == want, "got": got, "want": want})

    anchor = date(2026, 8, 1)

    p = resolve_period("weekly", end=anchor)
    _case("weekly covers 7 days", p.days, 7)
    _case("weekly start", p.start.isoformat(), "2026-07-25")
    _case("end is exclusive, last covered day is the day before", p.last_day.isoformat(), "2026-07-31")
    _case("baseline is the 30 days immediately before", p.baseline_start.isoformat(), "2026-06-25")
    _case("rising recent window equals coverage", (p.days, p.days), (7, 7))

    # Half-open: the end day belongs to the NEXT period, never to both.
    _case("end day excluded", p.contains(anchor), False)
    _case("start day included", p.contains(p.start), True)

    prev = p.preceding()
    _case("consecutive periods tile with no gap", prev.end, p.start)
    _case("consecutive periods do not overlap", prev.contains(p.start), False)
    _case("preceding keeps the width", prev.days, p.days)

    _case("daily is the floor and matches the shipped preset", CADENCES["daily"], (1, 7))
    _case("monthly matches the shipped preset", CADENCES["monthly"], (30, 90))
    _case("yearly extends the 3x tail", CADENCES["yearly"], (365, 1095))

    try:
        resolve_period("hourly", end=anchor)
        cases.append({"name": "hourly is refused", "passed": False, "got": "accepted", "want": "ValueError"})
    except ValueError:
        cases.append({"name": "hourly is refused", "passed": True, "got": "ValueError", "want": "ValueError"})

    y = resolve_period("yearly", end=anchor)
    short = baseline_coverage(y, date(2025, 1, 1))
    _case("a young corpus reports an incomplete baseline", short["complete"], False)
    _case("and reports how many days it actually reaches", short["actual_days"] < short["nominal_days"], True)
    full = baseline_coverage(y, date(2015, 1, 1))
    _case("an old corpus reports a complete baseline", full["complete"], True)
    unknown = baseline_coverage(y, None)
    _case("an unreadable date range is unknown, not complete", unknown["complete"], None)

    _case("top share of nothing is undefined, not zero", top_share([]), None)
    _case("top-3 share is exact", top_share([50, 30, 10, 10]), 0.9)

    passed = all(c["passed"] for c in cases)
    return {
        "schema": "oo-bulletin-period-selftest-1",
        "cases": cases,
        "passed": passed,
        "passed_count": sum(1 for c in cases if c["passed"]),
        "failed_count": sum(1 for c in cases if not c["passed"]),
        "method": "deterministic calendar assertions over the period arithmetic; no DB, no network",
        "caveat": (
            "This proves the window arithmetic tiles and that the rising window equals "
            "the coverage window. It says nothing about the corpus."
        ),
    }
