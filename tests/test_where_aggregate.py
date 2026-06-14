"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

Corpus-wide WHERE aggregation (the When/Where/Who remainder): queries.where_aggregate
and GET /api/insights/where roll the per-article ArticleMentionedPlace rows up to
the whole corpus with HONEST counts (distinct-article spread + summed mentions),
a kind filter, an optional window, the place's own gazetteer coordinate (or null —
no fabricated position), and NO score. Deduced, never confirmed.

The fixture stamps a private place-country ("zz") on every seeded place so each
assertion can scope to exactly those rows — deterministic regardless of the
shared test corpus.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

_CC = "zz"  # private place-country: nothing else in the suite seeds it


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def seeded(client):
    from src.database.models import Article, ArticleMentionedPlace, Source
    from src.database.session import session_scope

    made: dict = {"articles": [], "source": None}
    # (tag, age_days, [(name, kind, mentions, lat, lon)])
    plan = [
        ("a1", 0, [("Springfield", "city", 3, 1.0, 2.0), ("Atlantis", "country", 1, None, None)]),
        ("a2", 1, [("Springfield", "city", 1, 1.0, 2.0), ("Atlantis", "country", 2, None, None)]),
        ("a3", 400, [("Springfield", "city", 2, 1.0, 2.0), ("Gotham", "city", 5, 3.0, 4.0)]),
    ]
    with session_scope() as s:
        src = Source(name="WhereSeed", domain="whereseed.example", country="fr")
        s.add(src)
        s.flush()
        made["source"] = src.id
        for tag, age_days, places in plan:
            a = Article(
                url=f"https://whereseed.example/{tag}",
                canonical_url=f"https://whereseed.example/{tag}",
                source_id=src.id,
                title=tag,
                content="x",
                language="en",
                hash=f"where{tag}" + "9" * 55,
                country="fr",
                published_at=datetime.now(UTC) - timedelta(days=age_days),
            )
            s.add(a)
            s.flush()
            made["articles"].append(a.id)
            for name, kind, men, lat, lon in places:
                s.add(
                    ArticleMentionedPlace(
                        article_id=a.id,
                        name=name,
                        country=_CC,
                        kind=kind,
                        mentions=men,
                        lat=lat,
                        lon=lon,
                        snippet="seed",
                        note="seed",
                        extractor="lexical-v1",
                    )
                )
    yield made
    with session_scope() as s:
        for aid in made["articles"]:
            s.execute(
                text(f"DELETE FROM article_mentioned_places WHERE article_id = {aid}")  # noqa: S608
            )
            s.execute(text(f"DELETE FROM articles WHERE id = {aid}"))  # noqa: S608
        s.execute(text(f"DELETE FROM sources WHERE id = {made['source']}"))  # noqa: S608


def test_corpus_wide_counts_order_and_coords(seeded):
    from src.analytics import queries as q
    from src.database.session import session_scope

    with session_scope() as s:
        out = q.where_aggregate(s, country=_CC, limit=50)

    by = {(p["name"], p["kind"]): p for p in out["places"]}
    # Springfield: 3 distinct articles, 3+1+2=6 mentions, gazetteer coord present
    assert by[("Springfield", "city")]["articles"] == 3
    assert by[("Springfield", "city")]["mentions"] == 6
    assert by[("Springfield", "city")]["lat"] == 1.0 and by[("Springfield", "city")]["lon"] == 2.0
    # Atlantis: 2 articles, 1+2=3 mentions, NO coordinate (honest null)
    assert by[("Atlantis", "country")]["articles"] == 2
    assert by[("Atlantis", "country")]["lat"] is None
    # ordered by article spread
    names = [p["name"] for p in out["places"]]
    assert names.index("Springfield") < names.index("Atlantis") < names.index("Gotham")
    # placed = rows with coordinates (Springfield, Gotham); coverage = 3 seeded
    assert out["placed"] == 2
    assert out["coverage_articles"] == 3
    # honesty: no score; method + caveat carried
    assert all("score" not in p for p in out["places"])
    assert out["caveat"] == "Deduced from text, never confirmed."
    assert "gazetteer" in out["method"]


def test_kind_filter(seeded):
    from src.analytics import queries as q
    from src.database.session import session_scope

    with session_scope() as s:
        out = q.where_aggregate(s, country=_CC, kind="country", limit=50)
    assert out["kind"] == "country"
    assert {p["name"] for p in out["places"]} == {"Atlantis"}


def test_window_excludes_old(seeded):
    from src.analytics import queries as q
    from src.database.session import session_scope

    with session_scope() as s:
        out = q.where_aggregate(s, country=_CC, days=30, limit=50)
    names = {p["name"] for p in out["places"]}
    assert "Gotham" not in names  # only in the 400-day-old article
    sp = next(p for p in out["places"] if p["name"] == "Springfield")
    assert sp["articles"] == 2 and sp["mentions"] == 4
    assert out["coverage_articles"] == 2


def test_min_articles_having(seeded):
    from src.analytics import queries as q
    from src.database.session import session_scope

    with session_scope() as s:
        out = q.where_aggregate(s, country=_CC, min_articles=3, limit=50)
    assert {p["name"] for p in out["places"]} == {"Springfield"}


def test_endpoint(client, seeded):
    r = client.get("/api/insights/where", params={"country": _CC, "kind": "city", "limit": 10})
    assert r.status_code == 200
    data = r.json()
    assert data["kind"] == "city"
    assert {p["name"] for p in data["places"]} == {"Springfield", "Gotham"}
    assert "score" not in data
    assert data["placed"] == 2


def test_unknown_kind_falls_back_to_both(seeded):
    from src.analytics import queries as q
    from src.database.session import session_scope

    with session_scope() as s:
        out = q.where_aggregate(s, country=_CC, kind="bogus", limit=50)
    assert out["kind"] is None
    assert {p["kind"] for p in out["places"]} == {"city", "country"}
