"""
S5.1 — USGS Mineral Commodity Summaries SUPPLY parser (rare-earths ruling B12).

Proves the parser against a HAND-BUILT FIXTURE that mirrors the documented MCS
salient-statistics long shape. The fixture is NOT real USGS data (the real fetch is a
networked operator step) — it exists only to exercise the parser + its honesty guards.
The load-bearing guard is "supply, NEVER prices": a price / unit-value / currency-unit
row must be REFUSED (the negative-space discipline, #590).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base
from src.stats import store
from src.stats.usgs import AGENCY, _is_price_text, parse_mcs_csv

# --- HAND-BUILT FIXTURE (mirrors the USGS MCS salient-statistics long CSV) ----------- #
# NOT real data. Exercises: three supply measures, a published GAP (blank value), GROUPED
# THOUSANDS ("350,000" quoted — must PARSE, not fabricate a gap), a Europium supply row
# whose unit contains "euro" as a substring (must SURVIVE — the word-boundary guard), a
# PRICE measure + a unit-value measure + a currency-unit supply row + a €-symbol unit + a
# currency-in-the-VALUE-cell row (all must be REFUSED), and a malformed row (no area/year).
_FIXTURE = '''commodity,commodity_id,area,area_code,year,measure,value,unit
Rare earths,rare-earths,World,WLD,2023,production,"350,000",metric tons REO
Rare earths,rare-earths,China,CN,2023,production,240000,metric tons REO
Rare earths,rare-earths,United States,US,2023,production,43000,metric tons REO
Rare earths,rare-earths,World,WLD,2023,reserves,"110,000,000",metric tons REO
Rare earths,rare-earths,United States,US,2023,net_import_reliance,,percent
Europium,europium,China,CN,2023,production,340,metric tons Europium oxide
Rare earths,rare-earths,United States,US,2023,price,180,USD per kg
Rare earths,rare-earths,World,WLD,2023,unit value,95,dollars/kg
Lithium,lithium,World,WLD,2023,production,180000,metric tons Li content
Lithium,lithium,World,WLD,2023,production,999,USD/ton
Nickel,nickel,World,WLD,2023,production,3600000,€/t
Cobalt,cobalt,World,WLD,2023,production,180 USD,metric tons
Rare earths,rare-earths,,,2023,production,1,metric tons REO
'''


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()


def _figs(text=_FIXTURE, at="2026-07-12T00:00:00+00:00"):
    return parse_mcs_csv(text, extracted_at=at)


def test_parses_supply_measures_with_full_provenance():
    figs = _figs()
    by = {(f.series_id, f.ref_area) for f in figs}
    assert ("rare-earths:production", "CN") in by
    assert ("rare-earths:reserves", "WLD") in by
    assert ("rare-earths:net_import_reliance", "US") in by
    prod_cn = next(
        f for f in figs if f.series_id == "rare-earths:production" and f.ref_area == "CN"
    )
    assert prod_cn.agency == AGENCY == "us-usgs"
    assert prod_cn.value == 240000.0
    assert prod_cn.unit == "metric tons REO"
    assert prod_cn.time_period == "2023"
    assert "supply" in (prod_cn.methodology_ref or "").lower()
    assert prod_cn.adjustment is None and prod_cn.base_year is None


def test_vintage_is_recorded_verbatim():
    figs = _figs(at="2027-01-01T12:00:00+00:00")
    assert figs and all(f.extracted_at == "2027-01-01T12:00:00+00:00" for f in figs)


def test_published_gap_is_none_never_zero():
    figs = _figs()
    nir = next(f for f in figs if f.series_id == "rare-earths:net_import_reliance")
    assert nir.value is None  # a blank cell is a GAP, never fabricated to 0
    assert nir.unit == "percent"


# --- negative space (#590): should-be-EMPTY / should-be-REFUSED ---------------------- #
def test_a_price_measure_is_refused_never_a_price():
    figs = _figs()
    # "supply, never prices" by construction: no figure carries a price measure/series.
    assert all("price" not in f.series_id for f in figs)
    assert not [f for f in figs if f.series_id == "rare-earths:price"]


def test_a_unit_value_measure_is_refused():
    figs = _figs()
    assert not [f for f in figs if "unit" in f.series_id and "value" in f.series_id]


def test_a_supply_row_with_a_currency_unit_is_refused():
    # Lithium production with a "USD/ton" unit = a price-contaminated supply row → refused,
    # while the legitimate "metric tons Li content" lithium production row survives.
    figs = _figs()
    li = [f for f in figs if f.series_id == "lithium:production"]
    assert len(li) == 1 and li[0].unit == "metric tons Li content"
    assert all("usd" not in (f.unit or "").lower() and "$" not in (f.unit or "") for f in figs)


def test_no_figure_carries_a_price_unit_at_all():
    # the REAL guard (_is_price_text, word-boundary) — NOT a naive substring, so a legit
    # "metric tons Europium oxide" unit (contains "euro") is correctly not a price.
    figs = _figs()
    for f in figs:
        assert not _is_price_text(f.unit or ""), f"a price unit leaked: {f.unit!r}"


def test_grouped_thousands_parse_never_a_fabricated_gap():
    # "350,000" and "110,000,000" (quoted thousands) are REAL figures, not gaps (#5 skeptic).
    figs = _figs()
    prod_world = next(
        f for f in figs if f.series_id == "rare-earths:production" and f.ref_area == "WLD"
    )
    assert prod_world.value == 350000.0
    reserves = next(f for f in figs if f.series_id == "rare-earths:reserves")
    assert reserves.value == 110000000.0


def test_europium_supply_survives_the_currency_substring_guard():
    # "euro"/"eur" are substrings of "Europium" — the word-boundary guard must NOT drop it.
    figs = _figs()
    eu = [f for f in figs if f.series_id == "europium:production"]
    assert len(eu) == 1 and eu[0].value == 340.0
    assert "europium" in (eu[0].unit or "").lower()


def test_euro_symbol_and_currency_value_rows_are_refused():
    # nickel unit "€/t" (symbol) and cobalt value "180 USD" (currency IN the value cell) —
    # both refused, never emitted even as a gap (#1/#2/#7 skeptic).
    figs = _figs()
    assert not [f for f in figs if f.series_id == "nickel:production"]
    assert not [f for f in figs if f.series_id == "cobalt:production"]


def test_duplicate_read_column_raises_loudly():
    # two 'value' columns would silently last-wins (a price col shadowing a physical one).
    dupe = (
        "commodity_id,area,year,measure,value,unit,value\n"
        "rare-earths,World,2023,production,350000,metric tons,999\n"
    )
    with pytest.raises(ValueError):
        parse_mcs_csv(dupe, extracted_at="t")


def test_malformed_row_without_area_or_year_is_skipped():
    figs = _figs()
    # the trailing fixture row has empty area/area_code → not an observation
    assert all(f.ref_area for f in figs)


def test_empty_and_header_only_yield_nothing():
    assert parse_mcs_csv("", extracted_at="t") == []
    assert parse_mcs_csv("commodity,commodity_id,area,area_code,year,measure,value,unit\n", extracted_at="t") == []


def test_missing_required_column_raises_loudly():
    with pytest.raises(ValueError):
        parse_mcs_csv("commodity_id,area,year,value\nrare-earths,World,2023,1\n", extracted_at="t")


# --- store round-trip + the honest empty state --------------------------------------- #
def test_store_and_group_by_commodity_and_measure(db):
    # empty first: available:false + a reason pointing at the operator fetch
    empty = store.minerals_supply_summary(db)
    assert empty["available"] is False and "operator" in empty["reason"].lower()
    assert "not market prices" in empty["caveat"].lower()

    tally = store.store_figures(db, _figs())
    db.commit()
    assert tally["stored"] > 0 and tally["gaps"] == 1  # the NIR gap counted, not hidden

    summ = store.minerals_supply_summary(db)
    assert summ["available"] is True and summ["reason"] is None
    names = {c["commodity"] for c in summ["commodities"]}
    assert {"rare-earths", "lithium"} <= names
    ree = next(c for c in summ["commodities"] if c["commodity"] == "rare-earths")
    assert set(ree["measures"]) == {"production", "reserves", "net_import_reliance"}
    # no price/currency anywhere in the grouped surface
    import json

    assert "usd" not in json.dumps(summ).lower() and "price" in summ["caveat"].lower()
