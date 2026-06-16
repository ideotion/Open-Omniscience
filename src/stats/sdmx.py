"""
Offline parsers for official machine-readable statistics (Group N, official-statistics
ingestion — the parser core).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

This module turns already-decoded JSON responses from official statistical endpoints —
the World Bank API v2 JSON shape and the SDMX-JSON 2.1 "data message" shape used by
Eurostat / IMF — into provenance-rich :class:`StatFigure` rows. It is PURE: it takes
``dict`` / ``list`` objects a caller has already fetched and decoded and never imports
``requests`` / ``httpx`` / ``socket`` — it MUST NOT touch the network (the ingestion
layer that fetches lives elsewhere, behind the guarded factory + kill switch).

HONESTY (the Group N ruling, enforced here in code, not just prose):
  * a figure carries its PROVENANCE trail — producing/subject ``ref_area`` + ``agency``
    + ``series_id`` + the period exactly as published, plus comparability fields
    (``adjustment`` SA/NSA, ``base_year``, ``unit``) WHEN the response exposes them and
    ``None`` otherwise (never guessed);
  * VINTAGES are caller-stamped: ``extracted_at`` is recorded verbatim and never
    overwritten, so re-parsing the same payload at a later time yields a new vintage;
  * a published gap (a cell that exists but has no observation) becomes ``value=None`` —
    we degrade LOUDLY and never fabricate a 0, and never silently drop a present cell;
  * NO composite trust/quality/credibility/importance score, NO ranking, and producers
    are NEVER averaged — only the observed values + their trail.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StatFigure:
    """One observed value from an official statistical response, with its trail.

    A figure is a single (series, area, period) observation. It carries no score and no
    verdict — only the published value and the provenance needed to compare it honestly.
    """

    agency: str  # stable agency code matching agencies.py (e.g. "worldbank", "eurostat")
    series_id: str  # indicator / dataset series id (e.g. "NY.GDP.MKTP.CD")
    ref_area: str  # producing / subject area ISO code as published (e.g. "FR", "FRA", "EA19")
    time_period: str  # the period label exactly as published ("2021", "2021-Q3", "2021-03")
    value: float | None  # the observed value; None for a published gap (degrade loudly)
    unit: str | None  # unit / measure if the response states it, else None
    # provenance (the ruling): never a score, always the trail
    methodology_ref: str | None  # a URL/notes ref if the response carries one, else None
    adjustment: str | None  # seasonal-adjustment flag if present: "SA"/"NSA"/raw code, else None
    base_year: str | None  # index base period if present, else None
    extracted_at: str  # ISO-8601 UTC timestamp passed in by the caller (the VINTAGE marker)

    def to_dict(self) -> dict:
        # Plain dict — provenance only. NO *_score / rating / verdict field, ever.
        return {
            "agency": self.agency,
            "series_id": self.series_id,
            "ref_area": self.ref_area,
            "time_period": self.time_period,
            "value": self.value,
            "unit": self.unit,
            "methodology_ref": self.methodology_ref,
            "adjustment": self.adjustment,
            "base_year": self.base_year,
            "extracted_at": self.extracted_at,
        }


# --------------------------------------------------------------------------- #
# World Bank API v2 JSON
# --------------------------------------------------------------------------- #
def parse_worldbank(payload: Any, *, agency: str, extracted_at: str) -> list[StatFigure]:
    """Parse a World Bank API v2 JSON response into figures.

    The shape is a 2-element list ``[page_meta, [observations]]``. Each observation is a
    dict like::

        {"indicator": {"id": "NY.GDP.MKTP.CD", "value": "GDP (current US$)"},
         "country":   {"id": "FR", "value": "France"},
         "countryiso3code": "FRA", "date": "2021",
         "value": 2957000000000.0, "unit": "", "obs_status": ""}

    ``ref_area`` prefers ``countryiso3code`` then ``country.id``; ``series_id`` is
    ``indicator.id``; ``time_period`` is ``date``. A present cell with ``value: null``
    becomes ``value=None`` (a published gap, never dropped). methodology_ref / base_year
    / adjustment are usually absent in this shape → ``None``.
    """
    figures: list[StatFigure] = []
    observations = _worldbank_observations(payload)
    for obs in observations:
        if not isinstance(obs, dict):
            # Structurally absent / malformed row — not a published gap, skip honestly.
            continue
        indicator = obs.get("indicator") or {}
        country = obs.get("country") or {}
        series_id = _as_str(indicator.get("id")) if isinstance(indicator, dict) else ""
        iso3 = _as_str(obs.get("countryiso3code"))
        ref_area = iso3 or (_as_str(country.get("id")) if isinstance(country, dict) else "")
        time_period = _as_str(obs.get("date"))
        figures.append(
            StatFigure(
                agency=agency,
                series_id=series_id,
                ref_area=ref_area,
                time_period=time_period,
                value=_as_float(obs.get("value")),
                unit=_clean_opt(obs.get("unit")),
                methodology_ref=None,
                adjustment=None,
                base_year=None,
                extracted_at=extracted_at,
            )
        )
    return figures


def _worldbank_observations(payload: Any) -> list[Any]:
    """The observation list from a ``[page_meta, [observations]]`` payload.

    Defensive: a bare list of observations (no page-meta wrapper) is also accepted.
    """
    if isinstance(payload, list):
        if len(payload) == 2 and isinstance(payload[1], list):
            return payload[1]
        # A bare list of observation dicts.
        if payload and isinstance(payload[0], dict) and "indicator" in payload[0]:
            return payload
    return []


# --------------------------------------------------------------------------- #
# SDMX-JSON 2.1 "data message" (Eurostat / IMF)
# --------------------------------------------------------------------------- #
# Dimension ids that name the same concept across producers. Lower-cased on lookup.
_REF_AREA_DIMS = ("ref_area", "geo", "reporting_area", "area", "country")
_SERIES_DIMS = ("indicator", "na_item", "series", "subject", "measure", "transaction",
                "indicator_id")
_UNIT_DIMS = ("unit", "unit_measure", "measure_unit")
_ADJ_DIMS = ("adjustment", "s_adj", "seasonal_adjustment")
_TIME_DIMS = ("time_period", "time", "time_period_start")


def parse_sdmx_json(payload: Any, *, agency: str, extracted_at: str) -> list[StatFigure]:
    """Parse an SDMX-JSON 2.1 "data message" into figures.

    Shape (the parts we use)::

        {"data": {
            "structure": {"dimensions": {
                "series":      [{"id": "geo", "values": [{"id": "FR", ...}, ...]}, ...],
                "observation": [{"id": "TIME_PERIOD", "values": [{"id": "2021"}, ...]}]},
                "attributes": {...optional...}},
            "dataSets": [{"series": {
                "0:0": {"observations": {"0": [2957000000000.0], "1": [3010000000000.0]}},
                ...}}]}}

    A series key ``"0:0"`` indexes into the SERIES dimension ``values`` lists positionally;
    an observation key ``"1"`` indexes into the single OBSERVATION (time) dimension. We map
    each (series, observation) pair back to its dimension VALUE ids:

      * ``ref_area``  ← the REF_AREA / geo series dimension value id
      * ``series_id`` ← the indicator / na_item series dimension value id
      * ``time_period`` ← the TIME_PERIOD observation dimension value id
      * ``unit``       ← a UNIT series/observation dimension value, else None
      * ``adjustment`` ← an ADJUSTMENT / s_adj dimension value, else None

    Missing dimensions leave their field ``None`` (never guessed). A present observation
    cell whose value is null becomes ``value=None`` (a published gap, kept).
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return []

    structure = data.get("structure") or {}
    dims = structure.get("dimensions") if isinstance(structure, dict) else None
    dims = dims or {}
    series_dims = _dim_list(dims.get("series"))
    obs_dims = _dim_list(dims.get("observation"))

    datasets = data.get("dataSets") or data.get("dataSet") or []
    if isinstance(datasets, dict):
        datasets = [datasets]
    if not isinstance(datasets, list):
        return []

    figures: list[StatFigure] = []
    for dataset in datasets:
        if not isinstance(dataset, dict):
            continue
        series_map = dataset.get("series") or {}
        if not isinstance(series_map, dict):
            continue
        for series_key, series_body in series_map.items():
            if not isinstance(series_body, dict):
                continue
            series_idx = _parse_index_key(series_key)
            resolved = _resolve_dims(series_dims, series_idx)  # {dim_id_lower: (id, name)}

            ref_area = _pick_value_id(resolved, _REF_AREA_DIMS)
            series_id = _pick_value_id(resolved, _SERIES_DIMS)
            unit = _pick_value_label(resolved, _UNIT_DIMS)
            adjustment = _pick_value_id(resolved, _ADJ_DIMS)
            base_year = _base_year_from(resolved, _UNIT_DIMS)

            observations = series_body.get("observations") or {}
            if not isinstance(observations, dict):
                continue
            for obs_key, obs_cell in observations.items():
                obs_idx = _parse_index_key(obs_key)
                obs_resolved = _resolve_dims(obs_dims, obs_idx)
                time_period = _pick_value_id(obs_resolved, _TIME_DIMS)
                # An observation-level UNIT/ADJUSTMENT can override the series one.
                unit_o = _pick_value_label(obs_resolved, _UNIT_DIMS)
                adj_o = _pick_value_id(obs_resolved, _ADJ_DIMS)
                figures.append(
                    StatFigure(
                        agency=agency,
                        series_id=series_id or "",
                        ref_area=ref_area or "",
                        time_period=time_period or "",
                        value=_obs_value(obs_cell),
                        unit=unit_o or unit,
                        methodology_ref=None,
                        adjustment=adj_o or adjustment,
                        base_year=base_year,
                        extracted_at=extracted_at,
                    )
                )
    return figures


