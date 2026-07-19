"""Source-laundering detection (manipulation-pattern card #6, ruling #13).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Names the STRUCTURE: many DISTINCT sources citing one external origin = apparent
corroboration that isn't independent. These tests pin the honest gates — distinct
sources (not article count) is the measure, both gates apply, social/storefront
origins are excluded, no score — and the exact article set is returned.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.laundering import find_source_laundering
from src.database.models import Article, ArticleLink, Base, Source


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()


def _src(db, sid, domain):
    db.add(Source(id=sid, name=f"Src{sid}", domain=domain))
    db.commit()


def _art_citing(db, aid, source_id, url):
    db.add(Article(id=aid, url=f"https://x/{aid}", canonical_url=f"https://x/{aid}",
                   source_id=source_id, title="T", content="c", hash=f"h{aid}", language="en"))
    db.add(ArticleLink(article_id=aid, url=url, normalized_url=url, link_type="external"))
    db.commit()


def test_laundering_fires_on_distinct_sources(db):
    for sid in (1, 2, 3):
        _src(db, sid, f"src{sid}.test")
    # 3 articles from 3 DISTINCT sources all cite the same external origin.
    _art_citing(db, 1, 1, "https://origin.example/claim")
    _art_citing(db, 2, 2, "https://origin.example/claim")
    _art_citing(db, 3, 3, "https://origin.example/claim")
    out = find_source_laundering(db, min_sources=3, min_articles=3)
    assert out["count"] == 1
    c = out["clusters"][0]
    assert c["origin"] == "https://origin.example/claim"
    assert c["distinct_sources"] == 3 and c["n_articles"] == 3
    assert sorted(c["article_ids"]) == [1, 2, 3]
    assert "independent corroboration" in out["caveat"] and "never intent" in out["caveat"]
    # No score anywhere.
    assert not any("score" in k for k in c)


def test_one_chatty_source_cannot_launder(db):
    _src(db, 1, "src1.test")
    # 5 articles from ONE source citing the same origin -> distinct_sources = 1, no fire.
    for aid in range(1, 6):
        _art_citing(db, aid, 1, "https://origin.example/claim")
    assert find_source_laundering(db, min_sources=3, min_articles=3)["count"] == 0


def test_social_and_commerce_origins_excluded(db):
    for sid in (1, 2, 3):
        _src(db, sid, f"src{sid}.test")
    # 3 distinct sources all link twitter — excluded as noise, not corroboration.
    for aid, sid in ((1, 1), (2, 2), (3, 3)):
        _art_citing(db, aid, sid, "https://twitter.com/someone/status/1")
    assert find_source_laundering(db, min_sources=3, min_articles=3)["count"] == 0


def test_infrastructure_origins_excluded(db):
    """2026-07-18 field export (Leads-calibration §0 rows 1-3): a live corpus surfaced
    policies.google.com and addtoany.com as "source-laundering origins" — boilerplate/
    widget pages everyone links, never a corroborating citation."""
    for sid in (1, 2, 3):
        _src(db, sid, f"src{sid}.test")
    urls = (
        "https://policies.google.com/privacy",
        "https://www.addtoany.com/share",
        "https://creativecommons.org/licenses/by/4.0/",
    )
    for base, url in enumerate(urls):
        for sid in (1, 2, 3):
            _art_citing(db, base * 100 + sid, sid, url)
        assert find_source_laundering(db, min_sources=3, min_articles=3)["count"] == 0, url


def test_one_card_per_registrable_origin_domain(db):
    """Row 2: the same origin domain must never surface as two separate cards even
    when two distinct URL paths on it each clear the gates."""
    for sid in range(1, 7):
        _src(db, sid, f"src{sid}.test")
    for aid, sid in enumerate((1, 2, 3), start=1):
        _art_citing(db, aid, sid, "https://origin.example/claim-a")
    for aid, sid in enumerate((4, 5, 6), start=4):
        _art_citing(db, aid, sid, "https://origin.example/claim-b")
    out = find_source_laundering(db, min_sources=3, min_articles=3)
    domains = [c["origin_domain"] for c in out["clusters"]]
    assert domains.count("origin.example") == 1, domains
    assert out["count"] == 1
    assert "one card per registrable origin domain" in out["method"]


def test_below_gates_does_not_fire(db):
    _src(db, 1, "a.test")
    _src(db, 2, "b.test")
    _art_citing(db, 1, 1, "https://origin.example/x")
    _art_citing(db, 2, 2, "https://origin.example/x")
    # Only 2 distinct sources, gate is 3 -> no fire.
    assert find_source_laundering(db, min_sources=3, min_articles=3)["count"] == 0
    # Lowering the gate to 2 surfaces it.
    assert find_source_laundering(db, min_sources=2, min_articles=2)["count"] == 1


def test_source_laundering_endpoint(tmp_path):
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'l.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        for sid in (1, 2, 3):
            s.add(Source(id=sid, name=f"S{sid}", domain=f"s{sid}.test"))
        s.commit()
        for aid, sid in ((1, 1), (2, 2), (3, 3)):
            s.add(Article(id=aid, url=f"https://x/{aid}", canonical_url=f"https://x/{aid}",
                          source_id=sid, title="T", content="c", hash=f"h{aid}", language="en"))
            s.add(ArticleLink(article_id=aid, url="https://origin.example/c",
                              normalized_url="https://origin.example/c", link_type="external"))
        s.commit()

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as c:
            body = c.get("/api/insights/source-laundering").json()
        assert body["count"] == 1 and body["clusters"][0]["distinct_sources"] == 3
        assert sorted(body["clusters"][0]["article_ids"]) == [1, 2, 3]
    finally:
        app.dependency_overrides.clear()
