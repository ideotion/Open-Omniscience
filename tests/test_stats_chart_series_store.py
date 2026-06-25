"""
CI test for ``store.chart_series`` over a real in-memory SQLite DB (Group N).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The chart-feed store-pull: load the stored figures for one (series_id, ref_area), adapt
them to StatFigures, and run the pure ``to_chart_series`` — so the honesty lives in the
shape of the output: a unit / base-year / SA-NSA break starts a NEW segment (never joined),
a published gap is kept as ``None`` (never interpolated), and ``agency`` scopes a single
producer. Needs sqlalchemy (the ORM) so it runs in CI, not the bare sandbox.
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


def _fig(
    period: str,
    value: float | None,
    *,
    agency: str = "worldbank",
    series: str = "NY.GDP.MKTP.CD",
    area: str = "FR",
    unit: str | None = None,
    base: str | None = None,
    adj: str | None = None,
    at: str = "2026-06-25T00:00:00Z",
) -> StatFigure:
    return StatFigure(
        agency=agency,
        series_id=series,
        ref_area=area,
        time_period=period,
        value=value,
        unit=unit,
        methodology_ref=None,
        adjustment=adj,
        base_year=base,
        extracted_at=at,
    )


def test_chart_series_segments_at_a_comparability_break_and_keeps_a_gap(db):
    store.store_figures(
        db,
        [
            _fig("2018", 100.0, unit="Index", base="2010"),
            _fig("2019", 102.0, unit="Index", base="2010"),
            _fig("2020", None, unit="Index", base="2015"),  # a gap AND a base-year break
            _fig("2021", 51.0, unit="Index", base="2015"),
        ],
    )
    out = store.chart_series(db, series_id="NY.GDP.MKTP.CD", ref_area="FR")
    assert out["series_id"] == "NY.GDP.MKTP.CD"
    assert out["ref_area"] == "FR"
    # The 2010=100 run is NEVER joined to the 2015=100 run.
    assert out["n_segments"] == 2
    by_base = {s["base_year"]: s for s in out["segments"]}
    assert set(by_base) == {"2010", "2015"}
    # The published gap is kept as None inside its segment (never dropped / interpolated).
    assert any(p["value"] is None for p in by_base["2015"]["points"])


def test_chart_series_scopes_by_agency(db):
    store.store_figures(db, [_fig("2019", 10.0, agency="worldbank")])
    store.store_figures(db, [_fig("2019", 11.0, agency="eurostat")])
    wb = store.chart_series(db, series_id="NY.GDP.MKTP.CD", ref_area="FR", agency="worldbank")
    assert wb["n_points"] == 1
    assert wb["segments"][0]["points"][0]["value"] == 10.0


def test_chart_series_empty_is_honest(db):
    out = store.chart_series(db, series_id="NOPE", ref_area="FR")
    assert out["segments"] == []
    assert out["n_points"] == 0
    assert "caveat" in out  # the honesty envelope still travels
