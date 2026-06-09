"""Batch-ingest endpoint: fetch many source feeds in one bounded, best-effort run.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Source


def test_ingest_batch_is_best_effort_and_aggregates(tmp_path, monkeypatch):
    import src.api.ingestion as ing
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'b.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add_all(
            [
                Source(name="Has Feed", domain="feed.test", rss_url="https://feed.test/rss"),
                Source(name="No Feed", domain="nofeed.test", rss_url=None),
            ]
        )
        s.commit()

    # Stub the real fetch so the test is offline; return a canned per-source tally.
    monkeypatch.setattr(
        ing, "ingest_source", lambda db, source, **kw: {"stored": 2, "duplicate": 1}
    )

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as c:
            r = c.post("/api/sources/ingest-batch", json={"source_ids": [1, 2, 999, 1]})
            assert r.status_code == 200
            body = r.json()
        assert body["requested"] == 3  # de-duplicated (the repeated 1 dropped)
        assert body["ingested"] == 1  # only the feed-bearing source ran
        assert body["aggregate"] == {"stored": 2, "duplicate": 1}
        by_status = {res.get("source_id"): res["status"] for res in body["results"]}
        assert by_status[1] == "ok"
        assert by_status[2] == "no_feed"  # skipped with a clear reason
        assert by_status[999] == "not_found"
        # Empty request is rejected.
        assert c.post("/api/sources/ingest-batch", json={"source_ids": []}).status_code == 400
    finally:
        app.dependency_overrides.clear()
