"""
Offline parser for USGS Mineral Commodity Summaries (MCS) SUPPLY data.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The rare-earths ruling (B12): there is NO free rare-earth SPOT-price source, so the
honest path is the USGS **Mineral Commodity Summaries** — annual SUPPLY statistics
(mine production, reserves, net-import-reliance). These are supply figures, explicitly
**NOT market prices**, and this module fabricates none:

  * it emits provenance-rich ``StatFigure`` rows (the same value object ``sdmx.py`` uses,
    so the existing store/read/vintage path carries them unchanged);
  * it is PURE — it takes an already-decoded ``str`` a caller fetched and never imports
    ``requests`` / ``httpx`` / ``socket`` (the networked fetch lives behind the guarded
    factory + kill switch, on the operator list);
  * "supply, never prices" is enforced BY CONSTRUCTION: only a known SUPPLY measure is
    accepted, and a row whose measure OR unit reads like a price is REFUSED — so a
    rare-earth "price" can never leak out of this parser;
  * a published gap (a present cell with no observation) becomes ``value=None`` (degrade
    loudly, never a fabricated 0); ``extracted_at`` is the caller-stamped VINTAGE;
  * NO score, NO ranking, producers never averaged (the Group N honesty contract).

The REAL MCS data release is fetched by the operator (networked); this parser is proven
against a hand-built fixture that mirrors the documented MCS salient-statistics long
shape (see tests/test_usgs_mcs.py — clearly marked as a fixture, never presented as real
data).
"""

from __future__ import annotations

import csv
import io

from src.stats.sdmx import StatFigure, _as_float, _as_str, _clean_opt

# The stable agency code (matches the ``us-usgs`` entry in agencies.py).
AGENCY = "us-usgs"

# The SUPPLY measures MCS publishes that we accept, mapped to a canonical form. A row
# with ANY OTHER measure — notably a price / "unit value" — is REFUSED (never emitted):
# this parser produces supply figures ONLY. The allowlist IS the "never a price" guard.
_SUPPLY_MEASURES: dict[str, str] = {
    "production": "production",
    "mine_production": "mine_production",
    "mine production": "mine_production",
    "reserves": "reserves",
    "net_import_reliance": "net_import_reliance",
    "net import reliance": "net_import_reliance",
    "nir": "net_import_reliance",
    "imports": "imports",
    "exports": "exports",
    "consumption": "consumption",
    "apparent_consumption": "consumption",
    "apparent consumption": "consumption",
}

# Belt-and-braces (the allowlist above already excludes price MEASURES): a supply-measure
# row that carries a CURRENCY unit is a price-contaminated row and is refused too. Only
# unambiguous currency names/symbols — a physical unit ("metric tons REO", "percent",
# "thousand metric tons") never contains these.
_CURRENCY_MARKERS: tuple[str, ...] = ("$", "usd", "eur", "gbp", "dollar", "euro")

MCS_METHODOLOGY_REF = (
    "USGS Mineral Commodity Summaries — annual supply statistics (mine production / "
    "reserves / net-import-reliance). Supply data, NOT market prices."
)

# The documented long/tidy shape (case-insensitive header). commodity_id + area + year +
# measure + value are required; commodity (display), area_code (ISO), unit are optional.
_REQUIRED_COLS: tuple[str, ...] = ("commodity_id", "area", "year", "measure", "value")


def parse_mcs_csv(
    text: str, *, extracted_at: str, delimiter: str = ","
) -> list[StatFigure]:
    """Parse a USGS MCS salient-statistics long CSV into SUPPLY ``StatFigure`` rows.

    Expected columns (case-insensitive)::

        commodity,commodity_id,area,area_code,year,measure,value,unit
        Rare earths,rare-earths,World,WLD,2023,production,350000,metric tons REO
        Rare earths,rare-earths,China,CN,2023,production,240000,metric tons REO
        Rare earths,rare-earths,World,WLD,2023,reserves,110000000,metric tons REO
        Rare earths,rare-earths,United States,US,2023,net_import_reliance,,percent

    ``series_id`` = ``"<commodity_id>:<canonical measure>"`` (e.g. ``"rare-earths:production"``).
    ``ref_area`` = ``area_code`` when present, else ``area`` (as published). A blank value
    cell is a published GAP (``value=None``), kept. A row whose measure is not a known
    SUPPLY measure — a price / unit-value — is REFUSED (never a price). A malformed row (no
    commodity/area/year) is skipped honestly. A REQUIRED column absent from the header raises
    ``ValueError`` (a loud config error, not a silent empty result).
    """
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        return []
    header = [h.lstrip("\ufeff").strip().lower() for h in header]
    idx = {name: i for i, name in enumerate(header)}
    missing = [c for c in _REQUIRED_COLS if c not in idx]
    if missing:
        raise ValueError(f"USGS MCS CSV missing required column(s): {missing}")
    i_cid, i_area, i_year = idx["commodity_id"], idx["area"], idx["year"]
    i_measure, i_value = idx["measure"], idx["value"]
    i_code, i_unit = idx.get("area_code"), idx.get("unit")
    max_i = max(i_cid, i_area, i_year, i_measure, i_value)

    out: list[StatFigure] = []
    for row in reader:
        if len(row) <= max_i:
            continue  # short / blank line — not a published gap, skip honestly
        cid = _as_str(row[i_cid]).lower()
        area = _as_str(row[i_area])
        year = _as_str(row[i_year])
        if not cid or not area or not year:
            continue  # a row without commodity + area + year is not an observation
        measure = _SUPPLY_MEASURES.get(_as_str(row[i_measure]).lower())
        if measure is None:
            continue  # a non-supply measure (price / unit-value) — REFUSED, never a price
        unit = (
            _clean_opt(row[i_unit]) if i_unit is not None and i_unit < len(row) else None
        )
        if unit and any(m in unit.lower() for m in _CURRENCY_MARKERS):
            continue  # a currency/price unit on a supply row — refuse (never a price)
        code = _as_str(row[i_code]) if i_code is not None and i_code < len(row) else ""
        out.append(
            StatFigure(
                agency=AGENCY,
                series_id=f"{cid}:{measure}",
                ref_area=code or area,
                time_period=year,
                value=_as_float(row[i_value]),
                unit=unit,
                methodology_ref=MCS_METHODOLOGY_REF,
                adjustment=None,
                base_year=None,
                extracted_at=extracted_at,
            )
        )
    return out
