"""
The engagement epoch in the other recorders: a Stop pressed and cleared again inside a request's flight records nothing (R614, second PR).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

R614's first PR (``tests/test_kill_switch_epoch.py``) gave the switch a count and covered the robots read and the law tracker. This file
covers the recorders its second part names, each of which decided after a request by reading the switch (R320), so a Stop cleared before
that read was stored as the target's behaviour:

* the feed pass (``ingest_source``): the feed's validator stored and its backoff climbed past an entry the Stop cut, a refused feed GET
  erasing a quiet feed's backoff history, and the cut entry filed as the host's connect failure;
* the crawl rung (``_lane_step_crawl``): the outlet stamped crawled, or a discovery the Stop cut short falling back to a blind crawl;
* the archive backfill (``advance_backfill``): a cut enumeration recorded as an empty history, and a cut URL consumed;
* the sitemap enumeration has no recorder of its own (``update_source_sitemap_url`` stores a sitemap only once one was fetched and
  parsed), so its Stop is read by the crawl rung and the backfill above;
* the source preflight, the feed preflight and the feed verification it runs: a host the Stop cut logged as unreachable (a feed then
  climbs the re-check ladder, a month per rung), and the calendar auto-import beside it: a feed the Stop cut counted failed and
  stamped, so it waits 12 h;
* the source health count: a probe refused by name counted as down once the switch reads clear (the security read's note on PR #1849).

Where the production fetcher runs, the airplane socket guard is armed as boot arms it and a real request is only ever made with the
switch ENGAGED, so the guard refuses it before any socket call; the hosts are ``*.example`` (RFC 2606). The raw shape of a LAST request
(no retries left) is the HTTP-proxy one, which our anchored sentence match rightly refuses (R298), as in
``tests/test_stop_is_not_an_outcome.py``. Every recorder is read against a control: the same failure with no Stop, recorded as before.
"""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog.qualification import STATUS_QUALIFIED
from src.database.models import Base, FeedFetchState, Source
from src.ingest import FetchFailed, activate_kill_switch, clear_kill_switch, kill_switch_active
from src.ingest.fetch_verdict import KILL_SWITCH_REFUSAL
from src.ingest.pipeline import IngestOutcome, IngestResult, ingest_source
from src.safety.fetcher import make_fetcher

