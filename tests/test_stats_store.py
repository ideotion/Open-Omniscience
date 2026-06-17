"""Durable storage + vintages + honest triangulation for official statistics (Group N).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Asserts the honesty contract of src/stats/store.py against a real in-memory SQLite
DB (no network, no crypto): vintages are additive (a re-fetch is a new row, never an
overwrite), the same vintage is idempotent, published gaps are stored as None and
reported, and triangulation shows producers SIDE BY SIDE — never averaged — flagging
incomparable units / seasonal adjustment / base years.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base
from src.stats import store
from src.stats.sdmx import StatFigure


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


def _fig(agency, series, area, period, value, *, at, unit="USD", adj=None, base=None):
    return StatFigure(
        agency=agency, series_id=series, ref_area=area, time_period=period,
        value=value, unit=unit, methodology_ref=None, adjustment=adj,
        base_year=base, extracted_at=at,
    )


def test_store_is_idempotent_per_vintage_and_reports_gaps(db):
    figs = [
        _fig("worldbank", "NY.GDP.MKTP.CD", "FRA", "2021", 2.9e12, at="2026-06-17T00:00:00Z"),
        _fig("worldbank", "NY.GDP.MKTP.CD", "FRA", "2020", None, at="2026-06-17T00:00:00Z"),  # gap
    ]
    t1 = store.store_figures(db, figs)
    db.commit()
    assert t1 == {"stored": 2, "duplicate": 0, "gaps": 1}  # 2 stored, 0 dup, 1 gap

    # Re-storing the EXACT same vintage is a no-op (idempotent).
    t2 = store.store_figures(db, figs)
    db.commit()
    assert t2["stored"] == 0 and t2["duplicate"] == 2


def test_new_vintage_is_a_new_row_never_an_overwrite(db):
    store.store_figures(db, [_fig("worldbank", "S", "FRA", "2021", 100.0, at="2026-06-17T00:00:00Z")])
    db.commit()
    # A revised figure at a LATER vintage: a new row, both preserved.
    store.store_figures(db, [_fig("worldbank", "S", "FRA", "2021", 105.0, at="2026-06-18T00:00:00Z")])
    db.commit()

    v = store.vintages_for(db, agency="worldbank", series_id="S", ref_area="FRA", time_period="2021")
    assert v["count"] == 2
    assert [x["value"] for x in v["vintages"]] == [100.0, 105.0]  # oldest -> newest

    # The filterable view collapses to the latest vintage by default.
    latest = store.list_figures(db, series_id="S")
    assert latest["count"] == 1 and latest["figures"][0]["value"] == 105.0
    # ...but the full history is available on request.
    allv = store.list_figures(db, series_id="S", latest_vintage_only=False)
    assert allv["count"] == 2


def test_list_figures_filters_and_carries_caveat_no_score(db):
    store.store_figures(db, [
        _fig("worldbank", "S", "FRA", "2021", 1.0, at="2026-06-17T00:00:00Z"),
        _fig("eurostat", "S", "DEU", "2021", 2.0, at="2026-06-17T00:00:00Z"),
    ])
    db.commit()
    only_wb = store.list_figures(db, agency="worldbank")
    assert only_wb["count"] == 1 and only_wb["figures"][0]["ref_area"] == "FRA"
    fra = store.list_figures(db, ref_area="fra")  # case-insensitive area
    assert fra["count"] == 1 and fra["figures"][0]["agency"] == "worldbank"
    # No fabricated score field on any figure (the caveat prose may say "score" in
    # "never a credibility score" — that is honesty, not a data field).
    for f in store.list_figures(db)["figures"]:
        for k in f:
            assert "score" not in k and "rating" not in k and "credibility" not in k


def test_triangulation_shows_producers_side_by_side_never_averaged(db):
    # Two producers report the SAME series_id for FRA 2021 — different values.
    store.store_figures(db, [
        _fig("worldbank", "GDP", "FRA", "2021", 2.90e12, at="2026-06-17T00:00:00Z", unit="USD"),
        _fig("eurostat", "GDP", "FRA", "2021", 2.50e12, at="2026-06-17T00:00:00Z", unit="EUR"),
    ])
    db.commit()
    tri = store.triangulate(db, series_id="GDP", ref_area="FRA", time_period="2021")
    assert tri["count"] == 1
    cell = tri["cells"][0]
    assert cell["n_producers"] == 2
    values = {p["agency"]: p["value"] for p in cell["producers"]}
    assert values == {"worldbank": 2.90e12, "eurostat": 2.50e12}  # both kept, side by side
    # Different units => flagged NOT comparable, with the reason named (never reconciled).
    assert cell["comparability"]["comparable"] is False
    assert "unit" in cell["comparability"]["differs_on"]
    # No average / combined / total key fabricated.
    assert "average" not in str(cell) and "mean" not in cell and "combined" not in cell


def test_triangulation_comparable_when_denominators_match(db):
    store.store_figures(db, [
        _fig("worldbank", "GDP", "FRA", "2021", 2.9e12, at="2026-06-17T00:00:00Z", unit="USD", adj="SA", base="2015"),
        _fig("imf", "GDP", "FRA", "2021", 2.8e12, at="2026-06-17T00:00:00Z", unit="USD", adj="SA", base="2015"),
    ])
    db.commit()
    cell = store.triangulate(db, series_id="GDP")["cells"][0]
    assert cell["comparability"]["comparable"] is True
    assert cell["comparability"]["differs_on"] == []


def test_triangulation_does_not_infer_cross_agency_equivalence(db):
    # Different series_ids are NOT auto-equated (no fabricated mapping).
    store.store_figures(db, [
        _fig("worldbank", "NY.GDP.MKTP.CD", "FRA", "2021", 2.9e12, at="2026-06-17T00:00:00Z"),
        _fig("eurostat", "nama_10_gdp", "FRA", "2021", 2.5e12, at="2026-06-17T00:00:00Z"),
    ])
    db.commit()
    # Triangulating one series_id returns ONLY that series' producer(s).
    tri = store.triangulate(db, series_id="NY.GDP.MKTP.CD")
    assert tri["count"] == 1
    assert tri["cells"][0]["n_producers"] == 1
    assert tri["cells"][0]["producers"][0]["agency"] == "worldbank"
