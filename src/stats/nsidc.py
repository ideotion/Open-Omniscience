"""
Offline parser for the NSIDC Sea Ice Index daily extent CSV (G02135, version 3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Climate row A1-5, built like ``gistemp.py``: PURE (an already-decoded ``str`` in, figures out,
no ``requests`` / ``httpx`` / ``socket``, no clock), with the networked fetch behind the guarded
factory in ``src.stats.fetch.fetch_nsidc``.

**The file FORMAT below is documented from the published shape and is NOT verified against a
live download.** The build sandbox has no route to ``noaadata.apps.nsidc.org``; the parser
refuses anything it does not recognise and reports what it refused, so a format drift is a loud
gap rather than a plausible number. The operator's first real fetch is the check.

THE PUBLISHED SHAPE (``N_seaice_extent_daily_v3.0.csv``; ``S_`` is the same shape)::

    Year, Month, Day,     Extent,    Missing, Source Data
    YYYY,    MM,  DD, 10^6 sq km, 10^6 sq km, Source data product web site: http://nsidc.org/data/nsidc-0081.html
    1978,    10,  26,    10.231,      0.000, ['ftp://...']

HONESTY PROPERTIES, each a refusal rather than a caveat:

* **Extent is the area of ocean with at least 15 % ice concentration**, in millions of km2
  (``10^6 sq km``), not ice volume and not ice area; the unit string says ``Mkm2`` and the
  method string says what extent is.
* **``-9999`` is a gap, never a measurement** (``value=None``, row kept). A blank, ``nan``,
  ``inf``, an exponent, a negative extent or a duplicate date is refused, never read as a gap.
* **The early record is every other day** (1978 to 1987); days that were never published are
  simply absent. Nothing is interpolated, and the series is NOT claimed daily throughout.
* **The ``Missing`` column** (area with no data in the swath, in 10^6 km2) is validated but not
  emitted as its own series; it is counted in ``rows_with_missing_area`` so a consumer can say
  that some days were computed with part of the pole unobserved, and a ``-9999`` there is
  counted in ``rows_with_unknown_missing_area`` (coverage unknown is not full coverage);
  ``coverage_gaps`` names each such DAY, so a consumer can mark which figures are undercounts.
* **The column-names line is matched whole**, so a swapped or renamed column is refused, not
  read as Extent.
* **The units row is checked**: both area columns must say ``10^6 sq km``, or no row is read.
* **A line that is not a data row is refused and COUNTED**, so an HTML error page or a renamed
  product reads as ``looks_unrecognised`` and not as "no data".
* **Vintages are the point.** NSIDC reprocesses (the NRT tail is replaced by the final product);
  a re-fetch is a new vintage and ``extracted_at`` is caller-stamped verbatim.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date

from src.stats.sdmx import StatFigure

#: When the documented shape above was last written down (NOT a live verification).
NSIDC_AS_OF = "2026-11"

AGENCY = "us-nsidc"

#: Hemisphere file prefixes the Sea Ice Index publishes; ``ref_area`` carries the hemisphere.
REGIONS: tuple[str, ...] = ("N", "S")

SERIES_DAILY_EXTENT = "nsidc.sea_ice_extent_daily"
UNIT = "Mkm2"

METHODOLOGY_REF = (
    "NSIDC Sea Ice Index v3 (G02135): sea ice extent, the total area of ocean with at least "
    "15% ice concentration, in millions of square kilometres. "
    "https://nsidc.org/data/g02135"
)

_EXPECTED_FIELDS = 6
_MISSING_MARKER = -9999.0
_MIN_YEAR, _MAX_YEAR = 1978, 2100

_DECIMAL = re.compile(r"^[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)$")
_INT = re.compile(r"^[0-9]{1,4}$")

#: Stated plausibility bound (10^6 km2). The whole ocean is ~361; anything above is corrupt.
_MAX_EXTENT = 400.0

#: Refusals kept verbatim (the count is always exact in ``refused_total``).
MAX_REFUSALS_KEPT = 100


@dataclass
class NsidcParse:
    """Figures plus everything the parse refused - the refusals are half the output."""

    figures: list[StatFigure] = field(default_factory=list)
    refused: list[dict[str, str]] = field(default_factory=list)
    rows_read: int = 0
    refused_total: int = 0
    #: Rows whose ``Missing`` column was above zero (part of the pole unobserved that day).
    rows_with_missing_area: int = 0
    #: Rows whose ``Missing`` column was the ``-9999`` gap: that day's coverage is unknown.
    rows_with_unknown_missing_area: int = 0
    #: Per day, the area left unobserved (10^6 km2) on every day that was NOT fully observed, keyed by the
    #: figure's ``time_period``; ``None`` = unknown (the ``-9999`` gap). A day absent here was fully observed.
    coverage_gaps: dict[str, float | None] = field(default_factory=dict)
    header_lines: int = 0

    @property
    def refused_is_sample(self) -> bool:
        return self.refused_total > len(self.refused)

    @property
    def all_gap(self) -> bool:
        """True when rows parsed but every figure is a gap: a success that holds no numbers."""
        return self.rows_read > 0 and all(f.value is None for f in self.figures)

    @property
    def looks_unrecognised(self) -> bool:
        """True when nothing parsed AND something was refused: not this file (HTML, 404...)."""
        return self.rows_read == 0 and self.refused_total > 0

    def summary(self) -> dict[str, object]:
        return {
            "rows_read": self.rows_read,
            "figures": len(self.figures),
            "all_gap": self.all_gap,
            "rows_with_missing_area": self.rows_with_missing_area,
            "rows_with_unknown_missing_area": self.rows_with_unknown_missing_area,
            "coverage_gaps": dict(self.coverage_gaps),
            "refused_total": self.refused_total,
            "refused_sample": list(self.refused),
            "refused_is_sample": self.refused_is_sample,
        }


def _number(raw: str) -> tuple[float | None, str | None]:
    """``(value, refusal)``: ``-9999`` is a gap ``(None, None)``; otherwise a plain, finite,
    non-negative decimal within the stated bound, or a named refusal."""
    text = raw.strip()
    if not _DECIMAL.match(text):
        return None, "non-numeric value"
    value = float(text)
    if not math.isfinite(value):
        return None, "non-numeric value"
    if value == _MISSING_MARKER:
        return None, None
    if text.startswith("-"):
        return None, "negative value"  # includes -0.000: a sign on an area is not a measurement
    if value > _MAX_EXTENT:
        return None, f"value above the {_MAX_EXTENT:g} x 10^6 km2 bound"
    return value, None


_UNIT_TEXT = "10^6 sq km"
#: The column-names line, matched whole: a swapped or renamed column must not be read as Extent.
_NAMES: tuple[str, ...] = ("Year", "Month", "Day", "Extent", "Missing", "Source Data")


def parse_nsidc(text: str, *, region: str = "N", extracted_at: str) -> NsidcParse:
    """Parse one Sea Ice Index daily extent CSV into vintaged :class:`StatFigure` rows."""
    if region not in REGIONS:
        raise ValueError(f"not an NSIDC hemisphere: {region!r} (expected one of {REGIONS})")
    out = NsidcParse()
    seen: set[date] = set()
    names_seen = False
    header_seen = False  # True once BOTH header lines (names, then units) have been read
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        # The sixth field (source data) is free text that can itself hold commas.
        fields = [p.strip() for p in stripped.split(",", _EXPECTED_FIELDS - 1)]
        first = fields[0].lower()
        if first == "year" and not header_seen:
            out.header_lines += 1
            if tuple(fields) == _NAMES:
                names_seen = True
            else:
                _refuse(out, lineno, "column names or order changed", stripped)
            continue
        if first == "yyyy" and names_seen and not header_seen:
            out.header_lines += 1
            if len(fields) == _EXPECTED_FIELDS and fields[3] == _UNIT_TEXT and fields[4] == _UNIT_TEXT:
                header_seen = True
            else:
                _refuse(out, lineno, f"units row does not say {_UNIT_TEXT}", stripped)
            continue
        if not header_seen:
            _refuse(out, lineno, "data before the header", stripped)
            continue
        if len(fields) != _EXPECTED_FIELDS:
            _refuse(out, lineno, f"expected {_EXPECTED_FIELDS} fields", stripped)
            continue
        if not all(_INT.match(f) for f in fields[:3]):
            _refuse(out, lineno, "year, month or day is not an integer", stripped)
            continue
        year, month, day = (int(f) for f in fields[:3])
        if not (_MIN_YEAR <= year <= _MAX_YEAR):
            _refuse(out, lineno, "year out of range", stripped)
            continue
        try:
            when = date(year, month, day)
        except ValueError:
            _refuse(out, lineno, "not a calendar date", stripped)
            continue
        extent, why_extent = _number(fields[3])
        missing, why_missing = _number(fields[4])
        if why_extent or why_missing:
            _refuse(out, lineno, why_extent or why_missing or "", stripped)
            continue
        if when in seen:
            _refuse(out, lineno, "duplicate date", stripped)
            continue
        seen.add(when)
        out.rows_read += 1
        if missing is None:
            out.rows_with_unknown_missing_area += 1
            out.coverage_gaps[when.isoformat()] = None
        elif missing > 0:
            out.rows_with_missing_area += 1
            out.coverage_gaps[when.isoformat()] = missing
        out.figures.append(
            StatFigure(
                agency=AGENCY,
                series_id=SERIES_DAILY_EXTENT,
                ref_area=region,
                time_period=when.isoformat(),
                value=extent,
                unit=UNIT,
                methodology_ref=METHODOLOGY_REF,
                adjustment=None,
                base_year=None,
                extracted_at=extracted_at,
            )
        )
    if out.rows_read == 0 and out.refused_total == 0:
        _refuse(out, 0, "no data rows found" if header_seen else "header row not found", "")
    return out


def _refuse(out: NsidcParse, lineno: int, reason: str, text: str) -> None:
    out.refused_total += 1
    if len(out.refused) < MAX_REFUSALS_KEPT:
        out.refused.append({"line": str(lineno), "reason": reason, "text": text[:80]})
