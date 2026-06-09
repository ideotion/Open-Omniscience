"""
Test the offline article view endpoint (renders the stored copy, no network).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, ArticleLink, Base, Source


def test_article_offline_view(tmp_path):
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'v.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="Example News", domain="ex.test"))
        s.commit()
        s.add(
            Article(
                url="https://ex.test/story",
                canonical_url="https://ex.test/story",
                source_id=1,
                title="A Big Story",
                content="First paragraph here.\nSecond paragraph here.",
                hash="h1",
                language="en",
                author="J. Doe",
                published_at=datetime(2024, 6, 1, tzinfo=UTC),
                created_at=datetime.now(UTC),
            )
        )
        s.commit()

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            r = client.get("/api/articles/1/view")
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/html")
            body = r.text
            assert "A Big Story" in body
            assert "First paragraph here." in body and "Second paragraph here." in body
            assert "Example News" in body and "J. Doe" in body
            assert "https://ex.test/story" in body  # original source link present
            assert "offline stored copy" in body  # provenance crumb
            assert "Captured" in body  # ingest-date metadata row
            # Leaving the corpus is an explicit, confirmed action.
            assert "EXTERNAL site on the public web" in body
            # Missing article -> 404.
            assert client.get("/api/articles/999/view").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_article_view_shows_co_citation(tmp_path):
    """When two articles cite the same external link, the reader flags the shared source."""
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'cc.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    shared = "https://shared.example/primary-report"
    with Sess() as s:
        s.add(Source(name="Wire", domain="wire.test"))
        s.commit()
        s.add_all(
            [
                Article(
                    url="https://wire.test/a",
                    canonical_url="https://wire.test/a",
                    source_id=1,
                    title="Article A",
                    content="Body A.",
                    hash="ha",
                    language="en",
                    created_at=datetime.now(UTC),
                ),
                Article(
                    url="https://wire.test/b",
                    canonical_url="https://wire.test/b",
                    source_id=1,
                    title="Article B",
                    content="Body B.",
                    hash="hb",
                    language="en",
                    created_at=datetime.now(UTC),
                ),
            ]
        )
        s.commit()
        # Both articles cite the same external URL (the co-citation signal).
        s.add_all(
            [
                ArticleLink(
                    article_id=1,
                    url=shared,
                    normalized_url=shared,
                    link_text="the report",
                    link_type="external",
                ),
                ArticleLink(
                    article_id=2,
                    url=shared,
                    normalized_url=shared,
                    link_text="the report",
                    link_type="external",
                ),
            ]
        )
        s.commit()

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            body = client.get("/api/articles/1/view").text
            assert "Sources this article cites" in body
            assert "shared.example" in body
            assert "also cited by 1 of your article(s)" in body  # in-degree 2 -> 1 other
    finally:
        app.dependency_overrides.clear()
