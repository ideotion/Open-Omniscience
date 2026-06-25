"""
Offline tests for the bulk statistical parsers (``src/stats/bulk.py``): wide CSV + ZIP.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pure-data tests — a wide CSV (V-Dem / OWID-energy shape) projected to one figure per (row,
indicator), and an in-memory ZIP container (V-Dem / UCDP bulk download shape). They assert
the Group N honesty rules: a blank indicator cell is a published gap (``value=None``, never a
fabricated 0); ``series_id`` is the column name; comparability fields come from the caller's
config or stay ``None``; a missing required column / a ZIP overflow / an ambiguous member
all degrade LOUDLY (``ValueError``), never silently; the vintage is caller-stamped; and NO
figure carries a score. They import only the pure modules, so they run in the bare sandbox
and in CI alike.
"""

from __future__ import annotations

import io
import re
import zipfile

from src.stats.bulk import parse_csv_wide, read_zip_member, zip_csv_members
from src.stats.sdmx import StatFigure

_SCORE_RE = re.compile(r"score|credibility|reliability|quality|trust", re.IGNORECASE)

_WIDE_CSV = (
    "Entity,Code,Year,GDP,Population\n"
    "France,FRA,2019,2700,67.0\n"
    "France,FRA,2020,2600,67.4\n"
    "Germany,DEU,2020,3800,\n"  # blank Population — a published gap
)


