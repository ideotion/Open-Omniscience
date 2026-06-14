"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

Corpus-wide WHO aggregation (the When/Where/Who remainder): queries.who_aggregate
and GET /api/insights/who roll the per-article ArticleEntity rows up to the whole
corpus with HONEST counts (distinct-article spread + summed in-text mentions), a
class filter, an optional window/country, and NO score. Deduced, never confirmed.

The fixture stamps a private country code ("zz") on its source so every
assertion can scope to exactly the seeded rows — deterministic no matter what
else the shared test corpus holds.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

_CC = "zz"  # private scope: nothing else in the suite seeds this country


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def seeded(client):
    from src.database.models import Article, ArticleEntity, Source
    from src.database.session import session_scope

    made: dict = {"articles": [], "source": None}
    # (tag, age_days, [(name, class, mentions)])
    plan = [
        ("a1", 0, [("Jean Dupont", "person", 3), ("Acme Corp", "organization", 1)]),
        ("a2", 1, [("Jean Dupont", "person", 1), ("Acme Corp", "organization", 2)]),
        ("a3", 400, [("Jean Dupont", "person", 2), ("Marie Curie", "person", 5)]),
    ]
    with session_scope() as s:
        src = Source(name="WhoSeed", domain="whoseed.example", country=_CC)
        s.add(src)
        s.flush()
        made["source"] = src.id
        for tag, age_days, ents in plan:
            a = Article(
                url=f"https://whoseed.example/{tag}",
                canonical_url=f"https://whoseed.example/{tag}",
                source_id=src.id,
                title=tag,
                content="x",
                language="en",
                hash=f"who{tag}" + "9" * 57,
                country=_CC,
                published_at=datetime.now(UTC) - timedelta(days=age_days),
            )
            s.add(a)
            s.flush()
            made["articles"].append(a.id)
            for name, cls, men in ents:
                s.add(
                    ArticleEntity(
                        article_id=a.id,
                        name=name,
                        entity_class=cls,
                        mentions=men,
                        note="seed",
                        extractor="lexical-v1",
                    )
                )
    yield made
    with session_scope() as s:
        for aid in made["articles"]:
            s.execute(text(f"DELETE FROM article_entities WHERE article_id = {aid}"))  # noqa: S608
            s.execute(text(f"DELETE FROM articles WHERE id = {aid}"))  # noqa: S608
        s.execute(text(f"DELETE FROM sources WHERE id = {made['source']}"))  # noqa: S608


def test_corpus_wide_counts_and_order(seeded):
    from src.analytics import queries as q
    from src.database.session import session_scope

    with session_scope() as s:
        out = q.who_aggregate(s, country=_CC, limit=50)

    by = {(e["name"], e["class"]): e for e in out["entities"]}
    # Jean Dupont: 3 distinct articles, 3+1+2 = 6 mentions
    assert by[("Jean Dupont", "person")]["articles"] == 3
    assert by[("Jean Dupont", "person")]["mentions"] == 6
    # Acme Corp: 2 distinct articles, 1+2 = 3 mentions
    assert by[("Acme Corp", "organization")]["articles"] == 2
    assert by[("Acme Corp", "organization")]["mentions"] == 3
    # ordered by article spread: the 3-article name precedes the 2-article one
    names = [e["name"] for e in out["entities"]]
    assert names.index("Jean Dupont") < names.index("Acme Corp")
    # honesty: no score anywhere; method + caveat carried
    assert all("score" not in e for e in out["entities"])
    assert out["caveat"] == "Deduced from text, never confirmed."
    assert "lexical-v1" in out["method"]
    assert out["coverage_articles"] == 3


def test_class_filter(seeded):
    from src.analytics import queries as q
    from src.database.session import session_scope

    with session_scope() as s:
        out = q.who_aggregate(s, country=_CC, entity_class="organization", limit=50)
    assert out["entity_class"] == "organization"
    assert {e["name"] for e in out["entities"]} == {"Acme Corp"}


def test_window_excludes_old(seeded):
    from src.analytics import queries as q
    from src.database.session import session_scope

    with session_scope() as s:
        out = q.who_aggregate(s, country=_CC, days=30, limit=50)
    names = {e["name"] for e in out["entities"]}
    assert "Marie Curie" not in names  # only in the 400-day-old article
    jd = next(e for e in out["entities"] if e["name"] == "Jean Dupont")
    assert jd["articles"] == 2  # the two recent articles only
    assert jd["mentions"] == 4
    assert out["coverage_articles"] == 2


def test_min_articles_having(seeded):
    from src.analytics import queries as q
    from src.database.session import session_scope

    with session_scope() as s:
        out = q.who_aggregate(s, country=_CC, min_articles=3, limit=50)
    assert {e["name"] for e in out["entities"]} == {"Jean Dupont"}


def test_endpoint(client, seeded):
    r = client.get(
        "/api/insights/who", params={"country": _CC, "entity_class": "person", "limit": 10}
    )
    assert r.status_code == 200
    data = r.json()
    assert data["entity_class"] == "person"
    assert {e["name"] for e in data["entities"]} == {"Jean Dupont", "Marie Curie"}
    assert "score" not in data
    assert data["coverage_articles"] >= 1


def test_unknown_class_falls_back_to_both(seeded):
    from src.analytics import queries as q
    from src.database.session import session_scope

    with session_scope() as s:
        out = q.who_aggregate(s, country=_CC, entity_class="bogus", limit=50)
    assert out["entity_class"] is None
    classes = {e["class"] for e in out["entities"]}
    assert classes == {"person", "organization"}
