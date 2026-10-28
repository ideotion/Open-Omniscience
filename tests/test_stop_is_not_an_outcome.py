"""A Stop is not an outcome of the host: the crawl rung and the feed pass leave their records as they were (R327, D1 and D2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Export's switch sweep (``/mnt/project-files/export-lane/law-switch-sweep-2026-10-27/REPORT.md``) drove every recorder that stores a fetch
outcome with the PRODUCTION fetcher and the kill switch in each state a Stop leaves it in. Two of them stored the person's own Stop as the target's
behaviour (the S1 class of R293, the passphrase-rule twin for settings):

* D1 -- ``_lane_step_crawl`` stamped ``Source.last_crawled_at`` for outlets that were never visited (3 of 3 with the switch engaged before the
  step, and the outlet whose first request was cut), so they went to the back of the rotation unvisited. The lane checks the switch only
  before it STARTS.
* D2 -- ``ingest_source`` stored the feed's ETag after a Stop mid-feed and climbed the backoff, so the entries that were never asked for were
  not asked for again until the feed changed; and a Stop before the feed GET took the "a fetch error resets backoff" branch, erasing a quiet
  feed's history.

These tests are that sweep's harnesses (hosts ``*.example``, the production ``make_fetcher()``, a real request made only with the switch
engaged and cut by the airplane socket guard) reduced to what the fix decides. The decision in code is ``kill_switch_active()`` read AFTER the
step (R320), never the words of a refusal; each test fails when its statement is taken out. A REAL host failure is the control in each: it is
still recorded, because that is the existing design.
"""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime, timedelta

import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog.qualification import STATUS_QUALIFIED
from src.database.models import Base, FeedFetchState, Source
from src.ingest import activate_kill_switch, clear_kill_switch, kill_switch_active
from src.ingest.airplane import install_airplane_socket_guard
from src.ingest.pipeline import feed_is_due, ingest_source
from src.safety.fetcher import make_fetcher
from src.scheduler.runner import _lane_step_crawl
from src.scheduler.settings import SchedulerSettings

HOSTS = ("a.example", "b.example", "c.example")
FEED_HOST = "a.example"
FEED = f"https://{FEED_HOST}/feed.xml"
FEED_XML = (
    '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title><link>https://a.example/</link><description>d</description>'
    + "".join(f"<item><title>A{i}</title><link>https://{FEED_HOST}/story-{i}</link><guid>g{i}</guid></item>" for i in (1, 2, 3))
    + "</channel></rss>"
)


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_FETCH_MIN_INTERVAL", "0")
    monkeypatch.setenv("OO_FETCH_RETRY_BACKOFF", "0")
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    assert install_airplane_socket_guard()
    clear_kill_switch()
    yield
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


RAW_STOP = "('Connection aborted.', AirplaneModeError('airplane mode is engaged: refusing a network connection to a.example:443'))"
RAW_HOST = "('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))"


def _fetcher(tmp_path, calls, *, cut_on=None, feed=False, sitemap_urls=(), raw_on=None, raw_stop=True):
    """The production fetcher over a stubbed ``session.get``: a request made with the switch engaged goes to the REAL ``get`` and is cut by the
    airplane socket guard; ``cut_on`` engages the switch during the first request whose URL ends with it. ``raw_on`` is the LAST-request shape
    (no retries are left, so the fetcher's own switch check never runs after it): the first request whose URL ends with it raises the raw
    requests error through an HTTP proxy -- with the switch engaged first when ``raw_stop`` (a Stop in flight), without it (a host's reset)."""
    f = make_fetcher(retry_backoff_s=0, robots_cache_path=pathlib.Path(tmp_path) / "robots.json", **({"max_retries": 0} if raw_on else {}))

    def guard(host, *a, **k):  # the first line of ``_guard_target``: no lookup is ever made
        if kill_switch_active():
            from src.ingest import FetchFailed
            from src.ingest.fetch_verdict import KILL_SWITCH_REFUSAL

            raise FetchFailed(KILL_SWITCH_REFUSAL)

    f._guard_target = guard
    real_get = f.session.get

    def get(url, **kw):
        hdrs = kw.get("headers") or {}
        calls.append((url, hdrs.get("If-None-Match")))
        if raw_on is not None and url.endswith(raw_on):
            if raw_stop:
                activate_kill_switch()
            raise requests.exceptions.ProxyError(RAW_STOP if raw_stop else RAW_HOST)
        if cut_on is not None and url.endswith(cut_on):
            activate_kill_switch()
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

    f.session.get = get
    return f


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    yield s
    s.close()