# --------------------------------------------------------------------------- #
# SDMX helpers — resolve a positional index path to dimension value ids/labels.
# --------------------------------------------------------------------------- #
def _dim_list(raw: Any) -> list[dict]:
    """A list of dimension definition dicts, defensively."""
    if isinstance(raw, list):
        return [d for d in raw if isinstance(d, dict)]
    return []


def _parse_index_key(key: Any) -> list[int]:
    """Split an SDMX key like ``"0:1:2"`` into ``[0, 1, 2]``. Tolerant of junk."""
    out: list[int] = []
    for part in str(key).split(":"):
        part = part.strip()
        if part == "":
            continue
        try:
            out.append(int(part))
        except ValueError:
            out.append(-1)  # unresolvable position; keeps alignment, resolves to None
    return out


def _resolve_dims(
    dim_defs: list[dict], index_path: list[int]
) -> dict[str, tuple[str | None, str | None]]:
    """Map each dimension (by lower-cased id) to the (value_id, value_name) selected by
    the corresponding position in ``index_path``. Out-of-range / unresolvable → (None, None).
    """
    resolved: dict[str, tuple[str | None, str | None]] = {}
    for pos, dim in enumerate(dim_defs):
        dim_id = _as_str(dim.get("id")).lower()
        if not dim_id:
            continue
        values = dim.get("values")
        values = values if isinstance(values, list) else []
        idx = index_path[pos] if pos < len(index_path) else -1
        if 0 <= idx < len(values) and isinstance(values[idx], dict):
            v = values[idx]
            resolved[dim_id] = (_clean_opt(v.get("id")), _clean_opt(v.get("name")))
        else:
            resolved[dim_id] = (None, None)
    return resolved


