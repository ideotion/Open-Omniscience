"""
Tests for the official-CSV commodity feed importer.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

No network: feeds are served from in-test fixtures through a fake session, so the
parser, dedup and the catalog/API are exercised deterministically. The same code
fetches the real FRED/World Bank CSVs on the user's machine.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, CommodityPrice, Source
from src.ingest import EthicalFetcher
from src.markets.csv_feeds import import_feed, import_points, parse_series_csv
from src.markets.feed_catalog import get_feed, load_feeds

# A FRED-style export: date column first, value second, "." marks a missing day.
_FRED_CSV = "DATE,DCOILWTICO\n2024-01-02,70.38\n2024-01-03,72.70\n2024-01-04,.\n2024-01-05,73.81\n"
# Newer FRED header name + a blank cell.
_FRED_CSV2 = "observation_date,PCOPPUSDM\n2024-01-01,8450.5\n2024-02-01,\n2024-03-01,8600.0\n"


def test_parse_series_csv_fred_skips_missing():
    p = parse_series_csv(_FRED_CSV)
    assert [v for _d, v in p.points] == [70.38, 72.70, 73.81]  # "." skipped, not zero
    assert not p.errors


def test_parse_series_csv_observation_date_header():
    p = parse_series_csv(_FRED_CSV2)
    assert len(p.points) == 2  # blank skipped
    assert p.points[0][1] == pytest.approx(8450.5)


def test_parse_series_csv_named_columns():
    csv = "when,foo,price\n2024-01-01,x,12.5\n2024-01-02,y,13.0\n"
    p = parse_series_csv(csv, date_column="when", value_column="price")
    assert [v for _d, v in p.points] == [12.5, 13.0]


def test_parse_series_csv_unknown_column_errors():
    p = parse_series_csv("a,b\n2024-01-01,1\n", value_column="nope")
    assert not p.points and p.errors


def _db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_import_points_is_idempotent():
    s = _db()
    pts = parse_series_csv(_FRED_CSV).points
    r1 = import_points(s, symbol="WTI", points=pts, unit="barrel", market="EIA")
    assert r1["imported"] == 3
    r2 = import_points(s, symbol="WTI", points=pts, unit="barrel", market="EIA")
    assert r2["imported"] == 0 and r2["skipped_existing"] == 3
    assert s.query(CommodityPrice).filter_by(symbol="WTI").count() == 3
    s.close()


class FakeResponse:
    def __init__(self, status_code=200, text="", content_type="text/csv", url=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}
        self.url = url


class FakeSession:
    def __init__(self):
        self.headers = {}
        self._routes = {}

    def route(self, url, **kw):
        self._routes[url] = FakeResponse(url=url, **kw)

    def get(self, url, timeout=None, allow_redirects=True):
        return self._routes.get(url, FakeResponse(status_code=404, text="nf", url=url))


def _fetcher_serving(url, text):
    sess = FakeSession()
    sess.route("https://fred.stlouisfed.org/robots.txt", status_code=404, text="")
    sess.route(url, text=text)
    return EthicalFetcher(min_interval_s=0.0, session=sess)


def test_import_feed_happy_path():
    s = _db()
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILWTICO"
    res = import_feed(
        s,
        url=url,
        symbol="WTI",
        unit="barrel",
        market="EIA",
        fetcher=_fetcher_serving(url, _FRED_CSV),
    )
    assert res.status == "imported" and res.imported == 3
    assert s.query(CommodityPrice).filter_by(symbol="WTI").count() == 3
    s.close()


def test_import_feed_fetch_failure_is_explicit():
    s = _db()
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=NOPE"
    # robots ok, but the feed URL 404s -> fetch_failed, nothing stored.
    sess = FakeSession()
    sess.route("https://fred.stlouisfed.org/robots.txt", status_code=404, text="")
    res = import_feed(
        s, url=url, symbol="NOPE", fetcher=EthicalFetcher(min_interval_s=0.0, session=sess)
    )
    assert res.status == "fetch_failed"
    assert s.query(CommodityPrice).count() == 0
    s.close()


def test_catalog_loads_and_is_wellformed():
    feeds = load_feeds()
    assert len(feeds) >= 5
    assert all(f.key and f.symbol and f.url.startswith("http") for f in feeds)
    assert get_feed("copper") is not None
    assert get_feed("does-not-exist") is None


def test_catalog_keys_unique():
    keys = [f.key for f in load_feeds()]
    assert len(keys) == len(set(keys))
    _ = Source  # imported for parity with other tests; no row needed here


def test_feeds_api_list_and_import(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import src.api.markets as mk
    from src.database.session import get_db
    from src.markets.feed_catalog import get_feed

    # Isolated on-disk DB via dependency override (shared across the threadpool's
    # connections, unlike :memory:, and never touches the dev DB).
    engine = create_engine(
        f"sqlite:///{tmp_path / 'feeds.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)

    def _db():
        db = Sess()
        try:
            yield db
        finally:
            db.close()

    feed = get_feed("copper")
    # Stub the shared fetcher's transport so the endpoint never touches the network.
    sess = FakeSession()
    sess.route("https://fred.stlouisfed.org/robots.txt", status_code=404, text="")
    sess.route(feed.url, text="DATE,PCOPPUSDM\n2024-01-01,8450.5\n2024-02-01,8600.0\n")
    monkeypatch.setattr(mk._fetcher, "session", sess)

    from src.api.main import app

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            listed = client.get("/api/markets/feeds").json()
            assert any(f["key"] == "copper" for f in listed["feeds"])

            imp = client.post("/api/markets/feeds/copper/import")
            assert imp.status_code == 200, imp.text
            assert imp.json()["imported"] == 2

            # Unknown feed -> explicit 404.
            assert client.post("/api/markets/feeds/nope/import").status_code == 404

            # Imported points are now chartable via the commodity endpoint.
            prices = client.get("/api/commodities/COPPER/prices").json()
            assert prices["count"] == 2
    finally:
        app.dependency_overrides.clear()


def test_import_feed_never_raises_on_non_fetcherror():
    """A raw network error (not FetchError) is reported as a failed feed, never raised —
    otherwise one bad feed 500s the whole import-all batch (regression)."""
    from src.markets.csv_feeds import import_feed

    class _Boom:
        def fetch(self, *a, **k):
            raise RuntimeError("Connection reset by peer")

    res = import_feed(None, url="https://x.test/f.csv", symbol="SP500", fetcher=_Boom())
    assert res.status == "fetch_failed"
    assert "Connection reset" in (res.detail or "")
