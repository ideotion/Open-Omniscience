"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

S2 (2026-07-23 field-feedback workflow): the hourly Library-counter snapshot
recorder (:mod:`src.database.snapshots`) + ``GET /api/library/history``. The
maintainer asked for infinite-RETENTION history so the Library tab can show
small evolution graphs instead of bare live figures. Covers: the freshness
gate (no double-write within the same hour), a real write when due, honest
degrade on tables absent from a build, the articles/hour live-derived path
(backfills for free from ``Article.created_at``, no gap), the bounded read
window, and a wiring-composition guard for the new endpoint.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.database.models import Article, Source
from src.database.session import SessionLocal, init_db
from src.database.snapshots import (
    ALL_METRICS,
    hourly_article_counts,
    maybe_snapshot_library_stats,
    metric_history,
)


@pytest.fixture()
def db():
    init_db()
    s = SessionLocal()
    yield s
    s.rollback()
    s.close()


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


def _no_score(obj) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert "score" not in str(k).lower(), f"a composite score leaked: {k}"
            _no_score(v)
    elif isinstance(obj, list):
        for v in obj:
            _no_score(v)


def _seed_source(db) -> Source:
    src = Source(name=f"S {uuid.uuid4().hex[:6]}", domain=f"h-{uuid.uuid4().hex[:8]}.example", language="en")
    db.add(src)
    db.flush()
    return src


def test_snapshot_writes_once_then_skips_as_fresh(db):
    now = datetime(2027, 3, 4, 10, 30, tzinfo=UTC)
    out1 = maybe_snapshot_library_stats(db, now=now)
    db.commit()
    assert "recorded" in out1
    assert "articles" in out1["recorded"]
    assert out1["recorded"]["sources"] == 0 or isinstance(out1["recorded"]["sources"], int)

    # A second call within the SAME hour bucket must be a no-op (the (metric,
    # hour) unique constraint is the freshness gate — no separate marker file).
    out2 = maybe_snapshot_library_stats(db, now=now + timedelta(minutes=20))
    assert out2 == {"skipped": "fresh", "hour": "2027-03-04T10:00:00"}


def test_snapshot_records_a_real_row_reflecting_actual_counts(db):
    _seed_source(db)
    _seed_source(db)
    db.flush()
    now = datetime(2027, 3, 5, 11, 0, tzinfo=UTC)
    out = maybe_snapshot_library_stats(db, now=now)
    db.commit()
    assert out["recorded"]["sources"] >= 2

    hist = metric_history(db, metric="sources", days=7)
    assert hist["series"], "expected at least one recorded point"
    assert hist["series"][-1]["n"] >= 2
    assert hist["recording_began_at"] is not None


def test_a_mid_batch_collision_never_discards_sibling_inserts(db):
    """A concurrent writer could in principle race a snapshot for ONE metric
    (never the anchor, or the anchor-freshness check would already have
    short-circuited the whole call) while this call is still due. Each row
    insert runs in its own SAVEPOINT (session.begin_nested()) precisely so an
    IntegrityError on one metric's row can never discard the OTHER metrics
    already inserted earlier in the same loop -- the project's own documented
    lesson about a bare session.rollback() wiping a whole uncommitted batch."""
    hour = datetime(2027, 3, 9, 8, 0, tzinfo=UTC)
    bucket = hour.replace(minute=0, second=0, microsecond=0, tzinfo=None)
    from src.database.models import StatSnapshot

    # A pre-existing row for "sources" at this exact hour -- as if another
    # writer had already recorded it -- while "articles" (the anchor) has NOT
    # been recorded yet, so the freshness gate does not short-circuit.
    db.add(StatSnapshot(metric="sources", taken_at=bucket, value=999))
    db.commit()

    out = maybe_snapshot_library_stats(db, now=hour)  # must not raise
    db.commit()

    # "sources" collided -- never overwritten, never reported as freshly recorded.
    assert "sources" not in out.get("recorded", {})
    sources_hist = metric_history(db, metric="sources", days=7)
    at_hour = [p for p in sources_hist["series"] if p["t"] == "2027-03-09T08:00:00"]
    assert len(at_hour) == 1 and at_hour[0]["n"] == 999, "the pre-existing row must survive untouched"

    # "articles" (and any other present metric) still recorded in the SAME call,
    # despite the sibling collision -- the savepoint isolated the failure.
    assert "articles" in out.get("recorded", {}), (
        "a collision on one metric must not discard the others recorded in the same pass"
    )


