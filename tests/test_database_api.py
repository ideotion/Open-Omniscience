"""
Tests for the database overview API (/api/database/stats).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Verifies the Database management tab gets HONEST figures: real row counts that
move when rows are added, and that only present tables are reported.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from src.api.main import app
from src.database.models import Source
from src.database.session import init_db, session_scope


def setup_module(_module):
    init_db()


def test_stats_shape_and_backend():
    with TestClient(app) as client:
        r = client.get("/api/database/stats")
    assert r.status_code == 200
    body = r.json()
    assert "backend" in body
    assert isinstance(body["counts"], dict)
    # Core tables always present after init_db().
    assert "articles" in body["counts"]
    assert "sources" in body["counts"]
    # table_count reflects a real introspection, not a guess.
    assert body["table_count"] >= len(body["counts"])


def test_countries_breakdown_counts_and_keywords():
    # Add a couple of sources with country + tags, then check the breakdown.
    d1 = f"cov-{uuid.uuid4().hex}.test"
    d2 = f"cov-{uuid.uuid4().hex}.test"
    with session_scope() as s:
        s.add(Source(name="Cov A", domain=d1, country="ZZ", tags="politics,economy"))
        s.add(Source(name="Cov B", domain=d2, country="ZZ", tags="politics,sports", enabled=False))
    with TestClient(app) as client:
        body = client.get("/api/database/countries").json()
    try:
        row = next(c for c in body["countries"] if c["code"] == "zz")
        assert row["sources"] >= 2 and row["enabled"] >= 1
        tag_map = dict(row["top_tags"])
        assert tag_map.get("politics", 0) >= 2  # aggregated across the two sources
        assert "missing" in body and isinstance(body["missing"], list)
    finally:
        with session_scope() as s:
            s.query(Source).filter(Source.domain.in_([d1, d2])).delete(synchronize_session=False)


def test_source_count_increments_with_real_rows():
    # Unique domain so the test is idempotent against the persistent dev DB
    # (domain is UNIQUE); cleaned up afterwards to leave no trace.
    domain = f"stat-probe-{uuid.uuid4().hex}.test"
    with TestClient(app) as client:
        before = client.get("/api/database/stats").json()["counts"]["sources"]
        with session_scope() as s:
            s.add(Source(name="Stat Probe", domain=domain))
        after = client.get("/api/database/stats").json()["counts"]["sources"]
        assert after == before + 1
        with session_scope() as s:
            s.query(Source).filter_by(domain=domain).delete()


def test_three_class_sources_split_partitions_the_flat_total():
    """2026-07-23 field-feedback S1.3 (amended after adversarial review): the flat
    "sources" COUNT(*) blends enabled/qualified (actively collecting) sources with
    disabled discovery candidates AND enabled-but-not-yet-qualified sources --
    exactly the figure a field export showed as "~50k sources" against a ~5k-article
    corpus and read as an alarm. A first two-class cut (qualified vs candidates) did
    NOT sum back to the total -- an enabled-pending source was invisible in both. The
    three classes (qualified / pending / candidates) must move independently AND sum
    exactly to the flat total, so nothing is silently uncounted."""
    from src.catalog.qualification import STATUS_DISQUALIFIED, STATUS_QUALIFIED, STATUS_UNQUALIFIED

    collecting = f"collecting-{uuid.uuid4().hex}.test"
    pending = f"pending-{uuid.uuid4().hex}.test"
    disq_enabled = f"disq-enabled-{uuid.uuid4().hex}.test"
    candidate = f"candidate-{uuid.uuid4().hex}.test"
    with TestClient(app) as client:
        before = client.get("/api/database/stats").json()["counts"]
        with session_scope() as s:
            s.add(Source(name="Collecting", domain=collecting, enabled=True,
                         status=STATUS_QUALIFIED))
            s.add(Source(name="Pending", domain=pending, enabled=True,
                         status=STATUS_UNQUALIFIED))
            s.add(Source(name="Disqualified but enabled", domain=disq_enabled, enabled=True,
                         status=STATUS_DISQUALIFIED))
            s.add(Source(name="Candidate", domain=candidate, enabled=False,
                         status=STATUS_UNQUALIFIED))
        after = client.get("/api/database/stats").json()["counts"]
        assert after["sources_qualified"] == before["sources_qualified"] + 1
        # both the never-judged AND the disqualified-but-still-enabled source count
        # as "pending" -- neither collecting nor a review-queue candidate.
        assert after["sources_pending"] == before["sources_pending"] + 2
        assert after["sources_candidates"] == before["sources_candidates"] + 1
        # a disabled candidate never counts as collecting, and vice versa
        assert after["sources_qualified"] < after["sources"]
        # the three classes must sum EXACTLY to the flat total -- nothing uncounted.
        assert (
            after["sources_qualified"] + after["sources_pending"] + after["sources_candidates"]
            == after["sources"]
        )
        with session_scope() as s:
            s.query(Source).filter(
                Source.domain.in_([collecting, pending, disq_enabled, candidate])
            ).delete(synchronize_session=False)
