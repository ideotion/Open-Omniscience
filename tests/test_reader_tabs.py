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

            # The full sub-tab bar is present (corpus-of-1 facets), now incl. Mindmap.
            assert 'class="rtabs"' in body and 'role="tablist"' in body
            for key in ("read", "keywords", "mindmap", "sentiment", "related", "links"):
                assert f'data-rtab="{key}"' in body, f"missing the {key} tab"
                assert f'id="rp-{key}"' in body, f"missing the {key} pane"
            # The lazy analysis panes are marked for reader.js (incl. the mindmap).
            assert 'data-lazy="keywords"' in body and 'data-lazy="sentiment"' in body
            assert 'data-lazy="mindmap"' in body

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

            # The Mindmap tab fetches the article_ids-aware graph endpoint.
            g = client.get("/api/insights/graph?article_ids=1")
            assert g.status_code == 200
            gj = g.json()
            assert gj["level"] == "article"
            assert "nodes" in gj and "edges" in gj
            assert gj.get("method") and gj.get("caveat")
            # No composite score leaks into the graph payload.
            assert "score" not in gj and "relevance_score" not in gj
    finally:
        app.dependency_overrides.clear()


def test_article_graph_is_a_deterministic_outward_radial(tmp_path):
    """article_graph centres on the most-mentioned keyword and radiates OUTWARD —
    the mind-map rule (no cross-tangle): every edge is centre -> arm, sized by
    mention count, counts only (no score)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.analytics import queries as q
    from src.database.models import Article, Base, Keyword, KeywordMention, Source

    engine = create_engine(
        f"sqlite:///{tmp_path / 'g.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="N", domain="n.test"))
        s.add(
            Article(
                url="https://n.test/a", canonical_url="https://n.test/a", source_id=1,
                title="t", content="c", hash="h", language="en",
                created_at=datetime.now(UTC),
            )
        )
        s.commit()
        # Three non-stopword keywords with distinct mention counts.
        terms = [("election", 9), ("ballot", 5), ("turnout", 2)]
        for i, (term, n) in enumerate(terms, start=1):
            s.add(Keyword(id=i, term=term, normalized_term=term, language="en"))
            s.commit()
            s.add(KeywordMention(keyword_id=i, article_id=1, count=n))
        s.commit()

        g = q.article_graph(s, article_ids=[1])

    assert g["level"] == "article"
    centers = [n for n in g["nodes"] if n.get("center")]
    assert len(centers) == 1 and centers[0]["label"] == "election"  # most-mentioned leads
    # Every edge originates at the centre (always outward; a star, no cross-tangle).
    assert g["edges"] and all(e["a"] == "election" for e in g["edges"])
    arm_labels = {e["b"] for e in g["edges"]}
    assert arm_labels == {"ballot", "turnout"}
    # Sizes carry the real mention count; no composite score anywhere.
    assert centers[0]["mentions"] == 9
    assert not any("score" in n for n in g["nodes"])
