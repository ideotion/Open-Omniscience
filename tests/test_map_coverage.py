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
    from src.database.models import Article, Source
    from src.database.session import session_scope

    # (country, n_articles)
    plan = [(_ZY, 3), (_ZX, 1), (None, 2)]
    made: dict = {"sources": []}
    with session_scope() as s:
        for i, (cc, n_art) in enumerate(plan):
            src = Source(name=f"CovSeed{i}", domain=f"covseed{i}.example", country=cc)
            s.add(src)
            s.flush()
            made["sources"].append(src.id)
            for j in range(n_art):
                s.add(
                    Article(
                        url=f"https://covseed{i}.example/{j}",
                        canonical_url=f"https://covseed{i}.example/{j}",
                        source_id=src.id,
                        title=f"cov{i}-{j}",
                        content="x",
                        language="en",
                        hash=f"cov{i}_{j}_" + "0" * 50,
                    )
                )
    yield made
    # cleanup so repeated runs stay deterministic
    with session_scope() as s:
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

    # no score field leaks through the endpoint either.
    for row in d["by_country"]:
        assert not any("score" in k for k in row)
