"""
Offline tests for the CSV (OWID) + JSON-stat statistical parsers (``src/stats/sdmx.py``).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pure-data tests — small inline fixtures shaped like a real Our World in Data grapher CSV
export and a JSON-stat dataset (the Eurostat new API / IRENA / PxWeb shape). They assert
the Group N honesty rules: a published gap (blank CSV cell / ``null`` JSON-stat cell) →
``value=None`` (kept, never a fabricated 0); ``ref_area`` prefers the stable code column;
comparability fields (unit / base year / adjustment) come from the caller or the response —
never guessed; the ``extracted_at`` vintage is recorded verbatim; and NO figure carries a
composite score. These import ONLY the pure parser module (no ORM, no network), so they run
in the bare sandbox and in CI alike.
"""

from __future__ import annotations

import re

from src.stats.sdmx import StatFigure, parse_csv, parse_jsonstat

_SCORE_RE = re.compile(r"score|credibility|reliability|quality|trust", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# CSV (Our World in Data grapher export shape).
# --------------------------------------------------------------------------- #
_OWID_CSV = (
    "Entity,Code,Year,Annual CO2 emissions\n"
    "France,FRA,2020,277.7\n"
    "Germany,DEU,2020,644.3\n"
    "World,OWID_WRL,2020,34807.0\n"
    "France,FRA,2021,\n"  # a published gap — the cell exists but the value is blank
)


def test_csv_owid_grapher_shape() -> None:
    figs = parse_csv(
        _OWID_CSV,
        agency="owid",
        series_id="annual-co2-emissions",
        extracted_at="2026-06-25T12:00:00Z",
        area_col="Entity",
        code_col="Code",
        time_col="Year",
        value_col="Annual CO2 emissions",
        unit="tonnes CO2",
    )
    assert len(figs) == 4
    by = {(f.ref_area, f.time_period): f for f in figs}
    assert by[("FRA", "2020")].value == 277.7
    assert by[("DEU", "2020")].value == 644.3
    # OWID's special "World" aggregate keeps its OWID_WRL code verbatim (never dropped).
    assert by[("OWID_WRL", "2020")].value == 34807.0
    # The blank value cell is a published gap → None, kept (not dropped, not zeroed).
    assert by[("FRA", "2021")].value is None

    fr = by[("FRA", "2020")]
    assert fr.agency == "owid"
    assert fr.series_id == "annual-co2-emissions"
    assert fr.ref_area == "FRA"  # the stable Code is preferred over the Entity name
    assert fr.unit == "tonnes CO2"  # surfaced verbatim from the caller
    assert fr.extracted_at == "2026-06-25T12:00:00Z"
    # The caller stated no base year / adjustment / methodology → None (never guessed).
    assert fr.base_year is None
    assert fr.adjustment is None
    assert fr.methodology_ref is None


def test_csv_falls_back_to_entity_when_code_blank() -> None:
    figs = parse_csv(
        "Entity,Code,Year,GDP\nKosovo,,2021,9.4\n",
        agency="owid",
        series_id="gdp",
        extracted_at="V",
        area_col="Entity",
        code_col="Code",
        time_col="Year",
        value_col="GDP",
    )
    assert len(figs) == 1
    assert figs[0].ref_area == "Kosovo"  # blank Code → the Entity name is the area


def test_csv_without_code_col_uses_entity() -> None:
    figs = parse_csv(
        "country,year,value\nBrazil,2019,211.0\n",
        agency="owid",
        series_id="pop",
        extracted_at="V",
        area_col="country",
        time_col="year",
        value_col="value",
    )
    assert len(figs) == 1
    assert figs[0].ref_area == "Brazil"


def test_csv_value_na_tokens_are_gaps() -> None:
    figs = parse_csv(
        "Entity,Year,V\nA,2020,NA\nB,2020,\nC,2020,:\n",
        agency="x",
        series_id="s",
        extracted_at="V",
        area_col="Entity",
        time_col="Year",
        value_col="V",
    )
    # NA / blank / the SDMX ":" sentinel are all published gaps, never fabricated to 0.
    assert [f.value for f in figs] == [None, None, None]


def test_csv_missing_required_column_raises() -> None:
    # A column the caller named but the header lacks is a loud config error, not silence.
    raised = False
    try:
        parse_csv(
            "Entity,Year\nA,2020\n",
            agency="x",
            series_id="s",
            extracted_at="V",
            area_col="Entity",
            time_col="Year",
            value_col="DoesNotExist",
        )
    except ValueError as exc:
        raised = True
        assert "required" in str(exc).lower()
    assert raised, "a missing required column must raise ValueError"


def test_csv_skips_rows_without_area_or_time() -> None:
    figs = parse_csv(
        "Entity,Year,V\n,2020,1.0\nA,,2.0\nA,2020,3.0\n",
        agency="x",
        series_id="s",
        extracted_at="V",
        area_col="Entity",
        time_col="Year",
        value_col="V",
    )
    # Rows with no area (who) or no period (when) are not observations → skipped honestly.
    assert len(figs) == 1
    assert (figs[0].ref_area, figs[0].time_period, figs[0].value) == ("A", "2020", 3.0)


def test_csv_header_whitespace_and_case_tolerant() -> None:
    # A header with stray spaces / different case still resolves the caller's clean names.
    figs = parse_csv(
        " Entity , Year , Value \nA,2020,1.5\n",
        agency="x",
        series_id="s",
        extracted_at="V",
        area_col="entity",
        time_col="YEAR",
        value_col="value",
    )
    assert len(figs) == 1
    assert figs[0].value == 1.5


# --------------------------------------------------------------------------- #
# JSON-stat v2 dataset.
# --------------------------------------------------------------------------- #
def _jsonstat_geo_time() -> dict:
    """2 geo x 3 time, DENSE value array with one published gap (null)."""
    return {
        "version": "2.0",
        "class": "dataset",
        "id": ["geo", "time"],
        "size": [2, 3],
        "dimension": {
            "geo": {
                "category": {
                    "index": {"FR": 0, "DE": 1},
                    "label": {"FR": "France", "DE": "Germany"},
                }
            },
            "time": {"category": {"index": {"2019": 0, "2020": 1, "2021": 2}}},
        },
        # row-major: FR-2019, FR-2020, FR-2021, DE-2019, DE-2020(gap), DE-2021
        "value": [10.0, 11.0, 12.0, 20.0, None, 22.0],
    }


def test_jsonstat_dense_geo_time_with_gap() -> None:
    figs = parse_jsonstat(
        _jsonstat_geo_time(), agency="eurostat", extracted_at="2026-06-25T12:00:00Z",
        series_id="nrg",
    )
    assert len(figs) == 6
    by = {(f.ref_area, f.time_period): f for f in figs}
    assert set(by) == {
        ("FR", "2019"), ("FR", "2020"), ("FR", "2021"),
        ("DE", "2019"), ("DE", "2020"), ("DE", "2021"),
    }
    assert by[("FR", "2019")].value == 10.0
    assert by[("DE", "2021")].value == 22.0
    # The null cell is a published gap → None (kept, not dropped, not zeroed).
    assert by[("DE", "2020")].value is None
    assert all(f.series_id == "nrg" for f in figs)  # caller-supplied series id
    assert all(f.extracted_at == "2026-06-25T12:00:00Z" for f in figs)


def test_jsonstat_sparse_value_object() -> None:
    payload = _jsonstat_geo_time()
    # Only three present cells; absent keys are genuinely no observation (not a gap).
    payload["value"] = {"0": 10.0, "5": 22.0, "4": None}
    figs = parse_jsonstat(payload, agency="eurostat", extracted_at="V", series_id="nrg")
    by = {(f.ref_area, f.time_period): f for f in figs}
    assert set(by) == {("FR", "2019"), ("DE", "2021"), ("DE", "2020")}
    assert by[("FR", "2019")].value == 10.0
    assert by[("DE", "2021")].value == 22.0
    assert by[("DE", "2020")].value is None  # a present key with a null value → kept as None


def test_jsonstat_unit_label_and_base_year() -> None:
    payload = {
        "class": "dataset",
        "id": ["geo", "time", "unit"],
        "size": [1, 1, 1],
        "dimension": {
            "geo": {"category": {"index": {"FR": 0}, "label": {"FR": "France"}}},
            "time": {"category": {"index": {"2023": 0}}},
            "unit": {"category": {"index": {"I15": 0}, "label": {"I15": "Index, 2015=100"}}},
        },
        "value": [104.2],
    }
    figs = parse_jsonstat(payload, agency="eurostat", extracted_at="V")
    assert len(figs) == 1
    f = figs[0]
    assert f.ref_area == "FR"
    assert f.time_period == "2023"
    assert f.value == 104.2
    assert f.unit == "Index, 2015=100"  # the dimension LABEL (then id)
    assert f.base_year == "2015"  # literally stated in the unit label
    # No caller series id and no indicator dim → series_id is "" (never invented).
    assert f.series_id == ""


def test_jsonstat_indicator_dim_supplies_series_id() -> None:
    payload = {
        "class": "dataset",
        "id": ["geo", "indicator", "time"],
        "size": [1, 1, 1],
        "dimension": {
            "geo": {"category": {"index": {"BR": 0}}},
            "indicator": {
                "category": {
                    "index": {"SP.POP.TOTL": 0},
                    "label": {"SP.POP.TOTL": "Population, total"},
                }
            },
            "time": {"category": {"index": {"2019": 0}}},
        },
        "value": [211049527.0],
    }
    figs = parse_jsonstat(payload, agency="x", extracted_at="V")
    assert len(figs) == 1
    assert figs[0].series_id == "SP.POP.TOTL"  # resolved from the indicator dimension
    assert figs[0].ref_area == "BR"


def test_jsonstat_v1_wrapper_and_index_as_list() -> None:
    # JSON-stat v1: a {"dataset": {...}} wrapper, dimension.id/size, and category.index
    # given as an ORDERED LIST (both forms must parse).
    payload = {
        "dataset": {
            "dimension": {
                "id": ["geo", "time"],
                "size": [2, 1],
                "geo": {"category": {"index": ["FR", "DE"]}},
                "time": {"category": {"index": {"2020": 0}}},
            },
            "value": [1.1, 2.2],
        }
    }
    figs = parse_jsonstat(payload, agency="x", extracted_at="V", series_id="s")
    assert {f.ref_area: f.value for f in figs} == {"FR": 1.1, "DE": 2.2}


def test_jsonstat_malformed_returns_empty() -> None:
    assert parse_jsonstat("not a dict", agency="x", extracted_at="V") == []
    assert parse_jsonstat({"class": "dataset"}, agency="x", extracted_at="V") == []
    # ``size`` disagrees with the category count → bail honestly (no half-parsed rows).
    bad = {
        "class": "dataset",
        "id": ["geo"],
        "size": [3],
        "dimension": {"geo": {"category": {"index": {"FR": 0}}}},
        "value": [1.0],
    }
    assert parse_jsonstat(bad, agency="x", extracted_at="V") == []


# --------------------------------------------------------------------------- #
# Honesty: no composite score on ANY figure; the vintage is caller-stamped.
# --------------------------------------------------------------------------- #
def test_no_figure_carries_a_score_key() -> None:
    figs = parse_csv(
        _OWID_CSV,
        agency="owid",
        series_id="s",
        extracted_at="V",
        area_col="Entity",
        code_col="Code",
        time_col="Year",
        value_col="Annual CO2 emissions",
    ) + parse_jsonstat(_jsonstat_geo_time(), agency="eurostat", extracted_at="V")
    assert figs  # sanity: we actually produced figures to check
    for f in figs:
        for key in f.to_dict():
            assert not _SCORE_RE.search(key), f"forbidden score-like key: {key!r}"


def test_vintage_is_caller_stamped_per_parse() -> None:
    v1 = parse_jsonstat(_jsonstat_geo_time(), agency="e", extracted_at="2026-01-01T00:00:00Z")
    v2 = parse_jsonstat(_jsonstat_geo_time(), agency="e", extracted_at="2026-06-25T12:00:00Z")
    assert all(f.extracted_at == "2026-01-01T00:00:00Z" for f in v1)
    assert all(f.extracted_at == "2026-06-25T12:00:00Z" for f in v2)
    # Same payload, two vintages — the observed values themselves are identical.
    assert [f.value for f in v1] == [f.value for f in v2]


def test_parsers_always_return_typed_statfigures() -> None:
    out = parse_csv(
        "Entity,Year,V\nA,2020,1\n",
        agency="x",
        series_id="s",
        extracted_at="V",
        area_col="Entity",
        time_col="Year",
        value_col="V",
    )
    assert out
    assert all(isinstance(f, StatFigure) for f in out)
