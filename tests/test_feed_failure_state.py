"""A failed feed fetch is RECORDED in FeedFetchState (field analysis 2026-11, finding 3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Before: only a 200 or a 304 wrote ``last_status`` / ``last_checked_at`` (``_record_feed_state``). A feed whose own
fetch failed wrote nothing, so Coverage's "error" bucket could never fill and every export read a feed that failed
every pass as "never checked" (``last_feed_status: null``). Now the failure is recorded: the HTTP status the failure
names, else ``0`` ("checked, no HTTP status"), and the check time. A Stop (the kill switch) is the person's own setting,
not the feed's answer, so it records NOTHING (R614's rule, unchanged). The backoff still resets on a failure, as
tests/test_feed_backoff.py pins. No network: the fetcher is stubbed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.database.models import FeedFetchState, Source
from src.database.session import SessionLocal, init_db
from src.ingest import FetchError, RobotsDisallowed, RobotsUnavailable
from src.ingest import pipeline as P
from src.ingest.fetch_verdict import KILL_SWITCH_REFUSAL
from src.scheduler.coverage import _status_bucket


@pytest.fixture()
def db():
    init_db()
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _make_source(s) -> Source:
    src = Source(
        name=f"F {uuid.uuid4().hex[:6]}",
        domain=f"f-{uuid.uuid4().hex[:6]}.example",
        rss_url="https://feed.example/rss",
        language="en",
        enabled=True,
        status="qualified",
    )
    s.add(src)
    s.commit()
    return src


class _Raise:
    def __init__(self, exc: BaseException):
        self._exc = exc

    def fetch(self, *a, **k):
        raise self._exc


def _ingest_failing(db, exc: BaseException) -> FeedFetchState | None:
    src = _make_source(db)
    tally = P.ingest_source(db, src, fetcher=_Raise(exc))
    db.commit()
    assert tally.get("stored", 0) == 0
    return db.get(FeedFetchState, src.id)


def test_http_failure_records_its_status_and_time(db):
    before = datetime.now(UTC)
    st = _ingest_failing(db, FetchError("HTTP 403 for https://feed.example/rss"))
    assert st is not None
    assert st.last_status == 403
    checked = st.last_checked_at if st.last_checked_at.tzinfo else st.last_checked_at.replace(tzinfo=UTC)
    assert checked >= before - timedelta(seconds=1)


def test_failure_without_http_status_records_zero(db):
    st = _ingest_failing(db, FetchError("connection failed: name or service not known"))
    assert st is not None and st.last_status == 0 and st.last_checked_at is not None


@pytest.mark.parametrize("exc", [RobotsDisallowed("robots.txt disallows https://feed.example/rss"),
                                 RobotsUnavailable("robots.txt refused (HTTP 403) for https://feed.example")])
def test_robots_refusal_is_not_the_feeds_status(db, exc):
    st = _ingest_failing(db, exc)
    assert st is not None and st.last_status == 0 and st.last_checked_at is not None


def test_a_stop_records_nothing(db):
    st = _ingest_failing(db, FetchError(f"{KILL_SWITCH_REFUSAL}: https://feed.example/rss"))
    assert st is None  # no row: the person's setting says nothing about the feed


def test_failure_keeps_validators_and_still_resets_backoff(db):
    src = _make_source(db)
    db.add(FeedFetchState(source_id=src.id, etag='"v1"', last_modified="Mon, 02 Nov 2026 00:00:00 GMT",
                          last_status=200, consecutive_unchanged=3,
                          skip_until=datetime.now(UTC) + timedelta(hours=1)))
    db.commit()
    P.ingest_source(db, src, fetcher=_Raise(FetchError("HTTP 503 for https://feed.example/rss")))
    db.commit()
    st = db.get(FeedFetchState, src.id)
    assert st.last_status == 503
    assert st.etag == '"v1"' and st.last_modified == "Mon, 02 Nov 2026 00:00:00 GMT"
    assert st.consecutive_unchanged == 0 and st.skip_until is None


@pytest.mark.parametrize(("text", "status"), [
    ("HTTP 404 for https://x.example/rss", 404),
    ("HTTP 429 for https://x.example/rss", 429),
    ("timed out after 30 s", 0),
    ("", 0),
])
def test_feed_failure_status(text, status):
    assert P.feed_failure_status(FetchError(text)) == status


def test_recorded_failures_land_in_coverage_error_bucket():
    # Coverage buckets the recorded status: both a named HTTP failure and "no status" (0) read as an error,
    # where before the failure wrote nothing and the feed read as not reached.
    assert _status_bucket(403) == "error"
    assert _status_bucket(0) == "error"
    assert _status_bucket(None) == "unknown"
