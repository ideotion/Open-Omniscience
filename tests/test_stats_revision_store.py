"""
CI test for ``store.revision_anomalies`` over a real in-memory SQLite DB (Group N).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Stores several VINTAGES of one observation (a re-fetch at a later ``extracted_at`` is a new
row — revisions preserved) and asserts the store-pull feeds the pure, model-free
``find_revision_anomalies`` correctly: an outlier-sized latest revision is flagged, the
filters scope it, and an empty / calm corpus stays silent. Needs sqlalchemy (the ORM) so it
runs in CI, not the bare sandbox.
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


def _vintage(
    value: float | None,
    at: str,
    *,
    agency: str = "eurostat",
    series: str = "NY.GDP.MKTP.CD",
    area: str = "FR",
    period: str = "2019",
) -> StatFigure:
    return StatFigure(
        agency=agency,
        series_id=series,
        ref_area=area,
        time_period=period,
        value=value,
        unit=None,
        methodology_ref=None,
        adjustment=None,
        base_year=None,
        extracted_at=at,
    )


# A long trail of tiny revisions, then one big one (the months order the vintages).
_OUTLIER_TRAIL = [(1, 100.0), (2, 100.1), (3, 99.9), (4, 100.2), (5, 100.0), (6, 110.0)]


def _trail(values, **kw):
    return [_vintage(v, f"2026-{m:02d}-01T00:00:00Z", **kw) for m, v in values]


def test_revision_anomalies_flags_a_stored_outlier(db):
    store.store_figures(db, _trail(_OUTLIER_TRAIL))
    out = store.revision_anomalies(db)
    assert out["count"] == 1
    a = out["anomalies"][0]
    assert (a["from_value"], a["to_value"], a["abs_change"]) == (100.0, 110.0, 10.0)
    assert a["revised_at"] == "2026-06-01T00:00:00Z"  # the revising vintage
    assert a["robust_z"] > 3.5


def test_revision_anomalies_scope_by_series(db):
    store.store_figures(db, _trail(_OUTLIER_TRAIL))  # NY.GDP.MKTP.CD — anomalous
    store.store_figures(
        db,
        _trail([(1, 50.0), (2, 50.1), (3, 49.9), (4, 50.2), (5, 50.0), (6, 50.1)], series="OTHER"),
    )  # calm
    assert store.revision_anomalies(db, series_id="NY.GDP.MKTP.CD")["count"] == 1
    assert store.revision_anomalies(db, series_id="OTHER")["count"] == 0
    # Across the whole store, only the anomalous series is flagged.
    whole = store.revision_anomalies(db)
    assert whole["count"] == 1
    assert whole["anomalies"][0]["series_id"] == "NY.GDP.MKTP.CD"


def test_revision_anomalies_empty_store_is_silent(db):
    out = store.revision_anomalies(db)
    assert out["count"] == 0
    assert out["anomalies"] == []
    assert "Retrospective only" in out["method"]  # the honesty contract travels
