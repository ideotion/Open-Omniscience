"""An article the batch just inserted has no stored mention rows to read, so the read is not made (night list 17 Oct, build (b)).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``index_article`` read the article's stored mention rows INSIDE the write-gate hold, one statement per article, to diff
them against the rows the pass produces. For an article the batched collect flush has just inserted in the transaction it is
still inside, that read returns nothing, and every other writer waits behind the hold it lengthens (the measured longest holds
are made of INSERTs and per-article statements). ``index_article(..., inserted_in_this_transaction=True)`` takes the empty
answer without asking, and ``ArticleBatch._index_one`` is the one caller that says so (that one line is in ``src/ingest/batch.py``, in the same
commit as the parameter; ``tests/test_batch_inserted_in_transaction.py`` pins that the batch passes the flag). What is pinned here:

* the flag skips the read and without it the read is made (the anti-vacuity twin of every "no read" assertion);
* what is STORED is the same with and without it: the rows, the keyword counters and the tally;
* a RE-index (the article already has rows) still reads, and keeps its rows by the diff;
* THE PROOF the skipped read would have been empty, including the case that could have made it wrong: an article id that is
  handed out AGAIN after a delete (SQLite keeps no counter without AUTOINCREMENT). The old article's mention rows went with it
  (``ON DELETE CASCADE`` under ``PRAGMA foreign_keys=ON`` on every pooled connection), so the reused id meets none;
* the flag is the CALLER'S claim, and this file says exactly how far the function backs it: on an article that DOES have rows, keywords that
  overlap fail loudly on the unique index, and keywords that are DISJOINT stay attached to the article without a word (the Opus read of
  d8deefaa8, M1). That is why the batch asks :func:`articles_with_stored_mentions` once per flush and leaves the flag off for an article it
  names (``tests/test_batch_inserted_in_transaction.py`` pins that), and why the function that asks is pinned here.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

import src.analytics.store as store
from src.analytics.store import index_article
from src.database.models import Article, KeywordMention
from tests.test_collect_extraction_outside_gate import _ingest
from tests.test_mention_diff_write import _counters, _Ex, _payload, _rows, _session, _t

_MT = KeywordMention.__table__


def _flushed_article(s, h):
    """An article INSERTED in the open transaction: flushed (it has its id) and not committed, the batch's shape."""
    a = Article(url=f"https://s.test/{h}", canonical_url=f"https://s.test/{h}", source_id=1, title="T", content="body", hash=h,
                language="en", country=None, created_at=datetime.now(UTC))
    s.add(a)
    s.flush()
    assert a.id is not None
    return a


def _count_reads(monkeypatch):
    calls: list[int] = []
    real = store._read_mention_rows

    def spy(session, article_id):
        calls.append(article_id)
        return real(session, article_id)

    monkeypatch.setattr(store, "_read_mention_rows", spy)
    return calls


# --------------------------------------------------------------------------- #
#  the flag: skips the read, and without it the read is made
# --------------------------------------------------------------------------- #
def test_the_flag_skips_the_read_and_a_plain_call_makes_it(monkeypatch):
    s = _session()
    calls = _count_reads(monkeypatch)
    ex = _Ex([_t("x", 2), _t("y")])

    index_article(s, _flushed_article(s, "plain"), extractor=ex, country=None, city=None, commit=False)
    assert len(calls) == 1, "a plain call reads the article's stored rows (the anti-vacuity twin of the next assertion)"

    calls.clear()
    handed: list[object] = []
    real_diff = store._write_mention_diff
    monkeypatch.setattr(store, "_write_mention_diff", lambda session, article_id, old_rows, *a, **kw: (handed.append(old_rows), real_diff(session, article_id, old_rows, *a, **kw))[1])
    index_article(s, _flushed_article(s, "flagged"), extractor=ex, country=None, city=None, commit=False, inserted_in_this_transaction=True)
    assert calls == [], f"the flag was given and the read was made anyway: {calls}"
    # ``{}`` is "no rows"; ``None`` would be "two rows share a keyword" and take the delete-then-insert shape (a DELETE for nothing).
    assert handed == [{}], f"the diff was handed {handed!r}, not the empty answer"


