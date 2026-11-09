"""
A redirect hop to another host is a first request to that host: its robots.txt, then its interval, under its lock (R629).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Before R629, ``EthicalFetcher._guarded_redirect_get`` re-ran the SSRF guard on a hop and nothing else: a page whose host answered
``302 Location: https://b.example/page`` was followed to b.example with no robots.txt read for b.example and no wait for its
interval, inside a.example's host lock. A disallowing or unreadable robots.txt on b.example therefore refused b.example's pages
when they were asked for and let them through when they were reached by a redirect; and a crawl kept to one site
(``CrawlConfig.same_domain_only``) followed an on-site link that redirected off the site and stored the other site's page as its
own (found by R624's independent read). Now a hop to another host key reads that host's robots.txt (fail-closed: a disallow or
an unavailable robots.txt refuses the hop with the same types as a first request's) and waits its interval or Crawl-delay, under
that host's lock, handed over from the first host's, never taken on top of it; and a scope given to ``fetch`` (the crawl's site,
the sitemap's host) refuses a hop that leaves it before anything is asked of the other host.

Driven through the real ``EthicalFetcher`` (and the real ``crawl_source`` and ``discover_sitemap_urls``) over an injected session
that answers in memory, as tests/test_crawl_scope_userinfo_r624.py does; the kill-switch control uses a real ``requests.Session``
whose transport adapter answers in memory, so the fetcher's real-session guards run with no socket opened. Every planted URL on
the other host has a route, so a request to it is SEEN, never assumed. Time is a fake clock: a wait is recorded, never slept.
Every fetch runs in a bounded thread, so a design that holds a host lock twice fails here instead of hanging the suite.
"""

from __future__ import annotations

import io
import socket
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
import requests
from requests.adapters import BaseAdapter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.ingest as ingest
from src.database.models import Article, Base, Source
from src.ingest import (
    BlockedTarget,
    CrawlDelayDeferred,
    EthicalFetcher,
    FetchError,
    FetchFailed,
    RobotsDisallowed,
    RobotsUnavailable,
    activate_kill_switch,
    clear_kill_switch,
)
from src.ingest.crawl import CrawlConfig, crawl_source
from src.ingest.fetch_verdict import KILL_SWITCH_REFUSAL
from src.ingest.pipeline import IngestResult, ingest_url
from src.ingest.sitemap import discover_sitemap_urls
from src.monitoring.secret_scrub import record_text

A = "https://a.example"
B = "https://b.example"
C = "https://c.example"
_NOTE = "(reached by a redirect)"
_DISALLOW_ALL = "User-agent: *\nDisallow: /\n"
_ALLOW_ALL = "User-agent: *\nAllow: /\n"
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy")


def _html(title="Page", sentence="A plain page about a plain subject.", links=()):
    anchors = "".join(f'<a href="{href}">{href}</a>' for href in links)
    body = (sentence + " ") * 30
    return f"<html><head><title>{title}</title></head><body><article><h1>{title}</h1><p>{body}</p>{anchors}</article></body></html>"


class _Resp:
    def __init__(self, status_code, text, headers, url):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = headers
        self.url = url

    def close(self):
        pass


class _Session:
    """Answers in memory. A routed URL (matched as written) gets its answer; anything else is a 404, so an unrouted robots.txt allows
    everything. Records every request, in one event list shared with the clock, and runs a URL's ``on`` hook before answering."""

    def __init__(self, events: list | None = None):
        self.headers: dict = {}
        self.routes: dict[str, tuple[int, str, dict]] = {}
        self.on: dict = {}
        self.fetched: list[str] = []
        self.events = events if events is not None else []
        self._guard = threading.Lock()

    def page(self, url, text=None, *, status=200, content_type="text/html"):
        self.routes[url] = (status, _html() if text is None else text, {"Content-Type": content_type})

    def redirect(self, url, location, *, status=302):
        self.routes[url] = (status, "", {"Location": location, "Content-Type": "text/html"})

    def robots(self, origin, text, *, status=200):
        self.routes[f"{origin}/robots.txt"] = (status, text, {"Content-Type": "text/plain"})

    def get(self, url, timeout=None, allow_redirects=True, **kwargs):
        with self._guard:
            self.fetched.append(url)
            self.events.append(("get", url))
        hook = self.on.get(url)
        if hook is not None:
            hook()
        status, text, headers = self.routes.get(url, (404, "not found", {"Content-Type": "text/plain"}))
        return _Resp(status, text, dict(headers), url)

    def asked_of(self, host) -> list[str]:
        """Every request made to ``host`` (urllib.parse's reading), robots.txt included."""
        return [u for u in self.fetched if urlsplit(u).hostname == host]


class _Clock:
    """The fetcher's monotonic clock and sleep: a wait is recorded and the clock moved, never slept."""

    def __init__(self, events: list):
        self.t = 1000.0
        self.slept: list[float] = []
        self.events = events
        self.on_sleep = None

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.events.append(("sleep", seconds))
        self.t += seconds
        if self.on_sleep is not None:
            self.on_sleep()


def _fetcher(tmp_path, session, *, interval=0.0, clock=None, **kw) -> EthicalFetcher:
    kw.setdefault("max_retries", 0)
    f = EthicalFetcher(
        min_interval_s=interval, session=session, robots_cache_path=tmp_path / "robots_cache.json", retry_backoff_s=0, **kw
    )
    if clock is not None:
        f._now = clock.now  # type: ignore[method-assign]
        f._sleep = clock.sleep  # type: ignore[method-assign]
    return f


