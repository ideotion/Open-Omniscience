"""
Offline parser for the NASA GISS GISTEMP v4 global / hemispheric temperature-anomaly CSV.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The second keyless climate row of the 0.6 plan (row A1 / S06-04 S2), built exactly like
``oni.py``: PURE (an already-decoded ``str`` in, figures out, no ``requests`` / ``httpx`` /
``socket``, no clock), with the networked fetch behind the guarded factory in
``src.stats.fetch.fetch_gistemp``.

**The file FORMAT below is documented from the published shape and is NOT verified against a
live download.** This sandbox has no route to ``data.giss.nasa.gov``; the parser therefore
refuses anything it does not recognise and reports what it refused, so a format drift is a
loud gap rather than a plausible number. The operator's first real fetch is the check.

THE PUBLISHED SHAPE (``GLB.Ts+dSST.csv``; ``NH`` and ``SH`` are the same shape)::

    Land-Ocean: Global Means
    Year,Jan,Feb,Mar,Apr,May,Jun,Jul,Aug,Sep,Oct,Nov,Dec,J-D,D-N,DJF,MAM,JJA,SON
    1880,-.18,-.24,-.09,-.17,-.10,-.22,-.20,-.09,-.16,-.22,-.20,-.17,-.17,***,***,-.14,-.17,-.19

Values are temperature ANOMALIES in °C against GISS's own 1951-1980 base period, and ``***``
is the "not available" marker.

HONESTY PROPERTIES, each a refusal rather than a caveat:

* **Anomalies only, against the STATED baseline.** ``base_year`` is ``"1951-1980"`` on every
  figure and the unit is ``degC`` (an anomaly, not an absolute temperature). A consumer that
  wants another baseline must say so; nothing here re-bases.
* **``***`` is a gap, never a measurement** (``value=None``, row kept). The current year's
  not-yet-published months are gaps too, not zeros and not carried-forward values.
* **A line that is not a data row is refused and COUNTED**, never skipped silently, so an HTML
  error page or a renamed product reads as ``looks_unrecognised`` and not as "no data".
* **Vintages are the point.** GISTEMP is retro-revised on every release (station records,
  homogenisation); a re-fetch is a new vintage, ``extracted_at`` is caller-stamped verbatim.
* **Seasonal columns (DJF, MAM, JJA, SON) are NOT emitted.** Their year label straddles the
  year end (the same trap ``oni.season_months`` documents) and the format is unverified live;
  they are still VALIDATED (a malformed seasonal cell refuses the row) and are named in
  ``skipped_columns`` so the omission is stated.
* **A blank cell, ``nan``/``inf``, an exponent or a duplicate year is refused**, never read
  as a gap or a figure; a body with no data rows at all is ``looks_unrecognised``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from src.stats.sdmx import StatFigure

#: When the documented shape below was last written down (NOT a live verification).
GISTEMP_AS_OF = "2026-11"

#: The stable agency code for NASA's Goddard Institute for Space Studies.
AGENCY = "us-nasa-giss"

#: Regions the v4 table data publishes, each its own file; ``ref_area`` carries the region.
REGIONS: tuple[str, ...] = ("GLB", "NH", "SH")

SERIES_MONTHLY = "gistemp.monthly"
SERIES_ANNUAL_JD = "gistemp.annual_jd"
SERIES_ANNUAL_DN = "gistemp.annual_dn"

BASE_PERIOD = "1951-1980"
UNIT = "degC"

METHODOLOGY_REF = (
    "NASA GISS Surface Temperature Analysis (GISTEMP v4): land-ocean temperature anomalies "
    "against the 1951-1980 base period (GHCN v4 land stations + ERSST v5 ocean). "
    "https://data.giss.nasa.gov/gistemp/"
)

_MONTHS: tuple[str, ...] = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)
_ANNUAL_COLS: tuple[str, ...] = ("J-D", "D-N")
_SEASON_COLS: tuple[str, ...] = ("DJF", "MAM", "JJA", "SON")
_HEADER: tuple[str, ...] = ("Year", *_MONTHS, *_ANNUAL_COLS, *_SEASON_COLS)

_MISSING = frozenset({"***", "****", "*****", "******"})
_MIN_YEAR, _MAX_YEAR = 1800, 2100


@dataclass
class GistempParse:
    """Figures plus everything the parse refused — the refusals are half the output."""

    figures: list[StatFigure] = field(default_factory=list)
    refused: list[dict[str, str]] = field(default_factory=list)
    rows_read: int = 0
    #: Exact number of refused lines; ``refused`` keeps only the first MAX_REFUSALS_KEPT.
    refused_total: int = 0
    #: Columns published but deliberately not emitted (stated, not silent).
    skipped_columns: tuple[str, ...] = _SEASON_COLS
    #: Non-blank lines before the header (the title line); counted, never parsed.
    preamble_lines: int = 0

    @property
    def refused_is_sample(self) -> bool:
        """True when ``refused`` holds only the first MAX_REFUSALS_KEPT of ``refused_total``."""
        return self.refused_total > len(self.refused)

    @property
    def all_gap(self) -> bool:
        """True when rows parsed but every figure is a gap (``***``): a success that holds no numbers."""
        return self.rows_read > 0 and all(f.value is None for f in self.figures)

    def summary(self) -> dict[str, object]:
        """The counts a caller must show beside the figures; the refusals are a SAMPLE when flagged."""
        return {
            "rows_read": self.rows_read,
            "figures": len(self.figures),
            "all_gap": self.all_gap,
            "refused_total": self.refused_total,
            "refused_sample": list(self.refused),
            "refused_is_sample": self.refused_is_sample,
            "skipped_columns": list(self.skipped_columns),
        }

    @property
    def looks_unrecognised(self) -> bool:
        """True when nothing parsed AND something was refused: not this file (HTML, 404...)."""
        return self.rows_read == 0 and self.refused_total > 0


_DECIMAL = re.compile(r"^[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)$")
_YEAR = re.compile(r"^[0-9]{4}$")

#: Stated plausibility bound (degC). Real anomalies sit within a few degrees; a cell beyond this
#: is a corrupt or hostile body, refused as not-a-measurement rather than shown as a figure.
_MAX_ABS_ANOMALY = 50.0

#: Refusals kept verbatim (the count is always exact in ``refused_total``).
MAX_REFUSALS_KEPT = 100


def _cell(raw: str) -> tuple[float | None, bool]:
    """``(value, ok)``: ``***`` is a real gap ``(None, True)``; anything else must be a plain
    finite decimal. A blank cell is NOT a gap (the documented marker is ``***``; a blank is a
    truncated or malformed line), and ``nan`` / ``inf`` / ``1e9`` / ``1_0`` are refused rather
    than turned into figures."""
    text = raw.strip()
    if text in _MISSING:
        return None, True
    if not _DECIMAL.match(text):
        return None, False
    value = float(text)
    if not math.isfinite(value) or abs(value) > _MAX_ABS_ANOMALY:
        return None, False
    return value, True


def parse_gistemp(text: str, *, region: str = "GLB", extracted_at: str) -> GistempParse:
    """Parse one GISTEMP v4 table CSV into vintaged :class:`StatFigure` rows."""
    if region not in REGIONS:
        raise ValueError(f"not a GISTEMP region: {region!r} (expected one of {REGIONS})")
    out = GistempParse()
    header_seen = False
    seen_years: set[int] = set()
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        fields = [p.strip() for p in stripped.split(",")]
        if tuple(fields) == _HEADER:
            header_seen = True
            continue
        if not header_seen:
            # Before the header only the title line is expected; anything else is HTML or
            # another product. Counted either way, and the missing header refuses all rows.
            out.preamble_lines += 1
            if out.preamble_lines > 3 or "," in stripped:
                _refuse(out, {"line": str(lineno), "reason": "data before the header", "text": stripped[:80]})
            continue
        if len(fields) != len(_HEADER):
            _refuse(out, {"line": str(lineno), "reason": f"expected {len(_HEADER)} fields", "text": stripped[:80]})
            continue
        if not _YEAR.match(fields[0]):
            _refuse(out, {"line": str(lineno), "reason": "year is not an integer", "text": stripped[:80]})
            continue
        year = int(fields[0])
        if not (_MIN_YEAR <= year <= _MAX_YEAR):
            _refuse(out, {"line": str(lineno), "reason": "year out of range", "text": stripped[:80]})
            continue
        cells = [_cell(c) for c in fields[1:]]  # months, J-D, D-N AND the seasons: all validated
        if not all(ok for _, ok in cells):
            _refuse(out, {"line": str(lineno), "reason": "non-numeric value", "text": stripped[:80]})
            continue
        if year in seen_years:
            _refuse(out, {"line": str(lineno), "reason": "duplicate year", "text": stripped[:80]})
            continue
        seen_years.add(year)
        out.rows_read += 1
        values = [v for v, _ in cells]
        for i in range(len(_MONTHS)):
            out.figures.append(_fig(SERIES_MONTHLY, region, f"{year}-{i + 1:02d}", values[i], extracted_at))
        out.figures.append(_fig(SERIES_ANNUAL_JD, region, str(year), values[12], extracted_at))
        out.figures.append(_fig(SERIES_ANNUAL_DN, region, str(year), values[13], extracted_at))
    if out.rows_read == 0 and out.refused_total == 0:
        # An empty body, a title line only, or a header with no rows: not a series. Recorded
        # as a refusal so it reads as "unrecognised", never as a successful empty fetch.
        reason = "no data rows found" if header_seen else "header row not found"
        _refuse(out, {"line": "0", "reason": reason, "text": ""})
    return out


def _refuse(out: GistempParse, entry: dict[str, str]) -> None:
    out.refused_total += 1
    if len(out.refused) < MAX_REFUSALS_KEPT:
        out.refused.append(entry)


def _fig(series: str, region: str, period: str, value: float | None, extracted_at: str) -> StatFigure:
    return StatFigure(
        agency=AGENCY,
        series_id=series,
        ref_area=region,
        time_period=period,
        value=value,
        unit=UNIT,
        methodology_ref=METHODOLOGY_REF,
        adjustment=None,
        base_year=BASE_PERIOD,
        extracted_at=extracted_at,
    )
