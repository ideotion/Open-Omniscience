"""Keyword super-groups: a user-curated group-of-families (model + API).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base, Keyword, KeywordMention, Source


def _client(tmp_path):
    from src.api.main import app
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'sg.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    return app, Sess


def _seed_keyword(s, term, normalized, *, article_ids):
    k = Keyword(
        term=term,
        normalized_term=normalized,
        language="en",
        frequency=0,
        is_entity=True,
        entity_type="org",
        # Denormalised counters maintained at index time in production: one count=1
        # mention per article_id -> mention_count = total, article_count = distinct.
        mention_count=len(article_ids),
        article_count=len(set(article_ids)),
    )
    s.add(k)
    s.flush()
    for aid in article_ids:
        s.add(KeywordMention(keyword_id=k.id, article_id=aid, count=1, observed_on=date.today()))


def test_supergroup_crud_and_aggregate(tmp_path):
    app, Sess = _client(tmp_path)
    with Sess() as s:
        s.add(Source(name="Src", domain="s.test"))
        s.flush()
        for i in range(3):
            s.add(
                Article(
                    url=f"https://s.test/{i}",
                    canonical_url=f"https://s.test/{i}",
                    source_id=1,
                    title=f"t{i}",
                    content="x",
                    hash=f"h{i}",
                )
            )
        s.flush()
        _seed_keyword(s, "Russia", "russia", article_ids=[1, 2, 3])  # 3 mentions, 3 articles
        _seed_keyword(s, "Ukraine", "ukraine", article_ids=[1, 2])  # 2 mentions, 2 articles
        s.commit()

    try:
        with TestClient(app) as c:
            # Create.
            sg = c.post("/api/insights/supergroups", json={"name": "Russia–Ukraine war"}).json()
            sid = sg["id"]
            assert c.post("/api/insights/supergroups", json={"name": ""}).status_code == 400
            assert (
                c.post("/api/insights/supergroups", json={"name": "Russia–Ukraine war"}).status_code
                == 409
            )  # duplicate

            # Add members (idempotent).
            r = c.post(
                f"/api/insights/supergroups/{sid}/members",
                json={"normalized": ["russia", "ukraine", "russia"]},
            ).json()
            assert set(r["members"]) == {"russia", "ukraine"}

            # List with aggregates.
            body = c.get("/api/insights/supergroups").json()
            assert body["count"] == 1
            g = body["supergroups"][0]
            assert g["name"] == "Russia–Ukraine war" and g["count"] == 2
            assert g["mentions"] == 5  # 3 (russia) + 2 (ukraine)
            top = g["members"][0]
            assert top["normalized"] == "russia" and top["mentions"] == 3 and top["articles"] == 3

            # Remove a member.
            c.request(
                "DELETE",
                f"/api/insights/supergroups/{sid}/members",
                params={"normalized": "ukraine"},
            )
            assert c.get("/api/insights/supergroups").json()["supergroups"][0]["count"] == 1

            # Delete the super-group.
            assert c.delete(f"/api/insights/supergroups/{sid}").json()["deleted"] == sid
            assert c.get("/api/insights/supergroups").json()["count"] == 0
            assert c.delete(f"/api/insights/supergroups/{sid}").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_supergroup_totals_count_only_members(tmp_path):
    """Regression for the 2026-06-18 perf fix: the totals query used to GROUP BY
    every keyword×mention and discard non-members — O(whole corpus). The optimised
    query aggregates ONLY member keywords, so a high-mention NON-member must never
    leak into a super-group's totals (and the result is unchanged)."""
    app, Sess = _client(tmp_path)
    with Sess() as s:
        s.add(Source(name="Src", domain="s.test"))
        s.flush()
        for i in range(6):
            s.add(Article(url=f"https://s.test/{i}", canonical_url=f"https://s.test/{i}",
                          source_id=1, title=f"t{i}", content="x", hash=f"h{i}"))
        s.flush()
        _seed_keyword(s, "Russia", "russia", article_ids=[1, 2, 3])  # member: 3 mentions
        # A NON-member keyword with FAR more mentions than the member.
        _seed_keyword(s, "Weather", "weather", article_ids=[1, 2, 3, 4, 5, 6])
        s.commit()
    try:
        with TestClient(app) as c:
            sid = c.post("/api/insights/supergroups", json={"name": "Geo"}).json()["id"]
            c.post(f"/api/insights/supergroups/{sid}/members", json={"normalized": ["russia"]})
            g = c.get("/api/insights/supergroups").json()["supergroups"][0]
            # ONLY the member counts — the 6-mention non-member is excluded.
            assert g["mentions"] == 3 and g["count"] == 1
            assert g["members"][0]["normalized"] == "russia"
    finally:
        app.dependency_overrides.clear()


