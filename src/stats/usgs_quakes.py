"""
Offline parser for the USGS ComCat earthquake catalogue, as MONTHLY COUNTS (a statistics series).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The third keyless climate/geophysical row of the 0.6 plan (row A1 / S06-04 S2), built like
``gistemp.py``: PURE (an already-decoded ``str`` in, figures out, no ``requests`` / ``httpx`` /
``socket``, no clock), with the networked fetch behind the guarded factory in
``src.stats.fetch.fetch_usgs_quakes``.

THIS IS NOT THE HAZARDS FEED. ``src/hazards`` relays recent events live (a map of "what just
happened"). This module turns a stated window of the catalogue into a SERIES (events per month
at or above a stated magnitude), so it can sit in the same store, vintage and freshness path as
every other statistic. Nothing here forks or replaces the hazards fetch.

**The file FORMAT below is documented from the published FDSN ``query?format=csv`` shape and is
NOT verified against a live download.** The build sandbox has no route to ``earthquake.usgs.gov``
(CONNECT 403), so the parser refuses what it does not recognise and counts what it refused; the
operator's first real fetch is the check.

THE PUBLISHED SHAPE (columns are looked up BY NAME, so added columns do not break it)::

    time,latitude,longitude,depth,mag,magType,nst,gap,dmin,rms,net,id,updated,place,type,...,status,...
    2024-01-01T07:10:09.500Z,35.5,137.2,10,7.5,mww,,,,0.9,us,us6000m0xl,2024-02-01T00:00:00.000Z,"Noto, Japan",earthquake,...,reviewed,...

HONESTY PROPERTIES, each a refusal rather than a caveat:

* **A count is a count of CATALOGUE entries, not of earthquakes that happened.** Global
  completeness is documented by USGS at about magnitude 4.5; below that floor the catalogue
  is regional and a rising count can mean more seismometers. ``MIN_MAGNITUDE_FLOOR`` is
  therefore a refusal (``ValueError``), not a default someone may lower.
* **A trend in these counts is not a hazard forecast and not a "seismic risk score"**; nothing
  here rates, ranks or alerts. Magnitudes are the provider's own, and ``magType`` varies by
  event (Mw / mb / ...), which the methodology string states and no code reconciles.
* **Only ``type == earthquake`` is counted.** Explosions, quarry blasts and the like are
  EXCLUDED and the number excluded is reported (``excluded_non_earthquake``), never silently
  dropped and never folded into the count.
* **An incomplete month is a gap, never a smaller number.** The first and last month of a
  window must be whole; the month containing ``extracted_at`` (still in progress) is emitted
  with ``value=None`` and named in ``partial_periods``. A month with no qualifying event in a
  fully covered window is a true ``0`` (the catalogue is complete there), and its
  max-magnitude is ``None`` (there is no event to measure).
* **Revision is expected.** Automatic solutions are later reviewed, moved or deleted, so a
  re-fetch of the same window can differ; each fetch is a new vintage (``extracted_at`` is
  caller-stamped verbatim) and the share still ``automatic`` is reported in the summary.
* **A malformed row is refused and COUNTED** (not guessed, not skipped silently). A body with
  no recognisable header and no rows is ``looks_unrecognised`` (an HTML error page, a renamed
  product), never a successful empty series.
"""

from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass, field

from src.stats.sdmx import StatFigure

#: When the documented shape was last written down (NOT a live verification).
USGS_QUAKES_AS_OF = "2026-11"

#: A DISTINCT agency code: ``us-usgs`` is the Mineral Commodity Summaries feed and
#: ``minerals_supply_summary`` reads every figure of that agency.
AGENCY = "us-usgs-earthquakes"

#: The whole-catalogue series are worldwide; ``ref_area`` says so rather than leaving it blank.
REF_AREA = "WORLD"

#: Global completeness floor (USGS documents ~4.5 for the worldwide catalogue).
MIN_MAGNITUDE_FLOOR = 4.5

SERIES_COUNT_PREFIX = "usgs.quakes.count.m"  # + the threshold, e.g. "usgs.quakes.count.m5.0"
SERIES_MAX_MAG_PREFIX = "usgs.quakes.max_mag.m"

UNIT_COUNT = "events"
UNIT_MAG = "magnitude"

METHODOLOGY_REF = (
    "USGS Earthquake Hazards Program, ComCat catalogue via the FDSN event service: events of "
    "type 'earthquake' at or above the stated magnitude, counted per calendar month (UTC) by "
    "origin time. Counts are catalogue entries, not a measure of seismic hazard; magnitude "
    "types vary by event and later review can revise a count. "
    "https://earthquake.usgs.gov/fdsnws/event/1/"
)

