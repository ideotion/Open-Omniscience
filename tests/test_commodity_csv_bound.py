"""The commodity price CSV upload is read with a bound (audit 0.5.0 A-019).

The handler used to ``await file.read()`` the whole upload. Now a file over ``_MAX_PRICE_CSV_BYTES`` is refused with 413 after
reading only cap + 1 bytes, and nothing is imported. The cap names what it protects (the measurement is next to it in
``src/api/commodity.py``).
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.database.models import Base, CommodityPrice
from src.database.session import get_db

# the commodity router imports scipy (the [analysis] extra); a core install skips this file
pytest.importorskip("scipy", reason="the commodity router needs the [analysis] extra")
from src.api import commodity  # noqa: E402

_CSV = "date,price\n2024-01-01,10.5\n2024-01-02,11.0\n"


@pytest.fixture()
def client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'b.db'}", future=True, connect_args={"check_same_thread": False})
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


def test_a_csv_over_the_cap_is_refused_and_nothing_is_imported(client, monkeypatch):
    c, Sess = client
    monkeypatch.setattr(commodity, "_MAX_PRICE_CSV_BYTES", 100)
    r = c.post("/api/commodities/Nd/prices/import-csv", files={"file": ("big.csv", _CSV + "2024-01-03,12.0\n" * 20, "text/csv")})
    assert r.status_code == 413, r.text
    assert "Nothing was imported" in r.json()["detail"]
    with Sess() as s:
        assert s.query(CommodityPrice).count() == 0


def test_a_csv_at_the_cap_still_imports(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(commodity, "_MAX_PRICE_CSV_BYTES", len(_CSV))
    r = c.post("/api/commodities/Nd/prices/import-csv", files={"file": ("ok.csv", _CSV, "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 2


def test_the_cap_is_the_measured_one():
    mib = 1024 * 1024
    cap = commodity._MAX_PRICE_CSV_BYTES
    assert cap * 17 <= 300 * mib, "the parse holds about 17.4x the file; one parse must stay near 285 MiB"
    assert cap >= 40 * (mib * 4 // 10), "must stay well above the realistic file (a daily index since 1971, about 0.4 MiB)"


def test_the_csv_parse_does_not_run_on_the_event_loop(client, monkeypatch):
    """A-038: ``parse_price_csv`` is CPU-bound (about 44 s at 1.3 M rows) and was called inside the async handler, so every other
    request waited for it. ``asyncio.get_running_loop()`` raises in a worker thread and answers on the loop's own thread."""
    c, _ = client
    seen: dict[str, bool] = {}
    real = commodity.parse_price_csv

    def spy(text):
        try:
            asyncio.get_running_loop()
            seen["on_loop"] = True
        except RuntimeError:
            seen["on_loop"] = False
        return real(text)

    monkeypatch.setattr(commodity, "parse_price_csv", spy)
    r = c.post("/api/commodities/Nd/prices/import-csv", files={"file": ("p.csv", _CSV, "text/csv")})
    assert r.status_code == 200, r.text
    assert seen == {"on_loop": False}, seen