def _zip(members: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Wide CSV projection.
# --------------------------------------------------------------------------- #
def test_wide_csv_projects_one_figure_per_indicator() -> None:
    figs = parse_csv_wide(
        _WIDE_CSV,
        agency="vdem",
        extracted_at="2026-06-25T00:00:00Z",
        area_col="Entity",
        code_col="Code",
        time_col="Year",
        indicator_cols=["GDP", "Population"],
        units={"GDP": "billion USD", "Population": "millions"},
    )
    # 3 rows x 2 indicators = 6 figures.
    assert len(figs) == 6
    by = {(f.series_id, f.ref_area, f.time_period): f for f in figs}
    assert by[("GDP", "FRA", "2019")].value == 2700.0
    assert by[("Population", "FRA", "2020")].value == 67.4
    assert by[("GDP", "FRA", "2019")].unit == "billion USD"
    assert by[("Population", "FRA", "2020")].unit == "millions"
    # The blank Population cell is a published gap → None (kept, not zeroed).
    assert by[("Population", "DEU", "2020")].value is None
    # Stable Code preferred over Entity name; vintage caller-stamped.
    assert by[("GDP", "DEU", "2020")].ref_area == "DEU"
    assert all(f.extracted_at == "2026-06-25T00:00:00Z" for f in figs)


def test_wide_csv_unstated_comparability_is_none() -> None:
    figs = parse_csv_wide(
        _WIDE_CSV,
        agency="x",
        extracted_at="V",
        area_col="Entity",
        time_col="Year",
        indicator_cols=["GDP"],
    )
    # No units/base_years/adjustments map → all None (never guessed).
    assert figs
    for f in figs:
        assert f.unit is None
        assert f.base_year is None
        assert f.adjustment is None


def test_wide_csv_missing_indicator_column_raises() -> None:
    raised = False
    try:
        parse_csv_wide(
            _WIDE_CSV,
            agency="x",
            extracted_at="V",
            area_col="Entity",
            time_col="Year",
            indicator_cols=["GDP", "DoesNotExist"],
        )
    except ValueError as exc:
        raised = True
        assert "required" in str(exc).lower()
    assert raised, "a missing required indicator column must raise ValueError"


def test_wide_csv_ragged_row_skips_only_the_missing_cell() -> None:
    # The last row is missing its Population cell (4 columns, not 5).
    csv_text = "Entity,Year,GDP,Population\nA,2020,10,1.0\nB,2021,20\n"
    figs = parse_csv_wide(
        csv_text,
        agency="x",
        extracted_at="V",
        area_col="Entity",
        time_col="Year",
        indicator_cols=["GDP", "Population"],
    )
    by = {(f.series_id, f.ref_area): f.value for f in figs}
    assert by[("GDP", "A")] == 10.0
    assert by[("Population", "A")] == 1.0
    assert by[("GDP", "B")] == 20.0  # GDP cell present
    assert ("Population", "B") not in by  # the missing cell is skipped, not invented


def test_wide_csv_skips_rows_without_area_or_time() -> None:
    csv_text = "Entity,Year,GDP\n,2020,1\nA,,2\nA,2020,3\n"
    figs = parse_csv_wide(
        csv_text, agency="x", extracted_at="V", area_col="Entity", time_col="Year",
        indicator_cols=["GDP"],
    )
    assert len(figs) == 1
    assert (figs[0].ref_area, figs[0].time_period, figs[0].value) == ("A", "2020", 3.0)


def test_wide_csv_code_falls_back_to_entity() -> None:
    csv_text = "Entity,Code,Year,GDP\nKosovo,,2021,9.4\n"
    figs = parse_csv_wide(
        csv_text, agency="x", extracted_at="V", area_col="Entity", code_col="Code",
        time_col="Year", indicator_cols=["GDP"],
    )
    assert len(figs) == 1
    assert figs[0].ref_area == "Kosovo"


# --------------------------------------------------------------------------- #
# ZIP container.
# --------------------------------------------------------------------------- #
def test_zip_csv_members_lists_only_csvs_sorted() -> None:
    data = _zip({"b.csv": "x", "a.csv": "y", "readme.txt": "z", "sub/": ""})
    assert zip_csv_members(data) == ["a.csv", "b.csv"]


def test_read_named_member() -> None:
    data = _zip({"vdem.csv": "Entity,Year,GDP\nA,2020,1\n", "codebook.txt": "notes"})
    text = read_zip_member(data, "vdem.csv")
    assert text.startswith("Entity,Year,GDP")


def test_read_single_member_without_naming_it() -> None:
    data = _zip({"only.csv": "Entity,Year,GDP\nA,2020,1\n", "notes.txt": "x"})
    text = read_zip_member(data)  # exactly one .csv → picked automatically
    assert "A,2020,1" in text


def test_read_ambiguous_member_raises() -> None:
    data = _zip({"a.csv": "x", "b.csv": "y"})
    raised = False
    try:
        read_zip_member(data)  # two .csv members → must not guess
    except ValueError as exc:
        raised = True
        assert ".csv members" in str(exc)
    assert raised


def test_read_unknown_member_raises() -> None:
    data = _zip({"a.csv": "x"})
    raised = False
    try:
        read_zip_member(data, "nope.csv")
    except ValueError:
        raised = True
    assert raised


def test_read_member_over_ceiling_raises() -> None:
    data = _zip({"big.csv": "x" * 100})
    raised = False
    try:
        read_zip_member(data, "big.csv", max_bytes=10)  # 100 bytes > 10-byte ceiling
    except ValueError as exc:
        raised = True
        assert "ceiling" in str(exc)
    assert raised


def test_end_to_end_zip_to_wide_figures() -> None:
    data = _zip({"V-Dem-CY-Full.csv": _WIDE_CSV, "citation.txt": "cite us"})
    text = read_zip_member(data, "V-Dem-CY-Full.csv")
    figs = parse_csv_wide(
        text, agency="vdem", extracted_at="V", area_col="Entity", code_col="Code",
        time_col="Year", indicator_cols=["GDP", "Population"],
    )
    assert len(figs) == 6
    assert all(isinstance(f, StatFigure) for f in figs)


# --------------------------------------------------------------------------- #
# Honesty: no score key anywhere.
# --------------------------------------------------------------------------- #
def test_no_figure_carries_a_score_key() -> None:
    figs = parse_csv_wide(
        _WIDE_CSV, agency="x", extracted_at="V", area_col="Entity", code_col="Code",
        time_col="Year", indicator_cols=["GDP", "Population"],
    )
    assert figs
    for f in figs:
        for key in f.to_dict():
            assert not _SCORE_RE.search(key), f"forbidden score-like key: {key!r}"
