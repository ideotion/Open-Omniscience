"""The backfill queue must make forward progress past an un-indexable article (PRH-01).

``backfill_corpus`` selects articles that have no ``KeywordMention`` row. An article
can legitimately have none -- an empty body, all-stopword text, a body killed by
self-name suppression -- so "has no mentions" and "has never been indexed" are
DIFFERENT questions, and answering the second with the first meant such an article was
re-selected on every pass forever while everything behind it in id order was never
reached. Live-reproduced before the fix in ``scripts/analysis/repro_backfill_wedge.py``:
four passes, four articles attempted each time, three real articles left with zero
mentions.

These pin both halves: the queue ROTATES (the wedge is gone) and the attempt record is
an attempt, never a verdict (a stamped article with no mentions was examined and yielded
nothing, which must not read as "never examined").

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.store import backfill_corpus, index_article
from src.database.models import Article, Base, KeywordMention, Source

# Bodies that legitimately produce zero kept terms. Not malformed input -- each is a
# shape a real corpus contains (a paywalled stub, whitespace, pure function words).
_DUDS = ("", "     ", "the of and to in for on with a is", "\n\n")
_REAL = (
    "Parliament approved the regional infrastructure budget after a long committee "
    "inquiry into energy policy and inflation across the northern districts. "
) * 6


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="Wedge News", domain="wedge.test", enabled=True))
    s.commit()
    return s


def _add(db, key: str, body: str) -> Article:
    a = Article(
        url=f"https://wedge.test/{key}",
        canonical_url=f"https://wedge.test/{key}",
        source_id=1,
        title="",
        content=body,
        hash=key,
        language="en",
    )
    db.add(a)
    db.commit()
    return a


def _with_mentions(db) -> set[int]:
    return {a for (a,) in db.query(KeywordMention.article_id).distinct()}


def test_duds_do_not_wedge_the_queue_behind_them(db):
    """THE REGRESSION. Four un-indexable articles ahead of three real ones, and a window
    exactly the size of the duds -- the shape that made the queue permanently stuck."""
    for i, body in enumerate(_DUDS):
        _add(db, f"d{i}", body)
    real_ids = [_add(db, f"r{i}", _REAL).id for i in range(3)]

    # Pass 1 spends the whole window on the duds (they sort first: never attempted).
    r1 = backfill_corpus(db, extractor=BaselineExtractor(), limit=len(_DUDS))
    assert r1["newly_indexed"] == 0, "a dud cannot yield mentions"
    assert r1["no_terms"] == len(_DUDS)
    assert _with_mentions(db) == set()

    # Pass 2 must reach the real articles. Before the fix it re-selected the same duds.
    r2 = backfill_corpus(db, extractor=BaselineExtractor(), limit=len(_DUDS))
    assert r2["newly_indexed"] == 3, "the queue must rotate past the duds"
    assert _with_mentions(db) == set(real_ids)

    # And the honest backlog reaches zero even though `remaining` cannot: the duds still
    # have no mentions, but nothing is left that has never been looked at.
    assert r2["never_attempted"] == 0
    assert r2["remaining"] == len(_DUDS)


def test_an_attempt_is_recorded_but_is_never_a_verdict(db):
    """A stamped article with no mentions was EXAMINED and yielded nothing. That must be
    distinguishable from never-examined, and must not be recorded as a success."""
    dud = _add(db, "d", _DUDS[2])
    assert dud.keyword_indexed_at is None, "nothing has looked at it yet"

    r = backfill_corpus(db, extractor=BaselineExtractor(), limit=10)
    db.refresh(dud)
    assert dud.keyword_indexed_at is not None, "the pass ran; say so"
    assert r["no_terms"] == 1 and r["newly_indexed"] == 0, "ran is not found"


def test_a_permanently_failing_article_rotates_too(db, monkeypatch):
    """The wedge must not simply move from 'yields nothing' to 'always raises'. The
    success path's stamp dies with the rollback a failure requires, so the failure path
    records the attempt itself."""
    boom = _add(db, "boom", _REAL)
    good = _add(db, "good", _REAL)

    import src.analytics.store as store

    real_index = store.index_article

    def _explode(session, article, **kw):
        if article.id == boom.id:
            raise RuntimeError("extractor blew up on this one")
        return real_index(session, article, **kw)

    monkeypatch.setattr(store, "index_article", _explode)

    r1 = backfill_corpus(db, extractor=BaselineExtractor(), limit=1)
    assert r1["failed"] == 1 and r1["newly_indexed"] == 0
    db.refresh(boom)
    assert boom.keyword_indexed_at is not None, "a failed attempt is still an attempt"

    # With the failing article rotated out of the way, the window reaches the good one.
    r2 = backfill_corpus(db, extractor=BaselineExtractor(), limit=1)
    assert r2["newly_indexed"] == 1
    assert _with_mentions(db) == {good.id}


def test_the_stamp_survives_a_failing_when_where_who_pass(db, monkeypatch):
    """The stamp is assigned before the WWW savepoint on the premise that begin_nested()
    autoflushes pending state before opening the SAVEPOINT, so a WWW rollback cannot undo
    the record of a keyword pass that did complete. Verified rather than assumed."""
    art = _add(db, "www", _REAL)

    import src.timemap.datestore as datestore

    def _boom(*a, **kw):
        raise RuntimeError("dates blew up")

    monkeypatch.setattr(datestore, "store_for_article", _boom)

    out = index_article(db, art, extractor=BaselineExtractor())
    assert out["mentions"] > 0, "the keyword half must still have landed"
    db.refresh(art)
    assert art.keyword_indexed_at is not None
