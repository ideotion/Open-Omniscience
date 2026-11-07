"""
Offline parser for the Our World in Data CO2 and Energy bulk CSVs (the wide-CSV shape).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The third keyless climate row of the 0.6 plan (A1 / S06-04 S2). OWID publishes two wide CSVs,
``owid-co2-data.csv`` and ``owid-energy-data.csv`` (one row per country-or-aggregate and year,
many indicator columns). This module projects a CURATED subset of those columns into
:class:`~src.stats.sdmx.StatFigure` rows, using the same coercion helpers as ``bulk.py``.

PURE: an already-decoded ``str`` in, figures out; no network, no clock. The fetch lives behind
the guarded factory in ``src.stats.fetch.fetch_owid_dataset``.

**The column names, units and the CSV shape below are written from OWID's published codebook
and are NOT verified against a live download** (this sandbox cannot reach the host). The
parser therefore reports exactly which curated columns it found and which it did not, and
refuses a file it does not recognise.

HONESTY PROPERTIES, each a refusal rather than a caveat:

* **Only curated columns are emitted, with their units from the catalog**, never inferred from
  the data. A curated column that is absent from the header is reported in
  ``columns_missing`` (OWID renames and retires columns), and a file with the required
  ``country`` / ``year`` columns missing, or with none of the curated columns, is
  ``looks_unrecognised``.
* **A blank or ``NA`` cell is a gap (``value=None``), never 0.** Anything else that is not a
  finite decimal is refused and counted (the row is not emitted).
* **Aggregates are not countries.** A row without an ISO code (``World``, ``Africa (GCP)``,
  ``High-income countries`` ...) keeps its published NAME as ``ref_area`` (even when OWID gives it an OWID_ pseudo-code) and is tagged in
  ``aggregate_areas``; it is never given a country code, and a consumer must not sum
  countries and aggregates together (they overlap).
* **Per-column terms differ.** OWID's processed data is CC BY 4.0, but the columns come from
  different original producers (Global Carbon Project, Energy Institute, Ember, ...); the
  methodology text names the origin and says the per-column terms are an operator check.
* **Refusals are counted exactly and kept as a SAMPLE** (the first ``MAX_REFUSALS_KEPT``).
* Vintages: ``extracted_at`` is caller-stamped verbatim; OWID revises history every release.
"""

from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass, field

from src.stats.sdmx import StatFigure

#: When the curated catalog below was last written down (NOT a live verification).
OWID_CLIMATE_AS_OF = "2026-11"

AGENCY = "owid"

#: dataset id -> (path under the OWID repo, curated columns). ``unit`` strings are the codebook's.
CATALOG: dict[str, dict[str, object]] = {
    "co2": {
        "file": "owid-co2-data.csv",
        "origin": "Global Carbon Project, Jones et al., Our World in Data (CO2 and Greenhouse Gas Emissions)",
        "columns": {
            "co2": "Mt CO2",
            "co2_per_capita": "t CO2 per person",
            "cumulative_co2": "Mt CO2",
            "share_global_co2": "% of world",
            "methane": "Mt CO2e",
            "nitrous_oxide": "Mt CO2e",
            "total_ghg": "Mt CO2e",
            "temperature_change_from_co2": "degC",
        },
    },
    "energy": {
        "file": "owid-energy-data.csv",
        "origin": "Energy Institute, Ember, Our World in Data (Energy)",
        "columns": {
            "primary_energy_consumption": "TWh",
            "fossil_share_energy": "% of primary energy",
            "renewables_share_energy": "% of primary energy",
            "low_carbon_share_energy": "% of primary energy",
            "electricity_generation": "TWh",
            "renewables_share_elec": "% of electricity",
            "carbon_intensity_elec": "gCO2e per kWh",
        },
    },
}

MAX_REFUSALS_KEPT = 100
_YEAR = re.compile(r"^[0-9]{4}$")
_NUMBER = re.compile(r"^[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]{1,3})?$")
_GAP = frozenset({"", "na", "n/a", "nan", "null"})
_MIN_YEAR, _MAX_YEAR = 1700, 2200


def methodology_for(dataset: str) -> str:
    entry = CATALOG[dataset]
    return (
        f"Our World in Data, {entry['file']} (CC BY 4.0 for OWID's processing); column origin: "
        f"{entry['origin']}. Per-column terms of the original producers are an operator check. "
        "https://github.com/owid"
    )


@dataclass
class OwidParse:
    """Figures plus everything the parse refused or did not find."""

    dataset: str = ""
    figures: list[StatFigure] = field(default_factory=list)
    rows_read: int = 0
    columns_present: list[str] = field(default_factory=list)
    columns_missing: list[str] = field(default_factory=list)
    aggregate_areas: set[str] = field(default_factory=set)
    refused: list[dict[str, str]] = field(default_factory=list)
    refused_total: int = 0
    # Physical lines the refused records covered: a stray quote can make one refusal swallow
    # many lines, and refused_total alone would read as one bad row.
    refused_lines: int = 0
    header_ok: bool = False

    @property
    def refused_is_sample(self) -> bool:
        return self.refused_total > len(self.refused)

    @property
    def all_gap(self) -> bool:
        return bool(self.figures) and all(f.value is None for f in self.figures)

    @property
    def looks_unrecognised(self) -> bool:
        """No usable table: required columns missing, none of the curated columns, or no rows."""
        return (not self.header_ok) or (not self.columns_present) or self.rows_read == 0

    def summary(self) -> dict[str, object]:
        return {
            "dataset": self.dataset,
            "rows_read": self.rows_read,
            "figures": len(self.figures),
            "columns_present": list(self.columns_present),
            "columns_missing": list(self.columns_missing),
            "aggregate_areas": sorted(self.aggregate_areas),
            "all_gap": self.all_gap,
            "refused_total": self.refused_total,
            "refused_lines": self.refused_lines,
            "refused_sample": list(self.refused),
            "refused_is_sample": self.refused_is_sample,
        }


