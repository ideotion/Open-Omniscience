"""
Bulk official-statistics parsers (Group N, Phase E): wide CSV projection + ZIP container.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Handles the shapes the single-cell parsers in ``sdmx.py`` do not:

  * a WIDE CSV — one row per area+period, MANY indicator columns — projected to one
    :class:`~src.stats.sdmx.StatFigure` per (row, indicator). This is V-Dem's hundreds of
    variables and OWID's `owid-energy-data.csv` shape; ``series_id`` is the column name.
  * a ZIP archive whose member is one of those CSVs (the V-Dem / UCDP bulk downloads).

PURE: it takes the ``bytes`` / ``str`` a caller has already fetched (no network, no current
time) and inherits the sdmx honesty rules — a blank / NA cell is a published gap
(``value=None``, never a fabricated 0), comparability fields are surfaced only when the
caller's curated config states them (never inferred), the vintage ``extracted_at`` is
caller-stamped verbatim, and NO figure carries a composite score. (Reuses the sdmx
coercions / column resolver — internal helpers shared within the ``src.stats`` package.)
"""

from __future__ import annotations

import csv
import io
import zipfile

from src.stats.sdmx import StatFigure, _as_float, _as_str, _resolve_columns

# A decompression ceiling so a ZIP bomb degrades LOUDLY (the fetch layer bounds the
# download; this bounds the *decompressed* member). The caller may raise/lower it.
_DEFAULT_MAX_BYTES = 1_073_741_824  # 1 GiB


def parse_csv_wide(
    text: str,
    *,
    agency: str,
    extracted_at: str,
    area_col: str,
    time_col: str,
    indicator_cols: list[str],
    code_col: str | None = None,
    units: dict[str, str] | None = None,
    base_years: dict[str, str] | None = None,
    adjustments: dict[str, str] | None = None,
    methodology_ref: str | None = None,
    delimiter: str = ",",
) -> list[StatFigure]:
    """Project a WIDE CSV (one row per area+period, MANY indicator columns) into figures.

    Each named indicator column becomes its own series whose ``series_id`` is the column
    name; one figure is emitted per (row, indicator). A blank / ``NA`` cell in an indicator
    column is a published gap (``value=None``, kept, never fabricated to 0). The optional
    per-indicator comparability maps (``units`` / ``base_years`` / ``adjustments``, keyed by
    column name) come from the caller's curated config — surfaced verbatim, ``None`` when
    unstated, never inferred from the data.

    Single-pass over the rows: V-Dem has hundreds of indicator columns over thousands of
    rows, so calling the single-column parser once per indicator would re-read the file N
    times. A required column (``area``, ``time``, or any named indicator) absent from the
    header raises ``ValueError`` (a loud config error); a row missing the area or period is
    skipped honestly (a malformed row is not a published gap).
    """
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        return []
    header = [h.lstrip("\ufeff") for h in header]

    base = _resolve_columns(
        header, required={"area": area_col, "time": time_col}, optional={"code": code_col}
    )
    # Resolve every indicator column (clean per-column error messages); column name == role.
    ind = _resolve_columns(header, required={c: c for c in indicator_cols}, optional={})

    i_area, i_time = base["area"], base["time"]
    i_code = base.get("code")
    ind_index = [(c, ind[c]) for c in indicator_cols]
    units = units or {}
    base_years = base_years or {}
    adjustments = adjustments or {}

    figures: list[StatFigure] = []
    for row in reader:
        if i_area >= len(row) or i_time >= len(row):
            continue  # short / blank line — not a published gap
        area = _as_str(row[i_area])
        time_period = _as_str(row[i_time])
        if not area or not time_period:
            continue  # a row without a who + when is not an observation
        ref_area = ""
        if i_code is not None and i_code < len(row):
            ref_area = _as_str(row[i_code])
        ref_area = ref_area or area
        for col, idx in ind_index:
            if idx >= len(row):
                continue  # ragged row missing THIS indicator's cell — skip just that cell
            figures.append(
                StatFigure(
                    agency=agency,
                    series_id=col,
                    ref_area=ref_area,
                    time_period=time_period,
                    value=_as_float(row[idx]),
                    unit=units.get(col),
                    methodology_ref=methodology_ref,
                    adjustment=adjustments.get(col),
                    base_year=base_years.get(col),
                    extracted_at=extracted_at,
                )
            )
    return figures


def zip_csv_members(data: bytes) -> list[str]:
    """The ``.csv`` member names in a ZIP archive (bytes already fetched), sorted."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return sorted(
            n for n in zf.namelist() if n.lower().endswith(".csv") and not n.endswith("/")
        )


def read_zip_member(
    data: bytes,
    member: str | None = None,
    *,
    encoding: str = "utf-8",
    max_bytes: int = _DEFAULT_MAX_BYTES,
) -> str:
    """Decode one CSV member of a ZIP (bytes already fetched) to text.

    ``member`` selects the entry by name; ``None`` picks the SINGLE ``.csv`` member and
    raises if the archive has zero or several (the caller chooses explicitly — never a
    silent guess). An unknown member name raises. Decompression is bounded by ``max_bytes``
    and raises if the member exceeds it — a ZIP bomb degrades LOUDLY, never a silent
    truncation. Only ``max_bytes`` of the member is ever decompressed into memory.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        if member is None:
            candidates = [
                n for n in zf.namelist() if n.lower().endswith(".csv") and not n.endswith("/")
            ]
            if len(candidates) != 1:
                raise ValueError(
                    f"ZIP has {len(candidates)} .csv members; name one explicitly: {candidates!r}"
                )
            member = candidates[0]
        elif member not in zf.namelist():
            raise ValueError(f"ZIP has no member {member!r}; members: {zf.namelist()!r}")
        with zf.open(member) as fh:
            raw = fh.read(max_bytes + 1)  # one byte past the ceiling proves an overflow
    if len(raw) > max_bytes:
        raise ValueError(
            f"ZIP member {member!r} exceeds the {max_bytes}-byte decompression ceiling"
        )
    return raw.decode(encoding, errors="replace")
