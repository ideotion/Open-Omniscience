"""Per-tag scraping coverage (src.scheduler.coverage.tag_coverage).

Pins the honest contract: reach/fresh/failed/backed-off/not-read come only from
real FeedFetchState timestamps, a multi-tag source counts under each tag, crawl
sources are counted but not reach-tracked, and NO score field appears anywhere.

Pure ORM (no FastAPI/crypto): an in-memory SQLite engine, so it runs in the
sandbox as well as CI.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, FeedFetchState, Source
from src.scheduler.coverage import tag_coverage
from tests._app_engine import app_sqlite_engine


@pytest.fixture()
def db():
    engine = app_sqlite_engine(
        ":memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()


def _src(session, name, *, tags, rss=True, enabled=True) -> Source:
    src = Source(
        name=name,
        domain=f"{name}.example",
        rss_url=f"https://{name}.example/rss" if rss else None,
        tags=tags,
        enabled=enabled,
    )
    session.add(src)
    session.flush()
    return src


def _state(session, source_id, *, checked=None, status=None, skip_until=None):
    session.add(
        FeedFetchState(
            source_id=source_id,
            last_checked_at=checked,
            last_status=status,
            skip_until=skip_until,
        )
    )


def test_reach_and_fresh_from_real_timestamps(db):
    now = datetime.now(UTC)
    a = _src(db, "a", tags="news, politics")  # fetched 1h ago -> reached + fresh
    b = _src(db, "b", tags="news")  # fetched 40h ago -> reached, stale
    _src(db, "c", tags="news")  # no state row -> not read
    _state(db, a.id, checked=now - timedelta(hours=1), status=200)
    _state(db, b.id, checked=now - timedelta(hours=40), status=304)
    db.commit()

    cov = tag_coverage(db, fresh_window_hours=24)
    tags = {t["tag"]: t for t in cov["tags"]}

    news = tags["news"]
    assert news["total"] == 3
    assert news["reached"] == 2 and news["not_read"] == 1 and news["failed"] == 0
    assert news["fresh"] == 1 and news["stale"] == 1
    assert news["reach_pct"] == round(2 / 3, 4)
    assert news["fresh_pct"] == round(1 / 3, 4)
    # status mix: one ok (200), one unchanged (304), one unknown (no row)
    assert news["status"] == {"ok": 1, "unchanged": 1, "error": 0, "unknown": 1}
    # oldest reached is the 40h-old feed
    assert news["oldest_reached_age_seconds"] >= 39 * 3600

    # a multi-tag source counts under EACH of its tags (overlap, not partition)
    assert tags["politics"]["total"] == 1 and tags["politics"]["reached"] == 1

    totals = cov["totals"]
    assert totals["total"] == 3 and totals["reached"] == 2 and totals["fresh"] == 1


def test_backed_off_is_not_a_failure_and_window_is_echoed(db):
    now = datetime.now(UTC)
    a = _src(db, "a", tags="news")
    _state(
        db, a.id, checked=now - timedelta(hours=2), status=200,
        skip_until=now + timedelta(hours=3),
    )
    db.commit()

    cov = tag_coverage(db, fresh_window_hours=6)
    news = next(t for t in cov["tags"] if t["tag"] == "news")
    assert news["reached"] == 1 and news["fresh"] == 1  # reached+fresh despite backoff
    assert news["backed_off"] == 1
    assert news["status"]["error"] == 0  # backoff is NOT an error
    assert cov["fresh_window_hours"] == 6  # the window is always disclosed


def test_a_failing_feed_that_is_backed_off_counts_as_failed_not_backed_off(db):
    """Row 454: a failure now advances the back-off, so a failing feed carries a skip deadline too. It is counted under
    "failed" with its reason, never under "Backed off (de-churn, not failures)", whose label would then be wrong."""
    now = datetime.now(UTC)
    a = _src(db, "a", tags="news")
    _state(db, a.id, checked=now - timedelta(minutes=10), status=503, skip_until=now + timedelta(minutes=20))
    db.commit()
    news = next(t for t in tag_coverage(db, fresh_window_hours=6)["tags"] if t["tag"] == "news")
    assert news["failed"] == 1 and news["failed_by_reason"]["http_5xx"] == 1
    assert news["backed_off"] == 0
    assert news["reached"] == 0 and news["fresh"] == 0


def test_crawl_sources_counted_but_not_reach_tracked(db):
    _src(db, "rssone", tags="news", rss=True)
    _src(db, "crawlone", tags="news", rss=False)  # no rss_url -> crawl
    _src(db, "untag", tags="")  # untagged bucket
    db.commit()

    cov = tag_coverage(db)
    news = next(t for t in cov["tags"] if t["tag"] == "news")
    assert news["total"] == 1  # only the RSS source counts toward reach
    assert news["crawl"] == 1  # crawl source counted, honestly, separately
    assert cov["crawl_sources"] == 1
    assert any(t["tag"] == "·untagged" for t in cov["tags"])  # untagged not dropped


def test_disabled_sources_excluded(db):
    _src(db, "on", tags="news", enabled=True)
    _src(db, "off", tags="news", enabled=False)
    db.commit()
    news = next(t for t in tag_coverage(db)["tags"] if t["tag"] == "news")
    assert news["total"] == 1


def _walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_keys(v)


def test_no_score_or_ranking_fields(db):
    a = _src(db, "a", tags="news")
    _state(db, a.id, checked=datetime.now(UTC), status=200)
    db.commit()
    keys = {k.lower() for k in _walk_keys(tag_coverage(db))}
    assert not any(("score" in k or "ranking" in k or k == "rank") for k in keys)


# ---- R848 (row 448): only a READ check (200 / 304) is reached or fresh; a failed check is "failed" with its reason class;
# no check on record is "not read". Since #2419 a failed feed fetch writes last_checked_at + last_status, so the time alone
# must never read as a fetch.
def test_a_failed_check_is_never_reached_or_fresh_and_carries_its_reason_class(db):
    now = datetime.now(UTC)
    ok = _src(db, "ok", tags="news")
    e403 = _src(db, "e403", tags="news")
    e503 = _src(db, "e503", tags="news")
    e0 = _src(db, "e0", tags="news")
    _src(db, "none", tags="news")
    _state(db, ok.id, checked=now - timedelta(hours=1), status=200)
    _state(db, e403.id, checked=now - timedelta(minutes=5), status=403)
    _state(db, e503.id, checked=now - timedelta(minutes=5), status=503)
    _state(db, e0.id, checked=now - timedelta(minutes=5), status=0)
    db.commit()

    news = next(t for t in tag_coverage(db, fresh_window_hours=24)["tags"] if t["tag"] == "news")
    assert news["total"] == 5
    assert news["reached"] == 1 and news["fresh"] == 1  # the three recent FAILED checks count as neither
    assert news["failed"] == 3
    assert news["failed_by_reason"] == {"http_4xx": 1, "http_5xx": 1, "no_http_status": 1, "other": 0}
    assert news["not_read"] == 1
    assert news["reached"] + news["failed"] + news["not_read"] == news["total"]
    assert news["reach_pct"] == round(1 / 5, 4)
    # the oldest READ age is the 200's, never a failed check's
    assert news["oldest_reached_age_seconds"] >= 3500


def test_a_record_with_no_check_time_is_not_read(db):
    # a back-off-only row (no last_checked_at) is no evidence of a check of either kind
    a = _src(db, "a", tags="news")
    _state(db, a.id, checked=None, status=None, skip_until=datetime.now(UTC) + timedelta(hours=1))
    db.commit()
    news = next(t for t in tag_coverage(db)["tags"] if t["tag"] == "news")
    assert news["reached"] == 0 and news["failed"] == 0 and news["fresh"] == 0 and news["not_read"] == 1


def test_the_payload_names_reason_classes_never_an_address(db):
    a = _src(db, "a", tags="news")
    _state(db, a.id, checked=datetime.now(UTC), status=403)
    db.commit()
    text = repr(tag_coverage(db))
    assert "a.example" not in text and "http://" not in text and "https://" not in text


@pytest.mark.parametrize("status", [204, 206, 301, 302])
def test_a_failure_with_a_2xx_or_3xx_status_is_failed_not_read(db, status):
    # the fetcher raises on every status but 200 (a 204, a 3xx with no Location), and that failure is recorded
    # with its status: only 200 and 304 are reads
    a = _src(db, "a", tags="news")
    _state(db, a.id, checked=datetime.now(UTC), status=status)
    db.commit()
    news = next(t for t in tag_coverage(db)["tags"] if t["tag"] == "news")
    assert news["reached"] == 0 and news["fresh"] == 0 and news["failed"] == 1
    assert news["failed_by_reason"]["other"] == 1