def _bounded(fn, seconds: float = 10.0):
    """Run ``fn`` in a daemon thread and fail, instead of hanging, if it does not finish (a lock held twice, or never released)."""
    box: dict = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - handed back to the test as raised
            box["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    assert not t.is_alive(), "the call did not finish: a host lock is held twice, or was never released"
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _fetch(f, url, **kw):
    return _bounded(lambda: f.fetch(url, **kw))


def _no_lock_held(f, *hosts):
    for host in hosts:
        assert not f._host_lock(host).locked(), f"the lock of {host} was left held"


@pytest.fixture(autouse=True)
def _switch_clear(monkeypatch):
    monkeypatch.delenv("OO_CRAWL_DELAY_MAX_WAIT", raising=False)
    clear_kill_switch()
    yield
    clear_kill_switch()


# --- a disallowing robots.txt on the other host refuses the hop -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "location",
    [
        f"{B}/page",
        "//b.example/page",  # a network-path reference: the scheme of the page that redirected
        "http://b.example/page",  # another scheme too: read against http://b.example's robots.txt
        "https://B.Example:443/page",  # another spelling of the same host key
    ],
)
def test_a_hop_to_a_host_whose_robots_disallows_it_is_refused_and_never_requested(tmp_path, location):
    s = _Session()
    s.redirect(f"{A}/start", location)
    for origin in (B, "http://b.example"):
        s.robots(origin, "User-agent: *\nDisallow: /page\n")
    for page in (f"{B}/page", "http://b.example/page", "https://B.Example:443/page"):  # each spelling answers, so a follow is seen
        s.page(page)
    f = _fetcher(tmp_path, s)
    with pytest.raises(RobotsDisallowed) as caught:
        _fetch(f, f"{A}/start")
    text = record_text(caught.value, typed=False)
    assert text.startswith("robots.txt disallows ") and text.endswith(_NOTE), text
    asked = s.asked_of("b.example")
    assert asked and all(u.endswith("/robots.txt") for u in asked), asked  # the robots.txt was read, the page never asked
    _no_lock_held(f, "a.example", "b.example")


def test_a_hop_to_another_port_of_the_same_name_is_another_host(tmp_path):
    """The host key is the host AND the port (R621), so ``:8443`` is another host: its own robots.txt is read."""
    s = _Session()
    s.redirect(f"{A}/x", "https://a.example:8443/y")
    s.robots("https://a.example:8443", _DISALLOW_ALL)
    s.page("https://a.example:8443/y")
    f = _fetcher(tmp_path, s)
    with pytest.raises(RobotsDisallowed):
        _fetch(f, f"{A}/x")
    assert "https://a.example:8443/robots.txt" in s.fetched
    assert "https://a.example:8443/y" not in s.fetched


# --- an unavailable robots.txt on the other host refuses the hop ----------------------------------------------------------------------


@pytest.mark.parametrize(("answer", "cause"), [(403, "refused"), (500, "server_error"), ("raise", "unreachable")])
def test_a_hop_to_a_host_whose_robots_cannot_be_read_is_refused_fail_closed(tmp_path, answer, cause):
    s = _Session()
    s.redirect(f"{A}/start", f"{B}/page")
    s.page(f"{B}/page")
    if answer == "raise":

        def boom():
            raise requests.ConnectionError("connection refused")

        s.on[f"{B}/robots.txt"] = boom
    else:
        s.robots(B, "", status=answer)
    f = _fetcher(tmp_path, s)
    with pytest.raises(RobotsUnavailable) as caught:
        _fetch(f, f"{A}/start")
    assert caught.value.cause == cause
    text = record_text(caught.value, typed=False)
    assert text.startswith("robots.txt for https://b.example could not be determined") and text.endswith(_NOTE), text
    assert f"{B}/page" not in s.fetched
    # cached and backed off as a first request's robots failure is
    assert f._robots[B][0] is None and f._robots_fails[B] == 1
    _no_lock_held(f, "a.example", "b.example")


# --- the other host's interval and Crawl-delay are waited, before its request ---------------------------------------------------------


def test_the_other_hosts_interval_is_waited_before_its_page_is_requested(tmp_path):
    events: list = []
    s, clock = _Session(events), _Clock(events)
    s.page(f"{B}/first")
    s.redirect(f"{A}/start", f"{B}/page")
    s.page(f"{B}/page")
    f = _fetcher(tmp_path, s, interval=2.0, clock=clock)
    _fetch(f, f"{B}/first")  # b.example last asked at t=1000
    clock.t += 0.5
    result = _fetch(f, f"{A}/start")
    assert result.final_url == f"{B}/page"
    assert clock.slept == [1.5]  # the interval left on b.example; a.example had never been asked
    tail = events[events.index(("get", f"{A}/start")):]
    assert tail == [("get", f"{A}/start"), ("sleep", 1.5), ("get", f"{B}/page")], tail
    # each host stamped when ITS request was answered: a.example before the wait, b.example after it
    assert f._last_request["a.example"] == 1000.5 and f._last_request["b.example"] == 1002.0