def test_what_is_stored_is_the_same_with_and_without_the_flag():
    terms = [_t("x", 3, 4), _t("y"), _t("z", 2, 9)]
    out = {}
    for flagged in (False, True):
        s = _session()
        a = _flushed_article(s, "same")
        tally = index_article(s, a, extractor=_Ex(terms), country="fr", city="Lyon", commit=False, inserted_in_this_transaction=flagged)
        s.commit()
        out[flagged] = (tally, _payload(_rows(s, a.id)), _counters(s), a.top_keyword_id is not None)
    assert out[True] == out[False]
    assert out[True][1], "ANTI-VACUITY: no mention rows were stored, so the comparison above is of nothing"


def test_the_counters_of_a_flagged_article_are_exact_when_the_keyword_already_has_other_articles():
    """The old contribution comes from the read; for an article that was never indexed it is zero, and the counters must still
    move by exactly this article's mentions and one article."""
    s = _session()
    index_article(s, _flushed_article(s, "first"), extractor=_Ex([_t("x", 2)]), country=None, city=None, commit=False)
    s.commit()
    assert _counters(s) == {"x": (2, 1)}
    index_article(s, _flushed_article(s, "second"), extractor=_Ex([_t("x", 3), _t("y")]), country=None, city=None, commit=False,
                  inserted_in_this_transaction=True)
    s.commit()
    assert _counters(s) == {"x": (5, 2), "y": (1, 1)}


# --------------------------------------------------------------------------- #
#  a re-index still reads, and the flag on a re-index is refused loudly
# --------------------------------------------------------------------------- #
def test_a_reindex_reads_and_keeps_its_rows_by_the_diff(monkeypatch):
    s = _session()
    a = _flushed_article(s, "re")
    ex = _Ex([_t("x", 2), _t("y")])
    index_article(s, a, extractor=ex, country=None, city=None, commit=False, inserted_in_this_transaction=True)
    s.commit()
    before = _rows(s, a.id)
    calls = _count_reads(monkeypatch)

    tally = index_article(s, a, extractor=ex, country=None, city=None)  # the re-index every other caller makes
    assert calls == [a.id], "a re-index must read the stored rows: the diff is what keeps an unchanged row untouched"
    assert (tally["mentions_kept"], tally["mentions_added"], tally["mentions_removed"]) == (2, 0, 0)
    assert _rows(s, a.id) == before


def test_the_flag_on_an_article_that_has_overlapping_rows_fails_on_the_unique_index():
    """If the caller's claim is false and the keywords OVERLAP, the failure is loud and no second row is stored."""
    s = _session()
    a = _flushed_article(s, "liar")
    ex = _Ex([_t("x", 2)])
    index_article(s, a, extractor=ex, country=None, city=None)
    with pytest.raises(IntegrityError):
        index_article(s, a, extractor=ex, country=None, city=None, commit=False, inserted_in_this_transaction=True)
    s.rollback()
    assert s.execute(select(func.count()).select_from(_MT).where(_MT.c.article_id == a.id)).scalar() == 1


# --------------------------------------------------------------------------- #
#  the batch path: no read for what it stored, and the proof the read would have been empty
# --------------------------------------------------------------------------- #
def test_the_read_the_batch_skips_would_have_returned_nothing_even_for_a_reused_article_id(monkeypatch):
    """THE PROOF. Before every ``index_article`` call of the batch, run the REAL read for that article and keep its answer. Then
    the case that could have made the claim false: delete the article that holds the highest id (its mention rows go with it by
    cascade), store a new batch, and the first new article gets that id AGAIN (SQLite re-uses the highest rowid after a delete)."""
    from src.database.session import session_scope

    # The premise the claim stands on, read from the real pooled connection rather than assumed.
    with session_scope() as s:
        assert s.execute(text("PRAGMA foreign_keys")).scalar() == 1, "foreign keys are off on the pooled connection: the cascade the claim needs is not there"

    _dom, _src, first = _ingest(monkeypatch, n=3)
    assert first["stored"] == 3
    with session_scope() as s:
        top = s.execute(select(func.max(Article.id))).scalar()
        assert s.execute(select(func.count()).select_from(_MT).where(_MT.c.article_id == top)).scalar() > 0, "ANTI-VACUITY: the top article has no mentions to lose"
        s.execute(delete(Article).where(Article.id == top))
        s.commit()
        assert s.execute(select(func.count()).select_from(_MT).where(_MT.c.article_id == top)).scalar() == 0, "the cascade did not remove the mentions"

    answers: dict[int, object] = {}
    real_read = store._read_mention_rows
    real_index = store.index_article

    def proving(session, article, **kw):
        answers[article.id] = real_read(session, article.id)  # what the skipped read would have answered, in the same transaction
        return real_index(session, article, **kw)

    monkeypatch.setattr(store, "index_article", proving)
    _dom2, _src2, second = _ingest(monkeypatch, n=3)

    assert second["stored"] == 3
    assert top in answers, f"ANTI-VACUITY: no article of the second batch got the id {top} again (got {sorted(answers)}), so the reuse case was not exercised"
    assert len(answers) == 3
    assert all(v == {} for v in answers.values()), f"a read the batch skipped would have returned rows: { {k: v for k, v in answers.items() if v} }"


