"""
Tests for CSV price import (Action Plan Phase 6.7 -- practical bulk data path).
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.commodity.csv_import import parse_price_csv
from src.database.models import Base, CommodityPrice
from src.database.session import get_db

_CSV = (
    "date,price,currency,unit,market\n"
    "2026-01-01,100.5,USD,kg,china_spot\n"
    "2026-01-02,101.0,USD,kg,china_spot\n"
)


def test_parse_basic():
    parsed = parse_price_csv(_CSV)
    assert parsed.errors == []
    assert len(parsed.points) == 2
    assert parsed.points[0]["observed_on"] == date(2026, 1, 1)
    assert parsed.points[0]["price"] == 100.5
    assert parsed.points[0]["market"] == "china_spot"


def test_parse_header_aliases_and_minimal_columns():
    parsed = parse_price_csv("day,close\n2026-03-04,7.25\n")
    assert len(parsed.points) == 1
    assert parsed.points[0]["price"] == 7.25
    assert parsed.points[0]["observed_on"] == date(2026, 3, 4)


def test_parse_reports_bad_rows():
    parsed = parse_price_csv("date,price\n2026-01-01,abc\nnotadate,5\n2026-01-03,9\n")
    assert len(parsed.points) == 1  # only the valid row
    assert len(parsed.errors) == 2


def test_parse_requires_date_and_price():
    parsed = parse_price_csv("name,note\nfoo,bar\n")
    assert parsed.points == []
    assert parsed.errors


@pytest.fixture()
def client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'csv.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)

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


def test_import_csv_endpoint(client):
    c, Sess = client
    r = c.post(
        "/api/commodities/Nd/prices/import-csv", files={"file": ("prices.csv", _CSV, "text/csv")}
    )
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 2
    with Sess() as s:
        assert s.query(CommodityPrice).filter_by(symbol="Nd").count() == 2


def test_import_csv_bad_file_400(client):
    c, _ = client
    r = c.post(
        "/api/commodities/Nd/prices/import-csv", files={"file": ("x.csv", "nope\n1\n", "text/csv")}
    )
    assert r.status_code == 400
