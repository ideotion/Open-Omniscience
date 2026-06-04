"""
Tests for the commodity vertical (Action Plan Phase 3).

Covers:
  * unit conversion correctness (regression for the ~1000x oz/kg bug, P1-9);
  * REAL correlation statistics (coefficient + p-value from scipy), including the
    "no fabricated p-value" property and explicit insufficient-data handling;
  * the API: import prices, list (with unit normalization), correlate with news.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from scipy import stats
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.commodity.correlation import correlate_price_with_news
from src.commodity.units import UnitError, convert_price
from src.database.fts import ensure_fts
from src.database.models import Article, Base, Source
from src.database.session import get_db

# --------------------------------------------------------------------------- #
# units
# --------------------------------------------------------------------------- #

def test_convert_price_per_gram_to_per_kg():
    # A kilogram costs 1000x a gram -- NOT value/35.274 (the old bug).
    assert convert_price(100.0, "g", "kg") == pytest.approx(100_000.0)


def test_convert_price_kg_to_tonne_and_back():
    assert convert_price(50.0, "kg", "t") == pytest.approx(50_000.0)
    assert convert_price(50_000.0, "t", "kg") == pytest.approx(50.0)


def test_convert_price_troy_ounce():
    # 1 kg = 1 / 0.0311034768 troy oz; $/ozt -> $/kg multiplies accordingly.
    assert convert_price(1.0, "ozt", "kg") == pytest.approx(1 / 0.0311034768)


def test_convert_price_unknown_unit():
    with pytest.raises(UnitError):
        convert_price(1.0, "furlong", "kg")


# --------------------------------------------------------------------------- #
# correlation -- real statistics, no fabrication
# --------------------------------------------------------------------------- #

def test_correlation_matches_scipy_and_pvalue_is_real():
    # Imperfectly correlated so the p-value is a non-trivial real number.
    prices = [
        (date(2026, 1, 1), 100.0),
        (date(2026, 1, 2), 101.0),  # change +1
        (date(2026, 1, 3), 103.0),  # change +2
        (date(2026, 1, 4), 106.0),  # change +3
        (date(2026, 1, 5), 110.0),  # change +4
    ]
    # counts on change-dates Jan 2..5: 1, 3, 2, 5 (not a perfect line)
    article_dates = (
        [date(2026, 1, 2)] * 1 + [date(2026, 1, 3)] * 3 +
        [date(2026, 1, 4)] * 2 + [date(2026, 1, 5)] * 5
    )
    res = correlate_price_with_news(prices, article_dates, method="pearson")
    assert res.n == 4
    # The definitive proof the stat is real: it matches an independent scipy call
    # on the same aligned series exactly (the old code used p = 1 - coefficient).
    coef, p = stats.pearsonr([1.0, 2.0, 3.0, 4.0], [1.0, 3.0, 2.0, 5.0])
    assert res.coefficient == pytest.approx(coef)
    assert res.p_value == pytest.approx(p)  # real two-sided p, exactly matching scipy
    assert res.caveat  # causation caveat always present


def test_correlation_insufficient_data():
    prices = [(date(2026, 1, 1), 100.0), (date(2026, 1, 2), 101.0)]
    res = correlate_price_with_news(prices, [date(2026, 1, 2)], method="pearson")
    assert res.insufficient_data is True
    assert res.coefficient is None and res.p_value is None


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #

@pytest.fixture()
def client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'c.db'}", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    ensure_fts(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="S", domain="s.example"))
        s.commit()

    def _db():
        db = Sess()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    with TestClient(app) as c:
        yield c, Sess
    app.dependency_overrides.clear()


def test_import_list_normalize(client):
    client, _Sess = client
    points = [{"observed_on": "2026-01-01", "price": 100.0, "unit": "g"}]
    r = client.post("/api/commodities/Nd/prices", json={"points": points, "source": "fixture"})
    assert r.json()["imported"] == 1
    # normalize g -> kg on read
    r = client.get("/api/commodities/Nd/prices", params={"unit": "kg"})
    body = r.json()
    assert body["prices"][0]["price"] == pytest.approx(100_000.0)
    assert body["prices"][0]["unit"] == "kg"


def test_correlation_endpoint(client):
    client, Sess = client
    pts = [
        {"observed_on": "2026-01-01", "price": 100.0},
        {"observed_on": "2026-01-02", "price": 101.0},
        {"observed_on": "2026-01-03", "price": 103.0},
        {"observed_on": "2026-01-04", "price": 106.0},
        {"observed_on": "2026-01-05", "price": 110.0},
    ]
    client.post("/api/commodities/Nd/prices", json={"points": pts})
    # seed articles with publish dates and matching counts (unique hashes!)
    counts = {2: 1, 3: 2, 4: 3, 5: 4}
    aid = 0
    with Sess() as db:
        for day, c in counts.items():
            for _ in range(c):
                aid += 1
                db.add(Article(url=f"u{aid}", canonical_url=f"u{aid}", source_id=1,
                               title="neodymium", content="neodymium supply news",
                               hash=f"{aid:064d}",
                               published_at=datetime(2026, 1, day, tzinfo=UTC)))
        db.commit()

    r = client.get("/api/commodities/Nd/correlation", params={"query": "neodymium"})
    body = r.json()
    assert body["n"] == 4
    assert body["coefficient"] is not None
    assert body["p_value"] is not None
    assert "causation" in body["caveat"].lower()
