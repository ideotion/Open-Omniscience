"""
StatFigure → honest chart-series adapter (Group N, the official-statistics viz foundation).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Turns a list of provenance-rich :class:`~src.stats.sdmx.StatFigure` observations into a
time-ordered series a chart can render WITHOUT lying. It is PURE — it only reads the figures
it is given (no ORM, no network, no current-time dependence) — and it bakes the Group N
honesty rules into the SHAPE of its output, not just prose:

  * COMPARABILITY SEGMENTATION (the headline rule): a new line segment starts wherever the
    ``unit``, index ``base_year``, or seasonal ``adjustment`` changes. Values across a break
    are NOT comparable, so a chart draws each segment as its own line and never joins across
    the break (e.g. an "Index, 2010=100" run is never connected to a "2015=100" run, and a
    seasonally-adjusted run is never connected to a raw one);
  * A GAP IS A GAP: a ``value=None`` (a published gap) is kept in place inside its segment so
    the chart breaks the line there — never interpolated, never dropped, never zeroed;
  * NEVER POSITION WHAT WE CANNOT PLACE: a period label the adapter cannot parse onto the
    time axis is surfaced in ``unparseable_periods`` rather than placed at a guessed x;
  * VINTAGE-SAFE: when the same (period, comparability) appears more than once — different
    vintages of the same cell — the latest ``extracted_at`` wins (ISO-8601 UTC sorts
    chronologically) and the collapse count is reported; differing-comparability values at
    the same period are kept (they land in distinct, honestly-unjoined segments);
  * NO score, NO ranking, NO interpolation — only the observed values and their positions.

This is the Phase B1 adapter the chart layer (ooViz / ooChart gap subpaths + comparability
markers) consumes; it is deliberately independent of any renderer and of the store.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from src.stats.sdmx import StatFigure

# --------------------------------------------------------------------------- #
# Period parsing — a published period label → a decimal-year position + granularity.
# Order matters: the most specific / marker-bearing forms are matched before the bare ones.
# --------------------------------------------------------------------------- #
_ANNUAL = re.compile(r"^(\d{4})$")
_DAY = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_QUARTER = re.compile(r"^(\d{4})[-]?Q([1-4])$", re.IGNORECASE)
_SEMESTER = re.compile(r"^(\d{4})[-]?[SH]([12])$", re.IGNORECASE)
_WEEK = re.compile(r"^(\d{4})[-]?W(\d{1,2})$", re.IGNORECASE)
_MONTH = re.compile(r"^(\d{4})[-]?M?(\d{1,2})$")


def _parse_period(label: str) -> tuple[float | None, str]:
    """A period label → (decimal-year position, granularity).

    Each period is placed at its START (e.g. 2021-Q3 → 2021.5, 2021-03 → 2021 + 2/12), so a
    chart positions points consistently. An unrecognised / impossible label → ``(None,
    "unknown")`` — it is surfaced, never guessed onto the axis.
    """
    s = (label or "").strip()
    m = _ANNUAL.match(s)
    if m:
        return float(m.group(1)), "annual"
    m = _DAY.match(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            here = date(y, mo, d)
        except ValueError:
            return None, "unknown"
        jan1 = date(y, 1, 1)
        days_in_year = (date(y + 1, 1, 1) - jan1).days
        return y + (here - jan1).days / days_in_year, "day"
    m = _QUARTER.match(s)
    if m:
        return int(m.group(1)) + (int(m.group(2)) - 1) / 4.0, "quarter"
    m = _SEMESTER.match(s)
    if m:
        return int(m.group(1)) + (int(m.group(2)) - 1) / 2.0, "semester"
    m = _WEEK.match(s)
    if m:
        week = int(m.group(2))
        if 1 <= week <= 53:
            return int(m.group(1)) + (week - 1) / 52.0, "week"
        return None, "unknown"
    m = _MONTH.match(s)
    if m:
        mo = int(m.group(2))
        if 1 <= mo <= 12:
            return int(m.group(1)) + (mo - 1) / 12.0, "month"
    return None, "unknown"


# --------------------------------------------------------------------------- #
# The series shape.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SeriesPoint:
    """One placed observation: its published period, its decimal-year x, and the value
    (``None`` for a published gap — the chart breaks the line here)."""

    period: str
    t: float
    value: float | None

    def to_dict(self) -> dict:
        return {"period": self.period, "t": round(self.t, 6), "value": self.value}


@dataclass(frozen=True)
class SeriesSegment:
    """A comparability-homogeneous, time-ordered run of points. Every point in a segment
    shares the same unit / base year / seasonal adjustment, so the chart may join them; the
    boundary between two segments is a comparability break that must NOT be joined."""

    unit: str | None
    base_year: str | None
    adjustment: str | None
    points: tuple[SeriesPoint, ...]

    def to_dict(self) -> dict:
        return {
            "unit": self.unit,
            "base_year": self.base_year,
            "adjustment": self.adjustment,
            "points": [p.to_dict() for p in self.points],
        }


_COMPARABILITY_CAVEAT = (
    "A new line segment starts wherever the unit, index base year, or seasonal adjustment "
    "changes — values across a break are not comparable and are never joined. A missing "
    "value is shown as a gap in the line, never interpolated. Periods that could not be "
    "placed on the time axis are listed separately, never positioned arbitrarily."
)


def to_chart_series(
    figures: list[StatFigure], *, ref_area: str | None = None, series_id: str | None = None
) -> dict:
    """Adapt figures into an honest, time-ordered, comparability-segmented chart series.

    Optionally filtered to one ``ref_area`` and/or ``series_id`` (a figure list often holds
    several). Returns a plain dict (JSON-ready for the renderer):

        {"ref_area", "series_id",
         "segments": [{unit, base_year, adjustment, points: [{period, t, value}]}],
         "granularity": "annual"|"quarter"|…|"mixed"|"none",
         "n_points", "n_segments",
         "unparseable_periods": [labels we could not place],
         "duplicates_collapsed": <vintage collapses>,
         "caveat"}
    """
    selected = [
        f
        for f in figures
        if (ref_area is None or f.ref_area == ref_area)
        and (series_id is None or f.series_id == series_id)
    ]

    # Parse periods; what we cannot place is surfaced, never positioned at a guessed x.
    placeable: list[tuple[float, str, StatFigure]] = []
    unparseable: list[str] = []
    for f in selected:
        t, gran = _parse_period(f.time_period)
        if t is None:
            unparseable.append(f.time_period)
        else:
            placeable.append((t, gran, f))

    # Vintage dedup: same (period, comparability) → keep the latest extracted_at.
    best: dict[tuple[str, str | None, str | None, str | None], tuple[float, str, StatFigure]] = {}
    for t, gran, f in placeable:
        key = (f.time_period, f.unit, f.base_year, f.adjustment)
        current = best.get(key)
        if current is None or f.extracted_at > current[2].extracted_at:
            best[key] = (t, gran, f)
    duplicates_collapsed = len(placeable) - len(best)

    rows = sorted(best.values(), key=lambda r: (r[0], r[2].time_period))

    # Segment by comparability on consecutive points — a break is never joined.
    raw_segments: list[dict] = []
    prev_key: tuple[str | None, str | None, str | None] | None = None
    grans: set[str] = set()
    for t, gran, f in rows:
        grans.add(gran)
        ckey = (f.unit, f.base_year, f.adjustment)
        if not raw_segments or ckey != prev_key:
            raw_segments.append({"meta": ckey, "points": []})
            prev_key = ckey
        raw_segments[-1]["points"].append(SeriesPoint(f.time_period, t, f.value))

    segments = [
        SeriesSegment(s["meta"][0], s["meta"][1], s["meta"][2], tuple(s["points"]))
        for s in raw_segments
    ]

    if not grans:
        granularity = "none"
    elif len(grans) == 1:
        granularity = next(iter(grans))
    else:
        granularity = "mixed"

    return {
        "ref_area": ref_area,
        "series_id": series_id,
        "segments": [s.to_dict() for s in segments],
        "granularity": granularity,
        "n_points": sum(len(s.points) for s in segments),
        "n_segments": len(segments),
        "unparseable_periods": unparseable,
        "duplicates_collapsed": duplicates_collapsed,
        "caveat": _COMPARABILITY_CAVEAT,
    }
