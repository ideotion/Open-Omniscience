"""Recycled-claim detection (manipulation-pattern card, ruling #13).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Names the STRUCTURE: a recent article near-identical to a much OLDER one = a claim
resurfacing after dormancy. These tests pin the honest gates — the trigger is a measured
time GAP, a current member is required (not two equally-old near-dups), a single source
recycling its own evergreen is flagged, and there is no score.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.recycled_claim import find_recycled_claims
from src.database.models import Article, Base, Source

# A paragraph long enough to clear min_chars and to shingle to a high Jaccard with itself.
TEXT = (
    "The central bank announced on Monday that it would hold interest rates steady for "
    "the rest of the quarter, citing persistent uncertainty in global energy markets and "
    "a softer-than-expected reading on consumer demand. Officials said they would reassess "
    "the stance at the next scheduled meeting in the autumn before any further decision."
)
OTHER = (
    "A regional museum unveiled a restored mosaic floor this week after a decade of "
    "painstaking conservation work, drawing crowds of schoolchildren and historians alike "
    "to the coastal town where the artefact was first uncovered during roadworks in 1973."
)

NOW = datetime.now().replace(microsecond=0)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()


def _src(db, sid, domain):
    db.add(Source(id=sid, name=f"Src{sid}", domain=domain))
    db.commit()


def _art(db, aid, source_id, text, days_ago):
    db.add(Article(
        id=aid, url=f"https://x/{aid}", canonical_url=f"https://x/{aid}", source_id=source_id,
        title=f"Story {aid}", content=text, hash=f"h{aid}", language="en",
        published_at=NOW - timedelta(days=days_ago),
    ))
    db.commit()


def test_fires_on_a_recent_dup_of_a_much_older_article(db):
    _src(db, 1, "a.test")
    _src(db, 2, "b.test")
    _art(db, 1, 1, TEXT, days_ago=200)  # the dormant original
    _art(db, 2, 2, TEXT, days_ago=2)    # resurfaced now, a different source
    out = find_recycled_claims(db, min_gap_days=60)
    assert out["count"] == 1
    c = out["clusters"][0]
    assert c["gap_days"] >= 190 and c["n_articles"] == 2
    assert c["distinct_sources"] == 2 and c["single_source"] is False
    assert sorted(c["article_ids"]) == [1, 2]
    assert c["first_seen"] < c["resurfaced"]
    assert "much later" in out["caveat"]
    # No score anywhere on the cluster.
    assert not any("score" in k for k in c)


def test_a_short_gap_is_not_recycled(db):
    """Two recent near-dups are echo-chamber territory, not a resurfacing."""
    _src(db, 1, "a.test")
    _src(db, 2, "b.test")
    _art(db, 1, 1, TEXT, days_ago=5)
    _art(db, 2, 2, TEXT, days_ago=2)
    assert find_recycled_claims(db, min_gap_days=60)["count"] == 0


def test_two_old_dups_without_a_recent_member_do_not_fire(db):
    """A large gap between two OLD articles is not a CURRENT resurfacing."""
    _src(db, 1, "a.test")
    _src(db, 2, "b.test")
    _art(db, 1, 1, TEXT, days_ago=300)
    _art(db, 2, 2, TEXT, days_ago=120)  # gap 180 but newest is older than recent_days
    assert find_recycled_claims(db, recent_days=14, min_gap_days=60)["count"] == 0


def test_a_single_source_recycling_itself_is_flagged(db):
    _src(db, 1, "a.test")
    _art(db, 1, 1, TEXT, days_ago=250)
    _art(db, 2, 1, TEXT, days_ago=1)
    out = find_recycled_claims(db, min_gap_days=60)
    assert out["count"] == 1
    assert out["clusters"][0]["single_source"] is True
    assert out["clusters"][0]["distinct_sources"] == 1


def test_unrelated_text_does_not_cluster(db):
    _src(db, 1, "a.test")
    _src(db, 2, "b.test")
    _art(db, 1, 1, TEXT, days_ago=200)
    _art(db, 2, 2, OTHER, days_ago=2)  # different story -> no near-dup
    assert find_recycled_claims(db, min_gap_days=60)["count"] == 0


def test_recycled_claims_endpoint(tmp_path):
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'r.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(id=1, name="A", domain="a.test"))
        s.add(Source(id=2, name="B", domain="b.test"))
        s.commit()
        s.add(Article(id=1, url="https://x/1", canonical_url="https://x/1", source_id=1,
                      title="Story 1", content=TEXT, hash="h1", language="en",
                      published_at=NOW - timedelta(days=210)))
        s.add(Article(id=2, url="https://x/2", canonical_url="https://x/2", source_id=2,
                      title="Story 2", content=TEXT, hash="h2", language="en",
                      published_at=NOW - timedelta(days=3)))
        s.commit()

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as c:
            body = c.get("/api/insights/recycled-claims").json()
        assert body["count"] == 1
        assert body["clusters"][0]["distinct_sources"] == 2
        assert sorted(body["clusters"][0]["article_ids"]) == [1, 2]
    finally:
        app.dependency_overrides.clear()
