"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

T13 slice 1 — the omnibar endpoint: index-backed federation over articles
(FTS5), keywords, sources, wiki pages and law documents; first three per
group with the TRUE totals disclosed; a half-typed Boolean query falls back
to a phrase match instead of a 400 (mid-typing is not an error condition).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def omni_seed(client):
    from src.database.models import Article, Keyword, LawDocument, Source, WikiPage
    from src.database.session import session_scope

    with session_scope() as s:
        src = Source(name="Omnibar Gazette", domain="omnibargazette.example")
        s.add(src)
        s.flush()
        art_ids = []
        for i in range(4):
            a = Article(
                url=f"https://omnibargazette.example/{i}",
                canonical_url=f"https://omnibargazette.example/{i}",
                source_id=src.id,
                title=f"Quokkafloss report {i}",
                content=f"the quokkafloss situation, instalment {i}",
                language="en",
                hash=f"omni{i}" + "c" * 59,
                published_at=datetime.now(UTC),
            )
            s.add(a)
            s.flush()
            art_ids.append(a.id)
        kw = Keyword(term="quokkafloss", normalized_term="quokkafloss", frequency=7)
        s.add(kw)
        wp = WikiPage(wiki="en", title="Quokkafloss (disambiguation)")
        s.add(wp)
        ld = LawDocument(jurisdiction="eu", title="Quokkafloss Directive 2026",
                         url="https://example.eu/quokkafloss")
        s.add(ld)
        s.flush()
        ids = {"src": src.id, "arts": art_ids, "kw": kw.id, "wp": wp.id, "ld": ld.id}
    yield ids
    with session_scope() as s:
        for aid in ids["arts"]:
            s.execute(text(f"DELETE FROM articles WHERE id = {aid}"))  # noqa: S608
        s.execute(text(f"DELETE FROM keywords WHERE id = {ids['kw']}"))  # noqa: S608
        s.execute(text(f"DELETE FROM wiki_pages WHERE id = {ids['wp']}"))  # noqa: S608
        s.execute(text(f"DELETE FROM law_documents WHERE id = {ids['ld']}"))  # noqa: S608
        s.execute(text(f"DELETE FROM sources WHERE id = {ids['src']}"))  # noqa: S608


def _group(d, kind):
    return next(g for g in d["groups"] if g["kind"] == kind)


def test_omni_federates_with_disclosed_totals(client, omni_seed):
    d = client.get("/api/search/omni", params={"q": "quokkafloss"}).json()
    assert d["per_group"] == 3
    arts = _group(d, "articles")
    assert arts["total"] == 4, arts  # 4 matched, 3 shown -- the truth is disclosed
    assert len(arts["items"]) == 3
    assert arts["items"][0]["url"].startswith("/api/articles/")  # LOCAL reader first
    kws = _group(d, "keywords")
    assert kws["total"] >= 1
    assert any(i["normalized_term"] == "quokkafloss" for i in kws["items"])
    assert _group(d, "sources")["total"] == 0  # name does not contain the term
    assert any(i["title"].startswith("Quokkafloss") for i in _group(d, "wiki")["items"])
    assert any(i["jurisdiction"] == "eu" for i in _group(d, "law")["items"])
    assert "index-backed" in d["method"]


def test_omni_source_match_by_name_and_domain(client, omni_seed):
    d = client.get("/api/search/omni", params={"q": "omnibargazette"}).json()
    assert _group(d, "sources")["total"] == 1
    d2 = client.get("/api/search/omni", params={"q": "Omnibar Gaz"}).json()
    assert _group(d2, "sources")["total"] == 1


def test_omni_half_typed_boolean_is_not_an_error(client, omni_seed):
    r = client.get("/api/search/omni", params={"q": "quokkafloss AND"})
    assert r.status_code == 200
    arts = _group(r.json(), "articles")
    # Fallback path: either the phrase matched or it honestly reported
    # unsearchable -- never a 400 mid-keystroke.
    assert "note" in arts


def test_omni_bounds_and_like_escape(client):
    assert client.get("/api/search/omni", params={"q": "a"}).status_code == 422
    assert client.get("/api/search/omni", params={"q": "x" * 201}).status_code == 422
    r = client.get("/api/search/omni", params={"q": "100% \\_certain_"})
    assert r.status_code == 200  # LIKE wildcards arrive escaped, never crash
