"""Restore must not crash on the article_mentioned_dates UNIQUE collision (P0-2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field test 2026-06-22: the maintainer's OWN backup failed to preview with
"UNIQUE constraint failed: article_mentioned_dates.article_id, mentioned_on,
precision". Root cause: the merge dedup key checked ``snippet`` instead of
``precision``, so an incoming date row with the same (article, date, precision)
but a different snippet passed the NOT-EXISTS guard and then violated the real
unique constraint. The fix matches the constraint exactly + uses INSERT OR IGNORE
so an incoming corpus carrying its own duplicates can't abort the restore either.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.backup.merge import merge_corpus
from src.database.models import Article, ArticleMentionedDate, Base, Source

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


def _date_count(path: Path) -> int:
    engine = create_engine(f"sqlite:///{path}", future=True)
    try:
        with engine.connect() as c:
            return int(c.execute(text("SELECT COUNT(*) FROM article_mentioned_dates")).scalar())
    finally:
        engine.dispose()


def test_deduped_article_same_date_precision_different_snippet_does_not_collide(tmp_path):
    """An incoming article that dedups to a LOCAL article, whose date+precision
    already exists locally but with a different snippet, must NOT crash the merge
    (the exact field-test regression)."""
    working = tmp_path / "working.db"
    staged = tmp_path / "staged.db"

    Maker = _corpus(working)
    with Maker() as s:
        aid = _add_article(s, hashv="H1", content="same bytes")
        s.add(
            ArticleMentionedDate(
                article_id=aid, mentioned_on=date(2026, 1, 1), precision="day",
                snippet="local snippet", status="candidate",
            )
        )
        s.commit()

    Maker2 = _corpus(staged)
    with Maker2() as s:
        aid = _add_article(s, hashv="H1", content="same bytes")  # dedups to local H1
        s.add(
            ArticleMentionedDate(
                article_id=aid, mentioned_on=date(2026, 1, 1), precision="day",
                snippet="DIFFERENT snippet", status="candidate",  # same date+precision
            )
        )
        s.commit()

    # Must not raise (was: sqlite3.IntegrityError UNIQUE ... article_id,mentioned_on,precision).
    counts, _batch = merge_corpus(staged, working, _BATCH_META)
    # Additive: the local row is kept; the colliding incoming one is skipped (a duplicate
    # under the real constraint), so the working copy still has exactly one date row.
    assert _date_count(working) == 1
    assert counts["article_mentioned_dates"]["new"] == 0


def test_incoming_corpus_with_its_own_duplicate_date_rows_does_not_abort(tmp_path):
    """An incoming corpus whose article_mentioned_dates itself carries two rows with
    the same (article, date, precision) — an OLD backup predating the constraint —
    must merge via INSERT OR IGNORE rather than aborting the whole restore."""
    working = tmp_path / "working.db"
    staged = tmp_path / "staged.db"

    _corpus(working)()  # empty local corpus (just the schema, WITH the constraint)

    Maker = _corpus(staged)
    with Maker() as s:
        aid = _add_article(s, hashv="NEW1", content="new article body")
        s.commit()

    # Simulate a constraint-predating backup: rebuild the staged date table WITHOUT
    # the unique constraint, then insert two rows sharing (article, date, precision).
    eng = create_engine(f"sqlite:///{staged}", future=True)
    with eng.begin() as c:
        c.execute(text("DROP TABLE article_mentioned_dates"))
        c.execute(
            text(
                "CREATE TABLE article_mentioned_dates ("
                " id INTEGER PRIMARY KEY, article_id INTEGER NOT NULL,"
                " mentioned_on DATE NOT NULL, precision VARCHAR(10) NOT NULL DEFAULT 'day',"
                " snippet VARCHAR(300), confidence FLOAT, extractor VARCHAR(50),"
                " status VARCHAR(20), created_at DATETIME)"
            )
        )
        c.execute(
            text(
                "INSERT INTO article_mentioned_dates"
                " (article_id, mentioned_on, precision, snippet, status) VALUES"
                " (:a,'2026-02-02','day','A','candidate'),"
                " (:a,'2026-02-02','day','B','candidate')"
            ).bindparams(a=aid)
        )
    eng.dispose()
    assert _date_count(staged) == 2  # the incoming corpus genuinely has the duplicate

    # The working DB HAS the constraint; INSERT OR IGNORE must keep one, drop the dup,
    # and never abort the restore.
    counts, _batch = merge_corpus(staged, working, _BATCH_META)
    assert _date_count(working) == 1
    assert counts["article_mentioned_dates"]["new"] == 1
