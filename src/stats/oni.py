"""
Offline parser for the NOAA CPC Oceanic Niño Index (ONI) ASCII table.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The climate vertical's recommended first slice (V1_PATHWAY §4.3): one small, keyless,
public-domain file — ``oni.ascii.txt`` — parsed with the standard library alone. It is
also the one that closes a standing debt: ``configs/climate_events.yml`` bundles an El Niño
episode table drafted from training knowledge and marked *"clearnet check pending"* since
2026-06-12, and the CPC's own table is what settles it.

Like ``usgs.py``, this is PURE: it takes an already-decoded ``str`` a caller fetched and
never imports ``requests`` / ``httpx`` / ``socket``. The networked fetch lives behind the
guarded factory + kill switch and is on the operator list, because this sandbox cannot
reach ``origin.cpc.ncep.noaa.gov`` (probed 2026-09-07: CONNECT 403 via the proxy, with
``pypi.org`` at 200 as the control). **So the file FORMAT below is documented from the
published shape and is NOT verified against a live download** — the parser therefore
refuses anything it does not recognise rather than bending to fit, and reports what it
refused, so a format drift surfaces as a loud gap instead of a plausible number.

THE PUBLISHED SHAPE (a header line, then whitespace-separated columns)::

    SEAS YR   TOTAL ANOM
    DJF  1950 24.72 -1.53
    JFM  1950 25.17 -1.34

``SEAS`` is one of the twelve overlapping three-month seasons; ``TOTAL`` is the Niño-3.4
sea-surface temperature in °C and ``ANOM`` is the anomaly against the CPC's own centred
30-year base periods — which IS the ONI. Two series are emitted, never blended.

FOUR HONESTY PROPERTIES, each a refusal rather than a caveat:

* **A period label is published, never derived.** "DJF 1950" spans December *1949* to
  February 1950, so converting it to a date would silently pick one of three months and
  bake in an off-by-one-year for the two seasons that straddle the year end. The
  ``time_period`` is the label exactly as published (``"1950-DJF"``), per the StatFigure
  contract, and ``season_months()`` exposes the span for a caller that needs it — with the
  year rollback stated rather than assumed.

* **A missing sentinel is a gap, never a measurement.** CPC products use ``-99.9`` /
  ``-999.9`` / ``-9.99`` for "no observation". Read literally, a -99.9 °C anomaly would
  enter the corpus as the most extreme cooling ever recorded. Those become ``value=None``
  and the ROW IS STILL EMITTED, because a published gap is data.

* **An unparseable line is refused and COUNTED, never skipped silently.** If the fetch is
  handed a 404 HTML page, a naive parser returns an empty list that reads as "the file has
  no data". ``parse_oni`` returns the refusals with the figures, so all-garbage input is
  loud. See ``OniParse.looks_unrecognised``.

* **Vintages are the point.** GISTEMP and ONI both RETRO-REVISE history, so a re-fetch is a
  new vintage rather than an overwrite; ``extracted_at`` is caller-stamped verbatim and the
  StatFigure unique key already includes it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.stats.sdmx import StatFigure

#: The stable agency code for the NOAA Climate Prediction Center.
AGENCY = "us-noaa-cpc"

#: The two series this file publishes. Kept apart: an SST and an anomaly against a moving
#: 30-year base are different quantities, and a single series id would let a consumer
#: compare them or, worse, average them.
SERIES_ANOM = "oni.anom"
SERIES_TOTAL = "oni.sst"

#: The Niño 3.4 region is the subject area; there is no country, and inventing one (or
#: reusing a global "WLD" aggregate) would make this figure join country choropleths it
#: has no business in.
REF_AREA = "nino34"

METHODOLOGY_REF = (
    "NOAA Climate Prediction Center, Oceanic Niño Index (ONI): 3-month running mean of "
    "ERSST.v5 SST anomalies in the Niño 3.4 region (5°N-5°S, 120°-170°W), against "
    "centred 30-year base periods updated every 5 years."
)

#: The twelve overlapping three-month seasons, in calendar order. A token outside this set
#: is refused: it is the one field that can be validated exactly, so it is the cheapest
#: place to catch a file that is not the file we think it is.
SEASONS: tuple[str, ...] = (
    "DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ",
    "JJA", "JAS", "ASO", "SON", "OND", "NDJ",
)
_SEASON_INDEX = {s: i for i, s in enumerate(SEASONS)}

#: Missing-data sentinels seen in CPC ASCII products. Compared on the RAW TEXT rather than
#: on the parsed float, so a future -99.90 or -99.9000 is caught by value and a legitimate
#: -9.9 is not caught by a sloppy prefix match.
_MISSING_SENTINELS = frozenset({"-99.9", "-99.90", "-999.9", "-999.90", "-999", "-9.99", "-99.99"})

#: A plausible year range. ONI starts in 1950; the ceiling is deliberately generous but
#: finite, so a column-shifted line cannot land a temperature in the year field and be
#: silently accepted (the recorded "_MIN_YEAR lets any 4-digit number become a date" trap).
_MIN_YEAR, _MAX_YEAR = 1850, 2200


def season_months(season: str, year: int) -> tuple[tuple[int, int], ...]:
    """The three (year, month) pairs a published ``(season, year)`` label covers.

    The label's YEAR belongs to the season's LAST month, so DJF 1950 is December **1949**,
    January 1950, February 1950 — and NDJ 1950 runs into January **1951**. Exposed as a
    helper rather than folded into the parse, because the moment a period becomes a date
    the two straddling seasons acquire a silent off-by-one-year that nothing downstream
    can detect.
    """
    idx = _SEASON_INDEX.get(season.upper())
    if idx is None:
        raise ValueError(f"not a CPC season label: {season!r}")
    # DJF is index 0 and its months are Dec(-1), Jan, Feb -> start month 12 of year-1.
    start_month = 12 if idx == 0 else idx
    start_year = year - 1 if idx == 0 else year
    out = []
    m, y = start_month, start_year
    for _ in range(3):
        out.append((y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return tuple(out)


@dataclass
class OniParse:
    """Figures plus everything the parse refused — the refusals are half the output."""

    figures: list[StatFigure] = field(default_factory=list)
    refused: list[dict[str, str]] = field(default_factory=list)
    rows_read: int = 0

    @property
    def looks_unrecognised(self) -> bool:
        """True when the input produced refusals and NO rows at all.

        The signature of being handed something that is not this file — an HTML error
        page, a redirect body, a renamed product. A caller must treat this as a failed
        fetch rather than as an empty series, because an empty list and a wrong file are
        indistinguishable once the refusals are dropped.
        """
        return self.rows_read == 0 and bool(self.refused)


def _numeric(raw: str) -> tuple[float | None, bool]:
    """``(value, ok)`` for one cell: a sentinel yields ``(None, True)`` — a real gap.

    ``ok=False`` means the cell is not a number at all, which is a REFUSAL: unlike a
    sentinel, it is evidence the line is not what we think it is, and turning it into a
    gap would launder a parse failure into a published observation of nothing.
    """
    text = raw.strip()
    if not text:
        return None, True
    if text in _MISSING_SENTINELS:
        return None, True
    try:
        return float(text), True
    except ValueError:
        return None, False


def parse_oni(text: str, *, extracted_at: str) -> OniParse:
    """Parse the CPC ONI ASCII table into vintaged :class:`StatFigure` rows.

    ``extracted_at`` is the caller's vintage marker, stamped verbatim — the parser reads no
    clock, so a re-parse of the same bytes is byte-identical and a re-FETCH is a new
    vintage rather than an overwrite.
    """
    out = OniParse()
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split()
        # The header, and anything else with the wrong arity. Refused rather than
        # guessed at: a 3- or 5-column line is a different file, not a lenient one.
        if len(parts) != 4:
            out.refused.append({"line": str(lineno), "reason": "expected 4 fields", "text": stripped[:80]})
            continue
        season, year_raw, total_raw, anom_raw = parts
        season = season.upper()
        if season not in _SEASON_INDEX:
            out.refused.append({"line": str(lineno), "reason": "not a CPC season label", "text": stripped[:80]})
            continue
        try:
            year = int(year_raw)
        except ValueError:
            out.refused.append({"line": str(lineno), "reason": "year is not an integer", "text": stripped[:80]})
            continue
        if not (_MIN_YEAR <= year <= _MAX_YEAR):
            out.refused.append({"line": str(lineno), "reason": "year out of range", "text": stripped[:80]})
            continue

        total, total_ok = _numeric(total_raw)
        anom, anom_ok = _numeric(anom_raw)
        if not (total_ok and anom_ok):
            out.refused.append({"line": str(lineno), "reason": "non-numeric value", "text": stripped[:80]})
            continue

        out.rows_read += 1
        period = f"{year}-{season}"
        for series, value in ((SERIES_TOTAL, total), (SERIES_ANOM, anom)):
            out.figures.append(
                StatFigure(
                    agency=AGENCY,
                    series_id=series,
                    ref_area=REF_AREA,
                    time_period=period,
                    value=value,
                    unit="degC",
                    methodology_ref=METHODOLOGY_REF,
                    # The CPC publishes neither a seasonal-adjustment flag nor an index
                    # base period for this product. NULL means "the response did not
                    # state it" -- the base period IS in the methodology text above, but
                    # writing it here would claim the file declared a field it does not.
                    adjustment=None,
                    base_year=None,
                    extracted_at=extracted_at,
                )
            )
    return out


# --------------------------------------------------------------------------------------
# Episode derivation — what the parser is FOR.
#
# `configs/climate_events.yml` bundles an El Niño episode table drafted from training
# knowledge and marked "clearnet check pending" since 2026-06-12. The CPC's own convention
# is arithmetic over exactly the series above, so once the operator has the real file the
# bundled table stops being a claim and becomes a checkable one. Kept here, beside the
# parser, so the definition and the data that feeds it cannot drift apart.
# --------------------------------------------------------------------------------------

#: The CPC episode convention: ONI at or above +0.5 °C for at least five CONSECUTIVE
#: overlapping three-month seasons. La Niña is the mirror at -0.5; both are exposed so a
#: caller states which it asked for rather than inferring from a sign.
EPISODE_THRESHOLD = 0.5
EPISODE_MIN_SEASONS = 5

#: Peak-ONI intensity buckets, per CPC usage. A LABEL for a published number, never a
#: score: the bucket is derived from the peak alone and the peak travels beside it, so a
#: reader can always see the value the label came from.
_INTENSITY_BANDS: tuple[tuple[float, str], ...] = (
    (2.0, "very strong"),
    (1.5, "strong"),
    (1.0, "moderate"),
    (0.5, "weak"),
)


def intensity_for(peak: float) -> str | None:
    """The CPC intensity bucket for a peak ONI, or None below the episode threshold."""
    for floor, label in _INTENSITY_BANDS:
        if abs(peak) >= floor:
            return label
    return None


def episodes_from_oni(
    figures: list[StatFigure], *, warm: bool = True
) -> list[dict[str, object]]:
    """Derive El Niño (``warm``) or La Niña episodes from parsed ONI anomaly figures.

    An episode is a run of at least ``EPISODE_MIN_SEASONS`` consecutive seasons at or
    beyond ±``EPISODE_THRESHOLD``. Returns ``{start, end, seasons, peak_oni, intensity}``
    per episode, with ``start``/``end`` the PUBLISHED season labels — this function
    inherits the parser's refusal to turn a season into a date.

    THREE REFUSALS, each of which a looser implementation would fabricate through:

    * **A gap BREAKS a run; it never continues one.** A ``value=None`` season is not a
      season below the threshold and not one above it — it is an unobserved season, and
      bridging it would invent an episode that spans a hole. This is the chart toolkit's
      "render gaps as gaps" rule, one layer down in the arithmetic.
    * **A break in the season SEQUENCE also breaks a run.** Two runs on either side of a
      missing row are two runs; concatenating them because they are adjacent in the LIST
      would join 1972 to 1997 in a file with a hole in the middle.
    * **A run shorter than the minimum is not an episode**, and is not reported as a
      shorter one — the CPC definition is the definition, and softening it here would make
      the bundled table's comparison meaningless.
    """
    anoms = [f for f in figures if f.series_id == SERIES_ANOM]
    ordered = sorted(anoms, key=_season_sort_key)

    episodes: list[dict[str, object]] = []
    run: list[StatFigure] = []

    def flush() -> None:
        if len(run) >= EPISODE_MIN_SEASONS:
            values = [f.value for f in run if f.value is not None]
            peak = max(values) if warm else min(values)
            episodes.append({
                "start": run[0].time_period,
                "end": run[-1].time_period,
                "seasons": len(run),
                "peak_oni": peak,
                "intensity": intensity_for(peak),
            })
        run.clear()

    prev_key: tuple[int, int] | None = None
    for fig in ordered:
        key = _season_sort_key(fig)
        # A hole in the sequence ends whatever run was open, BEFORE the threshold test:
        # adjacency in the list is not adjacency in time.
        if prev_key is not None and key != _next_season_key(prev_key):
            flush()
        prev_key = key
        v = fig.value
        if v is None:
            flush()          # an unobserved season is not a continuation
            continue
        if (v >= EPISODE_THRESHOLD) if warm else (v <= -EPISODE_THRESHOLD):
            run.append(fig)
        else:
            flush()
    flush()
    return episodes


def _season_sort_key(fig: StatFigure) -> tuple[int, int]:
    """``(year, season index)`` for a ``YYYY-SEA`` period label."""
    year_s, _, season = fig.time_period.partition("-")
    return int(year_s), _SEASON_INDEX[season]


def _next_season_key(key: tuple[int, int]) -> tuple[int, int]:
    year, idx = key
    return (year + 1, 0) if idx == len(SEASONS) - 1 else (year, idx + 1)