def _refuse(out: OwidParse, line: int, reason: str, text: str = "", span: int = 1) -> None:
    out.refused_total += 1
    out.refused_lines += max(span, 1)
    if span > 1:
        reason = f"{reason} (the record spans {span} physical lines: a stray quote can swallow following rows)"
    if len(out.refused) < MAX_REFUSALS_KEPT:
        out.refused.append({"line": str(line), "reason": reason, "text": text[:80]})


def _is_aggregate(iso: str) -> bool:
    """No ISO code, or an OWID_ pseudo-code (OWID_WRL ...), is an aggregate; Kosovo's OWID_KOS is a country."""
    return not iso or (iso.startswith("OWID_") and iso != "OWID_KOS")


def _value(raw: str) -> tuple[float | None, bool]:
    text = raw.strip()
    if text.lower() in _GAP:
        return None, True
    if not _NUMBER.match(text):
        return None, False
    v = float(text)
    return (v, True) if math.isfinite(v) else (None, False)


def parse_owid(text: str, *, dataset: str, extracted_at: str) -> OwidParse:
    """Parse one OWID wide CSV into vintaged :class:`StatFigure` rows."""
    if dataset not in CATALOG:
        raise ValueError(f"not a curated OWID dataset: {dataset!r} (expected one of {sorted(CATALOG)})")
    units: dict[str, str] = CATALOG[dataset]["columns"]  # type: ignore[assignment]
    out = OwidParse(dataset=dataset)
    reader = csv.reader(io.StringIO(text))
    try:
        header = [h.lstrip("﻿").strip() for h in next(reader)]
    except StopIteration:
        return out
    idx = {name: i for i, name in reversed(list(enumerate(header)))}  # first occurrence wins
    if "country" not in idx or "year" not in idx or "iso_code" not in idx:
        # iso_code is required: without it every country would read as an aggregate.
        _refuse(out, 1, "required column country/year/iso_code missing", ",".join(header)[:80])
        return out
    duplicated = sorted({n for n in header if header.count(n) > 1 and (n in units or n in ("country", "year", "iso_code"))})
    if duplicated:
        _refuse(out, 1, f"duplicate header column(s) {duplicated}: which value is meant is not guessed", ",".join(header)[:80])
        return out
    out.header_ok = True
    present = [c for c in units if c in idx]
    out.columns_present = present
    out.columns_missing = [c for c in units if c not in idx]
    i_country, i_year, i_iso = idx["country"], idx["year"], idx["iso_code"]
    methodology = methodology_for(dataset)
    seen: set[tuple[str, str]] = set()
    prev_line = reader.line_num
    while True:
        try:
            row = next(reader)
        except StopIteration:
            break
        except csv.Error:  # e.g. one field over the csv module's size limit; the reader moves on
            _refuse(out, reader.line_num, "unreadable CSV record (csv.Error)", span=reader.line_num - prev_line)
            prev_line = reader.line_num
            continue
        lineno = reader.line_num  # the physical line the record ends on (quoted newlines count)
        span = lineno - prev_line
        prev_line = lineno
        if not row or not any(c.strip() for c in row):
            continue
        if len(row) != len(header):
            _refuse(out, lineno, f"expected {len(header)} fields", ",".join(row), span=span)
            continue
        country, year_raw = row[i_country].strip(), row[i_year].strip()
        if not country or not _YEAR.match(year_raw) or not (_MIN_YEAR <= int(year_raw) <= _MAX_YEAR):
            _refuse(out, lineno, "no country or year not a four-digit year", ",".join(row))
            continue
        iso = row[i_iso].strip()
        aggregate = _is_aggregate(iso)
        area = country if aggregate else iso  # an aggregate keeps its published NAME, never its pseudo-code
        if (area, year_raw) in seen:
            _refuse(out, lineno, "duplicate area and year", f"{area},{year_raw}")
            continue
        cells = [_value(row[idx[c]]) for c in present]
        if not all(ok for _, ok in cells):
            _refuse(out, lineno, "non-numeric value", ",".join(row))
            continue
        seen.add((area, year_raw))
        out.rows_read += 1
        if aggregate:
            out.aggregate_areas.add(area)
        for col, (val, _) in zip(present, cells, strict=True):
            out.figures.append(
                StatFigure(
                    agency=AGENCY,
                    series_id=f"{dataset}.{col}",
                    ref_area=area,
                    time_period=year_raw,
                    value=val,
                    unit=units[col],
                    methodology_ref=methodology,
                    adjustment=None,
                    base_year=None,
                    extracted_at=extracted_at,
                )
            )
    return out
