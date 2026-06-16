"""
Reader analysis tabs (Tier 1, PR1).

The offline article reader gained a sub-tab bar (Read · Keywords · Sentiment ·
Related · Links) backed by a self-contained /static/reader.js + reader.css. These
tests prove: (1) the reader page renders the tab structure + references the cached
assets + carries the article id reader.js needs; (2) the new static assets are
actually served (a 404 would silently break the tabs); (3) the existing reader
content is preserved (now inside the Read pane), so nothing is lost. node --check
proves reader.js's syntax separately.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base, Source


def _seed(tmp_path, name="r.db"):
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
                content="First paragraph here.\nSecond paragraph here.",
                hash="h1",
                language="en",
                author="J. Doe",
                published_at=datetime(2024, 6, 1, tzinfo=UTC),
                created_at=datetime.now(UTC),
            )
        )
        s.commit()
    return Sess


def test_reader_renders_tabs_and_references_assets(tmp_path):
    from src.api.main import app
    from src.database.session import get_db

    Sess = _seed(tmp_path)

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            body = client.get("/api/articles/1/view").text

            # The cached assets are referenced (same /static/ pattern as app.js).
            assert '<link rel="stylesheet" href="/static/reader.css">' in body
            assert '<script src="/static/reader.js" defer></script>' in body
            # reader.js needs the article id off the wrapper.
            assert 'data-article-id="1"' in body

            # The full sub-tab bar is present (corpus-of-1 facets).
            assert 'class="rtabs"' in body and 'role="tablist"' in body
            for key in ("read", "keywords", "sentiment", "related", "links"):
                assert f'data-rtab="{key}"' in body, f"missing the {key} tab"
                assert f'id="rp-{key}"' in body, f"missing the {key} pane"
            # The two new analysis panes lazy-load; they are marked for reader.js.
            assert 'data-lazy="keywords"' in body and 'data-lazy="sentiment"' in body

            # Existing reader content is preserved (now inside the Read pane).
            assert "A Big Story" in body
            assert "First paragraph here." in body and "Second paragraph here." in body
            assert "Example News" in body and "J. Doe" in body
            assert "EXTERNAL site on the public web" in body  # external-link guard intact
    finally:
        app.dependency_overrides.clear()


def test_reader_static_assets_are_served():
    """reader.js / reader.css must serve (a 404 would silently break the tabs)."""
    from src.api.main import app

    c = TestClient(app)
    for path, ctype in (("/static/reader.js", "javascript"), ("/static/reader.css", "css")):
        r = c.get(path)
        assert r.status_code == 200, f"{path} must be served"
        assert ctype in r.headers.get("content-type", "").lower(), (
            f"{path} must be served with a {ctype} content-type"
        )


def test_reader_lazy_endpoints_accept_single_article(tmp_path):
    """The tabs fetch the article_ids-aware insights endpoints for one article —
    prove they accept a single id and carry the honest caveat (informed consent)."""
    from src.api.main import app
    from src.database.session import get_db

    Sess = _seed(tmp_path, "r2.db")

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            kw = client.get("/api/insights/corpus-keywords?article_ids=1")
            assert kw.status_code == 200
            assert "terms" in kw.json() and "caveat" in kw.json()

            sent = client.get("/api/insights/corpus-sentiment?article_ids=1")
            assert sent.status_code == 200
            # The VADER English-only disclosure travels with the data (B1 honesty).
            assert "VADER" in sent.json().get("caveat", "")
    finally:
        app.dependency_overrides.clear()
