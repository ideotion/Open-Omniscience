"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

ooMap slice 2 -- the per-country COVERAGE choropleth substrate.

``queries.source_country_counts`` groups sources (and the articles collected
from them) by the source's catalogued country, bucketing country-less sources
as 'unlocated' -- never guessed onto the map. ``GET /api/insights/map-coverage``
enriches each located country with a display name + a centroid (so the UI can
fall back to a POINT for polygon-less territories) and carries method + caveat.
Counts only, NO score.

Scoped to PRIVATE ISO codes nothing else in the suite seeds, so the assertions
stay deterministic against the shared test corpus.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

_ZY, _ZX = "zy", "zx"  # private source-countries: nothing else in the suite seeds them


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def seeded(client):
    """Two private LOCATED countries + one country-less source, each with a
    distinct article count, so the grouping and the 'unlocated' bucket are both
    exercised deterministically. Depends on ``client`` so the app's startup has
    created the schema (the sibling where/who aggregate tests do the same)."""
    from src.database.models import Article, Keyword, KeywordMention, Source
    from src.database.session import session_scope

    # (country, [sentiment_score per article]) -- None = unscored (no English VADER)
    plan = [(_ZY, [0.2, 0.5, 0.8]), (_ZX, [0.0]), (None, [None, None])]
    made: dict = {"sources": [], "keyword": None}
    with session_scope() as s:
        zy_article_ids: list[int] = []
        for i, (cc, scores) in enumerate(plan):
            src = Source(name=f"CovSeed{i}", domain=f"covseed{i}.example", country=cc)
            s.add(src)
            s.flush()
            made["sources"].append(src.id)
            for j, sc in enumerate(scores):
                a = Article(
                    url=f"https://covseed{i}.example/{j}",
                    canonical_url=f"https://covseed{i}.example/{j}",
                    source_id=src.id,
                    title=f"cov{i}-{j}",
                    content="x",
                    language="en",
                    hash=f"cov{i}_{j}_" + "0" * 50,
                    sentiment_score=sc,
                )
                s.add(a)
                s.flush()
                if cc == _ZY:
                    zy_article_ids.append(a.id)
        # One keyword + two mentions denormalised to country zy (KeywordMention.country
        # is the SOURCE country, so the keyword dimension needs no Article join). The
        # unique (keyword_id, article_id) index forces two DISTINCT articles.
        kw = Keyword(term="covterm", normalized_term="covterm")
        s.add(kw)
        s.flush()
        made["keyword"] = kw.id
        for aid in zy_article_ids[:2]:
            s.add(KeywordMention(keyword_id=kw.id, article_id=aid, country=_ZY))
    yield made
    # cleanup so repeated runs stay deterministic
    with session_scope() as s:
        s.query(KeywordMention).filter(KeywordMention.keyword_id == made["keyword"]).delete(
            synchronize_session=False
        )
        s.query(Keyword).filter(Keyword.id == made["keyword"]).delete(synchronize_session=False)
        s.query(Article).filter(Article.source_id.in_(made["sources"])).delete(
            synchronize_session=False
        )
        s.query(Source).filter(Source.id.in_(made["sources"])).delete(
            synchronize_session=False
        )


def test_source_country_counts_groups_and_buckets(seeded):
    from src.analytics import queries as q
    from src.database.session import session_scope

    with session_scope() as s:
        data = q.source_country_counts(s)

    by = {r["country"]: r for r in data["by_country"]}
    assert by[_ZY]["sources"] == 1 and by[_ZY]["articles"] == 3
    assert by[_ZX]["sources"] == 1 and by[_ZX]["articles"] == 1

    # the country-less source is bucketed, NEVER given an empty/None country row.
    assert "" not in by and None not in by
    assert data["unlocated"]["sources"] >= 1
    assert data["unlocated"]["articles"] >= 2

    # counts only -- no composite score anywhere.
    for r in data["by_country"]:
        assert not any("score" in k for k in r)

    # by_country is ordered by source count (descending) -- an honest ordering.
    counts = [r["sources"] for r in data["by_country"]]
    assert counts == sorted(counts, reverse=True)


def test_keywords_and_sentiment_dimensions(seeded):
    """Slice 3: the extra choropleth dimensions -- keyword mentions (denormalised
    by source country, no Article join) and mean tone (VADER, over the SCORED
    subset, with sentiment_n; a country with no scored article reports None)."""
    from src.analytics import queries as q
    from src.database.session import session_scope

    with session_scope() as s:
        data = q.source_country_counts(s)

    by = {r["country"]: r for r in data["by_country"]}

    # keyword MENTIONS per source-country (two distinct articles tagged).
    assert by[_ZY]["keywords"] == 2
    assert by[_ZX]["keywords"] == 0

    # mean tone over the SCORED subset; sentiment_n discloses that subset size.
    assert by[_ZY]["sentiment_n"] == 3
    assert abs(by[_ZY]["sentiment"] - 0.5) < 1e-6  # (0.2 + 0.5 + 0.8) / 3
    assert by[_ZX]["sentiment_n"] == 1 and abs(by[_ZX]["sentiment"] - 0.0) < 1e-6

    # the tone field is named 'sentiment' -- never a '*score*' key (no composite).
    for r in data["by_country"]:
        assert "sentiment" in r and "keywords" in r
        assert not any("score" in k for k in r)


def test_map_coverage_endpoint_enriches_and_is_honest(client, seeded):
    r = client.get("/api/insights/map-coverage")
    assert r.status_code == 200
    d = r.json()

    assert d["dimension"] == "sources"
    assert d.get("method") and d.get("caveat")

    by = {row["country"]: row for row in d["by_country"]}
    assert _ZY in by and _ZX in by

    # a display name is always present (falls back to the uppercased code when the
    # catalogue has no name -- honest, never blank).
    assert by[_ZY]["name"] == _ZY.upper()

    # private codes are NOT in the gazetteer -> no fabricated centroid is attached.
    assert "lat" not in by[_ZY] and "lon" not in by[_ZY]

    # the 'continent' field is always present (the slice-4 aggregation reads it);
    # an unknown code maps to None -- honest, never a fabricated continent.
    assert "continent" in by[_ZY] and by[_ZY]["continent"] is None

    # no score field leaks through the endpoint either.
    for row in d["by_country"]:
        assert not any("score" in k for k in row)
