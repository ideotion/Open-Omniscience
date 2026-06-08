"""
Tests for the Wikipedia change-tracking API.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The shared MediaWiki client is monkeypatched with a fake so track endpoints never
touch the network; CRUD, tracking, the flagged-changes feed and revision detail
are exercised through the API.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base


class FakeClient:
    def __init__(self, *, current=None, revisions=None, compares=None):
        self._current = current or {}
        self._revisions = revisions or []
        self._compares = compares or {}

    def fetch_current_text(self, wiki, title):
        return dict(self._current)

    def fetch_revisions(self, wiki, title, *, limit=20, older_than=None):
        return [dict(r) for r in self._revisions]

    def fetch_compare(self, wiki, a, b):
        return self._compares.get((a, b), {"added": "", "removed": "", "added_bytes": 0, "removed_bytes": 0})


def _client(tmp_path):
    from src.database.session import get_db

    engine = create_engine(f"sqlite:///{tmp_path / 'wiki.db'}", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _db
    return app, TestClient(app)


def test_wiki_api_crud_track_and_changes(tmp_path, monkeypatch):
    import src.api.wiki as wapi

    app, client = _client(tmp_path)
    try:
        with client:
            # Add a watched page.
            r = client.post("/api/wiki/pages", json={"wiki": "en", "title": "Berlin", "category": "cities"})
            assert r.status_code == 200
            pid = r.json()["id"]
            assert any(p["title"] == "Berlin" for p in client.get("/api/wiki/pages").json()["pages"])

            # First track -> baseline only (stub the shared client to return current text).
            monkeypatch.setattr(wapi, "_client", FakeClient(current={"revid": 100, "text": "base", "size": 1200, "pageid": 7}))
            res = client.post(f"/api/wiki/pages/{pid}/track?ores=false").json()
            assert res["baseline"] is True

            # Second track -> a large anonymous removal, flagged + diff stored.
            now = datetime.now(UTC)
            revs = [
                {"revid": 101, "parent_revid": 100, "timestamp": now, "editor": "1.2.3.4",
                 "editor_anon": True, "comment": "blank section", "size": 50, "minor": False,
                 "bot": False, "tags": []},
                {"revid": 100, "parent_revid": 99, "timestamp": now, "size": 1200},
            ]
            comp = {(100, 101): {"added": "", "removed": "removed text", "added_bytes": 0, "removed_bytes": 1200}}
            monkeypatch.setattr(wapi, "_client", FakeClient(revisions=revs, compares=comp))
            res2 = client.post(f"/api/wiki/pages/{pid}/track?ores=false").json()
            assert res2["new"] == 1 and res2["flagged"] == 1

            # Flagged-changes feed shows it with reasons + a live diff URL.
            ch = client.get("/api/wiki/changes?flagged_only=true").json()
            assert ch["count"] == 1
            change = ch["changes"][0]
            assert "large_removal" in change["flag_reasons"]
            assert change["diff_url"].startswith("https://en.wikipedia.org")

            # Revision detail includes the stored diff text.
            detail = client.get(f"/api/wiki/revisions/{change['id']}").json()
            assert "removed text" in detail["diff"]

            # Status reflects the data.
            st = client.get("/api/wiki/status").json()
            assert st["pages"] == 1 and st["flagged"] == 1

            # Delete cascades.
            assert client.delete(f"/api/wiki/pages/{pid}").json()["deleted"] == pid
            assert client.get("/api/wiki/status").json()["pages"] == 0
    finally:
        app.dependency_overrides.clear()
