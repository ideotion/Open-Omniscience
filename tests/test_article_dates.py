"""Tests for article date-tags: extraction -> store -> confirm/reject -> filter.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base, Source
from src.timemap import datestore

TODAY = date(2026, 6, 9)


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'd.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="Wire", domain="wire.test"))
        s.commit()
        s.add(
            Article(
                url="https://wire.test/a",
                canonical_url="https://wire.test/a",
                source_id=1,
                title="Retrospective",
                hash="h1",
                language="en",
                content="The attacks of 11 September 2001 echoed for years; by March 2003 war had begun.",
                published_at=datetime(2024, 6, 1, tzinfo=UTC),
                created_at=datetime.now(UTC),
            )
        )
        s.add(
            Article(
                url="https://wire.test/b",
                canonical_url="https://wire.test/b",
                source_id=1,
                title="No dates here",
                hash="h2",
                language="en",
                content="A story with no explicit calendar dates at all.",
                published_at=datetime(2024, 6, 2, tzinfo=UTC),
                created_at=datetime.now(UTC),
            )
        )
        s.commit()
    return Sess


def test_store_extract_and_idempotent(tmp_path):
    Sess = _session(tmp_path)
    with Sess() as db:
        art = db.get(Article, 1)
        added = datestore.store_for_article(db, art, today=TODAY)
        assert added == 2  # 2001-09-11 (day) + 2003-03 (month)
        # re-running must not duplicate
        assert datestore.store_for_article(db, art, today=TODAY) == 0
        tags = datestore.for_article(db, 1)
        assert {t["date"] for t in tags} == {"2001-09-11", "2003-03-01"}
        assert all(t["status"] == "candidate" and t["snippet"] for t in tags)
        # an article without dates stores nothing
        assert datestore.store_for_article(db, db.get(Article, 2), today=TODAY) == 0


def test_store_inside_caller_savepoint_keeps_transaction_usable(tmp_path):
    """Regression (CI red 2026-07-17, the #691 follow-up): index_article's
    when/where/who pass wraps this store in session.begin_nested(). The store's
    internal commit used to CLOSE that caller's savepoint context, so the very
    next statement raised "Can't operate on closed transaction inside context
    manager" — swallowed upstream by design, silently costing every article
    with a newly-extracted date its places/entities. Inside a caller-owned
    savepoint the store must flush (never commit) and the caller's transaction
    must stay usable; the rows persist with the caller's own commit."""
    Sess = _session(tmp_path)
    with Sess() as db:
        art = db.get(Article, 1)
        with db.begin_nested():
            added = datestore.store_for_article(db, art, today=TODAY)
            assert added == 2
            # The caller's transaction must remain usable for further statements
            # (the WWW pass stores places/entities right after this call).
            assert db.query(Article).count() == 2
        db.commit()
    # The flushed rows joined the caller's transaction and survived its commit.
    with Sess() as db:
        tags = datestore.for_article(db, 1)
        assert {t["date"] for t in tags} == {"2001-09-11", "2003-03-01"}


def test_store_uses_article_anchor_and_language(tmp_path):
    """Ingest-time storage must feed the extractor the article's OWN date + language.

    Relative ("hier"/yesterday), no-year ("15 septembre") and language-ambiguous
    numeric ("11/06/2026" = DMY in fr) dates resolve ONLY when the anchor +
    language are passed (test_dateextract proves they are otherwise skipped, never
    guessed). This is the regression guard for the ingest wiring: a refactor that
    drops the anchor would silently regress date capture to explicit-only.
    """
    engine = create_engine(
        f"sqlite:///{tmp_path / 'anchor.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as db:
        db.add(Source(name="Wire", domain="wire.test"))
        db.commit()
        db.add(
            Article(
                url="https://wire.test/x",
                canonical_url="https://wire.test/x",
                source_id=1,
                title="Anchored forms",
                hash="hx",
                language="fr",
                content="La réunion était hier. Le sommet ouvre le 15 septembre. Vote le 11/06/2026.",
                published_at=datetime(2024, 6, 10, tzinfo=UTC),  # the anchor
                created_at=datetime.now(UTC),
            )
        )
        db.commit()
        added = datestore.store_for_article(db, db.get(Article, 1), today=TODAY)
        dates = {t["date"] for t in datestore.for_article(db, 1)}
        assert "2024-06-09" in dates  # "hier" resolved against the publication date
        assert "2024-09-15" in dates  # "15 septembre" — year filled from the anchor
        assert "2026-06-11" in dates  # "11/06/2026" read as DMY because language=fr
        assert added >= 3


def test_confirm_reject_preserved_on_reindex(tmp_path):
    Sess = _session(tmp_path)
    with Sess() as db:
        datestore.store_for_article(db, db.get(Article, 1), today=TODAY)
        tags = datestore.for_article(db, 1)
        tid = tags[0]["id"]
        assert datestore.set_status(db, tid, "confirmed")["status"] == "confirmed"
        # re-index must not reset the human decision
        datestore.store_for_article(db, db.get(Article, 1), today=TODAY)
        again = {t["id"]: t for t in datestore.for_article(db, 1)}
        assert again[tid]["status"] == "confirmed"
        assert datestore.set_status(db, 999999, "confirmed") is None


def test_articles_for_date_filter(tmp_path):
    Sess = _session(tmp_path)
    with Sess() as db:
        datestore.store_for_article(db, db.get(Article, 1), today=TODAY)
        hits = datestore.articles_for_date(db, date_str="2001-09-11")
        assert len(hits) == 1 and hits[0]["article_id"] == 1
        assert datestore.articles_for_date(db, date_str="1999-01-01") == []
        # precision filter
        assert datestore.articles_for_date(db, date_str="2003-03-01", precision="day") == []
        assert len(datestore.articles_for_date(db, date_str="2003-03-01", precision="month")) == 1


def test_index_recent_counts(tmp_path):
    Sess = _session(tmp_path)
    with Sess() as db:
        res = datestore.index_recent(db, limit=50, today=TODAY)
        assert res["scanned"] == 2
        assert res["articles_with_dates"] == 1  # only article 1 has dates
        assert res["new_tags"] == 2


def test_deleting_source_cascades_to_date_tags(tmp_path):
    # Source -> Article -> ArticleMentionedDate must all cascade on an ORM delete,
    # leaving no orphaned date tags.
    from src.database.models import ArticleMentionedDate

    Sess = _session(tmp_path)
    with Sess() as db:
        datestore.store_for_article(db, db.get(Article, 1), today=TODAY)
        assert db.query(ArticleMentionedDate).count() == 2
        db.delete(db.get(Source, 1))  # cascades to its articles, then their date tags
        db.commit()
        assert db.query(Article).count() == 0
        assert db.query(ArticleMentionedDate).count() == 0


def test_api_flow(tmp_path):
    from src.database.session import get_db

    Sess = _session(tmp_path)

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as c:
            assert c.post("/api/article-dates/article/1").json()["added"] == 2
            tags = c.get("/api/article-dates/article/1").json()["tags"]
            tid = tags[0]["id"]
            assert c.post(f"/api/article-dates/{tid}/confirm").json()["status"] == "confirmed"
            assert c.post(f"/api/article-dates/{tid}/reject").json()["status"] == "rejected"
            assert c.post("/api/article-dates/999999/confirm").status_code == 404
            byd = c.get("/api/article-dates/by-date?date=2001-09-11").json()
            assert byd["count"] == 1 and byd["articles"][0]["article_id"] == 1
            idx = c.post("/api/article-dates/index").json()
            assert idx["scanned"] == 2
    finally:
        app.dependency_overrides.pop(get_db, None)