def test_the_other_hosts_crawl_delay_is_waited_on_the_next_hop_to_it(tmp_path):
    events: list = []
    s, clock = _Session(events), _Clock(events)
    s.robots(B, "User-agent: *\nCrawl-delay: 7\n")
    for n in ("one", "two"):
        s.redirect(f"{A}/{n}", f"{B}/{n}")
        s.page(f"{B}/{n}")
    f = _fetcher(tmp_path, s, clock=clock)
    _fetch(f, f"{A}/one")  # the first contact with b.example: nothing to wait for
    assert clock.slept == []
    _fetch(f, f"{A}/two")
    assert clock.slept == [7.0]
    assert events[-2:] == [("sleep", 7.0), ("get", f"{B}/two")], events


def test_a_crawl_delay_past_the_cap_defers_the_hop_and_its_page_is_never_requested(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_CRAWL_DELAY_MAX_WAIT", "60")
    events: list = []
    s, clock = _Session(events), _Clock(events)
    s.robots(B, "User-agent: *\nCrawl-delay: 600\n")
    for n in ("one", "two"):
        s.redirect(f"{A}/{n}", f"{B}/{n}")
        s.page(f"{B}/{n}")
    f = _fetcher(tmp_path, s, clock=clock)
    _fetch(f, f"{A}/one")
    with pytest.raises(CrawlDelayDeferred) as caught:
        _fetch(f, f"{A}/two")
    assert caught.value.netloc == "b.example" and caught.value.delay_s == 600.0
    assert f"{A}/two" in s.fetched and f"{B}/two" not in s.fetched
    assert "b.example" in f._host_schedule  # the next-allowed-at is written before the refusal, as for a first request
    _no_lock_held(f, "a.example", "b.example")


@pytest.mark.parametrize("first_answer", ["503", "raise"])
def test_a_hop_that_defers_on_a_retry_reports_the_failed_request_before_it(tmp_path, monkeypatch, first_answer):
    """The rule ``_fetch_locked`` keeps for the first host, kept for a hop's: a retry that defers follows a request that WAS made and
    failed, so the failure is the answer (a deferral would give the failed request no back-off)."""
    monkeypatch.setenv("OO_CRAWL_DELAY_MAX_WAIT", "60")
    events: list = []
    s, clock = _Session(events), _Clock(events)
    s.robots(B, "User-agent: *\nCrawl-delay: 600\n")
    s.redirect(f"{A}/start", f"{B}/page")
    s.page(f"{B}/page")
    once = {"n": 0}

    def fail_once():
        once["n"] += 1
        if once["n"] == 1:
            if first_answer == "raise":
                raise requests.ConnectionError("reset by peer")
            s.routes[f"{B}/page"] = (503, "busy", {"Content-Type": "text/html"})
        else:
            s.page(f"{B}/page")

    s.on[f"{B}/page"] = fail_once
    f = _fetcher(tmp_path, s, clock=clock, max_retries=1)
    with pytest.raises(FetchError) as caught:
        _fetch(f, f"{A}/start")
    assert not isinstance(caught.value, CrawlDelayDeferred)
    text = record_text(caught.value, typed=False)
    assert text.startswith("HTTP 503 for " if first_answer == "503" else "request error for "), text
    assert s.fetched.count(f"{B}/page") == 1 and s.fetched.count(f"{A}/start") == 2
    _no_lock_held(f, "a.example", "b.example")


def test_a_fetcher_that_reads_no_robots_still_waits_the_other_hosts_interval(tmp_path):
    events: list = []
    s, clock = _Session(events), _Clock(events)
    s.page(f"{B}/first")
    s.redirect(f"{A}/start", f"{B}/page")
    s.page(f"{B}/page")
    f = _fetcher(tmp_path, s, interval=3.0, clock=clock, respect_robots=False)
    _fetch(f, f"{B}/first")
    _fetch(f, f"{A}/start")
    assert clock.slept == [3.0]
    assert not [u for u in s.fetched if u.endswith("/robots.txt")]


# --- a robots read's own redirect hops keep today's behaviour: no recursion -----------------------------------------------------------


def test_a_robots_reads_own_hop_to_another_host_reads_no_robots_there(tmp_path):
    events: list = []
    s, clock = _Session(events), _Clock(events)
    s.redirect(f"{A}/robots.txt", f"{B}/policy.txt")
    s.page(f"{B}/policy.txt", _ALLOW_ALL, content_type="text/plain")
    s.page(f"{A}/page")
    f = _fetcher(tmp_path, s, interval=5.0, clock=clock)
    _fetch(f, f"{A}/page")
    assert s.fetched == [f"{A}/robots.txt", f"{B}/policy.txt", f"{A}/page"]
    assert clock.slept == []
    assert "b.example" not in f._last_request


def test_declared_sitemaps_through_a_robots_hop_reads_no_robots_on_the_other_host(tmp_path):
    s = _Session()
    s.redirect(f"{A}/robots.txt", f"{B}/policy.txt")
    s.page(f"{B}/policy.txt", f"{_ALLOW_ALL}Sitemap: {A}/sitemap.xml\n", content_type="text/plain")
    f = _fetcher(tmp_path, s)
    assert _bounded(lambda: f.declared_sitemaps(f"{A}/")) == [f"{A}/sitemap.xml"]
    assert s.fetched == [f"{A}/robots.txt", f"{B}/policy.txt"]


def test_the_hops_robots_read_follows_its_own_hop_without_reading_robots_there(tmp_path):
    s = _Session()
    s.redirect(f"{A}/start", f"{B}/page")
    s.redirect(f"{B}/robots.txt", f"{C}/rules.txt")
    s.page(f"{C}/rules.txt", _ALLOW_ALL, content_type="text/plain")
    s.page(f"{B}/page")
    f = _fetcher(tmp_path, s)
    assert _fetch(f, f"{A}/start").final_url == f"{B}/page"
    assert s.fetched == [f"{A}/robots.txt", f"{A}/start", f"{B}/robots.txt", f"{C}/rules.txt", f"{B}/page"]


# --- same-host hops keep their host: no new lock, no second wait (their robots re-check is R636's) --------------------------------------


def test_a_hop_on_the_same_host_reads_nothing_more_and_waits_nothing(tmp_path):
    events: list = []
    s, clock = _Session(events), _Clock(events)
    s.page(f"{A}/0")
    s.redirect(f"{A}/x", f"{A}/y")
    s.page(f"{A}/y")
    f = _fetcher(tmp_path, s, interval=5.0, clock=clock)
    _fetch(f, f"{A}/0")
    clock.t += 10
    assert _fetch(f, f"{A}/x").final_url == f"{A}/y"
    assert s.fetched == [f"{A}/robots.txt", f"{A}/0", f"{A}/x", f"{A}/y"] and clock.slept == []


def test_an_http_to_https_upgrade_on_the_same_host_is_not_another_host(tmp_path):
    """The host key is the same (scheme-free, default port dropped): no wait. Its robots key is another one, so since R636 the https
    robots.txt is read before the hop (tests/test_redirect_robots_recheck_r636.py), still with no wait."""
    events: list = []
    s, clock = _Session(events), _Clock(events)
    s.redirect("http://a.example/x", f"{A}/x", status=301)
    s.page(f"{A}/x")
    f = _fetcher(tmp_path, s, interval=5.0, clock=clock)
    assert _fetch(f, "http://a.example/x").final_url == f"{A}/x"
    assert s.fetched == ["http://a.example/robots.txt", "http://a.example/x", f"{A}/robots.txt", f"{A}/x"] and clock.slept == []


def test_a_same_host_hop_to_a_path_its_robots_disallows_is_refused_since_r636(tmp_path):
    """Changed by R636 (R629 left it standing): a same-host hop to a new path is robots-checked, so a disallowed path is refused."""
    s = _Session()
    s.robots(A, "User-agent: *\nDisallow: /private\n")
    s.redirect(f"{A}/x", f"{A}/private")
    s.page(f"{A}/private")
    f = _fetcher(tmp_path, s)
    with pytest.raises(RobotsDisallowed):
        _fetch(f, f"{A}/x")
    assert f"{A}/private" not in s.fetched


def test_a_hop_the_redirect_bound_will_not_request_reads_no_robots(tmp_path):
    """``_MAX_REDIRECTS`` stays 5; a sixth Location to another host ends in "too many redirects" with nothing asked of that host."""
    s = _Session()
    for n in range(5):
        s.redirect(f"{A}/r{n}", f"{A}/r{n + 1}")
    s.redirect(f"{A}/r5", f"{C}/x")
    s.page(f"{C}/x")
    f = _fetcher(tmp_path, s)
    assert ingest._MAX_REDIRECTS == 5
    with pytest.raises(FetchFailed) as caught:
        _fetch(f, f"{A}/r0")
    assert record_text(caught.value, typed=False).startswith("too many redirects for ")
    assert s.asked_of("c.example") == []


# --- the lock is handed over, never taken twice ---------------------------------------------------------------------------------------


def test_the_hop_is_requested_under_the_other_hosts_lock_with_the_first_released(tmp_path):
    s = _Session()
    s.redirect(f"{A}/start", f"{B}/page")
    s.page(f"{B}/page")
    f = _fetcher(tmp_path, s)
    held: list[tuple[bool, bool]] = []
    s.on[f"{B}/page"] = lambda: held.append((f._host_lock("a.example").locked(), f._host_lock("b.example").locked()))
    _fetch(f, f"{A}/start")
    assert held == [(False, True)]
    _no_lock_held(f, "a.example", "b.example")


def test_two_chains_crossing_each_other_do_not_deadlock(tmp_path):
    """A -> B on one thread while B -> A runs on another. Each thread is inside its first host's lock when both first answers arrive
    (a barrier holds both requests open until the other is in flight), so a design that takes the second host's lock on top of the
    first's deadlocks here: each waits for the lock the other holds. Handing the lock over cannot."""
    s = _Session()
    s.redirect(f"{A}/x", f"{B}/from-a")
    s.redirect(f"{B}/z", f"{A}/from-b")
    s.page(f"{B}/from-a")
    s.page(f"{A}/from-b")
    barrier = threading.Barrier(2, timeout=5)
    s.on[f"{A}/x"] = barrier.wait
    s.on[f"{B}/z"] = barrier.wait
    f = _fetcher(tmp_path, s)
    results: dict = {}

    def run(url):
        try:
            results[url] = f.fetch(url).final_url
        except BaseException as exc:  # noqa: BLE001 - reported below
            results[url] = exc

    threads = [threading.Thread(target=run, args=(u,), daemon=True) for u in (f"{A}/x", f"{B}/z")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert not any(t.is_alive() for t in threads), "the two crossing chains deadlocked on each other's host lock"
    assert results == {f"{A}/x": f"{B}/from-a", f"{B}/z": f"{A}/from-b"}, results
    _no_lock_held(f, "a.example", "b.example")


def test_while_a_hop_waits_its_hosts_interval_no_other_request_reaches_that_host(tmp_path):
    """The hop holds b.example's lock through its wait and its request, as a first request does: a direct fetch of b.example on
    another thread waits for it, and its own interval is counted from the hop's request."""
    events: list = []
    s, clock = _Session(events), _Clock(events)
    s.page(f"{B}/first")
    s.page(f"{B}/other")
    s.redirect(f"{A}/start", f"{B}/page")
    s.page(f"{B}/page")
    f = _fetcher(tmp_path, s, interval=2.0, clock=clock)
    _fetch(f, f"{B}/first")
    waiting, go = threading.Event(), threading.Event()

    def held_sleep(seconds):
        clock.sleep(seconds)
        if not go.is_set():
            waiting.set()
            assert go.wait(5)

    f._sleep = held_sleep  # type: ignore[method-assign]
    out: dict = {}
    t1 = threading.Thread(target=lambda: out.setdefault("hop", f.fetch(f"{A}/start").final_url), daemon=True)
    t1.start()
    assert waiting.wait(5), "the hop never waited for b.example's interval"
    t2 = threading.Thread(target=lambda: out.setdefault("direct", f.fetch(f"{B}/other").final_url), daemon=True)
    t2.start()
    time.sleep(0.3)
    assert f"{B}/other" not in s.fetched, "another thread reached b.example while the hop held its turn"
    go.set()
    t1.join(5)
    t2.join(5)
    assert not t1.is_alive() and not t2.is_alive()
    assert out == {"hop": f"{B}/page", "direct": f"{B}/other"}
    assert s.fetched.index(f"{B}/page") < s.fetched.index(f"{B}/other")
    assert clock.slept == [2.0, 2.0]  # the hop's wait, then the direct fetch's, counted from the hop's request


# --- a crawl kept to one site refuses a hop off it ------------------------------------------------------------------------------------


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="Good", domain="good.example", language="en"))
    s.commit()
    yield s
    s.close()