def test_the_flag_does_not_see_orphan_rows_of_a_disjoint_keyword__it_is_the_callers_claim():
    """DOCUMENTED LIMIT (the Opus read of d8deefaa8, M1): rows left on an id by something that ran with foreign keys off, for a keyword the new
    article does not have, are not met by the unique index, so the flag keeps them. The call without the flag replaces them. The batch asks
    :func:`articles_with_stored_mentions` first so it never passes the flag for such an article."""
    for flagged in (True, False):
        s = _session()
        a = _flushed_article(s, "lost")
        index_article(s, a, extractor=_Ex([_t("old", 5)]), country=None, city=None)
        lost_id = a.id
        s.execute(text("PRAGMA foreign_keys=OFF"))
        s.execute(text("DELETE FROM articles WHERE id = :i"), {"i": lost_id})
        s.commit()
        s.expunge_all()
        b = _flushed_article(s, "new")
        assert b.id == lost_id, "ANTI-VACUITY: SQLite did not hand the id out again"
        index_article(s, b, extractor=_Ex([_t("fresh", 2)]), country=None, city=None, commit=False, inserted_in_this_transaction=flagged)
        s.commit()
        assert len(_rows(s, b.id)) == (2 if flagged else 1), f"flagged={flagged}"


def test_articles_with_stored_mentions_names_the_articles_that_have_rows_in_one_statement(monkeypatch):
    s = _session()
    with_rows = []
    for h in ("a", "b", "c"):
        art = _flushed_article(s, h)
        if h != "b":
            index_article(s, art, extractor=_Ex([_t("x")]), country=None, city=None, commit=False, inserted_in_this_transaction=True)
            with_rows.append(art.id)
        else:
            without = art.id
    s.commit()
    seen: list[str] = []
    from sqlalchemy import event as sa_event

    sa_event.listen(s.get_bind(), "before_cursor_execute", lambda *a: seen.append(a[2]))
    assert store.articles_with_stored_mentions(s, [*with_rows, without]) == set(with_rows)
    assert len(seen) == 1, f"one statement for the whole list, not one per article: {seen}"
    assert store.articles_with_stored_mentions(s, []) == set()
    assert len(seen) == 1, "an empty list asks nothing"


def test_articles_with_stored_mentions_chunks_a_long_list(monkeypatch):
    s = _session()
    ids = []
    for h in ("p", "q", "r", "t", "u"):
        art = _flushed_article(s, h)
        ids.append(art.id)
        if h in ("p", "u"):
            index_article(s, art, extractor=_Ex([_t("x")]), country=None, city=None, commit=False, inserted_in_this_transaction=True)
    s.commit()
    monkeypatch.setattr(store, "_MENTION_ID_CHUNK", 2)
    seen: list[str] = []
    from sqlalchemy import event as sa_event

    sa_event.listen(s.get_bind(), "before_cursor_execute", lambda *a: seen.append(a[2]))
    assert store.articles_with_stored_mentions(s, ids) == {ids[0], ids[4]}
    assert len(seen) == 3, "five ids in chunks of two are three statements"
