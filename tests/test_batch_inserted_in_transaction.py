"""The batched collect flush indexes the articles it has just inserted WITHOUT reading their mention rows (night list 17 Oct, build (b)).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``ArticleBatch._index_one`` passes ``inserted_in_this_transaction=True`` to ``index_article``: the flush above it gave each article its
id inside the transaction it is still in, so the article has no stored mention rows and the read of them (one statement per article, inside
the write-gate hold every other writer waits behind) can only return nothing. The flag itself, the re-index that still reads, the claim that
fails loudly when it is false and THE PROOF the skipped read would have been empty (including an id handed out again after a delete) are in
``tests/test_index_article_inserted_in_transaction.py``; this file pins the one thing that needs the batch: that it passes the flag. The
``src/ingest/batch.py`` line and ``index_article``'s parameter are in ONE commit: a batch that passes a keyword ``index_article`` does not
take fails every article's indexing, which ``_index_one`` reports as "kept unindexed".
"""

from __future__ import annotations

from sqlalchemy import func, select

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
