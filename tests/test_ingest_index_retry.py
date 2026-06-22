"""On-ingest indexing must RETRY a transient lock, never drop the data.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field log 2026-06-17 (P0-1): 62 "keyword indexing on ingest failed" + 87 "link
indexing on ingest failed" + several scheduler "transaction has been rolled
back ... Original exception was: database is locked". The single-writer gate
(keystone #1, ``do_orm_execute``, merged 2026-06-18) prevents the lock in the
first place, but the best-effort indexing sub-steps SWALLOWED a lock with a
rollback -- so on the rare residual lock (gate disabled, a restore's FTS rebuild
racing the live engine) the already-fetched article lost its keyword / link /
when-where-who indexing.

These tests pin the defence-in-depth: ``_maybe_index_keywords`` /
``_maybe_index_links`` now run their idempotent work through
``run_write_with_retry`` (so a transient lock is RETRIED, not dropped), and
``index_article`` re-raises a lock from the when/where/who block instead of
swallowing it (which used to poison the final commit). A genuine non-lock
extraction bug must still be swallowed (it must never cost the article its
keywords).
"""

from __future__ import annotations

import uuid

from sqlalchemy.exc import OperationalError

import src.analytics.store as store_mod
import src.timemap.datestore as datestore_mod
from src.database.models import Article, KeywordMention, Source
from src.database.session import init_db, session_scope
from src.ingest.pipeline import _maybe_index_keywords


def _locked() -> OperationalError:
    """An OperationalError that ``is_locked_error`` recognises as a transient lock."""
    return OperationalError("INSERT INTO keyword_mentions ...", {}, Exception("database is locked"))


def _seed_article(content: str) -> tuple[int, int]:
    """Persist one Source + one Article; return (source_id, article_id)."""
    tag = "rt" + uuid.uuid4().hex[:8]
    with session_scope() as s:
        src = Source(name=f"src-{tag}", domain=f"{tag}.example", enabled=True, language="en")
        s.add(src)
        s.flush()
        art = Article(
            url=f"https://{tag}.example/a",
            canonical_url=f"https://{tag}.example/a",
            source_id=src.id,
            title="An election report",
            content=content,
            hash=tag,
            language="en",
        )
        s.add(art)
        s.flush()
        return int(src.id), int(art.id)


def test_keyword_indexing_retries_a_transient_lock_and_loses_no_data(monkeypatch):
    """A 'database is locked' on the FIRST index attempt must be retried (the index
    is idempotent), so the article keeps its keywords -- not the 2026-06-17 loss."""
    init_db()
    source_id, article_id = _seed_article(
        "The election commission met. Inflation rose. The election result is contested."
    )

    real_index = store_mod.index_article
    calls = {"n": 0}

    def flaky_index(session, article, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _locked()  # transient lock on the first try
        return real_index(session, article, **kw)

    monkeypatch.setattr(store_mod, "index_article", flaky_index)

    with session_scope() as s:
        src = s.get(Source, source_id)
        art = s.get(Article, article_id)
        _maybe_index_keywords(s, art, src)

    assert calls["n"] >= 2, "the transient lock was not retried"
    with session_scope() as s:
        n = s.query(KeywordMention).filter_by(article_id=article_id).count()
    assert n > 0, "keywords were dropped despite the retry -- the field-log loss is back"


def test_exhausted_lock_degrades_gracefully_without_breaking_ingestion(monkeypatch):
    """If every retry still locks, indexing logs + gives up -- ingestion is never
    broken (the best-effort contract). The article survives; only its index is
    (this once) missing, recoverable by a re-index/backfill pass."""
    init_db()
    source_id, article_id = _seed_article("Persistent lock article about climate policy.")

    def always_locked(session, article, **kw):
        raise _locked()

    monkeypatch.setattr(store_mod, "index_article", always_locked)
    # Keep the test fast: a handful of attempts with no real backoff sleep.
    monkeypatch.setattr("src.database.write.DEFAULT_ATTEMPTS", 2)
    monkeypatch.setattr("src.database.write.DEFAULT_BASE_DELAY_S", 0.0)

    with session_scope() as s:
        src = s.get(Source, source_id)
        art = s.get(Article, article_id)
        # Must NOT raise: the outer best-effort handler swallows the exhausted lock.
        _maybe_index_keywords(s, art, src)

    with session_scope() as s:
        assert s.get(Article, article_id) is not None  # the article itself is intact


def test_nonlock_when_where_who_error_still_keeps_keywords(monkeypatch):
    """A NON-lock failure in the when/where/who block must stay swallowed: a bad
    date parse must never cost the article its keyword mentions (no regression of
    the deliberate best-effort WWW design)."""
    init_db()
    source_id, article_id = _seed_article("The summit on trade and tariffs and sanctions.")

    def boom(*_a, **_k):
        raise ValueError("synthetic extraction bug, not a lock")

    # store_for_article is imported inside index_article from this module.
    monkeypatch.setattr(datestore_mod, "store_for_article", boom)

    from src.analytics.extract import get_extractor

    with session_scope() as s:
        art = s.get(Article, article_id)
        # index_article must NOT raise on a non-lock WWW error; it commits keywords.
        store_mod.index_article(s, art, extractor=get_extractor("baseline"), country="fr")

    with session_scope() as s:
        n = s.query(KeywordMention).filter_by(article_id=article_id).count()
    assert n > 0, "a non-lock WWW error wrongly cost the article its keywords"
