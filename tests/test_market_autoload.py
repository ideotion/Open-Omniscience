"""Background auto-load of market feeds is freshness-gated (Slice 1 of the revamp).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The scheduler's markets pass now imports the curated CSV feeds (commodities +
indices) so the board fills itself — but only feeds whose latest stored point is
STALE for their cadence (daily named/commodity > 1 day; monthly OECD index > 25
days), so it never re-fetches an unchanged series every cycle.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

pytest.importorskip("feedparser", reason="the markets pipeline imports the ingest pipeline (feedparser)")

from src.database.models import Base, CommodityPrice
from src.markets import pipeline
from src.markets.feed_catalog import Feed


def _sess():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_import_due_feeds_is_freshness_gated(monkeypatch):
    import src.markets.csv_feeds as cf
    import src.markets.feed_catalog as fc

    s = _sess()
    today = date(2026, 6, 17)
    feeds = [
        Feed(key="f_fresh", name="F", symbol="FRESH", url="u", unit="pts"),  # daily, point today -> fresh
        Feed(key="f_stale", name="S", symbol="STALE", url="u", unit="pts"),  # daily, point 5d ago -> due
        Feed(key="f_new", name="N", symbol="NEW", url="u", unit="pts"),  # no data -> due (first fetch)
        Feed(key="f_oecd", name="O", symbol="OECD", url="u", unit="idx"),  # monthly, 10d ago -> fresh (<25)
    ]
    monkeypatch.setattr(fc, "load_feeds", lambda path=None: feeds)
    monkeypatch.setattr(fc, "load_index_feeds", lambda path=None: [])

    called: list[str] = []

    class _R:
        status = "imported"

    monkeypatch.setattr(cf, "import_feed", lambda session, **kw: (called.append(kw["symbol"]), _R())[1])

    for sym, d in [("FRESH", today), ("STALE", today - timedelta(days=5)), ("OECD", today - timedelta(days=10))]:
        s.add(CommodityPrice(symbol=sym, observed_on=d, price=1.0))
    s.commit()

    tally = pipeline.import_due_feeds(s, fetcher=object(), now=today)
    # only the stale daily feed + the never-seen feed are fetched
    assert set(called) == {"STALE", "NEW"}
    assert tally == {"checked": 4, "imported": 2, "fresh": 2, "failed": 0}
