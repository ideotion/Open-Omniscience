"""The convergence WATCH engine (ruling 2026-06-17 #3, ON by default).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A watch is a saved local condition that fires a "watch" Lead card when the corpus
gains enough NEW matching articles in its window. These tests pin the honest firing
semantics: fires on a real COUNT >= a user threshold WITH new evidence, never
re-alarms on the same articles, respects the window + the enabled flag, and survives a
bad query — local-only, counts only, no score. The matcher is injected so the firing
logic is tested without an FTS table.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import watches as W
from src.database.models import Article, Base


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()


def _art(db, h, *, days_ago=0):
    when = datetime.now(UTC) - timedelta(days=days_ago)
    a = Article(
        url=f"https://x.test/{h}", canonical_url=f"https://x.test/{h}", source_id=1,
        title="T", content="x", hash=h, language="en",
        published_at=when, created_at=when,
    )
    db.add(a)
    db.commit()
    return a


def test_crud_roundtrip(db):
    w = W.create_watch(db, name="Floods", query="flood", threshold=2, window_days=14)
    db.commit()
    assert w.enabled is True  # ON by default (#3)
    lst = W.list_watches(db)
    assert len(lst) == 1 and lst[0]["query"] == "flood" and lst[0]["history"] == []
    W.update_watch(db, w.id, enabled=False, threshold=5)
    db.commit()
    assert W.list_watches(db)[0]["enabled"] is False
    assert W.list_watches(db)[0]["threshold"] == 5
    assert W.delete_watch(db, w.id) is True
    assert W.list_watches(db) == []
    # A watch needs a query.
    with pytest.raises(ValueError):
        W.create_watch(db, name="x", query="   ")


def test_fires_on_threshold_with_new_evidence(db):
    a1, a2, a3 = _art(db, "a1"), _art(db, "a2"), _art(db, "a3")
    W.create_watch(db, name="W", query="flood", threshold=3, window_days=7)
    db.commit()
    matched = {a1.id, a2.id, a3.id}
    # Inject a matcher that returns our three articles for the query.
    fired = W.evaluate_watches(db, matcher=lambda s, q: list(matched))
    db.commit()
    assert len(fired) == 1
    assert fired[0]["n_articles"] == 3 and fired[0]["new_articles"] == 3
    assert sorted(fired[0]["article_ids"]) == sorted(matched)
    # History recorded; last_matched stamped.
    lst = W.list_watches(db)[0]
    assert lst["last_matched_at"] is not None and len(lst["history"]) == 1


def test_recent_matching_is_chunked_and_byte_identical(db, monkeypatch):
    """Audit finding 2026-07-17: _recent_matching's Article.id.in_(ids) date lookup
    was unchunked, but the default matcher (_fts_matcher -> search_ids) can return
    up to its own _MAX_CANDIDATES (20000) -- well past SQLite's historical ~999
    bound-variable ceiling. A broad watch would raise "too many SQL variables" on
    EVERY scrape pass, silently swallowed by evaluate_watches's per-watch
    try/except -- so the watch would simply never fire again, with no visible
    error. Forces chunking with a tiny W._IN_CHUNK (5 matched articles needing 5
    separate chunk queries of 1) and asserts the result is BYTE-IDENTICAL to the
    unchunked default -- chunking must be a pure implementation detail."""
    arts = [_art(db, f"c{i}") for i in range(5)]
    ids = [a.id for a in arts]
    W.create_watch(db, name="W", query="flood", threshold=1, window_days=7)
    db.commit()

    monkeypatch.setattr(W, "_IN_CHUNK", 1, raising=True)
    chunked = W._recent_matching(db, "flood", 7, lambda s, q: list(ids))
    monkeypatch.setattr(W, "_IN_CHUNK", 900, raising=True)
    unchunked = W._recent_matching(db, "flood", 7, lambda s, q: list(ids))
    assert sorted(chunked) == sorted(unchunked) == sorted(ids)


def test_does_not_refire_on_same_articles_but_fires_on_new(db):
    a1, a2, a3 = _art(db, "a1"), _art(db, "a2"), _art(db, "a3")
    w = W.create_watch(db, name="W", query="flood", threshold=3, window_days=7)
    db.commit()
    ids = [a1.id, a2.id, a3.id]
    assert len(W.evaluate_watches(db, matcher=lambda s, q: ids)) == 1
    db.commit()
    # Same articles next pass -> NO re-fire (no new evidence).
    assert W.evaluate_watches(db, matcher=lambda s, q: ids) == []
    db.commit()
    # A NEW article enters the matching set -> fires again, new_articles == 1.
    a4 = _art(db, "a4")
    fired = W.evaluate_watches(db, matcher=lambda s, q: ids + [a4.id])
    db.commit()
    assert len(fired) == 1 and fired[0]["new_articles"] == 1
    assert len(W.watch_history(db, w.id)) == 2


def test_below_threshold_and_disabled_do_not_fire(db):
    a1, a2 = _art(db, "a1"), _art(db, "a2")
    w = W.create_watch(db, name="W", query="flood", threshold=3, window_days=7)
    db.commit()
    # Only 2 matches, threshold 3 -> no fire.
    assert W.evaluate_watches(db, matcher=lambda s, q: [a1.id, a2.id]) == []
    db.commit()
    # Disabled watches are skipped entirely.
    W.update_watch(db, w.id, enabled=False)
    db.commit()
    a3 = _art(db, "a3")
    assert W.evaluate_watches(db, matcher=lambda s, q: [a1.id, a2.id, a3.id]) == []


def test_window_excludes_old_articles(db):
    recent = [_art(db, f"r{i}").id for i in range(2)]
    old = [_art(db, f"o{i}", days_ago=30).id for i in range(3)]
    W.create_watch(db, name="W", query="flood", threshold=3, window_days=7)
    db.commit()
    # All 5 match the query, but only 2 are within the 7-day window -> below threshold.
    assert W.evaluate_watches(db, matcher=lambda s, q: recent + old) == []


def test_bad_query_does_not_break_the_pass(db):
    _art(db, "a1")
    W.create_watch(db, name="bad", query="boom", threshold=1, window_days=7)
    a = _art(db, "a2")
    w2 = W.create_watch(db, name="good", query="flood", threshold=1, window_days=7)
    db.commit()

    def matcher(s, q):
        if q == "boom":
            raise RuntimeError("malformed FTS")
        return [a.id]

    fired = W.evaluate_watches(db, matcher=matcher)
    db.commit()
    # The good watch still fired; the bad one was stamped evaluated, not fatal.
    assert [f["id"] for f in fired] == [w2.id]
    assert W.list_watches(db)  # both still present


def test_recent_fired_watches_is_the_lead_card_source(db):
    a = [_art(db, f"a{i}") for i in range(3)]
    W.create_watch(db, name="W", query="flood", threshold=3, window_days=7)
    db.commit()
    W.evaluate_watches(db, matcher=lambda s, q: [x.id for x in a])
    db.commit()
    cards = W.recent_fired_watches(db, within_hours=48)
    assert len(cards) == 1 and cards[0]["name"] == "W" and cards[0]["n_articles"] == 3
    assert sorted(cards[0]["article_ids"]) == sorted(x.id for x in a)
    # No score field anywhere.
    for c in cards:
        assert not any("score" in k for k in c)
