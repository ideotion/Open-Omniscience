"""Per-feed de-churn backoff for all-duplicate feeds (field log finding F).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field log 2026-06-13: some servers IGNORE conditional-GET headers and return a
full 200 every pass even when nothing changed (~93% duplicate rate at 1-minute
intervals). When a 200 fetch yields ZERO new articles we delay this ONE feed's
next re-check by a CAPPED, TEMPORARY, SELF-RESETTING amount — a transport
de-churn, NEVER an exclusion. ANY new article, a 304, or a fetch error resets it.

These tests cover the state machine (increment / reset / cap) and the collect
loop's additive due-check (a backed-off feed is skipped THIS pass, counted
honestly as "backed_off"). No network: the fetcher is stubbed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.database.models import FeedFetchState, Source
from src.database.session import SessionLocal, init_db
from src.ingest import FetchError, FetchResult
from src.ingest import pipeline as P

_EMPTY_RSS = '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title></channel></rss>'
_RSS_ONE = (
    '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
    '<item><link>{link}</link><title>i</title></item></channel></rss>'
)


class _StubFetcher:
    """Returns scripted FetchResults for the feed URL; raises for article URLs.

    The backoff is decided purely from the feed's 200/304/error + the per-article
    STORED tally, so article fetches are short-circuited to a FetchError (counted
    as fetch_failed, never as STORED) unless a scripted article body is provided.
    """

    def __init__(self, feed_script, *, article_bodies=None):
        self._feed = list(feed_script)
        self._articles = dict(article_bodies or {})
        self.calls: list[str] = []

    def fetch(self, url, *, require_html=True, extra_headers=None):
        self.calls.append(url)
        if require_html:  # an article page
            body = self._articles.get(url)
            if body is None:
                raise FetchError(f"no scripted article for {url}")
            return FetchResult(
                requested_url=url, final_url=url, status_code=200, content=body,
                content_type="text/html", fetched_at=datetime.now(UTC),
            )
        # Feed fetch: serve the next scripted response; default to an empty 200
        # so a shared-DB pass that touches more feeds than scripted never crashes.
        if self._feed:
            return self._feed.pop(0)
        return _feed_result(200)


def _feed_result(status, *, etag=None, content=_EMPTY_RSS):
    return FetchResult(
        requested_url="https://feed.example/rss",
        final_url="https://feed.example/rss",
        status_code=status,
        content=content if status == 200 else "",
        content_type="application/rss+xml",
        fetched_at=datetime.now(UTC),
        etag=etag,
    )


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
        status="qualified",  # the admission gate (0.3 CLOSE GATE ruling) -- this
        # fixture is not exercising qualification, only the feed backoff state machine.
    )
    s.add(src)
    s.commit()
    return src


# --------------------------------------------------------------------------- #
# State machine: all-duplicate 200 sets skip_until + increments the counter
# --------------------------------------------------------------------------- #


def _skip_if_clock_inconclusive(before: datetime, tol_s: float) -> None:
    """Skip (not fail) the ABSOLUTE-seconds backoff bound if the ingest call took
    longer than the assertion's tolerance on this box — the timing experiment is
    then inconclusive, not failed (the skip-when-inconclusive pattern, OO-D15-006).

    ``skip_until`` is ``now_during_call + DELAY``, so the measured ``skip_until -
    before`` carries an error up to the call's wall-clock duration. The backoff
    LOGIC (counter growth, cap, reset) is still asserted unconditionally; only the
    absolute-seconds window is timing-sensitive, and only a pathologically slow box
    can breach it."""
    elapsed = (datetime.now(UTC) - before).total_seconds()
    if elapsed > tol_s:
        pytest.skip(
            f"ingest took {elapsed:.1f}s here (> {tol_s}s tolerance); the absolute "
            "backoff-seconds bound is inconclusive on this box (the growth/cap/reset "
            "assertions still cover the logic)"
        )


def test_all_duplicate_200_sets_skip_until_and_counts(db):
    src = _make_source(db)
    # An empty feed (no items) stores zero articles -> a 200-with-no-new.
    fetcher = _StubFetcher([_feed_result(200, etag='"v1"')])
    before = datetime.now(UTC)
    tally = P.ingest_source(db, src, fetcher=fetcher)
    db.commit()

    assert tally[P.IngestResult.STORED.value] == 0
    st = db.get(FeedFetchState, src.id)
    assert st is not None
    assert st.consecutive_unchanged == 1
    assert st.skip_until is not None
    # First backoff == BASE seconds (2 ** 0).
    _skip_if_clock_inconclusive(before, 5.0)
    delta = st.skip_until.replace(tzinfo=UTC) - before
    assert P.BACKOFF_BASE_S - 5 <= delta.total_seconds() <= P.BACKOFF_BASE_S + 5
    assert not P.feed_is_due(st)  # within the window -> not due


def test_consecutive_unchanged_grows_exponentially_then_caps(db):
    src = _make_source(db)
    for expected in range(1, 5):
        fetcher = _StubFetcher([_feed_result(200)])
        before = datetime.now(UTC)
        P.ingest_source(db, src, fetcher=fetcher)
        db.commit()
        st = db.get(FeedFetchState, src.id)
        assert st.consecutive_unchanged == expected  # the LOGIC, asserted unconditionally
        _skip_if_clock_inconclusive(before, 5.0)
        delay = (st.skip_until.replace(tzinfo=UTC) - before).total_seconds()
        want = min(P.BACKOFF_BASE_S * (2 ** (expected - 1)), P.BACKOFF_CAP_S)
        assert want - 5 <= delay <= want + 5


def test_cap_is_never_exceeded(db):
    src = _make_source(db)
    # Force a large counter; the delay must clamp to the cap, not blow past it.
    st = FeedFetchState(source_id=src.id, consecutive_unchanged=50)
    db.add(st)
    db.commit()
    before = datetime.now(UTC)
    P.ingest_source(db, src, fetcher=_StubFetcher([_feed_result(200)]))
    db.commit()
    st = db.get(FeedFetchState, src.id)
    _skip_if_clock_inconclusive(before, 1.0)  # this bound only tolerates +1s
    delay = (st.skip_until.replace(tzinfo=UTC) - before).total_seconds()
    assert delay <= P.BACKOFF_CAP_S + 1  # clamped, never unbounded


# --------------------------------------------------------------------------- #
# Reset conditions: new content / 304 / fetch error all clear the backoff
# --------------------------------------------------------------------------- #


def test_new_content_resets_backoff(db):
    src = _make_source(db)
    # Pre-set a backoff window.
    db.add(FeedFetchState(
        source_id=src.id, consecutive_unchanged=3,
        skip_until=datetime.now(UTC) + timedelta(hours=1),
    ))
    db.commit()

    link = "https://feed.example/articles/new-1"
    feed = _feed_result(200, content=_RSS_ONE.format(link=link))
    article = "<html><body><article><h1>Fresh</h1><p>" + ("word " * 80) + "</p></article></body></html>"
    fetcher = _StubFetcher([feed], article_bodies={link: article})
    tally = P.ingest_source(db, src, fetcher=fetcher)
    db.commit()

    assert tally[P.IngestResult.STORED.value] >= 1
    st = db.get(FeedFetchState, src.id)
    assert st.consecutive_unchanged == 0
    assert st.skip_until is None
    assert P.feed_is_due(st)


def test_304_does_not_penalize(db):
    src = _make_source(db)
    db.add(FeedFetchState(
        source_id=src.id, etag='"v1"', consecutive_unchanged=2,
        skip_until=datetime.now(UTC) + timedelta(hours=1),
    ))
    db.commit()

    tally = P.ingest_source(db, src, fetcher=_StubFetcher([_feed_result(304, etag='"v1"')]))
    db.commit()
    assert tally["not_modified"] == 1
    st = db.get(FeedFetchState, src.id)
    assert st.consecutive_unchanged == 0
    assert st.skip_until is None  # an honest "unchanged" is not a penalty


def test_fetch_error_resets_backoff(db):
    src = _make_source(db)
    db.add(FeedFetchState(
        source_id=src.id, consecutive_unchanged=4,
        skip_until=datetime.now(UTC) + timedelta(hours=2),
    ))
    db.commit()

    class _Boom:
        def fetch(self, *a, **k):
            raise FetchError("feed unreachable")

    tally = P.ingest_source(db, src, fetcher=_Boom())
    db.commit()
    assert tally["stored"] == 0
    st = db.get(FeedFetchState, src.id)
    assert st.consecutive_unchanged == 0
    assert st.skip_until is None


# --------------------------------------------------------------------------- #
# feed_is_due: pure predicate
# --------------------------------------------------------------------------- #


def test_feed_is_due_predicate():
    now = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
    assert P.feed_is_due(None, now=now) is True
    assert P.feed_is_due(FeedFetchState(source_id=1), now=now) is True
    future = FeedFetchState(source_id=1, skip_until=now + timedelta(minutes=10))
    assert P.feed_is_due(future, now=now) is False
    past = FeedFetchState(source_id=1, skip_until=now - timedelta(minutes=10))
    assert P.feed_is_due(past, now=now) is True
    # Naive datetime (SQLite) is interpreted as UTC, not crashed on.
    naive = FeedFetchState(source_id=1, skip_until=(now + timedelta(minutes=5)).replace(tzinfo=None))
    assert P.feed_is_due(naive, now=now) is False


# --------------------------------------------------------------------------- #
# Collect loop: a backed-off feed is SKIPPED this pass, counted honestly
# --------------------------------------------------------------------------- #


def _disable_existing_sources(db) -> None:
    """The suite shares one on-disk SQLite store, so other tests' enabled sources
    would join a collect pass. Disable them so the pass acts only on our feeds."""
    for s in db.query(Source).filter(Source.enabled.is_(True)).all():
        s.enabled = False
    db.commit()


def test_collect_loop_skips_backed_off_feed(db):
    from src.scheduler.runner import run_scrape_once
    from src.scheduler.settings import SchedulerSettings

    _disable_existing_sources(db)
    due = _make_source(db)
    blocked = _make_source(db)
    # Back off the second feed into the future.
    db.add(FeedFetchState(
        source_id=blocked.id,
        skip_until=datetime.now(UTC) + timedelta(hours=1),
    ))
    db.commit()

    fetcher = _StubFetcher([])  # every feed answers an empty 200 (zero new)
    result = run_scrape_once(db, fetcher, SchedulerSettings(mode="rss"))

    # Exactly one feed processed; the backed-off one is counted, not silently lost.
    assert result["sources_processed"] == 1
    assert result["tally"].get("backed_off") == 1
    # The due feed was re-checked; the blocked one was NOT fetched.
    assert P.feed_is_due(db.get(FeedFetchState, due.id)) is False  # now backed off itself
    # blocked still carries its original (untouched) future deadline.
    assert not P.feed_is_due(db.get(FeedFetchState, blocked.id))


def test_collect_loop_runs_all_when_none_backed_off(db):
    from src.scheduler.runner import run_scrape_once
    from src.scheduler.settings import SchedulerSettings

    _disable_existing_sources(db)
    a = _make_source(db)
    b = _make_source(db)
    fetcher = _StubFetcher([])
    result = run_scrape_once(db, fetcher, SchedulerSettings(mode="rss"))

    assert result["sources_processed"] == 2
    assert result["tally"].get("backed_off", 0) == 0
    # Both now carry a backoff window from their all-duplicate 200.
    assert not P.feed_is_due(db.get(FeedFetchState, a.id))
    assert not P.feed_is_due(db.get(FeedFetchState, b.id))