@pytest.fixture()
def source(db):
    return db.query(Source).first()


def _site(*, story_location, evil_robots=_ALLOW_ALL) -> _Session:
    s = _Session()
    s.page("https://good.example", _html("Front", "The front page of a good site.", links=["/story"]))
    s.redirect("https://good.example/story", story_location)
    s.robots("https://evil.example", evil_robots)
    s.page("https://evil.example/story", _html("Evil", "A story that lives on another site entirely."))
    s.page("https://www.good.example/story", _html("Story", "A story that lives on the good site itself."))
    return s


def _crawl(db, source, f, **cfg):
    return _bounded(lambda: crawl_source(db, source, fetcher=f, config=CrawlConfig(max_depth=1, max_pages=10, **cfg)))


def test_a_crawl_kept_to_its_site_refuses_a_hop_off_it_before_asking_the_other_host_anything(db, source, tmp_path):
    s = _site(story_location="https://evil.example/story")
    report = _crawl(db, source, _fetcher(tmp_path, s))
    assert s.asked_of("evil.example") == []  # no robots.txt read, no page
    assert report.tally[IngestResult.FETCH_FAILED.value] == 1
    assert not db.query(Article).filter(Article.url.contains("evil")).count()


def test_a_crawl_kept_to_its_site_refuses_a_start_url_that_redirects_off_it(db, source, tmp_path):
    s = _Session()
    s.redirect("https://good.example", "https://evil.example/")
    s.page("https://evil.example/")
    report = _crawl(db, source, _fetcher(tmp_path, s))
    assert report.pages_fetched == 0 and s.asked_of("evil.example") == []


