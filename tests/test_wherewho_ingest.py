"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

T12 — When×Where×Who at ingest (CONFIRMED GO): the extractors persist with
the keyword pass — snippet provenance + rule notes, deduced never promoted;
idempotent re-index; failures never block keyword indexing.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def article(client):
    from src.database.models import Article, Source
    from src.database.session import session_scope

    with session_scope() as s:
        src = Source(name="WWSeed", domain="wwseed.example", country="fr")
        s.add(src)
        s.flush()
        a = Article(
            url="https://wwseed.example/1", canonical_url="https://wwseed.example/1",
            source_id=src.id, title="t12",
            content=(
                "President Jean Dupont visited France on 5 January 2026. "
                "President Jean Dupont met officials in France again, the "
                "delegation said, and France welcomed the visit."
            ),
            language="en", hash="t12ww" + "1" * 59,
        )
        s.add(a)
        s.flush()
        ids = {"a": a.id, "s": src.id}
    yield ids
    with session_scope() as s:
        for tbl in ("article_entities", "article_mentioned_places",
                    "article_mentioned_dates", "keyword_mentions"):
            s.execute(text(f"DELETE FROM {tbl} WHERE article_id = {ids['a']}"))  # noqa: S608
        s.execute(text(f"DELETE FROM articles WHERE id = {ids['a']}"))  # noqa: S608
        s.execute(text(f"DELETE FROM sources WHERE id = {ids['s']}"))  # noqa: S608


def test_index_article_persists_when_where_who(client, article):
    from src.analytics.extract import BaselineExtractor
    from src.analytics.store import index_article
    from src.database.models import Article, ArticleEntity, ArticleMentionedPlace
    from src.database.session import session_scope

    with session_scope() as s:
        a = s.get(Article, article["a"])
        out = index_article(s, a, extractor=BaselineExtractor())
        assert out["places"] >= 1 and out["entities_stored"] >= 1 and out["dates"] >= 1

        places = s.query(ArticleMentionedPlace).filter_by(article_id=a.id).all()
        assert any(p.name.lower() == "france" for p in places)
        for p in places:
            assert p.snippet, "every deduced place carries snippet provenance"
            assert p.extractor == "lexical-v1"

        ents = s.query(ArticleEntity).filter_by(article_id=a.id).all()
        people = [e for e in ents if e.entity_class == "person"]
        assert any("jean dupont" in e.name.lower() for e in people)
        for e in ents:
            assert e.note, "every deduced entity carries the rule note"

        # Idempotent: re-index replaces, never duplicates.
        index_article(s, a, extractor=BaselineExtractor())
        again = s.query(ArticleMentionedPlace).filter_by(article_id=a.id).count()
        assert again == len(places)


def test_wherewho_failure_never_blocks_keywords(client, article, monkeypatch):
    import src.timemap.whostore as ws
    from src.analytics.extract import BaselineExtractor
    from src.analytics.store import index_article
    from src.database.models import Article
    from src.database.session import session_scope

    monkeypatch.setattr(ws, "store_places_for_article",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with session_scope() as s:
        a = s.get(Article, article["a"])
        out = index_article(s, a, extractor=BaselineExtractor())
        assert out["mentions"] > 0, "keyword indexing must survive a deduction failure"