_REQUIRED_COLUMNS = ("time", "mag", "type", "id")
_TIME = re.compile(r"^(\d{4})-(\d{2})-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
_DECIMAL = re.compile(r"^[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)$")
_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_MIN_YEAR, _MAX_YEAR = 1900, 2100
#: Stated plausibility bound: no earthquake has exceeded 10; a cell beyond is corrupt or hostile.
_MAX_MAGNITUDE = 10.0
#: Refusals kept verbatim (the count is always exact in ``refused_total``).
MAX_REFUSALS_KEPT = 100


def series_ids(min_magnitude: float) -> tuple[str, str]:
    """``(count_series_id, max_magnitude_series_id)`` for a threshold."""
    return (f"{SERIES_COUNT_PREFIX}{min_magnitude:.1f}", f"{SERIES_MAX_MAG_PREFIX}{min_magnitude:.1f}")


def month_index(period: str) -> int:
    """``"2024-03"`` -> a month number (year*12 + month-1); ValueError on anything else."""
    m = _MONTH.match(period)
    if not m:
        raise ValueError(f"not a YYYY-MM month: {period!r}")
    year = int(m.group(1))
    if not (_MIN_YEAR <= year <= _MAX_YEAR):
        raise ValueError(f"year out of range: {period!r}")
    return year * 12 + int(m.group(2)) - 1


def month_label(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


@dataclass
class QuakeParse:
    """Figures plus everything the parse refused or excluded; those are half the output."""

    figures: list[StatFigure] = field(default_factory=list)
    refused: list[dict[str, str]] = field(default_factory=list)
    refused_total: int = 0
    #: Rows that parsed as events (counted or excluded below).
    rows_read: int = 0
    #: Rows with ``type`` other than ``earthquake`` (explosions, quarry blasts...), EXCLUDED, stated.
    excluded_non_earthquake: int = 0
    #: Earthquake rows under the threshold or outside the window; excluded, stated.
    excluded_below_threshold: int = 0
    excluded_outside_window: int = 0
    #: Counted events whose ``status`` is not ``reviewed`` (may still be revised or deleted).
    unreviewed: int = 0
    #: Months emitted as gaps because they are not complete, each with the reason.
    partial_periods: dict[str, str] = field(default_factory=dict)
    window: tuple[str, str] = ("", "")  # first month, last month (inclusive)
    #: The service's own COUNT for the window, set by the fetch; ``None`` when parsed offline.
    declared_count: int | None = None
    min_magnitude: float = MIN_MAGNITUDE_FLOOR

    @property
    def counted(self) -> int:
        return self.rows_read - self.excluded_non_earthquake - self.excluded_below_threshold - self.excluded_outside_window

    @property
    def refused_is_sample(self) -> bool:
        return self.refused_total > len(self.refused)

    @property
    def looks_unrecognised(self) -> bool:
        """True when nothing parsed AND something was refused: not this file (HTML, 404...)."""
        return self.rows_read == 0 and self.refused_total > 0

    def summary(self) -> dict[str, object]:
        """The counts a caller must show beside the figures."""
        return {
            "window": list(self.window),
            "min_magnitude": self.min_magnitude,
            "rows_read": self.rows_read,
            "counted": self.counted,
            "declared_count": self.declared_count,
            "unreviewed": self.unreviewed,
            "excluded_non_earthquake": self.excluded_non_earthquake,
            "excluded_below_threshold": self.excluded_below_threshold,
            "excluded_outside_window": self.excluded_outside_window,
            "partial_periods": dict(self.partial_periods),
            "refused_total": self.refused_total,
            "refused_sample": list(self.refused),
            "refused_is_sample": self.refused_is_sample,
        }


def _refuse(out: QuakeParse, line: int, reason: str, text: str = "") -> None:
    out.refused_total += 1
    if len(out.refused) < MAX_REFUSALS_KEPT:
        out.refused.append({"line": str(line), "reason": reason, "text": text[:80]})


def _magnitude(raw: str) -> float | None:
    text = raw.strip()
    if not _DECIMAL.match(text):
        return None
    value = float(text)
    if not math.isfinite(value) or abs(value) > _MAX_MAGNITUDE:
        return None
    return value


def parse_usgs_quakes(
    text: str,
    *,
    start_month: str,
    end_month: str,
    min_magnitude: float,
    extracted_at: str,
) -> QuakeParse:
    """Parse one FDSN CSV body into monthly count and max-magnitude figures.

    ``start_month`` / ``end_month`` are ``YYYY-MM`` and BOTH INCLUSIVE: the window the request
    covered, in whole UTC months. ``extracted_at`` (ISO-8601, caller-stamped) names the vintage
    and decides which month is still in progress.
    """
    if min_magnitude < MIN_MAGNITUDE_FLOOR:
        raise ValueError(
            f"min_magnitude {min_magnitude} is under the {MIN_MAGNITUDE_FLOOR} global completeness floor: "
            "below it the catalogue is regional and a count measures instruments, not earthquakes"
        )
    if not (math.isfinite(min_magnitude) and min_magnitude <= _MAX_MAGNITUDE):
        raise ValueError(f"min_magnitude out of range: {min_magnitude!r}")
    first, last = month_index(start_month), month_index(end_month)
    if last < first:
        raise ValueError("end_month is before start_month")
    stamp = _TIME.match(extracted_at.strip()) or re.match(r"^(\d{4})-(\d{2})-\d{2}", extracted_at.strip())
    if not stamp:
        raise ValueError(f"extracted_at is not an ISO-8601 timestamp: {extracted_at!r}")
    now_month = int(stamp.group(1)) * 12 + int(stamp.group(2)) - 1

    out = QuakeParse(window=(start_month, end_month), min_magnitude=min_magnitude)
    counts = [0] * (last - first + 1)
    maxima: list[float | None] = [None] * (last - first + 1)
    seen_ids: set[str] = set()

    reader = csv.reader(io.StringIO(text))
    columns: dict[str, int] | None = None
    for lineno, row in enumerate(reader, start=1):
        if not row or all(not c.strip() for c in row):
            continue
        if columns is None:
            names = [c.strip() for c in row]
            if all(c in names for c in _REQUIRED_COLUMNS):
                columns = {n: i for i, n in enumerate(names)}
            else:
                _refuse(out, lineno, "not the catalogue header", ",".join(row))
                if out.refused_total >= 3:
                    break  # an HTML page is not worth reading to the end
            continue
        if len(row) <= max(columns[c] for c in _REQUIRED_COLUMNS):
            _refuse(out, lineno, "too few fields", ",".join(row))
            continue
        t = _TIME.match(row[columns["time"]].strip())
        if not t:
            _refuse(out, lineno, "time is not ISO-8601 UTC", row[columns["time"]])
            continue
        year = int(t.group(1))
        month = int(t.group(2))
        if not (_MIN_YEAR <= year <= _MAX_YEAR) or not (1 <= month <= 12):
            _refuse(out, lineno, "time out of range", row[columns["time"]])
            continue
        event_id = row[columns["id"]].strip()
        if not event_id:
            _refuse(out, lineno, "no event id", ",".join(row))
            continue
        if event_id in seen_ids:
            _refuse(out, lineno, "duplicate event id", event_id)
            continue
        mag_raw = row[columns["mag"]].strip()
        mag = _magnitude(mag_raw)
        kind = row[columns["type"]].strip().lower()
        if mag is None and not (mag_raw == "" and kind != "earthquake"):
            # A blank magnitude on a non-earthquake row is plausible; on an earthquake it is a gap in
            # the data we must not count as an event of unknown size.
            _refuse(out, lineno, "magnitude is not a finite number", mag_raw)
            continue
        seen_ids.add(event_id)
        out.rows_read += 1
        if kind != "earthquake":
            out.excluded_non_earthquake += 1
            continue
        assert mag is not None
        idx = year * 12 + month - 1 - first
        if idx < 0 or idx > last - first:
            out.excluded_outside_window += 1
            continue
        if mag < min_magnitude:
            out.excluded_below_threshold += 1
            continue
        counts[idx] += 1
        if maxima[idx] is None or mag > maxima[idx]:  # type: ignore[operator]
            maxima[idx] = mag
        if "status" in columns and columns["status"] < len(row) and row[columns["status"]].strip().lower() != "reviewed":
            out.unreviewed += 1

    if columns is None and out.refused_total == 0:
        _refuse(out, 0, "header row not found" if text.strip() else "empty body")
    count_id, max_id = series_ids(min_magnitude)
    for i, n in enumerate(counts):
        month_no = first + i
        label = month_label(month_no)
        partial = month_no >= now_month  # in progress at the vintage, or in the future
        if partial:
            out.partial_periods[label] = "month still in progress at the vintage" if month_no == now_month else "month after the vintage"
        if columns is None:
            continue  # nothing was read: emit no series at all rather than a column of zeros
        out.figures.append(_fig(count_id, label, None if partial else float(n), UNIT_COUNT, extracted_at))
        out.figures.append(_fig(max_id, label, None if partial else maxima[i], UNIT_MAG, extracted_at))
    return out


def _fig(series: str, period: str, value: float | None, unit: str, extracted_at: str) -> StatFigure:
    return StatFigure(
        agency=AGENCY,
        series_id=series,
        ref_area=REF_AREA,
        time_period=period,
        value=value,
        unit=unit,
        methodology_ref=METHODOLOGY_REF,
        adjustment=None,
        base_year=None,
        extracted_at=extracted_at,
    )