def test_a_crawl_hop_that_writes_a_userinfo_is_off_the_site(db, source, tmp_path):
    """The crawl's site test is ``_off_site``, for which a netloc holding an ``@`` is off the site (R624, R630): the hop is refused even
    on the same host, so a server-chosen login is neither sent nor stored."""
    s = _site(story_location="https://u:fake-secret@good.example/story2")
    s.page("https://u:fake-secret@good.example/story2")
    report = _crawl(db, source, _fetcher(tmp_path, s))
    assert "https://u:fake-secret@good.example/story2" not in s.fetched
    assert report.tally[IngestResult.FETCH_FAILED.value] == 1


def test_a_crawl_still_follows_a_hop_that_stays_on_its_site(db, source, tmp_path):
    s = _site(story_location="https://www.good.example/story")
    report = _crawl(db, source, _fetcher(tmp_path, s))
    assert "https://www.good.example/story" in s.fetched
    assert report.pages_fetched == 2


def test_an_on_site_hop_to_another_host_reads_that_hosts_robots_first(db, source, tmp_path):
    """www.good.example is the same SITE (the crawl strips ``www.``) and another HOST (another host key): its robots.txt is read."""
    s = _site(story_location="https://www.good.example/story")
    _crawl(db, source, _fetcher(tmp_path, s))
    www = s.asked_of("www.good.example")
    assert www == ["https://www.good.example/robots.txt", "https://www.good.example/story"], www


def test_an_open_crawl_follows_a_hop_off_the_site_only_after_that_hosts_robots(db, source, tmp_path):
    s = _site(story_location="https://evil.example/story")
    report = _crawl(db, source, _fetcher(tmp_path, s), same_domain_only=False)
    assert s.asked_of("evil.example") == ["https://evil.example/robots.txt", "https://evil.example/story"]
    assert report.pages_fetched == 2


def test_an_open_crawl_refuses_a_hop_off_the_site_that_the_other_hosts_robots_disallows(db, source, tmp_path):
    s = _site(story_location="https://evil.example/story", evil_robots=_DISALLOW_ALL)
    report = _crawl(db, source, _fetcher(tmp_path, s), same_domain_only=False)
    assert s.asked_of("evil.example") == ["https://evil.example/robots.txt"]
    assert report.tally[IngestResult.BLOCKED_ROBOTS.value] == 1


