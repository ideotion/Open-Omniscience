"""Interactive corpus facets — entity / place / temporal (keyword-engine P5.1b).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The When/Where/Who facet surface gains a TEMPORAL (When) facet and a DRILL that
narrows the corpus to the articles mentioning a facet value -- the thing that makes a
facet co-equal with the text query. Facet rows are inserted directly so the queries are
tested deterministically (independent of extractor behaviour). Counts only, no score.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analytics import queries as q
from src.database.models import (
    Article,
    ArticleEntity,
    ArticleMentionedDate,
    ArticleMentionedPlace,
    Base,
    Source,
)


def _seed(s):
    """Three articles with known who/where/when facet rows -- a2/a3 use a SECOND
    source + a non-English language so the source/language facet tests have signal."""
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.add(Source(name="T", domain="y.test", country="jp"))
    s.commit()
    ids = []
    for i in range(1, 4):
        a = Article(
            url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}",
            source_id=2 if i == 3 else 1,
            title=f"T{i}", content="Body.", hash=f"h{i}", language=("ja" if i == 3 else "en"),
            created_at=datetime.now(UTC),
        )
        s.add(a)
        s.flush()
        ids.append(a.id)
    a1, a2, a3 = ids
    # Entities: NATO in a1+a2, UN in a3.
    for aid in (a1, a2):
        s.add(ArticleEntity(article_id=aid, name="NATO", entity_class="organization", mentions=2))
    s.add(ArticleEntity(article_id=a3, name="UN", entity_class="organization", mentions=1))
    # Places: Paris in a1+a2, Tokyo in a3.
    for aid in (a1, a2):
        s.add(ArticleMentionedPlace(article_id=aid, name="Paris", country="fr", kind="city", mentions=1))
    s.add(ArticleMentionedPlace(article_id=a3, name="Tokyo", country="jp", kind="city", mentions=1))
    # Dates the text is ABOUT: 2024 in a1+a2, 1945 in a3.
    s.add(ArticleMentionedDate(article_id=a1, mentioned_on=date(2024, 9, 15), precision="day"))
    s.add(ArticleMentionedDate(article_id=a2, mentioned_on=date(2024, 3, 1), precision="day"))
    s.add(ArticleMentionedDate(article_id=a3, mentioned_on=date(1945, 8, 6), precision="day"))
    s.commit()
    return a1, a2, a3


def _session():
    eng = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, future=True)()


def test_corpus_when_buckets_by_year_scoped_to_the_article_set():
    s = _session()
    a1, a2, a3 = _seed(s)
    when = q.corpus_when(s, article_ids=[a1, a2, a3], limit=20)
    by_year = {row["year"]: row["articles"] for row in when["years"]}
    assert by_year == {"2024": 2, "1945": 1}  # 2024 spans a1+a2, 1945 only a3
    # scoped: dropping a3 drops the 1945 bucket entirely
    when2 = q.corpus_when(s, article_ids=[a1, a2], limit=20)
    assert {r["year"] for r in when2["years"]} == {"2024"}
    assert q.corpus_when(s, article_ids=[], limit=5)["count"] == 0
    assert "never confirmed" in when["caveat"]


def test_corpus_when_excludes_user_rejected_date_tags():
    s = _session()
    a1, a2, a3 = _seed(s)
    # The user rejects a1's 2024 tag; a2 still carries one, so 2024 stays but at 1 article.
    s.query(ArticleMentionedDate).filter(
        ArticleMentionedDate.article_id == a1
    ).update({"status": "rejected"})
    s.commit()
    by_year = {r["year"]: r["articles"] for r in q.corpus_when(s, article_ids=[a1, a2, a3])["years"]}
    assert by_year == {"2024": 1, "1945": 1}


def test_corpus_facet_article_ids_drills_within_the_corpus():
    s = _session()
    a1, a2, a3 = _seed(s)
    corpus = [a1, a2, a3]
    assert q.corpus_facet_article_ids(s, article_ids=corpus, facet="entity", value="NATO") == [a1, a2]
    assert q.corpus_facet_article_ids(s, article_ids=corpus, facet="place", value="Tokyo") == [a3]
    assert q.corpus_facet_article_ids(s, article_ids=corpus, facet="when", value="2024") == [a1, a2]
    # the drill stays WITHIN the passed corpus (a3 excluded from the corpus -> never returned)
    assert q.corpus_facet_article_ids(s, article_ids=[a1, a2], facet="place", value="Tokyo") == []
    # order is the corpus order, not insertion/id order
    assert q.corpus_facet_article_ids(s, article_ids=[a2, a1], facet="entity", value="NATO") == [a2, a1]


def test_corpus_facet_article_ids_honest_edges():
    s = _session()
    a1, a2, a3 = _seed(s)
    assert q.corpus_facet_article_ids(s, article_ids=[], facet="entity", value="NATO") == []
    assert q.corpus_facet_article_ids(s, article_ids=[a1], facet="entity", value="") == []
    assert q.corpus_facet_article_ids(s, article_ids=[a1], facet="bogus", value="NATO") == []
    assert q.corpus_facet_article_ids(s, article_ids=[a1], facet="entity", value="MISSING") == []


def test_corpus_www_endpoint_includes_when_and_drill_endpoint_intersects():
    from src.api.main import app
    from src.database.session import get_db

    eng = create_engine(
        "sqlite://", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)
    Sess = sessionmaker(bind=eng, future=True)
    with Sess() as s:
        a1, a2, a3 = _seed(s)

    def _override():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _override
    try:
        with TestClient(app) as client:
            ids = f"{a1},{a2},{a3}"
            www = client.get("/api/insights/corpus-www", params={"article_ids": ids}).json()
            # the When facet is now part of the When/Where/Who payload (additive)
            assert "when" in www and {r["year"] for r in www["when"]["years"]} == {"2024", "1945"}
            assert www["who"]["entities"] and www["where"]["places"]  # who/where unchanged
            # the drill narrows the corpus to the articles mentioning the value
            dr = client.get(
                "/api/insights/corpus-facet-articles",
                params={"article_ids": ids, "facet": "when", "value": "2024"},
            ).json()
            assert sorted(dr["article_ids"]) == sorted([a1, a2]) and dr["total"] == 2
            assert "score" not in dr  # counts only, never a score
            # an unknown facet is a 400, never a silent empty
            bad = client.get(
                "/api/insights/corpus-facet-articles",
                params={"article_ids": ids, "facet": "nope", "value": "x"},
            )
            assert bad.status_code == 400
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_corpus_facet_article_ids_source_and_language():
    s = _session()
    a1, a2, a3 = _seed(s)
    corpus = [a1, a2, a3]
    # a1/a2 are source "S" (id 1, x.test, en); a3 is source "T" (id 2, y.test, ja).
    # Matched by Source.ID, never name -- Source.name has no uniqueness constraint,
    # so a name lookup could collide across two same-named sources (see the
    # dedicated collision test below); the chip UI supplies the id directly.
    assert q.corpus_facet_article_ids(s, article_ids=corpus, facet="source", value="1") == [a1, a2]
    assert q.corpus_facet_article_ids(s, article_ids=corpus, facet="source", value="2") == [a3]
    assert q.corpus_facet_article_ids(s, article_ids=corpus, facet="language", value="en") == [a1, a2]
    assert q.corpus_facet_article_ids(s, article_ids=corpus, facet="language", value="ja") == [a3]
    # stays within the passed corpus
    assert q.corpus_facet_article_ids(s, article_ids=[a1, a2], facet="source", value="2") == []
    # an unknown source id, or a non-numeric value, is honestly empty, never a crash
    assert q.corpus_facet_article_ids(s, article_ids=corpus, facet="source", value="999") == []
    assert q.corpus_facet_article_ids(s, article_ids=corpus, facet="source", value="not-an-id") == []


def test_corpus_facet_article_ids_source_survives_a_name_collision():
    # Source.name carries no uniqueness constraint (only Source.domain does) -- two
    # sources can legitimately share a display name. Drilling by id (not name) must
    # still resolve unambiguously instead of raising MultipleResultsFound.
    s = _session()
    a1, a2, a3 = _seed(s)
    s.add(Source(name="S", domain="x2.test", country="fr"))  # same name as source id 1
    s.commit()
    assert q.corpus_facet_article_ids(s, article_ids=[a1, a2, a3], facet="source", value="1") == [a1, a2]


def test_corpus_source_language_facets_lists_whats_present_with_counts():
    s = _session()
    a1, a2, a3 = _seed(s)
    facets = q.corpus_source_language_facets(s, article_ids=[a1, a2, a3])
    by_source = {row["source_id"]: row["n"] for row in facets["sources"]}
    assert by_source == {1: 2, 2: 1}
    assert facets["sources"][0]["name"] == "S"  # most-cited source first
    by_lang = {row["language"]: row["n"] for row in facets["languages"]}
    assert by_lang == {"en": 2, "ja": 1}
    assert q.corpus_source_language_facets(s, article_ids=[])["sources"] == []


def test_corpus_facet_articles_endpoint_accepts_source_and_language():
    from src.api.main import app
    from src.database.session import get_db

    eng = create_engine(
        "sqlite://", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)
    Sess = sessionmaker(bind=eng, future=True)
    with Sess() as s:
        a1, a2, a3 = _seed(s)

    def _override():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _override
    try:
        with TestClient(app) as client:
            ids = f"{a1},{a2},{a3}"
            dr = client.get(
                "/api/insights/corpus-facet-articles",
                params={"article_ids": ids, "facet": "source", "value": "2"},  # source "T" is id 2
            ).json()
            assert dr["article_ids"] == [a3]

            langr = client.get(
                "/api/insights/corpus-facet-articles",
                params={"article_ids": ids, "facet": "language", "value": "ja"},
            ).json()
            assert langr["article_ids"] == [a3]

            facets = client.get(
                "/api/insights/corpus-source-language-facets", params={"article_ids": ids}
            ).json()
            assert {row["source_id"] for row in facets["sources"]} == {1, 2}
            assert {row["language"] for row in facets["languages"]} == {"en", "ja"}
    finally:
        app.dependency_overrides.pop(get_db, None)
