"""Watch-engine API (ruling 2026-06-17 #3): the Watches view CRUD + history + evaluate.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

LOCAL-only endpoints (no network, no consent gate): create / list / edit /
enable-disable / delete a watch, browse history, and evaluate on demand.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base


@pytest.fixture()
def client(tmp_path):
    import src.api.watches  # noqa: F401 - ensure the router import path is exercised
    from src.api.main import app
    from src.database.session import get_db

    from src.database.fts import ensure_fts

    engine = create_engine(
        f"sqlite:///{tmp_path / 'w.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    ensure_fts(engine)  # the watch matcher uses FTS5 search_ids; create_all doesn't build it
    Sess = sessionmaker(bind=engine, future=True)

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as c:
            yield c, Sess
    finally:
        app.dependency_overrides.clear()


def test_crud_and_list(client):
    c, _ = client
    r = c.post("/api/watches", json={"name": "Floods", "query": "flood", "threshold": 2})
    assert r.status_code == 200, r.text
    wid = r.json()["id"]
    assert r.json()["enabled"] is True  # ON by default (#3)

    body = c.get("/api/watches").json()
    assert body["count"] == 1 and body["watches"][0]["query"] == "flood"
    assert "never a verdict or score" in body["caveat"]

    # Edit (disable + retune).
    r = c.patch(f"/api/watches/{wid}", json={"enabled": False, "window_days": 30})
    assert r.status_code == 200 and r.json()["enabled"] is False and r.json()["window_days"] == 30

    # Delete.
    assert c.delete(f"/api/watches/{wid}").status_code == 200
    assert c.get("/api/watches").json()["count"] == 0
    # 404s for unknown ids.
    assert c.patch("/api/watches/999", json={"enabled": True}).status_code == 404
    assert c.delete("/api/watches/999").status_code == 404


def test_create_requires_a_query(client):
    c, _ = client
    # pydantic min_length rejects an empty query (422).
    assert c.post("/api/watches", json={"name": "x", "query": ""}).status_code == 422


def test_evaluate_fires_and_history(client):
    c, Sess = client
    # Seed three recent articles + a watch matching them.
    with Sess() as s:
        for h in ("a1", "a2", "a3"):
            s.add(Article(
                url=f"https://x.test/{h}", canonical_url=f"https://x.test/{h}", source_id=1,
                title="T", content="a flood hit the region", hash=h, language="en",
                published_at=datetime.now(UTC), created_at=datetime.now(UTC),
            ))
        s.commit()
    wid = c.post("/api/watches", json={"name": "W", "query": "flood", "threshold": 3}).json()["id"]

    fired = c.post("/api/watches/evaluate").json()
    # The FTS path runs over the real schema; the watch fires on >=3 in-window matches.
    assert fired["count"] == 1 and fired["fired"][0]["id"] == wid
    assert fired["fired"][0]["n_articles"] == 3

    hist = c.get(f"/api/watches/{wid}/history").json()
    assert len(hist["history"]) == 1 and hist["history"][0]["n_articles"] == 3
    # A second evaluation with no new articles does not re-fire.
    assert c.post("/api/watches/evaluate").json()["count"] == 0