def test_supergroup_endpoint_dedups_group_total_and_discloses_dominance(tmp_path):
    """The 2026-07-18 field export's row 1 + row 3, at the API surface: a group
    with a plain "ai" family member AND the "artificial-intelligence" ring member
    (whose own English member IS "ai") must report the TRUE deduped total, never
    the naive per-member sum, and must disclose which member dominates it."""
    app, Sess = _client(tmp_path)
    with Sess() as s:
        s.add(Source(name="Src", domain="s.test"))
        s.flush()
        s.add(Article(url="https://s.test/1", canonical_url="https://s.test/1",
                      source_id=1, title="t", content="x", hash="h1"))
        s.flush()
        _seed_keyword(s, "AI", "ai", article_ids=[1])  # 1 mention, 1 article
        s.commit()

    try:
        with TestClient(app) as c:
            sid = c.post("/api/insights/supergroups", json={"name": "Artificial intelligence"}).json()["id"]
            c.post(f"/api/insights/supergroups/{sid}/members", json={"normalized": ["ai"]})
            c.post(f"/api/insights/supergroups/{sid}/members", json={"rings": ["artificial-intelligence"]})

            body = c.get("/api/insights/supergroups").json()
            g = body["supergroups"][0]
            assert g["count"] == 2
            # NOT 2 (1 real mention double-counted across the two overlapping members).
            assert g["mentions"] == 1
            assert g["distinct_keywords"] == 1
            assert g["dominance"]["mentions"] == 1
            assert g["dominance"]["share"] == 1.0
            assert set(g["within_group_overlap"]) == {"ai", "artificial-intelligence"}
            assert isinstance(body["method"], str) and body["method"]
            assert isinstance(body["caveat"], str) and body["caveat"]
    finally:
        app.dependency_overrides.clear()


def test_supergroup_endpoint_discloses_cross_group_overlap_via_also_in(tmp_path):
    """Row 2: a ring member (e.g. "logic") legitimately sitting in TWO groups is
    disclosed per member as `also_in`, never silently summed as if exclusive."""
    app, Sess = _client(tmp_path)
    with Sess() as s:
        s.add(Source(name="Src", domain="s.test"))
        s.flush()
        s.commit()

    try:
        with TestClient(app) as c:
            m = c.post("/api/insights/supergroups", json={"name": "Mathematics"}).json()["id"]
            p = c.post("/api/insights/supergroups", json={"name": "Philosophy"}).json()["id"]
            c.post(f"/api/insights/supergroups/{m}/members", json={"rings": ["logic"]})
            c.post(f"/api/insights/supergroups/{p}/members", json={"rings": ["logic"]})

            body = c.get("/api/insights/supergroups").json()
            groups = {g["name"]: g for g in body["supergroups"]}
            assert groups["Mathematics"]["members"][0]["also_in"] == ["Philosophy"]
            assert groups["Philosophy"]["members"][0]["also_in"] == ["Mathematics"]
    finally:
        app.dependency_overrides.clear()


def test_supergroup_endpoint_no_overlap_disclosures_when_members_are_disjoint(tmp_path):
    """Negative space: two unrelated members in one group, and a member that sits
    in only ONE group, must carry no overlap disclosure at all."""
    app, Sess = _client(tmp_path)
    with Sess() as s:
        s.add(Source(name="Src", domain="s.test"))
        s.flush()
        s.add(Article(url="https://s.test/1", canonical_url="https://s.test/1",
                      source_id=1, title="t", content="x", hash="h1"))
        s.flush()
        _seed_keyword(s, "Trump", "trump", article_ids=[1])
        _seed_keyword(s, "Biden", "biden", article_ids=[1])
        s.commit()

    try:
        with TestClient(app) as c:
            sid = c.post("/api/insights/supergroups", json={"name": "People"}).json()["id"]
            c.post(f"/api/insights/supergroups/{sid}/members", json={"normalized": ["trump", "biden"]})

            g = c.get("/api/insights/supergroups").json()["supergroups"][0]
            assert g["within_group_overlap"] == {}
            assert all("also_in" not in m for m in g["members"])
            assert g["mentions"] == 2  # 1 + 1, no double count to worry about here
    finally:
        app.dependency_overrides.clear()