# --- the same scope rule in sitemap discovery -----------------------------------------------------------------------------------------

_URLSET = (
    '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<url><loc>{loc}</loc></url></urlset>"
)


def test_a_sitemap_that_redirects_off_the_host_is_refused_before_the_other_host_is_asked(tmp_path):
    s = _Session()
    s.redirect("https://example.com/sitemap.xml", "https://cdn.elsewhere.example/sitemap.xml")
    s.page("https://cdn.elsewhere.example/sitemap.xml", _URLSET.format(loc="https://cdn.elsewhere.example/a"),
           content_type="application/xml")
    report = _bounded(lambda: discover_sitemap_urls(_fetcher(tmp_path, s), "example.com"))
    assert s.asked_of("cdn.elsewhere.example") == []
    assert report.urls == [] and report.root_sitemap_url is None
    assert any("redirect leaves the site the fetch is kept to, not followed" in line for line in report.errors), report.errors


def test_a_sitemap_that_redirects_to_its_www_host_is_still_followed(tmp_path):
    s = _Session()
    s.redirect("https://example.com/sitemap.xml", "https://www.example.com/sitemap.xml")
    s.page("https://www.example.com/sitemap.xml", _URLSET.format(loc="https://example.com/a"), content_type="application/xml")
    report = _bounded(lambda: discover_sitemap_urls(_fetcher(tmp_path, s), "example.com"))
    assert report.urls == ["https://example.com/a"]


# --- the scope: asked on every hop, before the guard, failing closed ------------------------------------------------------------------


def test_the_scope_is_asked_about_every_hop_and_never_about_the_first_url(tmp_path):
    s = _Session()
    s.redirect(f"{A}/x", f"{A}/y")
    s.redirect(f"{A}/y", f"{B}/z")
    s.page(f"{B}/z")
    f = _fetcher(tmp_path, s)
    asked: list[str] = []

    def scope(url):
        asked.append(url)
        return True

    _fetch(f, f"{A}/x", redirect_scope=scope)
    assert asked == [f"{A}/y", f"{B}/z"]


@pytest.mark.parametrize("answer", ["false", "raise"])
def test_a_hop_the_scope_refuses_or_cannot_judge_asks_nothing_of_its_host(tmp_path, answer):
    s = _Session()
    s.redirect(f"{A}/start", f"{B}/page")  # a plain Location: one that writes a login is refused before any scope is asked (R633)
    s.page(f"{B}/page")

    def scope(url):
        if answer == "raise":
            raise ValueError("a scope that cannot read the hop")
        return False

    f = _fetcher(tmp_path, s)
    guarded: list = []
    real_guard = f._guard_target
    f._guard_target = lambda host: (guarded.append(host), real_guard(host))[1]  # type: ignore[method-assign]
    with pytest.raises(ingest.RedirectOutOfScope) as caught:
        _fetch(f, f"{A}/start", redirect_scope=scope)
    assert isinstance(caught.value, FetchFailed) and not isinstance(caught.value, requests.RequestException)
    text = record_text(caught.value, typed=False)
    assert text.startswith("redirect leaves the site the fetch is kept to, not followed: "), text
    assert s.asked_of("b.example") == [] and guarded == ["a.example"]  # the hop's host was not even looked up
    _no_lock_held(f, "a.example", "b.example")


# --- the kill switch still refuses mid-chain ------------------------------------------------------------------------------------------


class _MemoryAdapter(BaseAdapter):
    """A transport for a REAL requests.Session that answers in memory: the fetcher's real-session guards run, no socket is opened."""

    def __init__(self, routes: dict, asked: list, on: dict):
        super().__init__()
        self.routes, self.asked, self.on = routes, asked, on

    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        self.asked.append(request.url)
        hook = self.on.get(request.url)
        if hook is not None:
            hook()
        status, headers, body = self.routes.get(request.url, (404, {}, b""))
        resp = requests.Response()
        resp.status_code = status
        resp.headers.update({"Content-Type": "text/html", **headers})
        resp.raw = io.BytesIO(body)
        resp.url = request.url
        resp.request = request
        resp.encoding = "utf-8"
        return resp

    def close(self):
        pass


def test_a_stop_pressed_as_the_first_host_answers_refuses_the_hop_on_a_real_session(tmp_path, monkeypatch):
    for var in {*_PROXY_VARS, *(v for v in __import__("os").environ if v.lower().endswith("_proxy"))}:
        monkeypatch.delenv(var, raising=False)
    routes = {f"{A}/start": (302, {"Location": f"{B}/page"}, b""), f"{B}/page": (200, {}, _html().encode())}
    asked: list[str] = []
    on = {f"{A}/start": activate_kill_switch}
    f = EthicalFetcher(min_interval_s=0, retry_backoff_s=0, max_retries=0, robots_cache_path=tmp_path / "robots_cache.json")
    adapter = _MemoryAdapter(routes, asked, on)
    f.session.mount("https://", adapter)
    f.session.mount("http://", adapter)
    f._resolve_cached = lambda host: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0))]  # type: ignore[method-assign]
    assert f._real_session
    with pytest.raises(FetchFailed) as caught:
        _fetch(f, f"{A}/start")
    assert record_text(caught.value, typed=False) == KILL_SWITCH_REFUSAL
    assert [u for u in asked if urlsplit(u).hostname == "b.example"] == []
    _no_lock_held(f, "a.example", "b.example")