def test_a_new_hour_produces_a_new_row_never_overwriting_the_last(db):
    hour1 = datetime(2027, 3, 6, 9, 0, tzinfo=UTC)
    hour2 = datetime(2027, 3, 6, 10, 0, tzinfo=UTC)
    maybe_snapshot_library_stats(db, now=hour1)
    db.commit()
    _seed_source(db)
    db.commit()
    maybe_snapshot_library_stats(db, now=hour2)
    db.commit()

    hist = metric_history(db, metric="sources", days=7)
    taken_hours = {p["t"] for p in hist["series"]}
    assert "2027-03-06T09:00:00" in taken_hours
    assert "2027-03-06T10:00:00" in taken_hours
    by_hour = {p["t"]: p["n"] for p in hist["series"]}
    # the count strictly grew between the two snapshots — APPEND-only, never
    # an overwrite of the earlier (lower) value.
    assert by_hour["2027-03-06T10:00:00"] > by_hour["2027-03-06T09:00:00"]


def test_unknown_metric_is_reported_honestly(db):
    out = metric_history(db, metric="not-a-real-metric", days=7)
    assert out["series"] == []
    assert out["recording_began_at"] is None
    assert "error" in out


def test_articles_per_hour_backfills_live_from_created_at_with_no_gap(db):
    # articles/hour is DERIVED from Article.created_at directly -- real history
    # that already existed before this feature shipped, so there is no "recording
    # began at X" gap the way there is for the snapshot-table metrics.
    src = _seed_source(db)
    now = datetime.now(UTC)
    for i in range(3):
        db.add(Article(
            url=f"https://h.example/{uuid.uuid4().hex}",
            canonical_url=f"https://h.example/{uuid.uuid4().hex}",
            source_id=src.id,
            title=f"A{i}",
            content="x " * 40,
            language="en",
            hash=uuid.uuid4().hex + uuid.uuid4().hex,
            created_at=now - timedelta(hours=1),
        ))
    db.commit()
    series = hourly_article_counts(db, days=7, now=now)
    assert sum(p["n"] for p in series) >= 3


def test_all_metrics_registry_includes_the_live_derived_and_snapshot_kinds():
    assert "articles_per_hour" in ALL_METRICS
    assert "sources" in ALL_METRICS
    assert "wiki_pages" in ALL_METRICS
    assert "law_documents" in ALL_METRICS


def test_endpoint_serves_a_snapshot_metric(client, db):
    _seed_source(db)
    db.commit()
    now = datetime(2027, 3, 7, 12, 0, tzinfo=UTC)
    maybe_snapshot_library_stats(db, now=now)
    db.commit()
    r = client.get("/api/library/history", params={"metric": "sources", "days": 30})
    assert r.status_code == 200
    body = r.json()
    assert body["metric"] == "sources"
    assert isinstance(body["series"], list)
    _no_score(body)


def test_endpoint_serves_the_live_derived_articles_per_hour_metric(client):
    r = client.get("/api/library/history", params={"metric": "articles_per_hour", "days": 7})
    assert r.status_code == 200
    body = r.json()
    assert body["metric"] == "articles_per_hour"
    assert isinstance(body["series"], list)


def test_endpoint_rejects_an_unknown_metric(client):
    r = client.get("/api/library/history", params={"metric": "totally-bogus"})
    assert r.status_code == 400


def test_endpoint_clamps_an_absurd_days_value(client):
    # storage retention is infinite; the RESPONSE window must still be bounded.
    r = client.get("/api/library/history", params={"metric": "articles", "days": 999999999})
    assert r.status_code == 200


