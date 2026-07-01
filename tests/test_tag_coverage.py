"""Per-tag scraping coverage (src.scheduler.coverage.tag_coverage).

Pins the honest contract: reach/fresh/backed-off/never-reached come only from
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
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, FeedFetchState, Source
from src.scheduler.coverage import tag_coverage


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
    _src(db, "c", tags="news")  # no state row -> never reached
    _state(db, a.id, checked=now - timedelta(hours=1), status=200)
    _state(db, b.id, checked=now - timedelta(hours=40), status=304)
    db.commit()

    cov = tag_coverage(db, fresh_window_hours=24)
    tags = {t["tag"]: t for t in cov["tags"]}

    news = tags["news"]
    assert news["total"] == 3
    assert news["reached"] == 2 and news["never_reached"] == 1
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
