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

from src.database.models import (
    Article,
    ArticleEntity,
    ArticleLink,
    ArticleMentionedPlace,
    Base,
    Source,
)


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


def _engine_with_article(tmp_path, name):
    engine = create_engine(
        f"sqlite:///{tmp_path / name}", future=True, connect_args={"check_same_thread": False}
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
                content="Some body mentioning Paris and Angela Merkel.",
                hash="hwww",
                language="en",
                created_at=datetime.now(UTC),
            )
        )
        s.commit()
    return Sess


def test_reader_reads_stored_when_where_who_without_recomputing(tmp_path, monkeypatch):
    """An article WITH persisted T12 rows is rendered from the DB, NOT recomputed.

    We make the live extractors raise; the reader must still surface the stored
    place + entities, proving it read article_mentioned_places / article_entities.
    """
    from src.database.session import get_db

    Sess = _engine_with_article(tmp_path, "stored.db")
    with Sess() as s:
        s.add(
            ArticleMentionedPlace(
                article_id=1,
                name="Storedville",
                country="fr",
                kind="city",
                mentions=3,
                snippet="…near Storedville…",
                note="gazetteer match",
                extractor="lexical-v1",
            )
        )
        s.add(
            ArticleEntity(
                article_id=1,
                name="Stored Person",
                entity_class="person",
                mentions=2,
                note="capitalized bigram",
                extractor="lexical-v1",
            )
        )
        s.add(
            ArticleEntity(
                article_id=1,
                name="Stored Org Inc",
                entity_class="organization",
                mentions=4,
                note="org suffix",
                extractor="lexical-v1",
            )
        )
        s.commit()

    def _boom(*a, **k):  # pragma: no cover - must never be called
        raise AssertionError("live extractor recomputed despite stored rows")

    monkeypatch.setattr("src.timemap.locextract.extract_locations", _boom)
    monkeypatch.setattr("src.timemap.entextract.extract_entities", _boom)

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
            body = r.text
            assert "Storedville" in body  # stored place rendered
            assert "Stored Person" in body  # stored person rendered
            assert "Stored Org Inc" in body  # stored organization rendered
    finally:
        app.dependency_overrides.clear()


def test_reader_falls_back_to_live_when_no_stored_rows(tmp_path, monkeypatch):
    """An article with NO persisted T12 rows falls back to the live extractor."""
    from src.database.session import get_db

    Sess = _engine_with_article(tmp_path, "fallback.db")  # no place/entity rows

    calls = {"loc": 0, "ent": 0}

    def _fake_locs(*a, **k):
        calls["loc"] += 1
        return [{"name": "Fallbackton", "country": "us", "kind": "city", "mentions": 1}]

    def _fake_ents(*a, **k):
        calls["ent"] += 1
        return {
            "people": [{"name": "Fallback Person", "mentions": 1}],
            "organizations": [],
        }

    monkeypatch.setattr("src.timemap.locextract.extract_locations", _fake_locs)
    monkeypatch.setattr("src.timemap.entextract.extract_entities", _fake_ents)

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
            body = r.text
            assert "Fallbackton" in body  # live-computed place surfaced
            assert "Fallback Person" in body  # live-computed entity surfaced
            assert calls["loc"] == 1 and calls["ent"] == 1  # fallback ran
    finally:
        app.dependency_overrides.clear()