def test_filtered_source_status_metrics_partition_the_flat_total(db):
    """2026-07-24 Session A §5: the 4 filtered metrics (sources_qualified /
    sources_disqualified / sources_never_judged / sources_candidates) must sum
    back EXACTLY to the flat "sources" count, and must stay aligned with
    src/api/database.py's own database_stats() predicates -- ONE source of truth
    for what each bucket means, never two divergent definitions."""
    from src.catalog.qualification import STATUS_DISQUALIFIED, STATUS_QUALIFIED, STATUS_UNQUALIFIED

    s1 = _seed_source(db)
    s1.status = STATUS_QUALIFIED
    s2 = _seed_source(db)
    s2.status = STATUS_DISQUALIFIED
    s3 = _seed_source(db)
    s3.status = STATUS_UNQUALIFIED  # never judged (the model default)
    s4 = _seed_source(db)
    s4.enabled = False  # a discovery candidate, awaiting review
    db.commit()

    # A date strictly LATER than every other hardcoded date in this shared-DB
    # test file (the latest in use elsewhere is 2027-03-09), so this test's own
    # row is unambiguously the freshest when read back below -- this file's own
    # established convention (tests accumulate real history in the same store;
    # correctness is checked at a SPECIFIC hour, never by blindly trusting order).
    now = datetime(2027, 3, 15, 6, 0, tzinfo=UTC)
    out = maybe_snapshot_library_stats(db, now=now)
    db.commit()

    for m in (
        "sources_qualified", "sources_disqualified", "sources_never_judged", "sources_candidates",
    ):
        assert m in ALL_METRICS
        assert m in out["recorded"], f"{m} must be recorded in the same pass as the plain counts"

    assert out["recorded"]["sources_qualified"] >= 1
    assert out["recorded"]["sources_disqualified"] >= 1
    assert out["recorded"]["sources_never_judged"] >= 1
    assert out["recorded"]["sources_candidates"] >= 1
    total = (
        out["recorded"]["sources_qualified"] + out["recorded"]["sources_disqualified"]
        + out["recorded"]["sources_never_judged"] + out["recorded"]["sources_candidates"]
    )
    assert total == out["recorded"]["sources"], "the 4 buckets must partition the flat total exactly"

    # Cross-check against the live database_stats() predicates directly -- the
    # module this feature must never drift from. database_stats()'s own
    # "sources_pending" bucket is (enabled AND status != qualified), i.e. exactly
    # disqualified + never_judged combined -- the finer split this feature adds.
    from src.api.database import database_stats

    stats = database_stats(db)
    assert stats["counts"]["sources_qualified"] == out["recorded"]["sources_qualified"]
    assert (
        stats["counts"]["sources_pending"]
        == out["recorded"]["sources_disqualified"] + out["recorded"]["sources_never_judged"]
    )
    assert stats["counts"]["sources_candidates"] == out["recorded"]["sources_candidates"]

    hist = metric_history(db, metric="sources_qualified", days=7)
    at_hour = [p for p in hist["series"] if p["t"] == "2027-03-15T06:00:00"]
    assert len(at_hour) == 1 and at_hour[0]["n"] == out["recorded"]["sources_qualified"]
    assert hist["recording_began_at"] is not None


def test_filtered_metric_history_read_degrades_honestly_for_a_recognised_metric(db):
    """A recognised filtered-metric name must read as a plain list (never an
    exception, never the 'unknown metric' error the truly-bogus-name path
    returns) -- the honest-degrade contract for a metric that simply has no
    history yet, distinct from one that was never registered at all."""
    out = metric_history(db, metric="sources_never_judged", days=7)
    assert isinstance(out["series"], list)
    assert out.get("error") != "unknown metric"


def test_wiring_composes_the_real_route():
    """The 'slice-1c 404 lesson' (CLAUDE.md): a wiring test must COMPOSE the
    actual route (router prefix + decorator path), never assert two literal
    strings side by side."""
    lib_path = __import__("pathlib").Path(__file__).resolve().parents[1] / "src" / "api" / "library.py"
    src = lib_path.read_text(encoding="utf-8")
    prefix_m = re.search(r'APIRouter\(prefix="([^"]+)"', src)
    assert prefix_m, "router prefix not found"
    path_m = re.search(r'@router\.get\("(/history[^"]*)"', src)
    assert path_m, "the /history route decorator not found"
    composed = prefix_m.group(1) + path_m.group(1)
    assert composed == "/api/library/history"
