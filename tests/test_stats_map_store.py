"""
CI test for ``store.map_figures`` over a real in-memory SQLite DB (Group N) — the
choropleth feed.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The map data-pull: load the stored figures for one series, keep the latest vintage, and
emit ONE cell per ref_area (the area's latest period, or a pinned period). The honesty
lives in the shape: a published gap is carried as ``None`` (never zero), the comparability
fields ride along (the frontend ``ooViz.choroplethData`` is what shows an incomparable
basis as no-data), and the map is single-producer — several producers flag ``multi_producer``
and are NEVER averaged. Needs sqlalchemy (the ORM) so it runs in CI, not the bare sandbox.
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
    series: str = "SI.POV.GINI",
    area: str = "FR",
    unit: str | None = "%",
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


def _assert_no_score(out: dict) -> None:
    blob = repr(out).lower()
    assert "score" not in blob and "ranking" not in blob, "the map must carry no score/ranking"


def test_map_one_cell_per_area_at_each_area_latest_period(db):
    store.store_figures(
        db,
        [
            _fig("2019", 1.0, area="FR"),
            _fig("2021", 2.5, area="FR"),  # FR's latest period wins
            _fig("2020", 9.0, area="DE"),
        ],
    )
    out = store.map_figures(db, series_id="SI.POV.GINI")
    assert out["count"] == 2
    cells = {c["ref_area"]: c for c in out["cells"]}
    assert cells["FR"]["value"] == 2.5 and cells["FR"]["time_period"] == "2021"
    assert cells["DE"]["value"] == 9.0
    # Sorted by area (deterministic): DE before FR.
    assert [c["ref_area"] for c in out["cells"]] == ["DE", "FR"]
    assert out["periods"] == ["2021", "2020", "2019"]  # newest-first
    _assert_no_score(out)


def test_map_keeps_the_latest_vintage(db):
    store.store_figures(db, [_fig("2021", 50.0, at="2026-01-01T00:00:00Z")])
    store.store_figures(db, [_fig("2021", 52.0, at="2026-06-01T00:00:00Z")])  # a revision
    out = store.map_figures(db, series_id="SI.POV.GINI")
    assert out["count"] == 1
    assert out["cells"][0]["value"] == 52.0  # the newer vintage, not the first one


def test_map_pins_a_specific_period(db):
    store.store_figures(db, [_fig("2019", 1.0, area="FR"), _fig("2021", 2.5, area="FR")])
    out = store.map_figures(db, series_id="SI.POV.GINI", time_period="2019")
    assert out["count"] == 1
    assert out["cells"][0]["value"] == 1.0
    assert out["time_period"] == "2019"


def test_map_flags_multiple_producers_and_an_agency_pins_one(db):
    store.store_figures(db, [_fig("2020", 30.0, area="FR", agency="worldbank")])
    store.store_figures(db, [_fig("2020", 31.0, area="FR", agency="eurostat")])
    out = store.map_figures(db, series_id="SI.POV.GINI")
    assert out["multi_producer"] is True
    assert set(out["agencies"]) == {"worldbank", "eurostat"}
    # Pinning an agency makes it single-producer (never an average of 30 and 31).
    wb = store.map_figures(db, series_id="SI.POV.GINI", agency="worldbank")
    assert wb["multi_producer"] is False
    assert wb["count"] == 1 and wb["cells"][0]["value"] == 30.0


def test_map_carries_a_gap_and_the_comparability_fields(db):
    # FR's latest period is a published gap on a stated basis — carried verbatim.
    store.store_figures(
        db, [_fig("2021", None, area="FR", unit="Index", base="2015", adj="SA")]
    )
    out = store.map_figures(db, series_id="SI.POV.GINI")
    cell = out["cells"][0]
    assert cell["value"] is None  # a gap, never a fabricated zero
    assert cell["unit"] == "Index" and cell["base_year"] == "2015" and cell["adjustment"] == "SA"


def test_map_cells_carry_iso2_for_the_renderer(db):
    # The producer's ref_area (alpha-3 for WB/OWID, alpha-2 for Eurostat, plus aggregates)
    # is bridged to a lowercase alpha-2 iso2 so a map keys on it without a frontend bridge;
    # a non-country aggregate (WLD) → None so the map drops it honestly.
    store.store_figures(
        db,
        [
            _fig("2021", 1.0, area="FRA"),  # alpha-3 → "fr"
            _fig("2021", 2.0, area="DE"),   # alpha-2 passes through → "de"
            _fig("2021", 9.0, area="WLD"),  # World aggregate → None (never mapped)
        ],
    )
    out = store.map_figures(db, series_id="SI.POV.GINI")
    iso = {c["ref_area"]: c["iso2"] for c in out["cells"]}
    assert iso["FRA"] == "fr"
    assert iso["DE"] == "de"
    assert iso["WLD"] is None  # aggregate carries no country iso2 → the map drops it


def test_map_empty_is_honest(db):
    out = store.map_figures(db, series_id="NOPE")
    assert out["cells"] == []
    assert out["count"] == 0
    assert out["multi_producer"] is False
    assert "caveat" in out  # the honesty envelope still travels