def test_a_stop_pressed_as_the_first_host_answers_refuses_the_hop_on_an_injected_session(tmp_path):
    """The hop reads the switch itself, so an injected session sees the refusal a real one gets from the guard."""
    s = _Session()
    s.redirect(f"{A}/start", f"{B}/page")
    s.page(f"{B}/page")
    s.on[f"{A}/start"] = activate_kill_switch
    f = _fetcher(tmp_path, s)
    with pytest.raises(FetchFailed) as caught:
        _fetch(f, f"{A}/start")
    assert record_text(caught.value, typed=False) == KILL_SWITCH_REFUSAL
    assert s.asked_of("b.example") == []


def test_a_stop_pressed_while_the_hop_waits_its_interval_refuses_the_hop(tmp_path):
    events: list = []
    s, clock = _Session(events), _Clock(events)
    s.page(f"{B}/first")
    s.redirect(f"{A}/start", f"{B}/page")
    s.page(f"{B}/page")
    f = _fetcher(tmp_path, s, interval=2.0, clock=clock)
    _fetch(f, f"{B}/first")
    clock.on_sleep = activate_kill_switch
    with pytest.raises(FetchFailed) as caught:
        _fetch(f, f"{A}/start")
    assert record_text(caught.value, typed=False) == KILL_SWITCH_REFUSAL
    assert clock.slept == [2.0] and f"{B}/page" not in s.fetched
    assert f._robots[B][0] is not None  # b.example's robots verdict stands: the Stop is not the host's failure
    _no_lock_held(f, "a.example", "b.example")


def test_a_stop_pressed_while_the_hops_robots_is_read_is_not_cached_as_the_hosts_failure(tmp_path):
    s = _Session()
    s.redirect(f"{A}/start", f"{B}/page")
    s.page(f"{B}/page")

    def stop_then_cut():
        activate_kill_switch()
        raise requests.ConnectionError("cut off by the socket guard")

    s.on[f"{B}/robots.txt"] = stop_then_cut
    f = _fetcher(tmp_path, s)
    with pytest.raises(FetchFailed) as caught:
        _fetch(f, f"{A}/start")
    assert not isinstance(caught.value, RobotsUnavailable)
    assert record_text(caught.value, typed=False) == KILL_SWITCH_REFUSAL
    assert f"{B}/robots.txt" in s.fetched and f"{B}/page" not in s.fetched
    assert B not in f._robots and B not in f._robots_fails  # nothing remembered: the next fetch asks again (R297)


# --- what callers see -----------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("robots", "status", "outcome"),
    [(_DISALLOW_ALL, 200, IngestResult.BLOCKED_ROBOTS), ("", 403, IngestResult.ROBOTS_UNAVAILABLE)],
)
def test_ingest_files_a_refused_hop_in_the_robots_buckets_with_the_hops_address(db, source, tmp_path, robots, status, outcome):
    s = _Session()
    s.redirect("https://good.example/a", f"{B}/page")
    s.robots(B, robots, status=status)
    s.page(f"{B}/page")
    out = _bounded(lambda: ingest_url(db, source, "https://good.example/a", fetcher=_fetcher(tmp_path, s)))
    assert out.result is outcome
    assert "b.example" in (out.detail or "") and (out.detail or "").endswith(_NOTE), out.detail
    assert f"{B}/page" not in s.fetched


def test_the_preflight_homepage_ping_reads_the_robots_of_the_host_it_is_redirected_to(tmp_path):
    """Changed by R636 (R629 left the ping as it was): the ping obeys robots.txt, and its hop to another host reads that host's
    robots.txt first, with no lock and no wait, as the ping takes none (tests/test_redirect_robots_recheck_r636.py)."""
    from src.monitoring.preflight import _check_one

    s = _Session()
    s.redirect(f"{A}/", f"{B}/")
    s.page(f"{B}/")
    f = _fetcher(tmp_path, s)
    rec = _bounded(lambda: _check_one(f, SimpleNamespace(id=1, domain="a.example")))
    assert rec["homepage_status"] == 200 and rec["robots"] == "missing"
    assert s.fetched == [f"{A}/robots.txt", f"{A}/", f"{B}/robots.txt", f"{B}/"]


# --- a Location that writes a user name or password is never followed (R633) -------------------------------------------------------
#
# Measured by a review: a plain on-site link that 302s to https://alice:hunter2@good.example/landing was followed with
# ``Authorization: Basic`` and stored as the article's canonical_url. These run on a REAL requests.Session (the in-memory adapter),
# so what requests would send is what is recorded: every request's URL and headers.


class _RecordingAdapter(_MemoryAdapter):
    def __init__(self, routes: dict, asked: list, on: dict, sent: list):
        super().__init__(routes, asked, on)
        self.sent = sent

    def send(self, request, **kwargs):
        self.sent.append((request.url, dict(request.headers)))
        return super().send(request, **kwargs)


def _real_fetcher(tmp_path, monkeypatch, routes: dict):
    for var in {*_PROXY_VARS, *(v for v in __import__("os").environ if v.lower().endswith("_proxy"))}:
        monkeypatch.delenv(var, raising=False)
    asked: list[str] = []
    sent: list[tuple[str, dict]] = []
    f = EthicalFetcher(min_interval_s=0, retry_backoff_s=0, max_retries=0, robots_cache_path=tmp_path / "robots_cache.json")
    adapter = _RecordingAdapter(routes, asked, {}, sent)
    f.session.mount("https://", adapter)
    f.session.mount("http://", adapter)
    f._resolve_cached = lambda host: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0))]  # type: ignore[method-assign]
    return f, asked, sent


