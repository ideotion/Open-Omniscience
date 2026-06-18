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
