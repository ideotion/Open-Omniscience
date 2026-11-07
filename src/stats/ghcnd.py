"""
Offline parser for NOAA NCEI GHCN-Daily station files (``.dly``) and the station list.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Climate row A1-6 of the 0.6 plan, built like ``gistemp.py``: PURE (an already-decoded ``str``
in, figures out, no ``requests`` / ``httpx`` / ``socket``, no clock), with the networked fetch
behind the guarded factory in ``src.stats.fetch.fetch_ghcnd_station``.

**The FORMAT below is documented from NCEI's published ``readme.txt`` and is NOT verified
against a live download.** The build sandbox has no route to ``www.ncei.noaa.gov``; the
parser therefore refuses anything it does not recognise and counts what it refused, so a
format drift is a loud gap rather than a plausible number. The operator's first real fetch is
the check.

THE PUBLISHED SHAPE. One ``<STATION_ID>.dly`` file per station, one line per
(station, year, month, element), fixed width, 269 characters::

    cols  1-11  ID       station id (country code + network code + 8 characters)
    cols 12-15  YEAR
    cols 16-17  MONTH
    cols 18-21  ELEMENT  PRCP, SNOW, SNWD, TMAX, TMIN, ...
    then 31 groups of 8 characters, one per day of the month:
          VALUE (5, integer, -9999 = missing) · MFLAG (1) · QFLAG (1) · SFLAG (1)

Units are tenths: PRCP in tenths of mm, TMAX / TMIN in tenths of degC; SNOW and SNWD are whole
mm. The five elements above are the "core" ones; the others (WT01.., WV.., EVAP, ...) are not
emitted and are NAMED in ``skipped_elements`` with their line counts.

HONESTY PROPERTIES, each a refusal rather than a caveat:

* **A missing day is a gap, never a zero** (``value=None``, kept). Days that do not exist in
  the month (the 31st of April) are not emitted at all; a value there refuses the line.
* **A value that failed NCEI's quality checks is NOT shown as a measurement.** A non-blank
  QFLAG turns the figure into a gap and the reason (the flag letter) is counted in
  ``quality_flagged`` and sampled in ``flagged``. The original number is not kept here.
* **Trace precipitation** (MFLAG ``T``) is the value 0.0 and counted in ``trace_days``, so a
  consumer can tell "dry" from "a trace".
* **A line that is not a data row is refused and COUNTED**, never skipped silently, so an HTML
  error page or a renamed product reads as ``looks_unrecognised`` and not as "no data".
* **Vintages are the point.** GHCN-Daily is revised as sources are re-ingested; a re-fetch is
  a new vintage, ``extracted_at`` is caller-stamped verbatim.
* **A station id other than the expected one, a duplicate (year, month, element), a malformed
  or implausible value** (a temperature past stated physical limits, a negative amount of
  precipitation or snow) refuses the line.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field

from src.stats.sdmx import StatFigure

#: When the documented shape above was last written down (NOT a live verification).
GHCND_AS_OF = "2026-11"

#: NOAA's National Centers for Environmental Information, GHCN-Daily's publisher.
AGENCY = "us-noaa-ncei"

METHODOLOGY_REF = (
    "NOAA NCEI Global Historical Climatology Network - Daily (GHCN-Daily) v3: daily station "
    "observations with NCEI quality-assurance flags. "
    "https://www.ncei.noaa.gov/products/land-based-station/global-historical-climatology-network-daily"
)

#: element -> (unit, divisor from the published integer). Tenths for PRCP / TMAX / TMIN.
ELEMENTS: dict[str, tuple[str, int]] = {
    "TMAX": ("degC", 10),
    "TMIN": ("degC", 10),
    "PRCP": ("mm", 10),
    "SNOW": ("mm", 1),
    "SNWD": ("mm", 1),
}

SERIES_PREFIX = "ghcnd."

LINE_LENGTH = 269  # 21 header characters + 31 days x 8
_DAYS = 31
_MISSING = -9999

#: Stated physical bound for a temperature, in the published tenths of degC (+-100 degC).
_MAX_ABS_TEMP_TENTHS = 1000

#: Refusals / flagged values kept verbatim (the counts are always exact).
MAX_REFUSALS_KEPT = 100

_STATION_ID = re.compile(r"^[A-Z]{2}[A-Z0-9][A-Z0-9]{8}$")
_ELEMENT = re.compile(r"^[A-Z][A-Z0-9]{3}$")
_INT = re.compile(r"^ *-?[0-9]+$")


def valid_station_id(station: str) -> bool:
    """True for an 11-character GHCN id (country + network + 8); also what a URL may carry."""
    return bool(_STATION_ID.match(station))


@dataclass
class GhcndParse:
    """Figures plus everything the parse refused or blanked: those counts are half the output."""

    figures: list[StatFigure] = field(default_factory=list)
    refused: list[dict[str, str]] = field(default_factory=list)
    lines_read: int = 0
    refused_total: int = 0
    #: Figures blanked because the value failed a quality check: flag letter -> days.
    quality_flagged: dict[str, int] = field(default_factory=dict)
    #: The first MAX_REFUSALS_KEPT blanked days, verbatim (station, date, element, flag).
    flagged: list[dict[str, str]] = field(default_factory=list)
    #: Days published as missing (-9999), kept as gaps.
    missing_days: int = 0
    trace_days: int = 0
    #: Elements published but not emitted: element -> lines. Stated, not silent.
    skipped_elements: dict[str, int] = field(default_factory=dict)

    @property
    def refused_is_sample(self) -> bool:
        return self.refused_total > len(self.refused)

    @property
    def all_gap(self) -> bool:
        """True when lines parsed but every figure is a gap: a success that holds no numbers."""
        return bool(self.figures) and all(f.value is None for f in self.figures)

    @property
    def looks_unrecognised(self) -> bool:
        """True when nothing parsed AND something was refused: not this file (HTML, 404...)."""
        return self.lines_read == 0 and not self.skipped_elements and self.refused_total > 0

    def summary(self) -> dict[str, object]:
        """The counts a caller must show beside the figures."""
        return {
            "lines_read": self.lines_read,
            "figures": len(self.figures),
            "all_gap": self.all_gap,
            "missing_days": self.missing_days,
            "quality_flagged": dict(self.quality_flagged),
            "quality_flagged_total": sum(self.quality_flagged.values()),
            "trace_days": self.trace_days,
            "skipped_elements": dict(self.skipped_elements),
            "refused_total": self.refused_total,
            "refused_sample": list(self.refused),
            "refused_is_sample": self.refused_is_sample,
        }


def parse_ghcnd_dly(text: str, *, station: str, extracted_at: str) -> GhcndParse:
    """Parse one station's ``.dly`` file into vintaged daily :class:`StatFigure` rows.

    ``station`` is the id the caller asked for; a line carrying another id is refused, so a
    mislabelled or concatenated body cannot attribute one station's days to another.
    """
    if not valid_station_id(station):
        raise ValueError(f"not a GHCN station id: {station!r}")
    out = GhcndParse()
    seen: set[tuple[int, int, str]] = set()
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        if len(line) != LINE_LENGTH:
            _refuse(out, lineno, f"expected {LINE_LENGTH} characters, got {len(line)}", line)
            continue
        sid, ystr, mstr, element = line[0:11], line[11:15], line[15:17], line[17:21]
        if sid != station:
            _refuse(out, lineno, "station id is not the one requested", line)
            continue
        if not (ystr.isdigit() and mstr.isdigit() and _ELEMENT.match(element)):
            _refuse(out, lineno, "year, month or element is malformed", line)
            continue
        year, month = int(ystr), int(mstr)
        if not (1 <= month <= 12 and 1 <= year <= 9999):
            _refuse(out, lineno, "year or month out of range", line)
            continue
        key = (year, month, element)
        if key in seen:
            _refuse(out, lineno, "duplicate year, month and element", line)
            continue
        if element not in ELEMENTS:
            seen.add(key)
            out.skipped_elements[element] = out.skipped_elements.get(element, 0) + 1
            continue
        days = _parse_days(line, calendar.monthrange(year, month)[1], element)
        if days is None:
            _refuse(out, lineno, "a day group is malformed or implausible", line)
            continue
        seen.add(key)
        out.lines_read += 1
        unit, divisor = ELEMENTS[element]
        for day, value, mflag, qflag in days:
            date = f"{year:04d}-{month:02d}-{day:02d}"
            figure_value: float | None
            if value == _MISSING:
                figure_value = None
                out.missing_days += 1
            elif qflag != " ":
                figure_value = None
                out.quality_flagged[qflag] = out.quality_flagged.get(qflag, 0) + 1
                if len(out.flagged) < MAX_REFUSALS_KEPT:
                    out.flagged.append({"station": station, "date": date, "element": element, "qflag": qflag})
            else:
                figure_value = value / divisor if divisor != 1 else float(value)
                if element == "PRCP" and mflag == "T":
                    out.trace_days += 1
            out.figures.append(
                StatFigure(
                    agency=AGENCY,
                    series_id=SERIES_PREFIX + element,
                    ref_area=station,
                    time_period=date,
                    value=figure_value,
                    unit=unit,
                    methodology_ref=METHODOLOGY_REF,
                    adjustment=None,
                    base_year=None,
                    extracted_at=extracted_at,
                )
            )
    if out.lines_read == 0 and not out.skipped_elements and out.refused_total == 0:
        _refuse(out, 0, "no data lines found", "")
    return out


def _parse_days(line: str, days_in_month: int, element: str) -> list[tuple[int, int, str, str]] | None:
    """The (day, value, mflag, qflag) of every real day, or None when any group is bad."""
    out: list[tuple[int, int, str, str]] = []
    for d in range(1, _DAYS + 1):
        base = 21 + 8 * (d - 1)
        raw = line[base : base + 5]
        mflag, qflag = line[base + 5], line[base + 6]
        if not _INT.match(raw):
            return None
        value = int(raw)
        if d > days_in_month:
            if value != _MISSING:
                return None  # a measurement on a day the month does not have
            continue
        if value != _MISSING:
            if element in ("TMAX", "TMIN") and abs(value) > _MAX_ABS_TEMP_TENTHS:
                return None
            if element not in ("TMAX", "TMIN") and value < 0:
                return None
        out.append((d, value, mflag, qflag))
    return out


def _refuse(out: GhcndParse, lineno: int, reason: str, line: str) -> None:
    out.refused_total += 1
    if len(out.refused) < MAX_REFUSALS_KEPT:
        out.refused.append({"line": str(lineno), "reason": reason, "text": line[:80]})


# --------------------------------------------------------------------------- #
# ghcnd-stations.txt (the station list)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GhcndStation:
    """One row of ``ghcnd-stations.txt``. Unknown values are None, never a sentinel."""

    station_id: str
    latitude: float
    longitude: float
    elevation_m: float | None  # -999.9 is published for "unknown"
    state: str | None
    name: str
    gsn: bool
    hcn_crn: str | None  # "HCN" or "CRN" when flagged
    wmo_id: str | None


@dataclass
class GhcndStationParse:
    stations: list[GhcndStation] = field(default_factory=list)
    refused: list[dict[str, str]] = field(default_factory=list)
    refused_total: int = 0

    @property
    def looks_unrecognised(self) -> bool:
        return not self.stations and self.refused_total > 0


def parse_ghcnd_stations(text: str) -> GhcndStationParse:
    """Parse ``ghcnd-stations.txt`` (fixed width: id 1-11, lat 13-20, lon 22-30, elev 32-37,
    state 39-40, name 42-71, GSN 73-75, HCN/CRN 77-79, WMO 81-85)."""
    out = GhcndStationParse()
    seen: set[str] = set()
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        row = raw.ljust(85)
        sid = row[0:11]
        try:
            lat, lon, elev = float(row[12:20]), float(row[21:30]), float(row[31:37])
        except ValueError:
            out.refused_total += 1
            _sample(out, lineno, "latitude, longitude or elevation is not a number", raw)
            continue
        if not valid_station_id(sid) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            out.refused_total += 1
            _sample(out, lineno, "station id or coordinates out of range", raw)
            continue
        if sid in seen:
            out.refused_total += 1
            _sample(out, lineno, "duplicate station id", raw)
            continue
        seen.add(sid)
        state = row[38:40].strip()
        network = row[76:79].strip()
        wmo = row[80:85].strip()
        out.stations.append(
            GhcndStation(
                station_id=sid,
                latitude=lat,
                longitude=lon,
                elevation_m=None if elev == -999.9 else elev,
                state=state or None,
                name=row[41:71].strip(),
                gsn=row[72:75].strip() == "GSN",
                hcn_crn=network if network in ("HCN", "CRN") else None,
                wmo_id=wmo or None,
            )
        )
    return out


def _sample(out: GhcndStationParse, lineno: int, reason: str, line: str) -> None:
    if len(out.refused) < MAX_REFUSALS_KEPT:
        out.refused.append({"line": str(lineno), "reason": reason, "text": line[:80]})