def test_supergroup_endpoint_series_top_attaches_rate_and_series_to_top_groups_only(tmp_path):
    """S1.5, bounded: series_top=0 (the default) is byte-identical (no rate/series
    key at all); series_top>0 attaches both ONLY to that many top-mentioned groups,
    and the series is summed over the SAME deduped ids as the headline total (a
    day where the overlapping "ai"/"artificial-intelligence" pair both fire must
    show the true count once, not twice)."""
    app, Sess = _client(tmp_path)
    with Sess() as s:
        s.add(Source(name="Src", domain="s.test"))
        s.flush()
        s.add(Article(url="https://s.test/1", canonical_url="https://s.test/1",
                      source_id=1, title="t", content="x", hash="h1"))
        s.flush()
        _seed_keyword(s, "AI", "ai", article_ids=[1])
        s.commit()

    try:
        with TestClient(app) as c:
            sid = c.post("/api/insights/supergroups", json={"name": "AI"}).json()["id"]
            c.post(f"/api/insights/supergroups/{sid}/members", json={"normalized": ["ai"]})
            c.post(f"/api/insights/supergroups/{sid}/members", json={"rings": ["artificial-intelligence"]})

            default = c.get("/api/insights/supergroups").json()["supergroups"][0]
            assert "rate" not in default and "series" not in default

            body = c.get("/api/insights/supergroups?series_top=1&window_days=7").json()
            g = body["supergroups"][0]
            assert g["rate"]["recent"] == 1  # the ONE real mention, not 2
            today_iso = date.today().isoformat()
            assert g["series"] == [{"date": today_iso, "count": 1}]
    finally:
        app.dependency_overrides.clear()


def test_supergroup_endpoint_dominance_is_none_for_an_empty_group(tmp_path):
    app, Sess = _client(tmp_path)
    try:
        with TestClient(app) as c:
            c.post("/api/insights/supergroups", json={"name": "Empty"})
            g = c.get("/api/insights/supergroups").json()["supergroups"][0]
            assert g["dominance"] is None
            assert g["mentions"] == 0 and g["distinct_keywords"] == 0
    finally:
        app.dependency_overrides.clear()


def test_redundant_members_endpoint_reports_the_field_export_scenario(tmp_path):
    """S4.1 end to end: the report endpoint surfaces a plain family member fully
    covered by a ring in the same group -- a REPORT only (nothing is removed)."""
    app, Sess = _client(tmp_path)
    with Sess() as s:
        s.add(Source(name="Src", domain="s.test"))
        s.flush()
        s.add(Article(url="https://s.test/1", canonical_url="https://s.test/1",
                      source_id=1, title="t", content="x", hash="h1"))
        s.flush()
        _seed_keyword(s, "AI", "ai", article_ids=[1])
        s.commit()

    try:
        with TestClient(app) as c:
            sid = c.post("/api/insights/supergroups", json={"name": "AI"}).json()["id"]
            c.post(f"/api/insights/supergroups/{sid}/members", json={"normalized": ["ai"]})
            c.post(f"/api/insights/supergroups/{sid}/members", json={"rings": ["artificial-intelligence"]})

            r = c.get("/api/insights/supergroups/redundant-members").json()
            assert r["count"] == 1
            assert r["items"][0]["member"] == "ai"
            assert r["items"][0]["redundant_with_rings"] == ["artificial-intelligence"]
            assert isinstance(r["method"], str) and r["method"]

            # The report is read-only -- the member is still there afterwards.
            g = c.get("/api/insights/supergroups").json()["supergroups"][0]
            assert any(m["normalized"] == "ai" for m in g["members"])
    finally:
        app.dependency_overrides.clear()
