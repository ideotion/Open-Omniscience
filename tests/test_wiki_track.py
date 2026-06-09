"""
Tests for the Wikipedia tracking orchestrator + client wiring + ORES parse.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

No network: a FakeClient scripts API responses, so baseline capture, delta/diff
storage, honest flagging and ORES attachment are pinned deterministically.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, WikiRevision
from src.wiki.ores import parse_ores
from src.wiki.track import ensure_page, track_watched, update_page


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


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
        return self._compares.get(
            (a, b), {"added": "", "removed": "", "added_bytes": 0, "removed_bytes": 0}
        )


def test_baseline_captured_on_first_update(db):
    page = ensure_page(db, "en", "Berlin")
    client = FakeClient(current={"revid": 100, "text": "baseline text", "size": 1200, "pageid": 5})
    res = update_page(db, client, page)
    assert res["baseline"] is True
    assert page.baseline_revid == 100 and page.last_revid == 100
    assert page.baseline_text == "baseline text" and page.pageid == 5
    assert db.query(WikiRevision).count() == 0  # baseline is not a tracked edit


def test_large_anon_removal_is_stored_and_flagged(db):
    page = ensure_page(db, "en", "Berlin")
    page.baseline_revid = 100
    page.last_revid = 100
    db.commit()
    now = datetime.now(UTC)
    revs = [
        {
            "revid": 101,
            "parent_revid": 100,
            "timestamp": now,
            "editor": "1.2.3.4",
            "editor_anon": True,
            "comment": "remove section",
            "size": 100,
            "minor": False,
            "bot": False,
            "tags": [],
        },
        {
            "revid": 100,
            "parent_revid": 99,
            "timestamp": now,
            "editor": "Bot",
            "editor_anon": False,
            "size": 1200,
            "minor": False,
            "bot": True,
            "tags": [],
        },
    ]
    compares = {
        (100, 101): {
            "added": "",
            "removed": "a deleted paragraph",
            "added_bytes": 0,
            "removed_bytes": 1100,
        }
    }
    client = FakeClient(revisions=revs, compares=compares)
    res = update_page(db, client, page)
    assert res["new"] == 1 and res["flagged"] == 1
    rev = db.query(WikiRevision).filter_by(revid=101).one()
    assert rev.delta_bytes == -1100  # 100 - 1200
    assert rev.flagged and "large_removal" in rev.flag_reasons and "anon_large" in rev.flag_reasons
    assert rev.diff and "deleted paragraph" in rev.diff
    assert page.last_revid == 101


def test_repoll_stores_nothing_new(db):
    page = ensure_page(db, "en", "X")
    page.baseline_revid = 50
    page.last_revid = 50
    db.commit()
    client = FakeClient(
        revisions=[{"revid": 50, "parent_revid": 49, "size": 10, "timestamp": datetime.now(UTC)}]
    )
    res = update_page(db, client, page)
    assert res["new"] == 0
    assert db.query(WikiRevision).count() == 0


def test_ores_score_attached_and_flagged(db):
    page = ensure_page(db, "en", "Y")
    page.baseline_revid = 10
    page.last_revid = 10
    db.commit()

    class FakeOres:
        def score(self, wiki, revids):
            return {
                revids[0]: {
                    "damaging": 0.95,
                    "goodfaith": 0.1,
                    "provenance": "ores:damaging,goodfaith",
                }
            }

    revs = [
        {
            "revid": 11,
            "parent_revid": 10,
            "timestamp": datetime.now(UTC),
            "editor": "U",
            "editor_anon": False,
            "size": 100,
            "minor": True,
            "bot": False,
            "tags": [],
        },
        {"revid": 10, "size": 90, "timestamp": datetime.now(UTC)},
    ]
    client = FakeClient(
        revisions=revs,
        compares={(10, 11): {"added": "x", "removed": "", "added_bytes": 1, "removed_bytes": 0}},
    )
    update_page(db, client, page, ores_client=FakeOres())
    rev = db.query(WikiRevision).filter_by(revid=11).one()
    assert rev.ores_damaging == 0.95 and rev.ores_provenance.startswith("ores")
    assert rev.flagged and "ores_damaging" in rev.flag_reasons


def test_track_watched_aggregates(db):
    p1 = ensure_page(db, "en", "A")
    p1.baseline_revid = 1
    p1.last_revid = 1
    p2 = ensure_page(db, "fr", "B")
    p2.baseline_revid = 1
    p2.last_revid = 1
    db.commit()
    client = FakeClient(revisions=[])  # no new edits
    res = track_watched(db, client, limit_pages=10)
    assert res["pages"] == 2 and res["new_revisions"] == 0


def test_parse_ores_fixture():
    payload = {
        "enwiki": {
            "scores": {
                "101": {
                    "damaging": {"score": {"probability": {"true": 0.8, "false": 0.2}}},
                    "goodfaith": {"score": {"probability": {"true": 0.3, "false": 0.7}}},
                },
            }
        }
    }
    out = parse_ores(payload, "en")
    assert out[101]["damaging"] == 0.8 and out[101]["goodfaith"] == 0.3


def test_wiki_client_parses_through_fake_session():
    from src.wiki.client import WikiClient

    class Resp:
        def __init__(self, data):
            self._d = data

        def raise_for_status(self):
            return None

        def json(self):
            return self._d

    payload = {
        "query": {
            "pages": [
                {
                    "pageid": 1,
                    "title": "T",
                    "revisions": [
                        {
                            "revid": 9,
                            "parentid": 8,
                            "timestamp": "2024-01-01T00:00:00Z",
                            "user": "U",
                            "size": 100,
                            "tags": [],
                        }
                    ],
                }
            ]
        }
    }

    class Sess:
        headers = {}

        def get(self, url, params=None, timeout=None):
            assert "maxlag" in params  # etiquette honoured
            return Resp(payload)

    c = WikiClient(session=Sess(), min_interval_s=0.0)
    revs = c.fetch_revisions("en", "T")
    assert revs[0]["revid"] == 9
