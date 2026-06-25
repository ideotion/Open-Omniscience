"""BM25F per-column ranking weights (keyword-engine P5.1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

FTS5 search ranks with bm25 weighted per column (title vs body): a title keyword is a
stronger relevance signal than a body mention, so a title match ranks above a body-only
match. The weights are env-tunable and reversible (equal weights = the old flat rank).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.fts import _bm25_weights, ensure_fts, search_ids
from src.database.models import Article, Base, Source


def _env():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(eng)
    ensure_fts(eng)  # FTS table + triggers (inserts below populate it)
    Session = sessionmaker(bind=eng, future=True)
    with Session() as s:
        s.add(Source(name="S", domain="x.test"))
        s.commit()
    return Session


def _add(s, hash_, title, content):
    a = Article(
        url=f"u{hash_}", canonical_url=f"u{hash_}", source_id=1, title=title, content=content,
        hash=hash_, language="en", created_at=datetime.now(UTC),
    )
    s.add(a)
    s.flush()
    return a.id


def test_bm25f_ranks_a_title_match_above_a_body_only_match():
    Session = _env()
    with Session() as s:
        title_id = _add(s, "t1", "Inflation report", "general coverage of markets and trade")
        body_id = _add(s, "b1", "Markets report", "a longer body that mentions inflation once here")
        s.commit()
        ids = search_ids(s, "inflation")
        assert set(ids) == {title_id, body_id}  # both match
        assert ids[0] == title_id  # the title match ranks first under BM25F


def test_bm25f_weights_are_reversible_via_env(monkeypatch):
    Session = _env()
    with Session() as s:
        title_id = _add(s, "t1", "Inflation report", "general coverage of markets and trade")
        body_id = _add(s, "b1", "Markets report", "a longer body that mentions inflation once here")
        s.commit()
        # Weight the BODY far above the title -> the body match now ranks first.
        monkeypatch.setenv("OO_BM25_TITLE_WEIGHT", "1")
        monkeypatch.setenv("OO_BM25_BODY_WEIGHT", "20")
        ids = search_ids(s, "inflation")
        assert ids[0] == body_id and set(ids) == {title_id, body_id}


def test_bm25_weights_default_and_bad_env(monkeypatch):
    monkeypatch.delenv("OO_BM25_TITLE_WEIGHT", raising=False)
    monkeypatch.delenv("OO_BM25_BODY_WEIGHT", raising=False)
    wt, wb = _bm25_weights()
    assert wt > wb  # title weighted above body by default
    monkeypatch.setenv("OO_BM25_TITLE_WEIGHT", "not-a-number")
    assert _bm25_weights()[0] == 4.0  # a bad value falls back to the default, never crashes
