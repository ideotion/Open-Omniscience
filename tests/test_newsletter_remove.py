"""Live 'remove imported newsletters' maintenance action (brief §2.B).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Restore is additive-only, so excluding newsletters from a *backup* never purges the
*live* corpus. This action does — it removes the .eml + mailbox source articles AND
every dependent row (counters reconciled, FTS cleaned, the empty source rows kept so
a clean re-import re-attaches), closing the maintainer's "replace the faulty ones"
loop.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.models import Article, Base, Keyword, KeywordMention, Source
from src.ingest.email import (
    NEWSLETTER_SOURCE_DOMAINS,
    count_imported_newsletters,
    delete_imported_newsletters,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine, future=True)()
    sess._engine_for_test = engine  # type: ignore[attr-defined]
    return sess


def _src(db, name, domain, enabled=True):
    s = Source(name=name, domain=domain, enabled=enabled)
    db.add(s)
    db.commit()
    return s


def _article(db, source_id, h, text_):
    a = Article(
        url=f"https://x.test/{h}",
        canonical_url=f"https://x.test/{h}",
        source_id=source_id,
        title=f"T-{h}",
        content=text_,
        hash=h,
        language="en",
        published_at=datetime(2024, 3, 1, tzinfo=UTC),
        created_at=datetime.now(UTC),
    )
    db.add(a)
    db.commit()
    return a


def _seed(db):
    nl = _src(db, "Imported newsletters (.eml)", "newsletters.import.local", enabled=False)
    mb = _src(db, "Mailbox", "mailbox.import.local", enabled=False)
    web = _src(db, "Web", "news.test", enabled=True)
    ex = BaselineExtractor()
    a1 = _article(db, nl.id, "n1", "Election coverage and inflation in the newsletter today.")
    a2 = _article(db, mb.id, "n2", "Drought and climate policy from the mailbox digest.")
    a3 = _article(db, web.id, "w1", "Election coverage from the web about inflation worldwide.")
    for a in (a1, a2, a3):
        index_article(db, a, extractor=ex)
    return nl, mb, web, a1, a2, a3


def test_removes_only_newsletter_articles_and_dependents(db):
    nl, mb, web, a1, a2, a3 = _seed(db)
    a1_id, a2_id, a3_id = a1.id, a2.id, a3.id  # capture before the rows are deleted
    assert count_imported_newsletters(db) == 2

    res = delete_imported_newsletters(db)
    assert res["removed_articles"] == 2

    # Only the web article survives.
    assert {a.id for a in db.query(Article).all()} == {a3_id}
    # Dependent mentions of the removed articles are gone; the web article's remain.
    assert (
        db.query(KeywordMention)
        .filter(KeywordMention.article_id.in_([a1_id, a2_id]))
        .count()
        == 0
    )
    assert db.query(KeywordMention).filter_by(article_id=a3_id).count() > 0
    # The (now empty) source rows are LEFT so a clean re-import re-attaches.
    domains = {s.domain for s in db.query(Source).all()}
    assert set(NEWSLETTER_SOURCE_DOMAINS) <= domains


def test_denormalised_counters_are_reconciled_after_removal(db):
    _seed(db)
    delete_imported_newsletters(db)
    # Every keyword counter equals the live aggregate (no over-count drift).
    for kw in db.query(Keyword).all():
        live_m = (
            db.query(func.coalesce(func.sum(KeywordMention.count), 0))
            .filter_by(keyword_id=kw.id)
            .scalar()
        )
        live_a = (
            db.query(func.count(func.distinct(KeywordMention.article_id)))
            .filter_by(keyword_id=kw.id)
            .scalar()
        )
        assert kw.mention_count == live_m
        assert kw.article_count == live_a


def test_fts_index_is_cleaned_for_removed_articles(db):
    from src.database.fts import ensure_fts

    ensure_fts(db._engine_for_test)  # type: ignore[attr-defined]
    nl, mb, web, a1, a2, a3 = _seed(db)
    # FTS is populated by the AFTER INSERT trigger (rebuild covers pre-trigger rows).
    db.execute(text("INSERT INTO article_fts(article_fts) VALUES ('rebuild')"))
    db.commit()
    before = db.execute(
        text("SELECT rowid FROM article_fts WHERE article_fts MATCH 'mailbox'")
    ).fetchall()
    assert any(r[0] == a2.id for r in before)

    delete_imported_newsletters(db)
    after = db.execute(
        text("SELECT rowid FROM article_fts WHERE article_fts MATCH 'mailbox'")
    ).fetchall()
    assert all(r[0] != a2.id for r in after)


def test_live_and_backup_newsletter_domains_agree():
    """Single source of truth: the live-remove action and the backup-exclude filter must
    target the SAME source domains, or one would miss a bucket the other purges."""
    from src.backup.artifact import _NEWSLETTER_DOMAINS

    assert tuple(_NEWSLETTER_DOMAINS) == tuple(NEWSLETTER_SOURCE_DOMAINS)


def test_no_newsletter_source_is_a_noop(db):
    _src(db, "Web", "news.test")
    a = _article(db, 1, "w1", "Just a web article about elections and inflation.")
    index_article(db, a, extractor=BaselineExtractor())
    res = delete_imported_newsletters(db)
    assert res["removed_articles"] == 0
    assert db.query(Article).count() == 1