def _pick_value_id(
    resolved: dict[str, tuple[str | None, str | None]], candidates: tuple[str, ...]
) -> str | None:
    """The value *id* of the first matching dimension (by candidate id), else None."""
    for cand in candidates:
        if cand in resolved:
            return resolved[cand][0]
    return None


def _pick_value_label(
    resolved: dict[str, tuple[str | None, str | None]], candidates: tuple[str, ...]
) -> str | None:
    """The value *name* (falling back to id) of the first matching dimension, else None."""
    for cand in candidates:
        if cand in resolved:
            vid, name = resolved[cand]
            return name or vid
    return None


def _base_year_from(
    resolved: dict[str, tuple[str | None, str | None]], candidates: tuple[str, ...]
) -> str | None:
    """A best-effort index base period, surfaced ONLY when a unit/measure label literally
    states one (e.g. "Index, 2015=100"). Never guessed — None when not stated."""
    for cand in candidates:
        if cand in resolved:
            label = resolved[cand][1] or ""
            base = _extract_base_year(label)
            if base:
                return base
    return None


def _extract_base_year(label: str) -> str | None:
    """Extract a "YYYY=100" base period from a free-text unit label if literally present."""
    text = label or ""
    marker = "=100"
    pos = text.find(marker)
    if pos == -1:
        return None
    # Walk back over the digits/range immediately before "=100".
    end = pos
    start = pos
    while start > 0 and (text[start - 1].isdigit() or text[start - 1] in "-/"):
        start -= 1
    token = text[start:end].strip(" -/")
    return token or None


# --------------------------------------------------------------------------- #
# Small value coercions (shared).
# --------------------------------------------------------------------------- #
def _obs_value(cell: Any) -> float | None:
    """The numeric value from an SDMX observation cell (``[value, ...attrs]``) or a bare
    scalar. A present-but-null observation → None (a published gap, kept)."""
    if isinstance(cell, list):
        return _as_float(cell[0]) if cell else None
    return _as_float(cell)


def _as_float(v: Any) -> float | None:
    """Coerce to float, or None for a published gap / unparseable value. Never fabricate."""
    if v is None:
        return None
    if isinstance(v, bool):  # guard: bools are ints in Python, never a statistic
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if s == "" or s.lower() in {"na", "nan", "null", ":"}:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _as_str(v: Any) -> str:
    """A trimmed string, or "" for None — for required-shape fields."""
    if v is None:
        return ""
    return str(v).strip()


def _clean_opt(v: Any) -> str | None:
    """A trimmed string, or None for an empty / missing optional field."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None
