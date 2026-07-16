"""Restore must not crash when the incoming corpus has near-duplicate keyword rows
that collapse together (field bug 2026-07-16).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field report 2026-07-16: restoring an 18 GB "articles only" backup failed after
hours of merging with "UNIQUE constraint failed: keyword_mentions.keyword_id,
keyword_mentions.article_id". Root cause: ``keywords`` carries NO unique
constraint on (normalized_term, language) -- deliberately, so near-duplicate
keyword rows are reconciled later at the family/ring layer, never at the schema
layer (an accepted historical gap this project's own ledger documents at length).
So a large/old corpus can genuinely hold two keyword rows for the same
term+language. When such a corpus is the SOURCE of a restore, ``map_keywords``
(natural-key matched) collapses both incoming ids onto ONE local id; if both had
a mention/link row for the same article, the two candidate rows target the
identical (keyword_id, article_id) pair. The old plain ``NOT EXISTS`` guard only
checks the target table's PRE-STATEMENT state, so it does not stop the second
candidate from colliding with the first candidate's own insert within the SAME
statement, and the real unique index then aborts the whole restore. The fix
(mirroring the existing ``article_mentioned_dates`` P0-2 precedent) is
``INSERT OR IGNORE``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.backup.merge import merge_corpus
from src.database.models import Article, ArticleKeyword, Base, Keyword, KeywordMention, Source

_BATCH_META = {
    "artifact_kind": "oo-backup-2",
    "origin_fingerprint": "test",
    "app_version": "0.0.9",
    "alembic_rev": "head",
    "manifest": None,
}


def _corpus(path: Path):
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _add_article(s, *, hashv: str, content: str) -> int:
    src = s.query(Source).first()
    if src is None:
        src = Source(name="Wire", domain="wire.example")
        s.add(src)
        s.flush()
    a = Article(
        url=f"https://wire.example/{hashv}",
        canonical_url=f"https://wire.example/{hashv}",
        source_id=src.id,
        title="t",
        content=content,
        hash=hashv,
        language="en",
        created_at=datetime.now(UTC),
    )
    s.add(a)
    s.flush()
    return int(a.id)


def _counts(path: Path, table: str) -> int:
    engine = create_engine(f"sqlite:///{path}", future=True)
    try:
        with engine.connect() as c:
            return int(c.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar())  # noqa: S608
    finally:
        engine.dispose()


def test_incoming_corpus_with_duplicate_keyword_rows_sharing_a_mention_does_not_abort(tmp_path):
    """The exact field-test regression: the INCOMING corpus carries two keyword rows
    for the same (normalized_term, language) -- a historical near-duplicate, e.g. from
    a race predating the single-writer gate -- each with a mention/link on the SAME
    article. Both incoming ids collapse onto one new local keyword id; the merge must
    keep exactly one row per table, never raise, and never lose the article/keyword
    pairing entirely."""
    working = tmp_path / "working.db"
    staged = tmp_path / "staged.db"

    _corpus(working)()  # empty local corpus (just the schema)

    Maker = _corpus(staged)
    with Maker() as s:
        aid = _add_article(s, hashv="H1", content="petrol prices rose sharply today")
        kw_a = Keyword(term="petrol", normalized_term="petrol", language="en")
        kw_b = Keyword(term="Petrol", normalized_term="petrol", language="en")  # near-duplicate
        s.add_all([kw_a, kw_b])
        s.flush()
        s.add(KeywordMention(keyword_id=kw_a.id, article_id=aid, count=3))
        s.add(KeywordMention(keyword_id=kw_b.id, article_id=aid, count=2))
        s.add(ArticleKeyword(article_id=aid, keyword_id=kw_a.id, frequency=3))
        s.add(ArticleKeyword(article_id=aid, keyword_id=kw_b.id, frequency=2))
        s.commit()

    # Must not raise (was: sqlite3.IntegrityError UNIQUE constraint failed:
    # keyword_mentions.keyword_id, keyword_mentions.article_id).
    counts, _batch = merge_corpus(staged, working, _BATCH_META)

    assert counts["keywords"]["new"] == 1  # both incoming rows collapse to one local keyword
    # Exactly one mention/link row per table survives -- OR IGNORE dropped the collision,
    # it did not abort the whole restore and it did not double-insert either.
    assert _counts(working, "keyword_mentions") == 1
    assert _counts(working, "article_keywords") == 1
    assert counts["keyword_mentions"]["new"] == 1
    assert counts["article_keyword_links"]["new"] == 1


def test_target_already_has_a_mention_and_incoming_duplicate_still_does_not_abort(tmp_path):
    """The local corpus ALREADY has a keyword_mention for this article+keyword (from a
    prior, earlier restore or from live ingest). A LATER restore of a corpus whose own
    keywords table carries a near-duplicate for the same term+language must still merge
    additively without raising -- the pre-existing NOT EXISTS path and the new
    intra-statement collapse must compose safely."""
    working = tmp_path / "working.db"
    staged = tmp_path / "staged.db"

    MakerW = _corpus(working)
    with MakerW() as s:
        aid_local = _add_article(s, hashv="H1", content="petrol prices rose sharply today")
        kw = Keyword(term="petrol", normalized_term="petrol", language="en")
        s.add(kw)
        s.flush()
        s.add(KeywordMention(keyword_id=kw.id, article_id=aid_local, count=1))
        s.commit()

    Maker = _corpus(staged)
    with Maker() as s:
        aid = _add_article(s, hashv="H1", content="petrol prices rose sharply today")  # dedups to local
        kw_a = Keyword(term="petrol", normalized_term="petrol", language="en")
        kw_b = Keyword(term="Petrol", normalized_term="petrol", language="en")
        s.add_all([kw_a, kw_b])
        s.flush()
        s.add(KeywordMention(keyword_id=kw_a.id, article_id=aid, count=5))
        s.add(KeywordMention(keyword_id=kw_b.id, article_id=aid, count=9))
        s.commit()

    counts, _batch = merge_corpus(staged, working, _BATCH_META)

    assert _counts(working, "keyword_mentions") == 1  # the local row is kept; nothing added or lost
    assert counts["keyword_mentions"]["new"] == 0