# ---------------------------------------------------------------------- D1: the crawl rung


def _crawl(db, tmp_path, *, engage_before=False, cut_on=None, sitemap_urls=()):
    for i, h in enumerate(HOSTS):
        db.add(Source(name=h, domain=h, rss_url=None, enabled=True, status=STATUS_QUALIFIED, priority=2 + i))
    db.commit()
    calls: list = []
    f = _fetcher(tmp_path, calls, cut_on=cut_on, sitemap_urls=sitemap_urls)
    if engage_before:
        activate_kill_switch()
    settings = SchedulerSettings()
    settings.crawl_per_pass = 3
    out = _lane_step_crawl(db, f, settings)
    db.commit()
    stamped = sorted(s.domain for s in db.query(Source).all() if s.last_crawled_at is not None)
    return out, stamped, calls


def test_a_real_host_failure_still_stamps_the_outlets_crawled_the_control(db, tmp_path):
    out, stamped, calls = _crawl(db, tmp_path)
    assert stamped == list(HOSTS) and out["sources_crawled"] == 3, "the existing design (an outlet that failed was visited) was changed"
    assert calls, "the control made no request: it proves nothing"


def test_a_stop_before_the_step_stamps_no_outlet_and_makes_no_request(db, tmp_path):
    out, stamped, calls = _crawl(db, tmp_path, engage_before=True)
    assert stamped == [], f"outlets never visited were stamped crawled: {stamped}"
    assert out["sources_crawled"] == 0 and calls == []


def test_a_stop_in_the_first_outlets_first_request_stamps_none_and_ends_the_step(db, tmp_path):
    out, stamped, calls = _crawl(db, tmp_path, cut_on="/robots.txt")
    assert stamped == [], f"an outlet cut by the Stop was stamped crawled: {stamped}"
    assert out["sources_crawled"] == 0
    assert len(calls) <= 2, f"the step went on to the other outlets after the Stop: {calls}"


def test_a_stop_before_the_step_does_not_even_start_an_outlets_discovery(db, tmp_path, monkeypatch):
    from src.ingest import sitemap

    started: list = []
    real = sitemap.discover_sitemap_urls
    monkeypatch.setattr(sitemap, "discover_sitemap_urls", lambda *a, **k: started.append(a) or real(*a, **k))
    _crawl(db, tmp_path, engage_before=True)
    assert started == [], "the step began an outlet's discovery with the switch already engaged"


def test_a_stop_during_the_crawl_of_an_outlet_that_has_no_sitemap_does_not_stamp_it(db, tmp_path):
    # the Stop lands in the BFS fallback's page request, AFTER discovery finished: only the check before the stamp can see it
    out, stamped, calls = _crawl(db, tmp_path, cut_on="a.example")
    assert stamped == [], f"an outlet whose crawl was cut by the Stop was stamped crawled: {stamped}"
    assert out["sources_crawled"] == 0


def test_a_stop_during_an_outlets_discovery_does_not_fall_back_to_crawling_it(db, tmp_path, monkeypatch):
    # discovery cut short by the Stop reports "no sitemap" only because it was stopped: the BFS fallback must not run on that
    from src.ingest import crawl

    crawled: list = []
    real = crawl.crawl_source
    monkeypatch.setattr(crawl, "crawl_source", lambda *a, **k: crawled.append(a) or real(*a, **k))
    _crawl(db, tmp_path, cut_on="/robots.txt")
    assert crawled == [], "the fallback crawl ran on a discovery the Stop had cut short"


