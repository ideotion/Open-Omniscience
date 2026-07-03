"""Corpus-epoch mechanism (scaling 5A-bis / D3): the canonical source of the epoch
that guards the disposable columnar rollup against the delete-then-reinsert double-count.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Two layers are pinned here:
  * ``src.analytics.corpus_epoch`` -- get/bump over the ``derived_meta`` table, and that
    the three non-append mutators (reindex_all_batch / reindex_articles /
    prune_orphan_keywords) bump it.
  * the GUARD itself -- that ``refresh_keyword_daily`` FULL-rebuilds (never incrementally
    merges) once the epoch has changed, which is exactly what prevents a re-index from
    double-counting in the rollup. The trap is demonstrated (a stale-epoch incremental
    merge DOES double the counts) and then shown fixed by the epoch change.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.corpus_epoch import (
    CORPUS_EPOCH_KEY,
    bump_corpus_epoch,
    get_corpus_epoch,
)
from src.analytics.extract import BaselineExtractor
from src.analytics.store import (
    index_article,
    prune_orphan_keywords,
    reindex_all_batch,
    reindex_articles,
)
from src.database.models import Article, Base, DerivedMeta, Keyword, Source


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _article(db, hash_, text, *, when="2024-03-01"):
    a = Article(
        url=f"https://x.test/{hash_}",
        canonical_url=f"https://x.test/{hash_}",
        source_id=1,
        title="T",
        content=text,
        hash=hash_,
        country="fr",
        language="en",
        published_at=datetime.fromisoformat(when).replace(tzinfo=UTC),
        created_at=datetime.now(UTC),
    )
    db.add(a)
    db.commit()
    return a


def _seed(db, n=2):
    db.add(Source(name="S", domain="x.test", country="fr"))
    db.commit()
    ex = BaselineExtractor()
    for i in range(n):
        art = _article(
            db,
            f"h{i}",
            "Climate policy and trade dominated the summit. Climate policy again.",
        )
        index_article(db, art, extractor=ex, country="fr")
    return ex


# --------------------------------------------------------------------------- #
# corpus_epoch.py -- get / bump


def test_epoch_starts_at_zero_and_bumps(db):
    assert get_corpus_epoch(db) == 0  # never bumped
    assert db.get(DerivedMeta, CORPUS_EPOCH_KEY) is None
    assert bump_corpus_epoch(db, reason="t") == 1
    assert get_corpus_epoch(db) == 1
    assert bump_corpus_epoch(db) == 2
    assert bump_corpus_epoch(db) == 3
    assert get_corpus_epoch(db) == 3


def test_bump_recovers_from_a_garbage_value(db):
    db.add(DerivedMeta(key=CORPUS_EPOCH_KEY, value="not-a-number"))
    db.commit()
    assert get_corpus_epoch(db) == 0  # unparseable reads as 0
    assert bump_corpus_epoch(db) == 1  # and a bump restarts the counter cleanly


# --------------------------------------------------------------------------- #
# the mutators bump the epoch


def test_reindex_all_batch_bumps_epoch(db):
    _seed(db, n=2)
    before = get_corpus_epoch(db)
    r = reindex_all_batch(db, extractor=BaselineExtractor(), limit=300)
    assert r["reindexed"] == 2
    assert get_corpus_epoch(db) == before + 1  # one bump per non-empty batch


def test_reindex_all_batch_empty_does_not_bump(db):
    _seed(db, n=1)
    # after_id past the only article => empty batch, no work, no bump
    before = get_corpus_epoch(db)
    r = reindex_all_batch(db, extractor=BaselineExtractor(), limit=300, after_id=10_000)
    assert r["reindexed"] == 0 and r["done"]
    assert get_corpus_epoch(db) == before


def test_reindex_articles_bumps_epoch(db):
    _seed(db, n=2)
    aid = db.query(Article.id).order_by(Article.id).first()[0]
    before = get_corpus_epoch(db)
    reindex_articles(db, extractor=BaselineExtractor(), article_ids=[aid])
    assert get_corpus_epoch(db) == before + 1
    # an empty id list is a no-op (no bump)
    before2 = get_corpus_epoch(db)
    reindex_articles(db, extractor=BaselineExtractor(), article_ids=[])
    assert get_corpus_epoch(db) == before2


def test_prune_orphan_keywords_bumps_only_when_it_prunes(db):
    _seed(db, n=1)
    # No orphans yet -> no prune -> no bump.
    before = get_corpus_epoch(db)
    res = prune_orphan_keywords(db)
    assert res["pruned"] == 0
    assert get_corpus_epoch(db) == before
    # Create an orphan: a keyword with zero mentions.
    db.add(Keyword(term="orphan", normalized_term="orphan"))
    db.commit()
    before2 = get_corpus_epoch(db)
    res2 = prune_orphan_keywords(db)
    assert res2["pruned"] == 1
    assert get_corpus_epoch(db) == before2 + 1


# --------------------------------------------------------------------------- #
# THE GUARD: a changed epoch forces a full rebuild, preventing the double-count


def test_epoch_guard_forces_full_rebuild_and_prevents_double_count(db):
    pytest.importorskip("duckdb")
    from src.analytics import columnar

    ex = _seed(db, n=2)
    con = columnar.connect()  # in-memory (no passphrase) -- disposable
    assert con is not None
    try:
        # 1) FULL build at the current epoch (0). last_mention_id watermark recorded.
        epoch0 = get_corpus_epoch(db)
        r0 = columnar.refresh_keyword_daily(con, db, corpus_epoch=epoch0)
        assert r0["mode"] == "full"
        parity0 = columnar.keyword_daily_parity(con, db)
        assert parity0["mentions_exact"] and parity0["keywords_compared"] > 0

        # 2) A re-index (delete-then-reinsert of every mention) bumps the epoch. The
        #    reinserted mentions carry ids ABOVE the recorded watermark.
        reindex_all_batch(db, extractor=ex, limit=300)
        new_epoch = get_corpus_epoch(db)
        assert new_epoch == epoch0 + 1

        # 3) THE TRAP demonstrated: refreshing at the STALE epoch merges the tail
        #    incrementally, adding the reinserted rows ON TOP of the old ones -> doubled.
        stale = columnar.refresh_keyword_daily(con, db, corpus_epoch=epoch0)
        assert stale["mode"] == "incremental"
        trap = columnar.keyword_daily_parity(con, db)
        assert not trap["mentions_exact"], (
            "expected the stale-epoch incremental merge to double-count -- if this passes "
            "the reinserted ids did not exceed the watermark and the trap wasn't exercised"
        )

        # 4) THE GUARD: refreshing at the CURRENT epoch FULL-rebuilds -> exact again.
        fixed = columnar.refresh_keyword_daily(con, db, corpus_epoch=new_epoch)
        assert fixed["mode"] == "full"
        parity = columnar.keyword_daily_parity(con, db)
        assert parity["mentions_exact"], "the full rebuild must restore exact counts"
    finally:
        con.close()
