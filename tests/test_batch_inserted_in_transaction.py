"""The batched collect flush indexes the articles it has just inserted WITHOUT reading their mention rows, after ONE check for the flush (night list 17 Oct, build (b)).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``ArticleBatch._index_one`` passes ``inserted_in_this_transaction=True`` to ``index_article``: the flush above it gave each article its
id inside the transaction it is still in, so the article has no stored mention rows and the read of them (one statement per article, inside
the write-gate hold every other writer waits behind) can only return nothing. The flag itself, the re-index that still reads, the claim that
fails loudly when it is false and THE PROOF the skipped read would have been empty (including an id handed out again after a delete) are in
``tests/test_index_article_inserted_in_transaction.py``; this file pins the one thing that needs the batch: that it passes the flag, AFTER asking
once for the whole flush which of its articles' ids already carry mention rows (an id handed out again over rows a tool with foreign keys off left
behind: the read of the delta found that the flag alone would attach such a row to the new article silently when the keywords are disjoint). The
``src/ingest/batch.py`` line and ``index_article``'s parameter are in ONE commit: a batch that passes a keyword ``index_article`` does not
take fails every article's indexing, which ``_index_one`` reports as "kept unindexed".
"""

from __future__ import annotations

from sqlalchemy import func, select, text

import src.analytics.store as store
from src.database.models import KeywordMention
from tests.test_collect_extraction_outside_gate import _ingest

_MT = KeywordMention.__table__


def _count_reads(monkeypatch):
    calls: list[int] = []
    real = store._read_mention_rows

    def spy(session, article_id):
        calls.append(article_id)
        return real(session, article_id)

    monkeypatch.setattr(store, "_read_mention_rows", spy)
    return calls


def test_a_batched_flush_reads_no_mention_rows(monkeypatch):
    calls = _count_reads(monkeypatch)
    indexed: list[int] = []
    real = store.index_article

    def spy(session, article, **kw):
        indexed.append(article.id)
        return real(session, article, **kw)

    monkeypatch.setattr(store, "index_article", spy)
    _dom, src_id, tally = _ingest(monkeypatch, n=4)

    assert tally["stored"] == 4
    assert len(indexed) == 4, f"ANTI-VACUITY: the batch indexed {len(indexed)} articles, not 4, so 'no read' proves nothing"
    assert calls == [], f"the batched flush read the mention rows of articles it had just inserted: {calls}"
    from src.database.session import session_scope

    with session_scope() as s:
        stored = s.execute(select(func.count()).select_from(_MT).where(_MT.c.article_id.in_(indexed))).scalar()
    assert stored and stored >= 4, "the articles were indexed (each has mention rows)"


def test_the_batch_asks_once_for_the_whole_flush_which_articles_already_carry_rows(monkeypatch):
    asked: list[list[int]] = []
    real = store.articles_with_stored_mentions

    def spy(session, article_ids):
        asked.append(list(article_ids))
        return real(session, article_ids)

    monkeypatch.setattr(store, "articles_with_stored_mentions", spy)
    _dom, _src, tally = _ingest(monkeypatch, n=4)
    assert tally["stored"] == 4
    assert len(asked) == 1 and len(asked[0]) == 4, f"one statement for the flush's four articles, not one per article: {asked}"


def test_an_id_handed_out_again_over_orphan_rows_is_indexed_the_old_way_and_heals(monkeypatch):
    """THE CASE THE FLAG ALONE GOT WRONG (the Opus read of d8deefaa8, M1). The highest article is deleted by something that ran with foreign keys
    off, so its mention rows stay; the next flush's first article gets the id again. With the keywords DISJOINT from the new article's, the flag
    would have kept the orphan rows attached to it without a word. The batch asks first, reads that one article's rows and the diff replaces
    them; every other article of the flush still skips the read."""
    from datetime import UTC, datetime

    from src.analytics.store import index_article
    from src.database.models import Article, Keyword
    from src.database.session import engine, session_scope
    from tests.test_mention_diff_write import _Ex, _t

    _dom, src_id, first = _ingest(monkeypatch, n=3)
    assert first["stored"] == 3
    primed = [engine.connect() for _ in range(3)]  # three idle connections in the pool afterwards, as a full run leaves it
    for c in primed:
        c.exec_driver_sql("SELECT 1")
    for c in primed:
        c.close()
    with session_scope() as s:
        orphan = Article(url="https://o.test/orphan", canonical_url="https://o.test/orphan", source_id=src_id, title="T", content="body",
                         hash="orphan-hash", language="en", country=None, created_at=datetime.now(UTC))
        s.add(orphan)
        s.flush()
        orphan_id = orphan.id
        index_article(s, orphan, extractor=_Ex([_t("zzorphankeyword", 5)]), country=None, city=None, commit=False)
        s.commit()
        kid = s.execute(select(Keyword.id).where(Keyword.normalized_term == "zzorphankeyword")).scalar_one()
        s.commit()  # the read above ends: the delete below does not wait behind it
        # ONE checked-out connection from OFF to ON. The pragma belongs to the CONNECTION, and the pool hands out its idle ones in turn,
        # so turning it on through the session after a commit (which gives the connection back) can switch on a different one and leave
        # this one off for every later test of the process (the Opus read of 32cb12ea0, M1).
        with s.get_bind().connect() as c:
            try:
                c.exec_driver_sql("PRAGMA foreign_keys=OFF")  # as a database tool leaves it: the article goes, its mention rows stay
                c.execute(text("DELETE FROM articles WHERE id = :i"), {"i": orphan_id})
                c.commit()
            finally:
                c.rollback()  # a DELETE that failed leaves the driver's transaction open, and a pragma is a no-op inside one
                c.exec_driver_sql("PRAGMA foreign_keys=ON")
                c.commit()
        assert s.execute(select(func.count()).select_from(_MT).where(_MT.c.article_id == orphan_id)).scalar() == 1, "ANTI-VACUITY: no orphan row"

    # EVERY idle connection and one more: the pool hands out the oldest first, so a fixed number of checkouts misses the one left off
    # when the pool already holds more idle connections than that (the Opus read of 137a85525: eight idle ones hid it from four checkouts).
    wide = [engine.connect() for _ in range(engine.pool.checkedin() + 1)]
    try:
        flags = [c.exec_driver_sql("PRAGMA foreign_keys").scalar() for c in wide]
    finally:
        for c in wide:
            c.close()
    assert len(flags) >= 4 and set(flags) == {1}, f"a pooled connection was left with foreign keys off for every later test of the process: {flags}"

    reads = _count_reads(monkeypatch)
    indexed: list[int] = []
    real = store.index_article

    def spy(session, article, **kw):
        indexed.append(article.id)
        return real(session, article, **kw)

    monkeypatch.setattr(store, "index_article", spy)
    _dom2, _src2, second = _ingest(monkeypatch, n=3)

    assert second["stored"] == 3
    assert orphan_id in indexed, f"ANTI-VACUITY: no article of the second flush took the id {orphan_id} again (got {indexed})"
    assert reads == [orphan_id], f"only the article whose id carries rows is read; got {reads}"
    with session_scope() as s:
        left = s.execute(select(func.count()).select_from(_MT).where(_MT.c.article_id == orphan_id, _MT.c.keyword_id == kid)).scalar()
    assert left == 0, "the orphan row is still attached to the new article"
