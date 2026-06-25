"""
Offline parsers for official machine-readable statistics (Group N, official-statistics
ingestion — the parser core).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

This module turns already-decoded responses from official statistical endpoints into
provenance-rich :class:`StatFigure` rows. Four shapes are understood today: the World Bank
API v2 JSON shape, the SDMX-JSON 2.1 "data message" shape (Eurostat / IMF), a tidy (long)
CSV — e.g. an Our World in Data grapher export — and JSON-stat (the Eurostat new API,
IRENA, and many national PxWeb endpoints). It is PURE: it takes ``str`` / ``dict`` /
``list`` objects a caller has already fetched and decoded and never imports ``requests`` /
``httpx`` / ``socket`` — it MUST NOT touch the network (the ingestion layer that fetches
lives elsewhere, behind the guarded factory + kill switch).

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

import csv
import io
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


# --------------------------------------------------------------------------- #
# Tidy / long CSV (Our World in Data grapher exports, and any column-mapped CSV).
# --------------------------------------------------------------------------- #
def parse_csv(
    text: str,
    *,
    agency: str,
    series_id: str,
    extracted_at: str,
    area_col: str,
    time_col: str,
    value_col: str,
    code_col: str | None = None,
    unit: str | None = None,
    base_year: str | None = None,
    adjustment: str | None = None,
    methodology_ref: str | None = None,
    delimiter: str = ",",
) -> list[StatFigure]:
    """Parse a tidy (long) CSV — e.g. an Our World in Data grapher export — into figures.

    OWID's per-chart "Full data (CSV)" download is the canonical tidy shape::

        Entity,Code,Year,Annual CO2 emissions
        France,FRA,2020,277.7
        Germany,DEU,2020,644.3
        World,OWID_WRL,2020,34807.0

    A CSV carries no self-describing dimension metadata, so the caller maps the columns
    explicitly and the parser NEVER guesses which column is which:

      * ``area_col``  — the geographic entity column (``"Entity"`` / ``"country"`` / …);
      * ``code_col``  — an OPTIONAL stable code column (``"Code"`` / ``"iso_code"``),
        preferred for ``ref_area`` when present and non-empty, else ``area_col``;
      * ``time_col``  — the period column (``"Year"`` / …), kept verbatim as published;
      * ``value_col`` — the single observation column (call once per indicator for a WIDE
        dataset). A blank / ``NA`` cell becomes ``value=None`` — a published gap, kept and
        never fabricated to 0;
      * ``series_id`` + the comparability fields (``unit`` / ``base_year`` / ``adjustment``
        / ``methodology_ref``) come from the CALLER's curated config — surfaced verbatim,
        ``None`` when the caller does not state them, never inferred from the data.

    A REQUIRED column the header does not carry raises ``ValueError`` (a loud config error,
    not a silent empty result). A row missing the area or period is skipped honestly (a
    malformed row is not a published gap). The vintage ``extracted_at`` is recorded verbatim.
    """
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        return []
    # Strip a UTF-8 BOM from the header, then resolve each configured column name to its
    # index (exact, then whitespace-trimmed, then case-insensitive — the only normalisations).
    header = [h.lstrip("\ufeff") for h in header]
    cols = _resolve_columns(
        header,
        required={"area": area_col, "time": time_col, "value": value_col},
        optional={"code": code_col},
    )
    i_area, i_time, i_value = cols["area"], cols["time"], cols["value"]
    i_code = cols.get("code")
    need = max(i_area, i_time, i_value)

    figures: list[StatFigure] = []
    for row in reader:
        if len(row) <= need:
            continue  # short / blank line — not a published gap, skip honestly
        area = _as_str(row[i_area])
        time_period = _as_str(row[i_time])
        if not area or not time_period:
            continue  # a row without a who + when is not an observation
        ref_area = ""
        if i_code is not None and i_code < len(row):
            ref_area = _as_str(row[i_code])
        figures.append(
            StatFigure(
                agency=agency,
                series_id=series_id,
                ref_area=ref_area or area,
                time_period=time_period,
                value=_as_float(row[i_value]),
                unit=unit,
                methodology_ref=methodology_ref,
                adjustment=adjustment,
                base_year=base_year,
                extracted_at=extracted_at,
            )
        )
    return figures


def _resolve_columns(
    header: list[str],
    *,
    required: dict[str, str],
    optional: dict[str, str | None],
) -> dict[str, int]:
    """Resolve configured column NAMES to indices in ``header``.

    Matching is exact, then whitespace-trimmed, then case-insensitive — header whitespace
    and case are the ONLY normalisations (the parser never fuzzy-matches a different
    column). A required name absent from the header raises ``ValueError``; an optional name
    absent is simply omitted. First occurrence wins for a duplicated header label.
    """
    exact: dict[str, int] = {}
    trimmed: dict[str, int] = {}
    folded: dict[str, int] = {}
    for idx, name in enumerate(header):
        exact.setdefault(name, idx)
        trimmed.setdefault(name.strip(), idx)
        folded.setdefault(name.strip().casefold(), idx)

    def _find(name: str) -> int | None:
        if name in exact:
            return exact[name]
        key = name.strip()
        if key in trimmed:
            return trimmed[key]
        return folded.get(key.casefold())

    out: dict[str, int] = {}
    for role, name in required.items():
        found = _find(name)
        if found is None:
            raise ValueError(
                f"CSV is missing the required {role} column {name!r}; header is {header!r}"
            )
        out[role] = found
    for role, opt_name in optional.items():
        if opt_name is None:
            continue
        found = _find(opt_name)
        if found is not None:
            out[role] = found
    return out


# --------------------------------------------------------------------------- #
# JSON-stat (v2 ``class:"dataset"``; the Eurostat new API, IRENA, national PxWeb).
# --------------------------------------------------------------------------- #
def parse_jsonstat(
    payload: Any, *, agency: str, extracted_at: str, series_id: str | None = None
) -> list[StatFigure]:
    """Parse a JSON-stat dataset (v2 ``class:"dataset"`` or the v1 ``{"dataset": {...}}``
    wrapper) into figures.

    JSON-stat encodes an N-dimensional cube as a flat ``value`` array (or a sparse object)
    indexed row-major over ``size``, with each dimension's categories in ``dimension``::

        {"class": "dataset",
         "id":   ["geo", "time"],
         "size": [2, 3],
         "dimension": {
            "geo":  {"category": {"index": {"FR": 0, "DE": 1},
                                  "label": {"FR": "France", "DE": "Germany"}}},
            "time": {"category": {"index": {"2019": 0, "2020": 1, "2021": 2}}}},
         "value": [10, 11, 12, 20, null, 22]}

    Each cell is decomposed back to its per-dimension category id and surfaced:

      * ``ref_area``    ← a geo-like dimension's category id (``geo`` / ``ref_area`` / …);
      * ``time_period`` ← a time-like dimension's category id;
      * ``series_id``   ← the caller's ``series_id`` if given, else an indicator-like
        dimension's category id, else ``""``;
      * ``unit``        ← a unit-like dimension's label (then id), else ``None``;
      * ``adjustment``  ← an adjustment-like dimension's category id, else ``None``;
      * ``base_year``   ← parsed from a unit label that literally states ``"YYYY=100"``,
        else ``None`` (never guessed).

    A DENSE ``value`` array keeps a ``null`` cell as ``value=None`` (a published gap). A
    SPARSE ``value`` object emits ONLY its present keys (an absent key is genuinely no
    cell), again keeping an explicit ``null`` as ``None``. Dimensions the parser does not
    recognise still constrain which cell we are at but map to no field — so request a
    single-series slice for unambiguous rows (the same contract as the SDMX parser).
    """
    ds = _jsonstat_dataset(payload)
    if ds is None:
        return []

    dim_ids = _as_str_list(ds.get("id")) or _as_str_list(_get(ds, "dimension", "id"))
    size = _as_int_list(ds.get("size")) or _as_int_list(_get(ds, "dimension", "size"))
    dimension = ds.get("dimension")
    if not dim_ids or len(dim_ids) != len(size) or not isinstance(dimension, dict):
        return []

    cat_ids: list[list[str]] = []
    cat_labels: list[dict[str, str]] = []
    for d in dim_ids:
        ids, labels = _jsonstat_categories(dimension.get(d))
        cat_ids.append(ids)
        cat_labels.append(labels)
    # A dimension whose category count disagrees with ``size`` is malformed → bail honestly.
    if any(len(ids) != n for ids, n in zip(cat_ids, size, strict=True)):
        return []

    total = 1
    for n in size:
        total *= n

    lower_ids = [d.lower() for d in dim_ids]
    p_area = _first_dim_pos(lower_ids, _REF_AREA_DIMS)
    p_time = _first_dim_pos(lower_ids, _TIME_DIMS)
    p_series = _first_dim_pos(lower_ids, _SERIES_DIMS)
    p_unit = _first_dim_pos(lower_ids, _UNIT_DIMS)
    p_adj = _first_dim_pos(lower_ids, _ADJ_DIMS)

    figures: list[StatFigure] = []
    for flat, raw in _jsonstat_cells(ds.get("value"), total):
        coords = _decompose_index(flat, size)
        if coords is None:
            continue
        unit_label = _jsonstat_cat_label(cat_ids, cat_labels, coords, p_unit)
        figures.append(
            StatFigure(
                agency=agency,
                series_id=(
                    series_id
                    if series_id is not None
                    else (_jsonstat_cat_id(cat_ids, coords, p_series) or "")
                ),
                ref_area=_jsonstat_cat_id(cat_ids, coords, p_area) or "",
                time_period=_jsonstat_cat_id(cat_ids, coords, p_time) or "",
                value=_as_float(raw),
                unit=unit_label,
                methodology_ref=None,
                adjustment=_jsonstat_cat_id(cat_ids, coords, p_adj),
                base_year=_extract_base_year(unit_label) if unit_label else None,
                extracted_at=extracted_at,
            )
        )
    return figures


def _jsonstat_dataset(payload: Any) -> dict | None:
    """The single JSON-stat dataset object from a v2 top-level dataset or a v1
    ``{"dataset": {...}}`` wrapper. A JSON-stat 'collection' (many datasets) is not handled
    here — request one dataset — so it returns ``None``."""
    if not isinstance(payload, dict):
        return None
    if payload.get("class") == "dataset" or ("dimension" in payload and "value" in payload):
        return payload
    inner = payload.get("dataset")
    return inner if isinstance(inner, dict) else None


def _jsonstat_categories(dim: Any) -> tuple[list[str], dict[str, str]]:
    """The ordered category ids (by index position) + the ``{id: label}`` map for one
    JSON-stat dimension. ``category.index`` may be a ``{id: pos}`` map OR an ordered
    ``[id, ...]`` list; ``category.label`` is an optional ``{id: label}`` map."""
    category = dim.get("category") if isinstance(dim, dict) else None
    if not isinstance(category, dict):
        return [], {}
    index = category.get("index")
    ids: list[str] = []
    if isinstance(index, dict):
        pairs: list[tuple[int, str]] = []
        for cid, pos in index.items():
            try:
                pairs.append((int(pos), str(cid)))
            except (TypeError, ValueError):
                continue
        pairs.sort(key=lambda t: t[0])
        ids = [cid for _, cid in pairs]
    elif isinstance(index, list):
        ids = [str(c) for c in index]
    else:
        # A single-category dimension may omit ``index`` — fall back to the label keys.
        labels_only = category.get("label")
        if isinstance(labels_only, dict):
            ids = [str(k) for k in labels_only]
    labels: dict[str, str] = {}
    raw_labels = category.get("label")
    if isinstance(raw_labels, dict):
        for cid, lab in raw_labels.items():
            labels[str(cid)] = str(lab)
    return ids, labels


def _jsonstat_cells(value: Any, total: int) -> list[tuple[int, Any]]:
    """``(flat_index, raw_value)`` pairs from a JSON-stat ``value``.

    A LIST is dense — every position ``0..len-1`` is a present cell (``null`` kept as a
    gap). A DICT is sparse — only its keys are present cells. Indices outside
    ``0..total-1`` are dropped (defensive)."""
    cells: list[tuple[int, Any]] = []
    if isinstance(value, list):
        cells = [(i, v) for i, v in enumerate(value) if i < total]
    elif isinstance(value, dict):
        for k, v in value.items():
            try:
                i = int(k)
            except (TypeError, ValueError):
                continue
            if 0 <= i < total:
                cells.append((i, v))
    return cells


def _decompose_index(flat: int, size: list[int]) -> list[int] | None:
    """Decompose a row-major flat index into per-dimension positions (the LAST dimension
    varies fastest). ``None`` if any dimension size is non-positive (malformed)."""
    coords = [0] * len(size)
    rem = flat
    for pos in range(len(size) - 1, -1, -1):
        n = size[pos]
        if n <= 0:
            return None
        coords[pos] = rem % n
        rem //= n
    return coords


def _first_dim_pos(lower_ids: list[str], candidates: tuple[str, ...]) -> int | None:
    """The position of the first dimension whose lower-cased id is in ``candidates``."""
    for cand in candidates:
        if cand in lower_ids:
            return lower_ids.index(cand)
    return None


def _jsonstat_cat_id(
    cat_ids: list[list[str]], coords: list[int], pos: int | None
) -> str | None:
    """The category id selected at dimension position ``pos`` for this cell, or ``None``."""
    if pos is None:
        return None
    return cat_ids[pos][coords[pos]]


def _jsonstat_cat_label(
    cat_ids: list[list[str]],
    cat_labels: list[dict[str, str]],
    coords: list[int],
    pos: int | None,
) -> str | None:
    """The category label (then id) at dimension position ``pos`` for this cell, else ``None``."""
    if pos is None:
        return None
    cid = cat_ids[pos][coords[pos]]
    return cat_labels[pos].get(cid) or cid


def _as_str_list(v: Any) -> list[str]:
    """A list of strings, or ``[]`` for a non-list."""
    return [str(x) for x in v] if isinstance(v, list) else []


def _as_int_list(v: Any) -> list[int]:
    """A list of ints, or ``[]`` if not a list or any element is non-integer."""
    if not isinstance(v, list):
        return []
    out: list[int] = []
    for x in v:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            return []
    return out


def _get(d: Any, *path: str) -> Any:
    """Nested ``dict`` get — ``_get(d, "dimension", "id")`` — ``None`` if any step is absent
    or not a dict."""
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur
