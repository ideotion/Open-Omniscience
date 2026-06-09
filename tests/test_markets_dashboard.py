"""
Tests for the markets dashboard backend: import-all feeds + series listing.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base


class FakeResp:
    def __init__(self, text):
        self.status_code = 200
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": "text/csv"}
        self.url = "https://fred.stlouisfed.org/x"

    def raise_for_status(self):
        return None


class FakeSession:
    headers: dict = {}

    def get(self, url, timeout=None, allow_redirects=True, **kw):
        if url.endswith("robots.txt"):
            return FakeResp("")
        return FakeResp("DATE,V\n2024-01-01,10\n2024-02-01,11\n2024-03-01,.\n")


def test_import_all_and_series(tmp_path, monkeypatch):
    import src.api.markets as mk
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'mk.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)

    # Stub the shared fetcher so all feeds resolve to a tiny CSV (no network).
    monkeypatch.setattr(mk._fetcher, "session", FakeSession())
    monkeypatch.setattr(mk._fetcher, "respect_robots", False)

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            res = client.post("/api/markets/feeds/import-all").json()
            assert res["feeds"] >= 10 and res["points_imported"] >= 2 and res["failed"] == 0

            series = client.get("/api/markets/series").json()
            symbols = {s["symbol"] for s in series["series"]}
            assert {"COPPER", "WTI", "EURUSD", "GOLD"} <= symbols
            wti = next(s for s in series["series"] if s["symbol"] == "WTI")
            assert wti["points"] == 2 and wti["latest"]["price"] == 11.0  # "." row skipped

            # Re-import is idempotent (no duplicate points).
            res2 = client.post("/api/markets/feeds/import-all").json()
            assert res2["points_imported"] == 0
    finally:
        app.dependency_overrides.clear()
