"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion
GPL-3.0-or-later (see other test headers for the full notice).

---

T10 slice 1 — the corpus LINKS substrate: shared outbound links among the
member articles of a keyword corpus, with the anti-false-triangulation
framing (shared origin made visible; counts never dressed as confirmation).
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
def linked_corpus(client):
    from src.database.models import Article, ArticleLink, Keyword, KeywordMention, Source
    from src.database.session import session_scope

    with session_scope() as s:
        src = Source(name="LinkSeed", domain="linkseed.example")
        s.add(src); s.flush()
        kw = Keyword(term="t10-linktopic", normalized_term="t10-linktopic", language="en")
        s.add(kw); s.flush()
        arts = []
        for i in range(3):
            a = Article(
                url=f"https://linkseed.example/{i}", canonical_url=f"https://linkseed.example/{i}",
                source_id=src.id, title=f"l{i}", content="x", language="en",
                hash=f"t10link{i:057d}",
            )
            s.add(a); arts.append(a)
        s.flush()
        for a in arts:
            s.add(KeywordMention(keyword_id=kw.id, article_id=a.id, count=1))
        # Articles 0+1 cite the SAME origin; article 2 cites something unique.
        common = "https://origin.example/report"
        s.add(ArticleLink(article_id=arts[0].id, url=common, normalized_url=common))
        s.add(ArticleLink(article_id=arts[1].id, url=common, normalized_url=common))
        s.add(ArticleLink(article_id=arts[2].id, url="https://elsewhere.example/x",
                          normalized_url="https://elsewhere.example/x"))
        ids = {"kw": kw.id, "arts": [a.id for a in arts], "src": src.id}
    yield ids
    with session_scope() as s:
        alist = ",".join(str(i) for i in ids["arts"])
        s.execute(text(f"DELETE FROM article_links WHERE article_id IN ({alist})"))
        s.execute(text(f"DELETE FROM keyword_mentions WHERE keyword_id = {ids['kw']}"))
        s.execute(text(f"DELETE FROM keywords WHERE id = {ids['kw']}"))
        s.execute(text(f"DELETE FROM articles WHERE id IN ({alist})"))
        s.execute(text(f"DELETE FROM sources WHERE id = {ids['src']}"))


def test_shared_links_surface_shared_origin_only(client, linked_corpus):
    body = client.get("/api/links/shared?term=t10-linktopic").json()
    assert body["members"] == 3
    urls = [s["url"] for s in body["shared"]]
    assert "https://origin.example/report" in urls
    assert "https://elsewhere.example/x" not in urls, "unique links are not 'shared'"
    row = body["shared"][0]
    assert row["cited_by_articles"] == 2
    # Same SOURCE citing twice = one path wearing two hats — the note says so.
    assert row["citing_sources"] == 1 and "one path" in row["note"]
    assert "NEVER independent confirmation" in body["method"]


def test_shared_links_unknown_term_is_honest(client):
    body = client.get("/api/links/shared?term=t10-no-such-term-xyz").json()
    assert body["resolved"] is None and body["shared"] == []
