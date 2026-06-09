"""World stock-index catalog + the /api/markets/board endpoint.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The Indices board reuses the commodity store/import path but stays a separate,
curated catalog. These tests assert the catalog is well-formed and that the board
returns honest cards: real day-over-day change from stored points, curated entries
shown even before any import (latest=null), and nothing fabricated.
"""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, CommodityPrice
from src.markets.feed_catalog import get_index_feed, load_feeds, load_index_feeds


def test_index_catalog_wellformed_and_disjoint_from_commodities():
    idx = load_index_feeds()
    assert len(idx) >= 6
    assert all(f.key and f.symbol and f.url.startswith("http") for f in idx)
    assert all(f.category == "index" and f.unit == "pts" for f in idx)
    # Keys are unique and do not collide with the commodity catalog.
    idx_keys = {f.key for f in idx}
    assert len(idx_keys) == len(idx)
    assert idx_keys.isdisjoint({f.key for f in load_feeds()})
    assert get_index_feed("idx_sp500") is not None
    assert get_index_feed("nope") is None


def _client(tmp_path):
    import src.api.markets as mk  # noqa: F401  (ensures router import path is exercised)
    from src.api.main import app
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'idx.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    return app, Sess


def test_board_lists_curated_indices_even_before_import(tmp_path):
    app, _ = _client(tmp_path)
    try:
        with TestClient(app) as c:
            body = c.get("/api/markets/board?category=index").json()
        assert body["category"] == "index"
        assert body["count"] >= 6  # whole curated catalog is shown
        assert body["with_data"] == 0  # nothing imported yet -> all latest=null
        sp = next(card for card in body["cards"] if card["symbol"] == "SP500")
        assert sp["latest"] is None and sp["change_pct"] is None and sp["points"] == 0
        assert "real-time" in body["note"].lower()  # honest EOD caveat present
    finally:
        app.dependency_overrides.clear()


def test_board_reports_real_change_from_stored_points(tmp_path):
    app, Sess = _client(tmp_path)
    try:
        with Sess() as s:
            s.add_all(
                [
                    CommodityPrice(
                        symbol="SP500",
                        observed_on=date(2026, 6, 5),
                        price=5000.0,
                        currency="USD",
                        unit="pts",
                        source="test",
                    ),
                    CommodityPrice(
                        symbol="SP500",
                        observed_on=date(2026, 6, 6),
                        price=5100.0,
                        currency="USD",
                        unit="pts",
                        source="test",
                    ),
                ]
            )
            s.commit()
        with TestClient(app) as c:
            body = c.get("/api/markets/board?category=index").json()
        sp = next(card for card in body["cards"] if card["symbol"] == "SP500")
        assert sp["latest"]["price"] == 5100.0
        assert sp["change"] == 100.0
        assert sp["change_pct"] == 2.0  # (5100-5000)/5000 * 100
        assert sp["spark"][-1] == ["2026-06-06", 5100.0]
        assert body["with_data"] >= 1
    finally:
        app.dependency_overrides.clear()
