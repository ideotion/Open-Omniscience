"""
Tests for the per-page wiki tracked-changes endpoint
(GET /api/wiki/pages/{page_id}/revisions).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The endpoint returns a watched page's stored revisions (newest first) with per-revision
diffs, from the stored rows only (no network). Deduced/versioned, honest: a revision
without a stored diff surfaces an empty diff, and ``total`` discloses the full count so a
bounded window is never mistaken for the whole history.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, WikiPage, WikiRevision


def _client(tmp_path):
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'wiki.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
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
    return app, TestClient(app), Sess


def _seed(Sess) -> int:
    """A watched page with three stored revisions; returns the page id."""
    s = Sess()
    try:
        page = WikiPage(wiki="en", title="Climate change", watched=True)
        s.add(page)
        s.flush()
        # Oldest -> newest; only the middle one has a stored diff; newest is flagged +
        # has full_text; the oldest (baseline) has no parent and no stored diff.
        s.add_all(
            [
                WikiRevision(
                    page_id=page.id, revid=100, parent_revid=None,
                    timestamp=datetime(2026, 1, 1, tzinfo=UTC), delta_bytes=0,
                    diff=None, full_text=None, flagged=False,
                ),
                WikiRevision(
                    page_id=page.id, revid=200, parent_revid=100,
                    timestamp=datetime(2026, 2, 1, tzinfo=UTC), delta_bytes=42,
                    diff="+ added a sentence\n- removed a clause", full_text=None, flagged=False,
                ),
                WikiRevision(
                    page_id=page.id, revid=300, parent_revid=200,
                    timestamp=datetime(2026, 3, 1, tzinfo=UTC), delta_bytes=-500,
                    diff="- large removal", full_text="The exact article text at rev 300.",
                    flagged=True, flag_reasons="large_delta",
                ),
            ]
        )
        s.commit()
        return page.id
    finally:
        s.close()


def test_revisions_returned_newest_first_with_diffs(tmp_path):
    app, client, Sess = _client(tmp_path)
    try:
        pid = _seed(Sess)
        r = client.get(f"/api/wiki/pages/{pid}/revisions")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 3
        assert data["count"] == 3
        revids = [rev["revid"] for rev in data["revisions"]]
        assert revids == [300, 200, 100]  # newest first
        # Per-revision stored diffs surface; the parentless baseline has an empty diff.
        by_revid = {rev["revid"]: rev for rev in data["revisions"]}
        assert by_revid[200]["diff"] == "+ added a sentence\n- removed a clause"
        assert by_revid[100]["diff"] == ""  # no stored diff -> honest empty, never fabricated
        assert by_revid[300]["has_full_text"] is True
        assert by_revid[100]["has_full_text"] is False
        # Page block + method are present; no score anywhere.
        assert data["page"]["title"] == "Climate change"
        assert data["page"]["revisions"] == 3
        assert data["page"]["flagged"] == 1
        assert "score" not in str(data).lower() or "no score" in data["method"].lower()
    finally:
        app.dependency_overrides.clear()


def test_unknown_page_is_404(tmp_path):
    app, client, Sess = _client(tmp_path)
    try:
        _seed(Sess)
        r = client.get("/api/wiki/pages/999999/revisions")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_flagged_only_filter(tmp_path):
    app, client, Sess = _client(tmp_path)
    try:
        pid = _seed(Sess)
        r = client.get(f"/api/wiki/pages/{pid}/revisions", params={"flagged_only": True})
        assert r.status_code == 200
        data = r.json()
        # total reflects the scoped (flagged) count; flagged_total drives page.flagged.
        assert data["total"] == 1
        assert [rev["revid"] for rev in data["revisions"]] == [300]
        assert data["flagged_only"] is True
        assert data["page"]["flagged"] == 1
    finally:
        app.dependency_overrides.clear()


def test_include_diff_false_omits_diff_body(tmp_path):
    app, client, Sess = _client(tmp_path)
    try:
        pid = _seed(Sess)
        r = client.get(f"/api/wiki/pages/{pid}/revisions", params={"include_diff": False})
        assert r.status_code == 200
        for rev in r.json()["revisions"]:
            assert "diff" not in rev  # list-only, cheaper payload
            assert "revid" in rev
    finally:
        app.dependency_overrides.clear()


def test_limit_bounds_the_window_but_total_is_honest(tmp_path):
    app, client, Sess = _client(tmp_path)
    try:
        pid = _seed(Sess)
        r = client.get(f"/api/wiki/pages/{pid}/revisions", params={"limit": 2})
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 2
        assert data["total"] == 3  # window discloses the true total
        assert [rev["revid"] for rev in data["revisions"]] == [300, 200]
    finally:
        app.dependency_overrides.clear()