HOSTS = ("a.example", "b.example", "c.example")
FEED_HOST = "a.example"
FEED = f"https://{FEED_HOST}/feed.xml"
FEED_XML = (
    '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title><link>https://a.example/</link><description>d</description>'
    + "".join(f"<item><title>A{i}</title><link>https://{FEED_HOST}/story-{i}</link><guid>g{i}</guid></item>" for i in (1, 2, 3))
    + "</channel></rss>"
)
#: The raw requests error of a Stop on the LAST request through an HTTP proxy: not our sentence at the start, so only the switch or the
#: epoch can say it was a Stop.
RAW_STOP = "('Connection aborted.', AirplaneModeError('airplane mode is engaged: refusing a network connection to a.example:443'))"
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    """The switch clear, the guard armed as boot arms it (put back as found), and no proxy or fetch-mode setting."""
    from src.ingest import airplane

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_FETCH_MIN_INTERVAL", "0")
    monkeypatch.setenv("OO_FETCH_RETRY_BACKOFF", "0")
    for var in (*_PROXY_VARS, "OO_FETCH_MODE", "OO_HTTP_PROXY", "OO_HTTP_PROXIES"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(airplane, "_airplane_armed", airplane._airplane_armed)  # restored at teardown
    assert airplane.install_airplane_socket_guard()
    clear_kill_switch()
    yield
    clear_kill_switch()


def _stop_and_clear() -> None:
    """The operator presses Stop and goes back online again: the count moves, the switch reads clear."""
    activate_kill_switch()
    clear_kill_switch()


class _Stub:
    def __init__(self, url, status=200, body=b"", headers=None):
        self.status_code, self.url, self._body = status, url, body
        self.headers = {"Content-Type": "text/html", **(headers or {})}
        self.content, self.text, self.encoding = body, body.decode("utf-8", "replace"), "utf-8"

    def iter_content(self, chunk_size=16384):
        yield self._body

    def close(self):
        pass


def _fetcher(tmp_path, calls, *, feed=False, sitemap_urls=(), cut_clear_on=None, raw_clear_on=None, down_on=None, retries=None):
    """The production fetcher over a scripted ``session.get``, every scripted fault firing ONCE, on the first URL ending with it:

    ``cut_clear_on`` Stop pressed while the request is in flight (the REAL guard refuses the connect and requests wraps its error), then
    cleared before the failure reaches the caller · ``raw_clear_on`` the same Stop on a last request, arriving as the raw proxy error with
    the switch already clear · ``down_on`` a host's own reset, no Stop. Anything else: robots allow all, the feed, a sitemap, else a 503."""
    f = make_fetcher(
        retry_backoff_s=0, robots_cache_path=pathlib.Path(tmp_path) / "robots.json",
        **({"max_retries": retries} if retries is not None else {}),
    )
    assert type(f.session).__name__ == "Session", type(f.session)  # a plain requests.Session: the real request path

    def guard(host, *_a, **_k):  # the first line of ``_guard_target``: no lookup is ever made
        if kill_switch_active():
            raise FetchFailed(KILL_SWITCH_REFUSAL)

    f._guard_target = guard  # type: ignore[method-assign]
    real_get = f.session.get
    pending = {"cut": cut_clear_on, "raw": raw_clear_on, "down": down_on}

    def fires(kind: str, url: str) -> bool:
        if pending[kind] is not None and url.endswith(pending[kind]):
            pending[kind] = None
            return True
        return False

    def get(url, **kw):
        calls.append(url)
        if fires("raw", url):
            _stop_and_clear()
            raise requests.exceptions.ProxyError(RAW_STOP)
        if fires("down", url):
            raise requests.exceptions.ProxyError("('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))")
        if fires("cut", url):
            activate_kill_switch()
            assert kill_switch_active(), "a real request is only ever made with the switch engaged"
            try:
                return real_get(url, **kw)
            finally:
                clear_kill_switch()
        if kill_switch_active():
            return real_get(url, **kw)
        if url.endswith("/robots.txt"):
            return _Stub(url, 200, b"User-agent: *\nAllow: /\n", {"Content-Type": "text/plain"})
        if sitemap_urls and url == "https://a.example/sitemap.xml":
            body = ("<?xml version='1.0'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
                    + "".join(f"<url><loc>{u}</loc></url>" for u in sitemap_urls) + "</urlset>")
            return _Stub(url, 200, body.encode(), {"Content-Type": "application/xml"})
        if feed and url == FEED:
            return _Stub(url, 200, FEED_XML.encode(), {"Content-Type": "application/rss+xml", "ETag": "v1"})
        return _Stub(url, 503)

    f.session.get = get  # type: ignore[method-assign]
    return f


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    yield s
    s.close()


# --------------------------------------------------------------------------- #
#  The feed pass
# --------------------------------------------------------------------------- #
def _source(db, *, seed=False):
    row = Source(name=FEED_HOST, domain=FEED_HOST, rss_url=FEED, enabled=True, status=STATUS_QUALIFIED)
    db.add(row)
    db.commit()
    if seed:
        db.add(FeedFetchState(
            source_id=row.id, etag="old", consecutive_unchanged=4, last_status=200,
            last_checked_at=datetime.now(UTC) - timedelta(days=2), skip_until=datetime.now(UTC) - timedelta(hours=1),
        ))
        db.commit()
    return row


def _state(db, source_id):
    db.expire_all()
    return db.get(FeedFetchState, source_id)


@pytest.mark.parametrize("seeded", [False, True])
def test_a_stop_cleared_inside_an_entry_stores_no_validator_and_climbs_no_backoff(db, tmp_path, seeded):
    """The entry the Stop cut was never stored, and a stored validator would hide it from the next pass (a 304)."""
    row = _source(db, seed=seeded)
    calls: list = []
    tally = ingest_source(db, row, fetcher=_fetcher(tmp_path, calls, feed=True, cut_clear_on="/story-1"))
    assert not kill_switch_active()
    st = _state(db, row.id)
    if seeded:
        assert st.etag == "old" and st.consecutive_unchanged == 4 and st.skip_until is not None, "a cleared Stop was recorded as the feed's"
    else:
        assert st is None, f"a cleared Stop created a feed state: etag={st.etag!r}"
    # back online, the walk goes on: the entries after the Stop are asked for, and none is counted as held back
    assert {u for u in calls if "/story-" in u} == {f"https://{FEED_HOST}/story-{i}" for i in (1, 2, 3)}, calls
    assert "stopped_unwalked" not in tally and "skipped_offline" not in tally, tally


def test_a_stop_cleared_inside_an_entrys_last_request_is_filed_as_offline_not_connect(db, tmp_path):
    row = _source(db)
    tally = ingest_source(db, row, fetcher=_fetcher(tmp_path, [], feed=True, raw_clear_on="/story-1", retries=0))
    assert not kill_switch_active()
    assert tally.get("ff:offline") == 1 and "ff:connect" not in tally, f"the Stop was filed as the host's: {tally}"


def test_each_entry_is_judged_by_its_own_window(db, tmp_path):
    """The Stop touched entry 1 only: entry 2's reset is the host's, though the pass as a whole saw a Stop."""
    row = _source(db)
    tally = ingest_source(db, row, fetcher=_fetcher(tmp_path, [], feed=True, raw_clear_on="/story-1", down_on="/story-2", retries=0))
    assert tally.get("ff:offline") == 1 and tally.get("ff:connect") == 1, tally


def test_a_stop_cleared_inside_the_feed_get_keeps_the_backoff_history_and_is_a_refused_feed(db, tmp_path):
    row = _source(db, seed=True)
    tally = ingest_source(db, row, fetcher=_fetcher(tmp_path, [], feed=True, raw_clear_on="/feed.xml", retries=0))
    assert not kill_switch_active()
    st = _state(db, row.id)
    assert st.etag == "old" and st.consecutive_unchanged == 4 and st.skip_until is not None, "a cleared Stop erased the backoff history"
    assert tally.get("skipped_offline") == 1, "a feed the Stop cut is not counted as the person's setting"


def test_a_stop_cleared_inside_the_feed_get_that_a_retry_got_past_still_leaves_the_row_alone(db, tmp_path):
    """The window is the whole pass from before the feed's request, its retries included: the stated cost is one more read of the feed
    on the next pass (the dedup step skips what was stored), never a validator stored over a pass a Stop touched."""
    row = _source(db, seed=True)
    calls: list = []
    ingest_source(db, row, fetcher=_fetcher(tmp_path, calls, feed=True, cut_clear_on="/feed.xml"))
    assert calls.count(FEED) == 2, f"the retry did not get past the cut attempt: {calls}"
    st = _state(db, row.id)
    assert st.etag == "old" and st.consecutive_unchanged == 4, "a pass whose feed GET a Stop cut was recorded"


def test_a_feed_pass_with_no_stop_records_the_feed_as_before_the_control(db, tmp_path):
    row = _source(db, seed=True)
    tally = ingest_source(db, row, fetcher=_fetcher(tmp_path, [], feed=True, down_on="/story-1", retries=0))
    st = _state(db, row.id)
    assert st.etag == "v1" and st.consecutive_unchanged == 5, "a pass with no Stop no longer records the feed"
    assert tally.get("ff:connect") == 1 and "ff:offline" not in tally, tally


def test_a_host_failure_of_the_feed_get_resets_the_backoff_as_before_the_control(db, tmp_path):
    row = _source(db, seed=True)
    tally = ingest_source(db, row, fetcher=_fetcher(tmp_path, [], feed=True, down_on="/feed.xml", retries=0))
    st = _state(db, row.id)
    assert st.consecutive_unchanged == 0 and "skipped_offline" not in tally, (st.consecutive_unchanged, tally)


# --------------------------------------------------------------------------- #
#  The crawl rung
# --------------------------------------------------------------------------- #
def _crawl(db, tmp_path, **script):
    from src.scheduler.runner import _lane_step_crawl
    from src.scheduler.settings import SchedulerSettings

    for i, h in enumerate(HOSTS):
        db.add(Source(name=h, domain=h, rss_url=None, enabled=True, status=STATUS_QUALIFIED, priority=2 + i))
    db.commit()
    calls: list = []
    f = _fetcher(tmp_path, calls, **script)
    settings = SchedulerSettings()
    settings.crawl_per_pass = 3
    out = _lane_step_crawl(db, f, settings)
    db.commit()
    stamped = sorted(s.domain for s in db.query(Source).all() if s.last_crawled_at is not None)
    return out, stamped, calls


def _stop_right_after_the_loop_check(monkeypatch, function, loop_line):
    """The check at the head of ``function``'s loop (the first ``if kill_switch_active():`` after ``loop_line``) reads clear, and the
    operator presses Stop the instant after it, before the request that check lets go: the case where an epoch taken AFTER the check
    would already hold the Stop and read the request's refusal as the target's failure once the switch is cleared again."""
    import inspect
    import sys

    import src.ingest as ingest_pkg

    lines, first = inspect.getsourcelines(function)
    start = next(i for i, line in enumerate(lines) if line.strip() == loop_line)
    target = first + next(i for i in range(start, len(lines)) if lines[i].strip() == "if kill_switch_active():")
    real = ingest_pkg.kill_switch_active
    fired: list[int] = []

    def check() -> bool:
        engaged = real()
        caller = sys._getframe(1)
        if not fired and caller.f_code is function.__code__ and caller.f_lineno == target:
            fired.append(target)
            activate_kill_switch()
        return engaged

    monkeypatch.setattr(ingest_pkg, "kill_switch_active", check)
    return fired


def _record(monkeypatch, module, name):
    seen: list = []
    real = getattr(module, name)

    def spy(*a, **k):
        seen.append(a)
        return real(*a, **k)

    monkeypatch.setattr(module, name, spy)
    return seen


def test_a_stop_cleared_inside_an_outlets_discovery_does_not_fall_back_to_crawling_it(db, tmp_path, monkeypatch):
    from src.ingest import crawl

    crawled = _record(monkeypatch, crawl, "crawl_source")
    out, stamped, _calls = _crawl(db, tmp_path, cut_clear_on="a.example/robots.txt")
    assert not kill_switch_active()
    assert crawled == [], "a discovery the Stop cut short fell back to a blind crawl"
    assert stamped == [] and out["sources_crawled"] == 0, stamped


def test_a_stop_cleared_inside_an_outlets_crawl_does_not_stamp_it(db, tmp_path):
    # no sitemap, so the Stop lands in the fallback crawl's first page, after discovery finished: only the check before the stamp sees it
    out, stamped, calls = _crawl(db, tmp_path, cut_clear_on="//a.example")  # the fallback crawl's start page
    assert "https://a.example" in calls, calls
    assert stamped == [] and out["sources_crawled"] == 0, f"an outlet whose crawl was cut by a cleared Stop was stamped: {stamped}"


def test_a_stop_cleared_inside_a_sitemap_page_ends_the_walk_and_stamps_nothing(db, tmp_path, monkeypatch):
    from src.ingest import pipeline

    walked = _record(monkeypatch, pipeline, "ingest_url")
    urls = [f"https://a.example/p-{i}" for i in (1, 2, 3)]
    out, stamped, _ = _crawl(db, tmp_path, cut_clear_on="/p-1", sitemap_urls=urls)
    assert [a[2] for a in walked] == urls[:1], f"the pages after the Stop were walked: {[a[2] for a in walked]}"
    assert stamped == [] and out["sitemap_urls_ingested"] == 0, "the page the Stop cut was counted as an attempt"


def test_a_stop_pressed_just_after_the_outlet_check_and_cleared_after_the_refusal_is_a_stop(db, tmp_path, monkeypatch):
    """The outlet's epoch is taken before the check that lets its first request go, so a Stop between the two is in its window."""
    from src.ingest import crawl, sitemap
    from src.scheduler.runner import _lane_step_crawl

    crawled = _record(monkeypatch, crawl, "crawl_source")
    real_discover = sitemap.discover_sitemap_urls

    def discover(fetcher, domain, **kw):
        assert kill_switch_active(), "premise: the Stop is engaged when discovery asks"
        try:
            return real_discover(fetcher, domain, **kw)  # every request refused by name
        finally:
            clear_kill_switch()  # back online before the rung reads its answer

    monkeypatch.setattr(sitemap, "discover_sitemap_urls", discover)
    fired = _stop_right_after_the_loop_check(monkeypatch, _lane_step_crawl, "for source, source_id, domain in batch:")
    out, stamped, _calls = _crawl(db, tmp_path)
    assert fired, "premise: the Stop landed right after the loop's check"
    assert crawled == [], "a discovery the Stop refused fell back to a blind crawl"
    assert stamped == [] and out["sources_crawled"] == 0, stamped


def test_an_outlet_crawled_with_no_stop_is_stamped_the_control(db, tmp_path):
    out, stamped, calls = _crawl(db, tmp_path)
    assert stamped == list(HOSTS) and out["sources_crawled"] == 3, stamped
    assert calls


# --------------------------------------------------------------------------- #
#  The archive backfill (its test seams: the recorder is what is under test)
# --------------------------------------------------------------------------- #
def _backfill_source(db):
    s = Source(name="Example News", domain="example.com", enabled=True)
    db.add(s)
    db.commit()
    return s


def _tick(db, sp, *, discover=None, ingest=None):
    from src.ingest.archive_backfill import advance_backfill

    return advance_backfill(db, fetcher=object(), per_pass=5, state_path=sp, ingest_fn=ingest, discover_fn=discover)


def _urls(n):
    return [f"https://example.com/a{i}" for i in range(n)]


def _active(db, source, sp):
    from src.ingest.archive_backfill import enqueue_source

    enqueue_source(source.id, state_path=sp)
    out = _tick(db, sp, discover=lambda f, s, *, full_history: _urls(3))
    assert out["enumerated"] is True


def _outcome(url, result):
    return IngestOutcome(url=url, result=result, article_id=None, detail="request error")


def test_a_stop_cleared_inside_the_enumeration_is_not_recorded_as_an_empty_history(db, tmp_path):
    from src.ingest.archive_backfill import enqueue_source, load_state

    source, sp = _backfill_source(db), tmp_path / "s.json"
    enqueue_source(source.id, state_path=sp)

    def cut(fetcher, src, *, full_history):
        _stop_and_clear()  # the sitemaps were refused while the switch was engaged
        return []

    out = _tick(db, sp, discover=cut)
    assert out == {"enabled": True, "source_id": source.id, "skipped_offline": 1}, out
    state = load_state(sp)
    assert state["queue"] == [{"source_id": source.id, "full_history": False}], "the entry is still at the head of the queue"
    assert source.id not in state.get("done_sources", [])


def test_a_url_cut_by_a_stop_cleared_in_its_flight_is_not_passed_over(db, tmp_path):
    from src.ingest.archive_backfill import load_state

    source, sp = _backfill_source(db), tmp_path / "s.json"
    _active(db, source, sp)

    def cut(session, src, url, *, fetcher):
        _stop_and_clear()
        return _outcome(url, IngestResult.FETCH_FAILED)

    out = _tick(db, sp, ingest=cut)
    assert out["attempted"] == 0 and out["cursor"] == 0 and out["tally"] == {} and out["skipped_offline"] == 1, out
    assert load_state(sp)["active"]["cursor"] == 0, "the cursor stays on the cut URL"


def test_each_url_is_judged_by_its_own_window(db, tmp_path):
    """A Stop cleared while the first URL was being stored touches that URL only: the next URL's failure is the page's."""
    source, sp = _backfill_source(db), tmp_path / "s.json"
    _active(db, source, sp)

    def ingest(session, src, url, *, fetcher):
        if url.endswith("a0"):
            _stop_and_clear()
            return _outcome(url, IngestResult.STORED)
        return _outcome(url, IngestResult.FETCH_FAILED if url.endswith("a1") else IngestResult.STORED)

    out = _tick(db, sp, ingest=ingest)
    assert out["attempted"] == 3 and out["tally"] == {"stored": 2, "fetch_failed": 1} and "skipped_offline" not in out, out


def test_a_stop_pressed_just_after_the_url_check_and_cleared_after_the_refusal_is_a_stop(db, tmp_path, monkeypatch):
    from src.ingest.archive_backfill import advance_backfill, load_state

    source, sp = _backfill_source(db), tmp_path / "s.json"
    _active(db, source, sp)

    def refused(session, src, url, *, fetcher):
        assert kill_switch_active(), "premise: the Stop is engaged when the URL is asked for"
        clear_kill_switch()  # refused by name, then back online before the outcome is read
        return _outcome(url, IngestResult.FETCH_FAILED)

    fired = _stop_right_after_the_loop_check(monkeypatch, advance_backfill, "for url in active_urls[cursor : cursor + per_pass]:")
    out = _tick(db, sp, ingest=refused)
    assert fired, "premise: the Stop landed right after the loop's check"
    assert out["attempted"] == 0 and out["cursor"] == 0 and out["tally"] == {} and out["skipped_offline"] == 1, out
    assert load_state(sp)["active"]["cursor"] == 0


def test_a_url_that_failed_with_no_stop_is_consumed_the_control(db, tmp_path):
    source, sp = _backfill_source(db), tmp_path / "s.json"
    _active(db, source, sp)
    out = _tick(db, sp, ingest=lambda session, src, url, *, fetcher: _outcome(url, IngestResult.FETCH_FAILED))
    assert out["attempted"] == 3 and out["tally"] == {"fetch_failed": 3} and "skipped_offline" not in out, out


# --------------------------------------------------------------------------- #
#  The source preflight
# --------------------------------------------------------------------------- #
_SRC = SimpleNamespace(id=1, domain="a.example")


def test_a_stop_cleared_inside_the_preflight_robots_read_is_skipped_offline(tmp_path):
    from src.monitoring.preflight import _check_one

    rec = _check_one(_fetcher(tmp_path, [], cut_clear_on="/robots.txt"), _SRC)
    assert not kill_switch_active()
    assert rec["verdict"] == "skipped_offline" and rec.get("skipped_offline") is True, rec


def test_a_stop_cleared_inside_the_preflight_homepage_read_is_skipped_offline(tmp_path):
    from src.monitoring.preflight import _check_one

    rec = _check_one(_fetcher(tmp_path, [], cut_clear_on="a.example/"), _SRC)
    assert rec["verdict"] == "skipped_offline", rec


def test_a_stop_cleared_inside_the_preflight_target_check_is_skipped_offline(tmp_path):
    from src.monitoring.preflight import _check_one

    f = _fetcher(tmp_path, [])

    def guard(host, *_a, **_k):  # a lookup already under way when the Stop came, answering after the clear
        _stop_and_clear()
        raise OSError("[Errno -3] Temporary failure in name resolution")

    f._guard_target = guard  # type: ignore[method-assign]
    rec = _check_one(f, _SRC)
    assert rec["verdict"] == "skipped_offline", rec


def test_a_host_failure_in_the_preflight_is_unreachable_the_control(tmp_path):
    from src.monitoring.preflight import _check_one

    rec = _check_one(_fetcher(tmp_path, [], down_on="/robots.txt"), _SRC)
    assert rec["robots"] == "unreachable" and rec["verdict"] == "unreachable" and "skipped_offline" not in rec, rec


# --------------------------------------------------------------------------- #
#  The feed preflight and the feed verification it runs
# --------------------------------------------------------------------------- #
def test_a_stop_cleared_inside_a_feed_preflight_robots_read_is_skipped_offline(tmp_path):
    from src.monitoring.feed_preflight import _check_host_robots

    rec = _check_host_robots(_fetcher(tmp_path, [], cut_clear_on="/robots.txt"), "a.example")
    assert rec.get("skipped_offline") is True and rec["robots"] == "skipped_offline", rec


def test_a_host_failure_of_a_feed_preflight_robots_read_is_unreachable_the_control(tmp_path):
    from src.monitoring.feed_preflight import _check_host_robots

    rec = _check_host_robots(_fetcher(tmp_path, [], down_on="/robots.txt"), "a.example")
    assert rec["robots"] == "unreachable" and "skipped_offline" not in rec, rec


def _sweep(monkeypatch, *, market=(), calendar=()):
    from src.monitoring import feed_preflight as fp

    monkeypatch.setattr(fp, "_feed_targets", lambda: (list(market), list(calendar)))
    monkeypatch.setattr(fp, "_check_host_robots", lambda fetcher, host: {"kind": "robots", "host": host, "robots": "allowed"})
    return fp


class _CutFetcher:
    """A feed fetch the Stop cut on its last request, the switch clear again when the failure arrives."""

    def __init__(self, *, stop: bool = True):
        self.stop = stop

    def fetch(self, url, **_kw):
        if self.stop:
            _stop_and_clear()
            raise FetchFailed(f"request error for {url}: {RAW_STOP}")
        raise FetchFailed(f"HTTP 503 for {url}")


def test_a_stop_cleared_inside_a_market_feed_sample_logs_nothing(monkeypatch):
    fp = _sweep(monkeypatch, market=[{"kind": "market_feed", "key": "m1", "url": "https://m.example/q.csv", "host": "m.example"}])
    out = fp.run_feed_preflight(_CutFetcher())
    assert out["complete"] is False and out["skipped_offline"] == 1, out
    assert not fp._log_path().exists(), "a sweep the Stop cut wrote a log, which marks the feeds done"


def test_a_stop_cleared_inside_a_calendar_feed_sample_logs_nothing(monkeypatch):
    """Through the real verification: it answers skipped_offline itself, and the sweep stops on it."""
    from src.events import feeds as F

    fp = _sweep(monkeypatch, calendar=[{"kind": "calendar_feed", "key": _FEED_ID, "url": "https://c.example/x.ics", "host": "c.example"}])
    out = fp.run_feed_preflight(_CutFetcher())
    assert out["complete"] is False and out["skipped_offline"] == 1, out
    assert not fp._log_path().exists()
    assert F.load_verdicts() == {} and F.load_attempts() == {}


def test_the_calendar_sample_reads_the_epoch_behind_the_verification_too(monkeypatch):
    """The sweep's own second check, behind the verification's: a verdict of unreachable whose window saw a Stop stops the sweep."""
    from src.events import feeds as F

    fp = _sweep(monkeypatch, calendar=[{"kind": "calendar_feed", "key": "k1", "url": "https://c.example/x.ics", "host": "c.example"}])

    def verify(fetcher, key):
        _stop_and_clear()
        return {"status": "unreachable", "error": "request error"}

    monkeypatch.setattr(F, "verify_feed", verify)
    out = fp.run_feed_preflight(object())
    assert out["complete"] is False and out["skipped_offline"] == 1, out
    assert not fp._log_path().exists()


def test_a_market_feed_that_failed_with_no_stop_is_logged_unreachable_the_control(monkeypatch):
    fp = _sweep(monkeypatch, market=[{"kind": "market_feed", "key": "m1", "url": "https://m.example/q.csv", "host": "m.example"}])
    out = fp.run_feed_preflight(_CutFetcher(stop=False))
    assert out["complete"] is True and out["market_feeds_sampled"] == 1 and "skipped_offline" not in out, out


_FEED_ID = "wph-hol-ad"  # a bundled calendar feed (the id tests/test_feed_verify_offline.py uses)


def test_a_stop_cleared_inside_a_feed_verification_records_no_verdict_and_no_attempt():
    from src.events import feeds as F

    out = F.verify_feed(_CutFetcher(), _FEED_ID)
    assert not kill_switch_active()
    assert out["status"] == "skipped_offline", out
    assert F.load_verdicts() == {} and F.load_attempts() == {}, "a cleared Stop moved the feed up the re-check ladder"


def test_a_feed_verification_that_failed_with_no_stop_is_recorded_the_control():
    from src.events import feeds as F

    out = F.verify_feed(_CutFetcher(stop=False), _FEED_ID)
    assert out["status"] == "unreachable", out
    assert F.load_verdicts()[_FEED_ID]["status"] == "unreachable" and F.load_attempts(), "an honest failure is no longer recorded"


def _autoimport_stamps() -> dict:
    from src.events import feeds as F

    return F._load_json("calendar_autoimport.json")


def test_a_stop_cleared_inside_a_calendar_auto_import_is_neither_a_failure_nor_stamped():
    from src.events import feeds as F

    out = F.auto_import_due_feeds(_CutFetcher(), batch=1)
    assert out["picked"] == 1 and out["imported"] == 0 and out["failed"] == 0, out
    assert _autoimport_stamps() == {}, "a feed the Stop cut was stamped as checked: it would wait 12 h"


def test_a_stop_pressed_just_after_the_auto_import_check_and_cleared_after_the_refusal_is_a_stop(monkeypatch):
    from src.events import feeds as F

    class _RefusedByName:
        def fetch(self, url, **_kw):
            assert kill_switch_active(), "premise: the Stop is engaged when the feed is asked for"
            clear_kill_switch()  # back online before the failure reaches the batch
            raise FetchFailed(KILL_SWITCH_REFUSAL)

    fired = _stop_right_after_the_loop_check(monkeypatch, F.auto_import_due_feeds, "for fid in picked:")
    out = F.auto_import_due_feeds(_RefusedByName(), batch=1)
    assert fired, "premise: the Stop landed right after the loop's check"
    assert out["picked"] == 1 and out["imported"] == 0 and out["failed"] == 0, out
    assert _autoimport_stamps() == {}, "a feed the Stop refused was stamped as checked: it would wait 12 h"


def test_a_calendar_auto_import_that_failed_with_no_stop_is_a_failure_and_stamped_the_control():
    from src.events import feeds as F

    out = F.auto_import_due_feeds(_CutFetcher(stop=False), batch=1)
    assert out["picked"] == 1 and out["failed"] == 1, out
    assert len(_autoimport_stamps()) == 1


# --------------------------------------------------------------------------- #
#  The source health count
# --------------------------------------------------------------------------- #
def test_a_probe_refused_by_name_is_counted_as_the_switch_after_the_switch_is_cleared(monkeypatch, tmp_path):
    """The probe was refused by the switch's own sentence and the operator went back online before the count: the count still names the
    switch, and so does the next probe the guard cut in that window. The control in the same call: a host's 503 that QUOTES the sentence
    is a host that is down (R298)."""
    from fastapi.testclient import TestClient

    from src.api import monitoring
    from src.api.main import app
    from src.database.session import get_db

    engine = create_engine(f"sqlite:///{tmp_path / 'h.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    with Session() as s:
        s.add_all([Source(name=f"S{i}", domain=f"s{i}.example", rss_url=f"https://s{i}.example/rss", enabled=True, priority=i)
                   for i in range(3)])
        s.commit()

    def _db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    # the socket guard's refusal as requests wraps it on a direct connection: read as the switch's only because a Stop touched the sweep
    wrapped = ("request error for https://s1.example/: HTTPSConnectionPool(host='s1.example', port=443): Max retries exceeded with url: / "
               "(Caused by NewConnectionError(\"HTTPSConnection(host='s1.example', port=443): Failed to establish a new connection: "
               "airplane mode is engaged: refusing a network connection to 's1.example'\"))")
    details = iter([KILL_SWITCH_REFUSAL, wrapped, f"HTTP 503 for https://s2.example (server said: {KILL_SWITCH_REFUSAL})"])

    def probe(source, fetcher=None):
        detail = next(details)
        if detail == KILL_SWITCH_REFUSAL:
            _stop_and_clear()
        return SimpleNamespace(to_dict=lambda: {"source_id": 1, "name": "s", "url": "https://s.example", "status": "down", "detail": detail})

    monkeypatch.setattr(monitoring, "check_source", probe)
    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app, base_url="http://127.0.0.1") as c:
            body = c.get(
                "/api/monitoring/health?limit=3",
                headers={"Sec-Fetch-Site": "same-origin", "Referer": "http://127.0.0.1/", "Origin": "http://127.0.0.1"},
            ).json()
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
    assert not kill_switch_active()
    assert body["checked"] == 3 and body["summary"] == {"refused_by_kill_switch": 2, "down": 1}, body