def _logins(sent) -> list[str]:
    return [url for url, headers in sent if any(k.lower() == "authorization" for k in headers)]


_CREDENTIALED = "https://alice:hunter2@{host}/landing"


@pytest.mark.parametrize("host", ["a.example", "b.example"])
def test_a_location_with_a_login_is_never_requested_and_no_login_is_sent(tmp_path, monkeypatch, host):
    location = _CREDENTIALED.format(host=host)
    routes = {f"{A}/a": (302, {"Location": location}, b""), location: (200, {}, _html().encode())}
    f, asked, sent = _real_fetcher(tmp_path, monkeypatch, routes)
    with pytest.raises(BlockedTarget) as caught:  # the type of R622's refusals of the address (R633)
        _fetch(f, f"{A}/a")
    text = record_text(caught.value, typed=False)
    assert text.startswith("redirect to an address that carries a user name or password, not followed: "), text
    assert "hunter2" not in text and "alice" not in text
    assert [u for u in asked if "@" in urlsplit(u).netloc] == [] and _logins(sent) == []
    assert asked == [f"{A}/robots.txt", f"{A}/a"]  # nothing asked of the other host either, not even its robots.txt
    _no_lock_held(f, "a.example", "b.example")


def test_a_robots_read_that_redirects_to_a_login_is_refused_fail_closed(tmp_path, monkeypatch):
    location = "https://alice:hunter2@a.example/private-robots.txt"
    routes = {f"{A}/robots.txt": (302, {"Location": location}, b""), location: (200, {"Content-Type": "text/plain"}, b""),
              f"{A}/page": (200, {}, _html().encode())}
    f, asked, sent = _real_fetcher(tmp_path, monkeypatch, routes)
    with pytest.raises(RobotsUnavailable) as caught:
        _fetch(f, f"{A}/page")
    assert caught.value.cause == "unreachable"
    assert asked == [f"{A}/robots.txt"] and _logins(sent) == []


def test_an_ingested_link_that_redirects_to_a_login_stores_nothing(db, source, tmp_path):
    s = _Session()
    s.redirect("https://good.example/a", "https://alice:hunter2@good.example/landing")
    s.page("https://alice:hunter2@good.example/landing", _html("Landing", "A landing page behind a login nobody asked for."))
    out = _bounded(lambda: ingest_url(db, source, "https://good.example/a", fetcher=_fetcher(tmp_path, s)))
    assert out.result is IngestResult.FETCH_FAILED
    assert "hunter2" not in (out.detail or "")
    assert "https://alice:hunter2@good.example/landing" not in s.fetched
    assert db.query(Article).count() == 0


@pytest.mark.parametrize(
    "location",
    [
        "https://a.example/landing?by=alice@example.org",  # an @ in the query
        "/people/@alice",  # an @ in the path
        "https://a.example/x#me@frag",  # an @ in the fragment
    ],
)
def test_an_at_sign_outside_the_authority_is_followed(tmp_path, monkeypatch, location):
    target = location if location.startswith("https") else f"{A}{location}"  # requests sends the fragment as written
    routes = {f"{A}/a": (302, {"Location": location}, b""), target: (200, {}, _html().encode())}
    f, asked, sent = _real_fetcher(tmp_path, monkeypatch, routes)
    result = _fetch(f, f"{A}/a")
    assert result.status_code == 200 and asked[-1] == target and _logins(sent) == []


def test_an_operators_login_stays_on_its_own_host_across_a_relative_hop(tmp_path, monkeypatch):
    """Unchanged: a relative Location writes no authority, so the address the caller wrote with a login keeps it, on that host
    only, as it did before."""
    first = "https://op:fake-token@a.example/feed"
    routes = {first: (301, {"Location": "/feed/"}, b""), f"{first}/": (200, {}, _html().encode())}
    f, asked, sent = _real_fetcher(tmp_path, monkeypatch, routes)
    assert _fetch(f, first, require_html=False).status_code == 200
    assert asked == [f"{A}/robots.txt", first, f"{first}/"]
    assert _logins(sent) == [first, f"{first}/"]


@pytest.mark.parametrize(
    "location",
    [
        "https://other:fake-2@a.example/feed/",  # another login on the same host
        "https://op:fake-token@b.example/feed/",  # the caller's own login, handed to another host
        "https://op:fake-token@a.example/feed/",  # the caller's own login written out again: a Location that writes one is refused
        "//op:fake-token@a.example/feed/",  # the same, as a network-path reference
    ],
)
def test_a_location_that_writes_a_login_is_refused_even_the_callers_own(tmp_path, monkeypatch, location):
    first = "https://op:fake-token@a.example/feed"
    routes = {first: (302, {"Location": location}, b""), location: (200, {}, _html().encode())}
    f, asked, sent = _real_fetcher(tmp_path, monkeypatch, routes)
    with pytest.raises(BlockedTarget) as caught:  # the type of R622's refusals of the address (R633)
        _fetch(f, first, require_html=False)
    text = record_text(caught.value, typed=False)
    assert text.startswith("redirect to an address that carries a user name or password"), text
    assert "fake-token" not in text and "fake-2" not in text
    assert asked == [f"{A}/robots.txt", first] and _logins(sent) == [first]
