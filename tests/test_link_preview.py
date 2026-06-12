"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

Invariant #6 EXTENDED, first target (maintainer-repeated): before any Home-card
external link is followed, a LOCAL preview shows the database extraction for
the URL — known source, local copy, citation count from the user's own corpus,
tracked law/wiki matches — built from local reads only, zero network.
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
def linked_world(client):
    from src.database.models import Article, ArticleLink, LawDocument, Source
    from src.database.session import session_scope

    target = "https://lpseed.example/report"
    with session_scope() as s:
        src = Source(name="LP Seed Times", domain="lpseed.example")
        s.add(src)
        s.flush()
        arts = []
        for i in range(2):
            a = Article(
                url=f"https://citer{i}.example/{i}",
                canonical_url=f"https://citer{i}.example/{i}",
                source_id=src.id, title=f"Citing piece {i}", content="x",
                language="en", hash=f"lpv{i}" + "d" * 59,
            )
            s.add(a)
            s.flush()
            arts.append(a.id)
            s.add(ArticleLink(article_id=a.id, url=target, normalized_url=target))
        local = Article(
            url="https://lpseed.example/report",
            canonical_url="https://lpseed.example/report",
            source_id=src.id, title="The report itself", content="x",
            language="en", hash="lpvL" + "e" * 60,
        )
        s.add(local)
        law = LawDocument(jurisdiction="eu", title="LP Seed Act",
                          url="https://lpseed.example/law")
        s.add(law)
        s.flush()
        ids = {"src": src.id, "arts": arts, "local": local.id, "law": law.id,
               "target": target}
    yield ids
    with session_scope() as s:
        for aid in ids["arts"]:
            s.execute(text(f"DELETE FROM article_links WHERE article_id = {aid}"))  # noqa: S608
            s.execute(text(f"DELETE FROM articles WHERE id = {aid}"))  # noqa: S608
        s.execute(text(f"DELETE FROM articles WHERE id = {ids['local']}"))  # noqa: S608
        s.execute(text(f"DELETE FROM law_documents WHERE id = {ids['law']}"))  # noqa: S608
        s.execute(text(f"DELETE FROM sources WHERE id = {ids['src']}"))  # noqa: S608


def test_preview_extracts_what_the_db_knows(client, linked_world):
    d = client.get("/api/links/preview", params={"url": linked_world["target"]}).json()
    assert d["domain"] == "lpseed.example"
    assert d["known_source"]["name"] == "LP Seed Times"
    assert d["cited_by_articles"] == 2
    assert {x["article_id"] for x in d["citing_examples"]} == set(linked_world["arts"])
    assert d["local_article"]["article_id"] == linked_world["local"]
    assert d["local_article"]["reader_url"].startswith("/api/articles/")
    assert "no network call" in d["method"]


def test_preview_matches_tracked_law_url(client, linked_world):
    d = client.get("/api/links/preview", params={"url": "https://lpseed.example/law"}).json()
    assert d["law_document"]["title"] == "LP Seed Act"
    assert d["law_document"]["jurisdiction"] == "eu"


def test_preview_unknown_url_is_honestly_empty(client):
    d = client.get("/api/links/preview",
                   params={"url": "https://never-seen.example/x"}).json()
    assert d["local_article"] is None
    assert d["known_source"] is None
    assert d["cited_by_articles"] == 0
    assert d["law_document"] is None and d["wiki_page"] is None


def test_preview_rejects_non_http_urls(client):
    assert client.get("/api/links/preview", params={"url": "ftp://x.example/a"}).status_code == 422
    assert client.get("/api/links/preview", params={"url": "not a url"}).status_code == 422
    assert client.get("/api/links/preview",
                      params={"url": "javascript:alert(1)"}).status_code == 422