def test_a_stop_in_a_sitemap_page_ends_that_outlets_walk_and_stamps_nothing(db, tmp_path, monkeypatch):
    from src.ingest import pipeline

    walked: list = []
    real = pipeline.ingest_url
    monkeypatch.setattr(pipeline, "ingest_url", lambda s, src, link, **k: walked.append(link) or real(s, src, link, **k))
    urls = [f"https://a.example/p-{i}" for i in (1, 2, 3)]
    out, stamped, _ = _crawl(db, tmp_path, cut_on="/p-1", sitemap_urls=urls)
    assert walked == urls[:1], f"the pages after the Stop were walked: {walked}"
    assert stamped == [] and out["sitemap_urls_ingested"] == 0, "the page the Stop cut was counted as an attempt"


def test_a_page_stored_before_the_stop_is_counted_as_an_attempt(db, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from src.ingest import pipeline

    def ingest(session, source, link, **kw):  # a page that was fetched and stored, the Stop pressed while it was being stored
        activate_kill_switch()
        return SimpleNamespace(result=pipeline.IngestResult.STORED)

    monkeypatch.setattr(pipeline, "ingest_url", ingest)
    urls = [f"https://a.example/p-{i}" for i in (1, 2, 3)]
    out, stamped, _ = _crawl(db, tmp_path, sitemap_urls=urls)
    assert out["sitemap_urls_ingested"] == 1, "a stored page was not counted"
    assert stamped == [], "the outlet was stamped crawled although its walk was stopped"


# ---------------------------------------------------------------------- D2: the feed pass


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


def test_a_real_article_failure_still_records_the_feed_the_control(db, tmp_path):
    row = _source(db)
    calls: list = []
    ingest_source(db, row, fetcher=_fetcher(tmp_path, calls, feed=True))
    st = _state(db, row.id)
    assert st is not None and st.etag == "v1" and st.consecutive_unchanged == 1, "the existing design (a failed article is consumed) was changed"
    assert len({u for u, _ in calls if "/story-" in u}) == 3, "the control did not walk the three entries"


@pytest.mark.parametrize("seeded", [False, True])
def test_a_stop_mid_feed_stores_no_validator_climbs_no_backoff_and_asks_no_more_entries(db, tmp_path, seeded):
    row = _source(db, seed=seeded)
    calls: list = []
    tally = ingest_source(db, row, fetcher=_fetcher(tmp_path, calls, cut_on="/story-1", feed=True))
    st = _state(db, row.id)
    if seeded:
        assert st.etag == "old" and st.consecutive_unchanged == 4 and st.skip_until is not None, "a Stop was recorded as the feed's behaviour"
    else:
        assert st is None, f"a Stop created a feed state: etag={st.etag!r}"
    assert {u for u, _ in calls if "/story-" in u} == {f"https://{FEED_HOST}/story-1"}, "the entries after the Stop were walked through a refusal"
    assert tally["fetch_failed"] == 1 and kill_switch_active()
    assert tally.get("stopped_unwalked") == 2, "the two entries never asked for are not visible in the tally"
    assert "skipped_offline" not in tally, "the entries were counted as refused FEEDS: the Sources UI reads that key as 'nothing was fetched'"
    if seeded:
        clear_kill_switch()
        assert feed_is_due(st), "the stopped feed would not be taken again by the scheduler"


def test_a_stop_cleared_during_the_flush_still_leaves_the_row_alone(db, tmp_path, monkeypatch):
    # the loop saw the Stop and broke; the batch flush then waits on the writer gate, and the Stop is cleared in that wait: the decision
    # was made when the loop broke and is not re-asked of a switch that has changed since
    from src.ingest import batch as batch_mod

    real_flush = batch_mod.ArticleBatch.flush

    def flush(self):
        clear_kill_switch()
        return real_flush(self)

    monkeypatch.setattr(batch_mod.ArticleBatch, "flush", flush)
    row = _source(db, seed=True)
    ingest_source(db, row, fetcher=_fetcher(tmp_path, [], cut_on="/story-1", feed=True))
    st = _state(db, row.id)
    assert st.etag == "old" and st.consecutive_unchanged == 4, "a Stop cleared during the flush was recorded as the feed's behaviour"


def test_a_stop_mid_feed_stops_walking_the_entries(db, tmp_path, monkeypatch):
    from src.ingest import pipeline

    walked: list = []
    real = pipeline.ingest_url
    monkeypatch.setattr(pipeline, "ingest_url", lambda s, src, link, **k: walked.append(link) or real(s, src, link, **k))
    row = _source(db)
    ingest_source(db, row, fetcher=_fetcher(tmp_path, [], cut_on="/story-1", feed=True))
    assert walked == [f"https://{FEED_HOST}/story-1"], f"the entries after the Stop were walked: {walked}"


def test_a_stop_before_the_feed_get_leaves_a_quiet_feeds_backoff_history(db, tmp_path):
    row = _source(db, seed=True)
    activate_kill_switch()
    tally = ingest_source(db, row, fetcher=_fetcher(tmp_path, [], feed=True))
    st = _state(db, row.id)
    assert st.etag == "old" and st.consecutive_unchanged == 4, f"a refusal erased the backoff history: {st.consecutive_unchanged}"
    assert st.skip_until is not None, "the deadline was cleared"
    assert tally.get("skipped_offline") == 1, "the refusal is still named as the person's setting"


def test_a_stop_before_the_feed_get_with_no_row_writes_none(db, tmp_path):
    row = _source(db)
    activate_kill_switch()
    ingest_source(db, row, fetcher=_fetcher(tmp_path, [], feed=True))
    assert _state(db, row.id) is None


# ---------------------------------------------------------------------- the same Stop, arriving as the raw error of the LAST request (R320, R298)
#
# With retries left, the fetcher's next attempt sees the switch and words the failure as OUR refusal sentence, which the anchored match
# recognises. On the LAST request nothing follows, so the raw requests error (here the HTTP-proxy shape) is what the collector classifies, and
# the anchored match rightly does not read it as ours: the failure was filed as the host's (``ff:connect``) and the feed not counted refused.


def test_a_stop_in_the_feed_get_with_no_retries_left_is_still_counted_as_a_refused_feed(db, tmp_path):
    row = _source(db, seed=True)
    tally = ingest_source(db, row, fetcher=_fetcher(tmp_path, [], feed=True, raw_on="/feed.xml"))
    assert kill_switch_active()
    assert tally.get("skipped_offline") == 1, "a Stop that arrived as the raw error was not counted as the person's setting"
    st = _state(db, row.id)
    assert st.etag == "old" and st.consecutive_unchanged == 4, "the backoff history was touched"


def test_a_host_reset_in_the_feed_get_is_not_counted_as_a_refused_feed_the_control(db, tmp_path):
    row = _source(db)
    tally = ingest_source(db, row, fetcher=_fetcher(tmp_path, [], feed=True, raw_on="/feed.xml", raw_stop=False))
    assert not kill_switch_active()
    assert "skipped_offline" not in tally, "a host's own failure was filed as the person's Stop"


def test_a_stop_in_an_article_request_with_no_retries_left_is_filed_as_offline_not_connect(db, tmp_path):
    row = _source(db)
    tally = ingest_source(db, row, fetcher=_fetcher(tmp_path, [], feed=True, raw_on="/story-1"))
    assert kill_switch_active()
    assert tally.get("ff:offline") == 1 and "ff:connect" not in tally, f"the Stop was filed as the host's: {tally}"
    assert tally["fetch_failed"] == 1 and tally.get("stopped_unwalked") == 2


def test_a_host_reset_in_an_article_request_is_still_filed_as_connect_the_control(db, tmp_path):
    row = _source(db)
    tally = ingest_source(db, row, fetcher=_fetcher(tmp_path, [], feed=True, raw_on="/story-1", raw_stop=False))
    assert not kill_switch_active()
    assert tally.get("ff:connect") == 1 and "ff:offline" not in tally, tally


def test_an_http_status_stays_the_hosts_answer_whatever_the_switch_says():
    from src.ingest.pipeline import _failure_reason

    activate_kill_switch()
    assert _failure_reason("HTTP 503 for https://a.example/x") == "http_5xx", "a status line cannot be produced by a Stop"
    assert _failure_reason("HTTP 403 for https://a.example/x") == "http_403"
    assert _failure_reason(f"request error for https://a.example/x: {RAW_STOP}") == "offline"
    clear_kill_switch()
    assert _failure_reason(f"request error for https://a.example/x: {RAW_STOP}") == "connect", "with the switch off the raw shape is a connect failure"


#: The sentences ``EthicalFetcher`` really raises (src/ingest/__init__.py), one per shape that the classifier files under a response answer.
_RESPONSE_SENTENCES = [
    ("non-HTML content ('application/pdf') for https://a.example/x", "not_html"),
    ("declared length 99999999 exceeds 5000000 bytes for https://a.example/x", "too_large"),
    ("response exceeds 5000000 bytes for https://a.example/x", "too_large"),
    ("body read exceeded 30s for https://a.example/x (after 12 bytes)", "slow_body"),
    ("unsupported or malformed URL: 'ftp://a.example/x'", "bad_url"),
    ("missing host", "bad_url"),
    ("redirect to unsupported URL: 'ftp://a.example/y'", "bad_url"),
    ("too many redirects for https://a.example/x", "bad_url"),
]

#: What a Stop CAN produce, or what we cannot tell from it: the shapes the switch reclaims. ``other`` is any sentence the classifier does not know.
_RECLAIMED_SENTENCES = [
    ("cannot resolve host 'a.example': [Errno -2] Name or service not known", "dns"),
    (f"request error for https://a.example/x: {RAW_STOP}", "connect"),
    ("a sentence nobody classified", "other"),
]


@pytest.mark.parametrize(("detail", "reason"), _RESPONSE_SENTENCES)
def test_a_response_that_arrived_stays_the_hosts_answer_whatever_the_switch_says(detail, reason):
    """The switch acts at name resolution and connect, so a content-type, length, slow-body or redirect verdict was formed from a response that
    had arrived: a Stop that lands afterwards did not produce it."""
    from src.ingest.fetch_verdict import classify_fetch_failure
    from src.ingest.pipeline import _failure_reason

    assert classify_fetch_failure(detail) == reason, "premise: the shape is the one the classifier files under this reason"
    activate_kill_switch()
    assert _failure_reason(detail) == reason


@pytest.mark.parametrize(("detail", "reason"), _RECLAIMED_SENTENCES)
def test_what_a_stop_can_produce_is_reclaimed_by_the_switch_and_only_while_it_is_engaged(detail, reason):
    """The other half of the boundary: a name-resolution, connect or unclassified failure under an engaged switch is the switch's. Adding any of
    ``dns``, ``connect`` or ``other`` to the host's answers makes the first assertion fail."""
    from src.ingest.fetch_verdict import classify_fetch_failure
    from src.ingest.pipeline import _failure_reason

    assert classify_fetch_failure(detail) == reason, "premise: the shape is the one the classifier files under this reason"
    activate_kill_switch()
    assert _failure_reason(detail) == "offline"
    clear_kill_switch()
    assert _failure_reason(detail) == reason, "with the switch off nothing is reclaimed"


def test_a_robots_disallow_in_the_feed_get_is_the_hosts_answer_even_if_a_stop_lands_after(db, tmp_path):
    row = _source(db)
    f = _fetcher(tmp_path, [], feed=True)
    real = f.session.get

    def get(url, **kw):
        if url.endswith("/robots.txt"):
            activate_kill_switch()  # a Stop pressed just as the robots read returns its Disallow
            return _Stub(url, 200, b"User-agent: *\nDisallow: /\n", {"Content-Type": "text/plain"})
        return real(url, **kw)

    f.session.get = get
    tally = ingest_source(db, row, fetcher=f)
    assert kill_switch_active()
    assert "skipped_offline" not in tally, "the host's disallow was filed as the person's Stop"
