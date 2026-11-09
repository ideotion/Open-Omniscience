"""
A redirect hop is robots-checked again whenever its robots key or its path changes, and the preflight's homepage ping obeys
robots.txt too (R636).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

R629 made a hop to ANOTHER host a first request to that host, and left one early return standing: a hop on the same host key was
neither robots-checked nor charged an interval. So ``https://a.example/x`` answering ``302 Location: /private`` was followed into a
path a.example's robots.txt disallows, and ``http://a.example/x`` answering ``301 Location: https://a.example/x`` never read the https
robots.txt at all (the robots cache is keyed by scheme and host, and the host key leaves the scheme out). The first-run preflight's
homepage ping, a side door that calls ``_guarded_redirect_get`` directly, was made whatever the robots.txt it had just read said.

Now (R636), fail-closed:
  - a hop whose robots key (scheme and host) or request target (path, ``;params`` and query, which robots rules match) differs from
    the address that answered is checked through ``_enforce_robots`` before it is requested: from the cached robots.txt for another
    path or query on the same key (no new read), from the https robots.txt for an upgrade. The refusal keeps R629's words, "(reached
    by a redirect)". A same-host hop keeps its lock and waits no second interval: the interval is per host and is unchanged;
  - the ping is made only when the preflight's own read allows the homepage or finds no robots.txt, and each hop it would follow is
    checked the same way (``hop_robots``); a ping robots.txt keeps from being made is recorded in fixed words, and a ping whose hop
    was refused is not "ok": "robots_denied" for a disallow, "unreachable" for a robots.txt that could not be read;
  - the switch is read again after a hop's robots check, which may have gone to the network: a Stop pressed during it (or pressed and
    cleared again, the R614 epoch) refuses the hop, which is never requested.
A robots read passes no chain and no ``hop_robots``, so its own hops never read robots.txt: no recursion.

Driven through the real ``EthicalFetcher`` (and the real ``ingest_url``, ``crawl_source`` and the preflight's ``_check_one`` and
``preflight_sources``) over an injected session that answers in memory, as tests/test_redirect_hop_robots_r629.py does; the kill-switch
tests also run on a real ``requests.Session`` whose transport adapter answers in memory. Every planted URL has a route, so a request to it is
SEEN, never assumed. Time is a fake clock: a wait is recorded, never slept. Every fetch runs in a bounded thread, so a design that takes
a host lock it already holds fails here instead of hanging the suite. Nothing leaves the machine.
"""

from __future__ import annotations

import io
import os
import socket
import threading
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
import requests
from requests.adapters import BaseAdapter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.models import Article, Base, Source, SourceMetadata
from src.ingest import (
    EthicalFetcher,
    FetchFailed,
    RobotsDisallowed,
    RobotsUnavailable,
    activate_kill_switch,
    clear_kill_switch,
)
from src.ingest.crawl import CrawlConfig, crawl_source
from src.ingest.fetch_verdict import KILL_SWITCH_REFUSAL
from src.ingest.pipeline import IngestResult, ingest_url
from src.monitoring import preflight
from src.monitoring.feed_preflight import _check_host_robots
from src.monitoring.secret_scrub import record_text

A = "https://a.example"
H = "http://a.example"
B = "https://b.example"
C = "https://c.example"
_NOTE = "(reached by a redirect)"
_DISALLOW_ALL = "User-agent: *\nDisallow: /\n"
_ALLOW_ALL = "User-agent: *\nAllow: /\n"
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy")

# The fixed words of a skipped ping, written out here rather than imported: a change to them is a change to the record operators read.
_SKIPPED_DISALLOWED = "homepage not requested: robots.txt disallows it"
_SKIPPED_UNREADABLE = "homepage not requested: robots.txt could not be read"
_HOP_DISALLOWED = "homepage redirect not followed: robots.txt disallows the address it leads to"
_HOP_UNREADABLE = "homepage redirect not followed: the robots.txt of the address it leads to could not be read"


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

    def robots_reads(self) -> list[str]:
        return [u for u in self.fetched if urlsplit(u).path == "/robots.txt"]


class _Clock:
    """The fetcher's monotonic clock and sleep: a wait is recorded and the clock moved, never slept."""

    def __init__(self, events: list):
        self.t = 1000.0
        self.slept: list[float] = []
        self.events = events

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.events.append(("sleep", seconds))
        self.t += seconds


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
    """Run ``fn`` in a daemon thread and fail, instead of hanging, if it does not finish (a host lock taken while already held)."""
    box: dict = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - handed back to the test as raised
            box["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    assert not t.is_alive(), "the call did not finish: a host lock was taken while already held, or never released"
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _fetch(f, url, **kw):
    return _bounded(lambda: f.fetch(url, **kw))


def _no_lock_held(f, *hosts):
    for host in hosts:
        assert not f._host_lock(host).locked(), f"the lock of {host} was left held"


def _spy_robots_checks(f) -> list[tuple[str, bool]]:
    """Every ``_enforce_robots`` call, as (url, hop): the decisions taken, read or cached alike."""
    calls: list[tuple[str, bool]] = []
    real = f._enforce_robots

    def spy(url, host_key, parsed, *, hop=False):
        calls.append((url, hop))
        return real(url, host_key, parsed, hop=hop)

    f._enforce_robots = spy  # type: ignore[method-assign]
    return calls


def _ping(f, domain="a.example"):
    return _bounded(lambda: preflight._check_one(f, SimpleNamespace(id=1, domain=domain)))


@pytest.fixture(autouse=True)
def _switch_clear(monkeypatch):
    monkeypatch.delenv("OO_CRAWL_DELAY_MAX_WAIT", raising=False)
    clear_kill_switch()
    yield
    clear_kill_switch()


# --- a same-host hop to a new path is robots-checked ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "location",
    [
        f"{A}/private",  # absolute
        "/private",  # absolute path
        "private",  # relative path, against /x
        "//a.example/private",  # network-path reference
        "https://A.Example:443/private",  # another spelling of the same robots key
    ],
)
def test_a_same_host_hop_to_a_disallowed_path_is_refused_and_never_requested(tmp_path, location):
    s = _Session()
    s.robots(A, "User-agent: *\nDisallow: /private\n")
    s.redirect(f"{A}/x", location)
    for page in (f"{A}/private", "https://A.Example:443/private"):  # each spelling answers, so a follow is seen
        s.page(page)
    f = _fetcher(tmp_path, s)
    with pytest.raises(RobotsDisallowed) as caught:
        _fetch(f, f"{A}/x")
    text = record_text(caught.value, typed=False)
    assert text.startswith("robots.txt disallows ") and text.endswith(_NOTE), text
    assert s.fetched == [f"{A}/robots.txt", f"{A}/x"]  # the cached robots.txt answers: no new read, and the hop never asked
    _no_lock_held(f, "a.example")


def test_every_same_host_hop_of_a_chain_is_checked_and_the_one_disallowed_is_refused(tmp_path):
    s = _Session()
    s.robots(A, "User-agent: *\nDisallow: /private\n")
    s.redirect(f"{A}/x", f"{A}/y")
    s.redirect(f"{A}/y", f"{A}/private/z")
    s.page(f"{A}/private/z")
    f = _fetcher(tmp_path, s)
    calls = _spy_robots_checks(f)
    with pytest.raises(RobotsDisallowed):
        _fetch(f, f"{A}/x")
    assert s.fetched == [f"{A}/robots.txt", f"{A}/x", f"{A}/y"]
    assert calls == [(f"{A}/x", False), (f"{A}/y", True), (f"{A}/private/z", True)]


def test_a_same_host_hop_after_a_host_move_is_checked_against_the_host_it_moved_to(tmp_path):
    """a.example -> b.example (R629: b's robots.txt read) -> b.example/private (R636: checked against b's, not a's)."""
    s = _Session()
    s.robots(A, _ALLOW_ALL)
    s.robots(B, "User-agent: *\nDisallow: /private\n")
    s.redirect(f"{A}/x", f"{B}/y")
    s.redirect(f"{B}/y", "/private")
    s.page(f"{B}/private")
    f = _fetcher(tmp_path, s)
    with pytest.raises(RobotsDisallowed) as caught:
        _fetch(f, f"{A}/x")
    assert record_text(caught.value, typed=False) == f"robots.txt disallows {B}/private {_NOTE}"
    assert s.fetched == [f"{A}/robots.txt", f"{A}/x", f"{B}/robots.txt", f"{B}/y"]
    _no_lock_held(f, "a.example", "b.example")


def test_a_same_host_hop_to_an_allowed_path_is_followed(tmp_path):
    s = _Session()
    s.robots(A, "User-agent: *\nDisallow: /private\n")
    s.redirect(f"{A}/x", f"{A}/public")
    s.page(f"{A}/public")
    f = _fetcher(tmp_path, s)
    assert _fetch(f, f"{A}/x").final_url == f"{A}/public"
    assert s.fetched == [f"{A}/robots.txt", f"{A}/x", f"{A}/public"]


def test_a_refusal_of_a_hop_writes_its_address_through_failure_url(tmp_path):
    """The operator's own login, kept on its host across a relative hop (R633), is masked in the refusal's sentence."""
    first = "https://op:fake-token@a.example/feed"
    s = _Session()
    s.robots(A, "User-agent: *\nDisallow: /feed/\n")
    s.redirect(first, "/feed/")
    s.page(f"{first}/")
    f = _fetcher(tmp_path, s)
    with pytest.raises(RobotsDisallowed) as caught:
        _fetch(f, first, require_html=False)
    text = record_text(caught.value, typed=False)
    assert "fake-token" not in text and "op:" not in text and text.endswith(_NOTE), text
    assert f"{first}/" not in s.fetched


# --- http -> https (and back) on the same host reads that scheme's robots.txt ---------------------------------------------------------


@pytest.mark.parametrize(("start", "target", "other"), [(H, A, A), (A, H, H)])
def test_a_scheme_change_reads_the_other_schemes_robots_and_its_disallow_refuses_the_hop(tmp_path, start, target, other):
    s = _Session()
    s.robots(start, _ALLOW_ALL)
    s.robots(other, _DISALLOW_ALL)
    s.redirect(f"{start}/x", f"{target}/x", status=301)
    s.page(f"{target}/x")
    f = _fetcher(tmp_path, s)
    with pytest.raises(RobotsDisallowed) as caught:
        _fetch(f, f"{start}/x")
    assert record_text(caught.value, typed=False) == f"robots.txt disallows {target}/x {_NOTE}"
    assert s.fetched == [f"{start}/robots.txt", f"{start}/x", f"{other}/robots.txt"]
    _no_lock_held(f, "a.example")


@pytest.mark.parametrize(("answer", "cause"), [(403, "refused"), (500, "server_error"), (503, "server_error"), ("raise", "unreachable")])
def test_an_upgrade_whose_https_robots_cannot_be_read_is_refused_fail_closed(tmp_path, answer, cause):
    s = _Session()
    s.robots(H, _ALLOW_ALL)
    s.redirect(f"{H}/x", f"{A}/x", status=301)
    s.page(f"{A}/x")
    if answer == "raise":

        def boom():
            raise requests.ConnectionError("connection refused")

        s.on[f"{A}/robots.txt"] = boom
    else:
        s.robots(A, "", status=answer)
    f = _fetcher(tmp_path, s)
    with pytest.raises(RobotsUnavailable) as caught:
        _fetch(f, f"{H}/x")
    assert caught.value.cause == cause
    text = record_text(caught.value, typed=False)
    assert text.startswith(f"robots.txt for {A} could not be determined ({cause})") and text.endswith(_NOTE), text
    assert f"{A}/x" not in s.fetched
    assert f._robots[A][0] is None and f._robots_fails[A] == 1  # cached and backed off, as a first request's robots failure is
    assert f._robots[H][0] is not None  # the http verdict is untouched
    _no_lock_held(f, "a.example")


def test_an_allowed_upgrade_reads_the_https_robots_once_and_is_followed(tmp_path):
    s = _Session()
    s.robots(H, _ALLOW_ALL)
    s.robots(A, _ALLOW_ALL)
    for n in ("one", "two"):
        s.redirect(f"{H}/{n}", f"{A}/{n}", status=301)
        s.page(f"{A}/{n}")
    f = _fetcher(tmp_path, s)
    assert _fetch(f, f"{H}/one").final_url == f"{A}/one"
    assert _fetch(f, f"{H}/two").final_url == f"{A}/two"
    assert s.robots_reads() == [f"{H}/robots.txt", f"{A}/robots.txt"]  # each scheme's robots.txt read once, then cached


def test_the_upgrades_robots_read_is_made_under_the_lock_already_held(tmp_path):
    """No second lock: the read runs under a.example's lock, the one the chain holds (a second acquire would hang _bounded)."""
    s = _Session()
    s.redirect(f"{H}/x", f"{A}/x", status=301)
    s.page(f"{A}/x")
    f = _fetcher(tmp_path, s)
    held: list[bool] = []
    s.on[f"{A}/robots.txt"] = lambda: held.append(f._host_lock("a.example").locked())
    assert _fetch(f, f"{H}/x").final_url == f"{A}/x"
    assert held == [True]
    _no_lock_held(f, "a.example")


# --- a robots.txt that redirects ------------------------------------------------------------------------------------------------------


def test_an_upgrades_robots_txt_that_redirects_is_followed_and_reads_no_robots_on_its_hop(tmp_path):
    s = _Session()
    s.robots(H, _ALLOW_ALL)
    s.redirect(f"{A}/robots.txt", f"{C}/rules.txt")
    s.page(f"{C}/rules.txt", _DISALLOW_ALL, content_type="text/plain")
    s.redirect(f"{H}/x", f"{A}/x", status=301)
    s.page(f"{A}/x")
    f = _fetcher(tmp_path, s)
    with pytest.raises(RobotsDisallowed):
        _fetch(f, f"{H}/x")
    assert s.fetched == [f"{H}/robots.txt", f"{H}/x", f"{A}/robots.txt", f"{C}/rules.txt"]  # no c.example robots.txt: no recursion
    _no_lock_held(f, "a.example", "c.example")


def test_an_http_robots_txt_that_redirects_to_the_https_one_is_read_again_for_the_upgrade(tmp_path):
    """The usual site: http://host/robots.txt 301s to https://host/robots.txt. The http key's read follows it; the upgrade then reads
    the https key's robots.txt itself (one more request, stated: the cache is keyed by scheme and host, and a read is filed under
    the key asked for)."""
    s = _Session()
    s.redirect(f"{H}/robots.txt", f"{A}/robots.txt", status=301)
    s.robots(A, _ALLOW_ALL)
    s.redirect(f"{H}/x", f"{A}/x", status=301)
    s.page(f"{A}/x")
    f = _fetcher(tmp_path, s)
    assert _fetch(f, f"{H}/x").final_url == f"{A}/x"
    assert s.fetched == [f"{H}/robots.txt", f"{A}/robots.txt", f"{H}/x", f"{A}/robots.txt", f"{A}/x"]


def test_a_robots_txt_that_redirects_off_the_host_on_a_same_host_hop_is_not_read_again(tmp_path):
    """A new path on the same key asks the cache, which holds the redirected read's verdict: nothing is read twice."""
    s = _Session()
    s.redirect(f"{A}/robots.txt", f"{C}/rules.txt")
    s.page(f"{C}/rules.txt", "User-agent: *\nDisallow: /private\n", content_type="text/plain")
    s.redirect(f"{A}/x", "/private")
    s.page(f"{A}/private")
    f = _fetcher(tmp_path, s)
    with pytest.raises(RobotsDisallowed):
        _fetch(f, f"{A}/x")
    assert s.fetched == [f"{A}/robots.txt", f"{C}/rules.txt", f"{A}/x"]


# --- the query: a query-only hop is checked, from the cache ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("first", "hop", "rule"),
    [
        ("/page?a=1", "/page?private=1", "Disallow: /page?private"),
        ("/page", "/page?private=1", "Disallow: /page?private"),
        ("/x;a", "/x;sess=1", "Disallow: /x;sess"),  # the ;params robots rules match as well
    ],
)
def test_a_query_only_hop_into_a_disallowed_query_is_refused_with_no_new_read(tmp_path, first, hop, rule):
    s = _Session()
    s.robots(A, f"User-agent: *\n{rule}\n")
    s.redirect(f"{A}{first}", hop)
    s.page(f"{A}{hop}")
    f = _fetcher(tmp_path, s)
    with pytest.raises(RobotsDisallowed) as caught:
        _fetch(f, f"{A}{first}")
    assert record_text(caught.value, typed=False).endswith(_NOTE)
    assert s.fetched == [f"{A}/robots.txt", f"{A}{first}"]


def test_a_query_only_hop_that_robots_allows_is_followed_with_no_new_read(tmp_path):
    s = _Session()
    s.robots(A, "User-agent: *\nDisallow: /page?private\n")
    s.redirect(f"{A}/page?a=1", "/page?b=2")
    s.page(f"{A}/page?b=2")
    f = _fetcher(tmp_path, s)
    calls = _spy_robots_checks(f)
    assert _fetch(f, f"{A}/page?a=1").final_url == f"{A}/page?b=2"
    assert s.fetched == [f"{A}/robots.txt", f"{A}/page?a=1", f"{A}/page?b=2"]
    assert calls == [(f"{A}/page?a=1", False), (f"{A}/page?b=2", True)]  # checked, from the cache


def test_a_hop_to_the_same_robots_key_and_target_is_not_checked_again(tmp_path):
    """Only the fragment differs (it is never sent): the same decision, so no robots check is taken for the hop."""
    s = _Session()
    s.robots(A, _ALLOW_ALL)
    s.redirect(f"{A}/x", f"{A}/x#top")
    s.page(f"{A}/x#top")
    f = _fetcher(tmp_path, s)
    calls = _spy_robots_checks(f)
    assert _fetch(f, f"{A}/x").status_code == 200
    assert calls == [(f"{A}/x", False)]


def test_robots_target_reads_the_key_path_params_and_query_and_leaves_the_fragment_out():
    t = EthicalFetcher._robots_target
    assert t("https://u:p@A.Example:443/p;q?r=1#f") == ("https://a.example", "/p;q?r=1")
    assert t("http://a.example/p") != t("https://a.example/p")
    assert t("https://a.example/p?x") != t("https://a.example/p?y")
    assert t("https://a.example/p#one") == t("https://a.example/p#two")


@pytest.mark.parametrize(
    ("start", "location", "hop", "hosts", "keys"),
    [
        (f"{H}/x", "https://A.Example:443/x", "https://A.Example:443/x", {"a.example"}, {H, A}),
        ("https://alice:hunter2@a.example/feed", "/feed/", "https://alice:hunter2@a.example/feed/", {"a.example"}, {A}),
        (f"{A}/x", "https://B.Example:443/y", "https://B.Example:443/y", {"a.example", "b.example"}, {A, B}),
    ],
    ids=["mixed-case-upgrade", "login-same-host", "mixed-case-other-host"],
)
def test_a_hops_robots_read_is_keyed_and_circuit_named_on_the_host_key(tmp_path, start, location, hop, hosts, keys):
    """The independent read's N2: a hop's robots.txt is read under the host key (``_host_netloc``: the host as urllib.parse reads it,
    lower-cased, no default port, no login), and its Tor circuit is named on that key too, never on the netloc as the Location wrote
    it. A circuit named on ``alice:hunter2@a.example`` or ``A.Example:443`` is another circuit for the same host, and a login in it goes
    to the proxy. The login case pops the cached entry as the first request is answered, so the same-host hop reads robots.txt again."""
    s = _Session()
    s.redirect(start, location)
    s.page(hop)
    f = _fetcher(tmp_path, s)
    if "@" in start:
        s.on[start] = lambda: f._robots.pop(A, None)
    names: list = []
    real = f._isolated_proxies

    def spy(netloc):
        names.append(netloc)
        return real(netloc)

    f._isolated_proxies = spy  # type: ignore[method-assign]
    assert _fetch(f, start).final_url == hop
    assert set(names) == hosts, names
    assert set(f._robots) == keys
    assert {urlsplit(u).netloc for u in s.robots_reads()} == hosts
    assert len(s.robots_reads()) == (2 if "@" in start else len(keys))


# --- the interval: an allowed same-host hop is not slowed by a second one ------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "location"),
    [(f"{A}/x", "/y"), (f"{H}/x", f"{A}/x"), (f"{A}/p?a=1", "/p?b=2")],
    ids=["new-path", "upgrade", "query-only"],
)
def test_an_allowed_same_host_hop_waits_no_second_interval(tmp_path, start, location):
    events: list = []
    s, clock = _Session(events), _Clock(events)
    s.robots(H, _ALLOW_ALL)
    s.robots(A, _ALLOW_ALL)
    s.page(f"{A}/0")
    s.redirect(start, location)
    target = location if location.startswith("http") else f"{A}{location}"
    s.page(target)
    f = _fetcher(tmp_path, s, interval=5.0, clock=clock)
    _fetch(f, f"{A}/0")
    clock.t += 1.0
    assert _fetch(f, start).final_url == target
    assert clock.slept == [4.0]  # the first request's interval left on a.example, once; the hop waits nothing more
    tail = events[events.index(("get", start)):]
    assert ("sleep", 4.0) not in tail, tail
    assert f._last_request["a.example"] == 1005.0  # one stamp, when the host's last request was answered


def test_a_same_host_hop_waits_no_second_crawl_delay(tmp_path):
    events: list = []
    s, clock = _Session(events), _Clock(events)
    for origin in (H, A):
        s.robots(origin, "User-agent: *\nCrawl-delay: 7\n")
    s.page(f"{H}/0")
    s.redirect(f"{H}/x", f"{A}/x", status=301)
    s.page(f"{A}/x")
    f = _fetcher(tmp_path, s, clock=clock)
    _fetch(f, f"{H}/0")
    assert _fetch(f, f"{H}/x").final_url == f"{A}/x"
    assert clock.slept == [7.0]


@pytest.mark.parametrize(("start", "location"), [(f"{H}/x", f"{A}/x"), (f"{A}/x", "/y")], ids=["upgrade", "new-path"])
def test_a_same_host_hop_on_first_contact_with_a_crawl_delay_waits_no_second_delay(tmp_path, start, location):
    """The independent read's S1: on first contact with a host that declares a Crawl-delay, the first request's wait stamps the host's
    schedule (host_schedule.json) before the request is made, so a second wait taken for the hop would owe the whole delay (their probe:
    7.0 s against 0). The hop waits nothing; so does the first request, since nothing was asked of the host before it."""
    events: list = []
    s, clock = _Session(events), _Clock(events)
    for origin in (H, A):
        s.robots(origin, "User-agent: *\nCrawl-delay: 7\n")
    s.redirect(start, location, status=301)
    target = location if location.startswith("http") else f"{A}{location}"
    s.page(target)
    f = _fetcher(tmp_path, s, clock=clock)
    assert _fetch(f, start).final_url == target
    assert clock.slept == []


def test_a_retry_rechecks_its_hop_from_the_cache_and_reads_robots_once(tmp_path):
    s = _Session()
    s.robots(A, "User-agent: *\nDisallow: /private\n")
    s.redirect(f"{A}/x", "/y")
    once = {"n": 0}

    def busy_once():
        once["n"] += 1
        s.page(f"{A}/y", status=503 if once["n"] == 1 else 200)

    s.on[f"{A}/y"] = busy_once
    f = _fetcher(tmp_path, s, max_retries=1)
    calls = _spy_robots_checks(f)
    assert _fetch(f, f"{A}/x").status_code == 200
    assert s.fetched == [f"{A}/robots.txt", f"{A}/x", f"{A}/y", f"{A}/x", f"{A}/y"]
    assert calls == [(f"{A}/x", False), (f"{A}/y", True), (f"{A}/y", True)]


# --- controls: what R629 and the fetcher already did stays as it was ------------------------------------------------------------------


def test_a_hop_the_redirect_bound_will_not_request_reads_no_robots(tmp_path):
    """Five same-host hops (each checked from the cache), then a sixth Location to https: never requested, so no https read."""
    s = _Session()
    for n in range(5):
        s.redirect(f"{H}/r{n}", f"{H}/r{n + 1}")
    s.redirect(f"{H}/r5", f"{A}/x")
    s.page(f"{A}/x")
    f = _fetcher(tmp_path, s)
    with pytest.raises(FetchFailed) as caught:
        _fetch(f, f"{H}/r0")
    assert record_text(caught.value, typed=False).startswith("too many redirects for ")
    assert s.robots_reads() == [f"{H}/robots.txt"]


def test_a_fetcher_that_reads_no_robots_still_reads_none_on_a_same_host_hop(tmp_path):
    s = _Session()
    s.robots(A, _DISALLOW_ALL)
    s.redirect(f"{H}/x", f"{A}/private", status=301)
    s.page(f"{A}/private")
    f = _fetcher(tmp_path, s, respect_robots=False)
    assert _fetch(f, f"{H}/x").final_url == f"{A}/private"
    assert s.robots_reads() == []


def test_a_hop_to_another_host_still_reads_its_robots_once_and_waits_its_interval(tmp_path):
    events: list = []
    s, clock = _Session(events), _Clock(events)
    s.page(f"{B}/first")
    s.redirect(f"{A}/start", f"{B}/page")
    s.page(f"{B}/page")
    f = _fetcher(tmp_path, s, interval=2.0, clock=clock)
    calls = _spy_robots_checks(f)
    _fetch(f, f"{B}/first")
    clock.t += 0.5
    assert _fetch(f, f"{A}/start").final_url == f"{B}/page"
    assert clock.slept == [1.5]
    assert s.robots_reads() == [f"{B}/robots.txt", f"{A}/robots.txt"]
    assert calls == [(f"{B}/first", False), (f"{A}/start", False), (f"{B}/page", True)]  # once, not again as a same-host check


def test_a_robots_reads_own_same_host_hop_is_not_robots_checked(tmp_path):
    """No recursion: a robots read that redirects to another path on its own host follows it with no robots check of the hop."""
    s = _Session()
    s.redirect(f"{A}/robots.txt", "/robots-v2.txt")
    s.page(f"{A}/robots-v2.txt", "User-agent: *\nDisallow: /robots-v2.txt\n", content_type="text/plain")
    s.page(f"{A}/page")
    f = _fetcher(tmp_path, s)
    assert _fetch(f, f"{A}/page").status_code == 200
    assert s.fetched == [f"{A}/robots.txt", f"{A}/robots-v2.txt", f"{A}/page"]


def test_a_stop_pressed_while_the_upgrades_robots_is_read_is_not_cached_as_the_hosts_failure(tmp_path):
    s = _Session()
    s.robots(H, _ALLOW_ALL)
    s.redirect(f"{H}/x", f"{A}/x", status=301)
    s.page(f"{A}/x")

    def stop_then_cut():
        activate_kill_switch()
        raise requests.ConnectionError("cut off by the socket guard")

    s.on[f"{A}/robots.txt"] = stop_then_cut
    f = _fetcher(tmp_path, s)
    with pytest.raises(FetchFailed) as caught:
        _fetch(f, f"{H}/x")
    assert not isinstance(caught.value, RobotsUnavailable)
    assert record_text(caught.value, typed=False) == KILL_SWITCH_REFUSAL
    assert f"{A}/x" not in s.fetched
    assert A not in f._robots and A not in f._robots_fails  # nothing remembered: the next fetch asks again (R297)
    _no_lock_held(f, "a.example")


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


def _real_fetcher(tmp_path, monkeypatch, routes: dict, asked: list, on: dict) -> EthicalFetcher:
    """A fetcher on a REAL requests.Session whose transport answers in memory, every host resolving to one public address."""
    for var in {*_PROXY_VARS, *(v for v in os.environ if v.lower().endswith("_proxy"))}:
        monkeypatch.delenv(var, raising=False)
    f = EthicalFetcher(min_interval_s=0, retry_backoff_s=0, max_retries=0, robots_cache_path=tmp_path / "robots_cache.json")
    adapter = _MemoryAdapter(routes, asked, on)
    f.session.mount("https://", adapter)
    f.session.mount("http://", adapter)
    f._resolve_cached = lambda host: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0))]  # type: ignore[method-assign]
    assert f._real_session
    return f


def _pressed_and_cleared():
    activate_kill_switch()
    clear_kill_switch()


def _on_call(n: int, fn):
    """A hook that runs ``fn`` on the ``n``-th request to its URL only (the fetcher's read of a robots.txt the preflight read first)."""
    seen = [0]

    def hook():
        seen[0] += 1
        if seen[0] == n:
            fn()

    return hook


_ROBOTS_200 = (200, {"Content-Type": "text/plain"}, _ALLOW_ALL.encode())
_PAGE_200 = (200, {}, _html().encode())
_STOPS = pytest.mark.parametrize("stop", [activate_kill_switch, _pressed_and_cleared], ids=["engaged", "pressed-and-cleared"])


def test_a_stop_pressed_as_the_first_host_answers_refuses_an_upgrade_before_its_robots_read(tmp_path, monkeypatch):
    """On a real session the hop's own guard reads the switch (where R629 placed the reads): no https robots.txt is asked."""
    routes = {f"{H}/x": (301, {"Location": f"{A}/x"}, b""), f"{A}/x": (200, {}, _html().encode())}
    asked: list[str] = []
    f = _real_fetcher(tmp_path, monkeypatch, routes, asked, {f"{H}/x": activate_kill_switch})
    with pytest.raises(FetchFailed) as caught:
        _fetch(f, f"{H}/x")
    assert record_text(caught.value, typed=False) == KILL_SWITCH_REFUSAL
    assert asked == [f"{H}/robots.txt", f"{H}/x"]
    _no_lock_held(f, "a.example")


@_STOPS
def test_a_stop_pressed_while_an_upgrades_robots_is_read_refuses_the_hop_when_the_read_allows_it(tmp_path, monkeypatch, stop):
    """The independent read's M1, on the page fetch: the hop's last switch read was its guard's, before its robots read, and its
    request may go out on a pooled keep-alive connection, which opens no socket for the airplane guard to see. A Stop pressed while the
    https robots.txt is read (it answers 200 and allows the page) refuses the hop, and so does one pressed and cleared again (R614)."""
    routes = {f"{H}/robots.txt": _ROBOTS_200, f"{H}/x": (301, {"Location": f"{A}/x"}, b""), f"{A}/robots.txt": _ROBOTS_200,
              f"{A}/x": _PAGE_200}
    asked: list[str] = []
    f = _real_fetcher(tmp_path, monkeypatch, routes, asked, {f"{A}/robots.txt": stop})
    with pytest.raises(FetchFailed) as caught:
        _fetch(f, f"{H}/x")
    assert record_text(caught.value, typed=False) == KILL_SWITCH_REFUSAL
    assert asked == [f"{H}/robots.txt", f"{H}/x", f"{A}/robots.txt"]
    _no_lock_held(f, "a.example")


@_STOPS
def test_a_stop_pressed_while_an_upgrades_robots_is_read_refuses_the_hop_on_an_injected_session_too(tmp_path, stop):
    s = _Session()
    s.robots(H, _ALLOW_ALL)
    s.robots(A, _ALLOW_ALL)
    s.redirect(f"{H}/x", f"{A}/x", status=301)
    s.page(f"{A}/x")
    s.on[f"{A}/robots.txt"] = stop
    f = _fetcher(tmp_path, s)
    with pytest.raises(FetchFailed) as caught:
        _fetch(f, f"{H}/x")
    assert record_text(caught.value, typed=False) == KILL_SWITCH_REFUSAL
    assert f"{A}/x" not in s.fetched


@_STOPS
def test_a_stop_pressed_while_another_hosts_robots_is_read_refuses_the_hop(tmp_path, monkeypatch, stop):
    """The re-read of the fold: R629's other-host branch read the switch again after its robots read and its waits, but without the
    epoch, so a Stop pressed and cleared again while b.example's robots.txt was read (it answers 200 and allows the page) let the hop
    out. The epoch is now taken before that branch's first read (R614)."""
    routes = {f"{A}/robots.txt": _ROBOTS_200, f"{A}/x": (302, {"Location": f"{B}/y"}, b""), f"{B}/robots.txt": _ROBOTS_200,
              f"{B}/y": _PAGE_200}
    asked: list[str] = []
    f = _real_fetcher(tmp_path, monkeypatch, routes, asked, {f"{B}/robots.txt": stop})
    with pytest.raises(FetchFailed) as caught:
        _fetch(f, f"{A}/x")
    assert record_text(caught.value, typed=False) == KILL_SWITCH_REFUSAL
    assert asked == [f"{A}/robots.txt", f"{A}/x", f"{B}/robots.txt"]
    _no_lock_held(f, "a.example")
    _no_lock_held(f, "b.example")


@_STOPS
def test_a_stop_pressed_while_another_hosts_robots_is_read_refuses_the_hop_on_an_injected_session_too(tmp_path, stop):
    s = _Session()
    s.robots(A, _ALLOW_ALL)
    s.robots(B, _ALLOW_ALL)
    s.redirect(f"{A}/x", f"{B}/y")
    s.page(f"{B}/y")
    s.on[f"{B}/robots.txt"] = stop
    f = _fetcher(tmp_path, s)
    with pytest.raises(FetchFailed) as caught:
        _fetch(f, f"{A}/x")
    assert record_text(caught.value, typed=False) == KILL_SWITCH_REFUSAL
    assert f"{B}/y" not in s.fetched


@_STOPS
def test_a_stop_pressed_while_the_hop_takes_another_hosts_lock_refuses_the_hop(tmp_path, monkeypatch, stop):
    """The same branch: its first read comes before the lock handover, which may wait on another fetch of b.example, so the epoch is
    taken before that read, not after the handover."""
    import src.ingest as ingest

    real_move = ingest._RedirectChain.move

    def move(chain, key):
        stop()
        return real_move(chain, key)

    monkeypatch.setattr(ingest._RedirectChain, "move", move)
    s = _Session()
    s.robots(A, _ALLOW_ALL)
    s.robots(B, _ALLOW_ALL)
    s.redirect(f"{A}/x", f"{B}/y")
    s.page(f"{B}/y")
    f = _fetcher(tmp_path, s)
    with pytest.raises(FetchFailed) as caught:
        _fetch(f, f"{A}/x")
    assert record_text(caught.value, typed=False) == KILL_SWITCH_REFUSAL
    assert f"{B}/y" not in s.fetched
    _no_lock_held(f, "a.example", "b.example")


@_STOPS
@pytest.mark.parametrize(
    ("location", "hop", "robots", "nth"),
    [(f"{B}/", f"{B}/", f"{B}/robots.txt", 1), ("/en/", f"{A}/en/", f"{A}/robots.txt", 2)],
    ids=["other-host", "same-host-cold-cache"],
)
def test_a_stop_pressed_while_a_ping_hops_robots_is_read_is_skipped_offline_and_the_hop_never_asked(
    tmp_path, monkeypatch, stop, location, hop, robots, nth
):
    """M1 on the homepage ping: the hop's robots.txt answers 200 and allows it, and a Stop pressed inside that read (engaged, or pressed
    and cleared again) refuses the hop, recorded as skipped_offline. On the same host the fetcher's cache is cold, so its read is the
    second request to a.example/robots.txt (the preflight's own read is the first)."""
    routes = {f"{A}/robots.txt": _ROBOTS_200, f"{A}/": (302, {"Location": location}, b""), robots: _ROBOTS_200, hop: _PAGE_200}
    asked: list[str] = []
    f = _real_fetcher(tmp_path, monkeypatch, routes, asked, {robots: _on_call(nth, stop)})
    rec = _ping(f)
    assert rec["verdict"] == "skipped_offline" and rec["skipped_offline"] is True and rec["reachable"] is None
    assert rec["refusal"] == KILL_SWITCH_REFUSAL and "homepage_skipped" not in rec
    assert asked == [f"{A}/robots.txt", f"{A}/", robots]


# --- what callers see -----------------------------------------------------------------------------------------------------------------


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="Good", domain="good.example", language="en", enabled=True))
    s.commit()
    yield s
    s.close()


@pytest.fixture()
def source(db):
    return db.query(Source).first()


G = "https://good.example"
OK = "https://ok.example"


@pytest.mark.parametrize(
    ("robots", "status", "outcome"),
    [("User-agent: *\nDisallow: /private\n", 200, IngestResult.BLOCKED_ROBOTS), ("", 403, IngestResult.ROBOTS_UNAVAILABLE)],
)
def test_ingest_files_a_refused_same_host_hop_in_the_robots_buckets(db, source, tmp_path, robots, status, outcome):
    s = _Session()
    s.robots("http://good.example", _ALLOW_ALL)
    s.robots(G, robots, status=status)
    s.redirect("http://good.example/a", f"{G}/private", status=301)
    s.page(f"{G}/private")
    out = _bounded(lambda: ingest_url(db, source, "http://good.example/a", fetcher=_fetcher(tmp_path, s)))
    assert out.result is outcome
    assert (out.detail or "").endswith(_NOTE), out.detail
    assert f"{G}/private" not in s.fetched and db.query(Article).count() == 0


def test_a_crawl_does_not_store_an_on_site_link_that_redirects_to_a_disallowed_path(db, source, tmp_path):
    s = _Session()
    s.robots(G, "User-agent: *\nDisallow: /members\n")
    s.page(G, _html("Front", "The front page of a good site.", links=["/story"]))
    s.redirect(f"{G}/story", "/members/story")
    s.page(f"{G}/members/story", _html("Members", "A story behind a path the site asks robots to leave alone."))
    report = _bounded(lambda: crawl_source(db, source, fetcher=_fetcher(tmp_path, s), config=CrawlConfig(max_depth=1, max_pages=10)))
    assert f"{G}/members/story" not in s.fetched
    assert report.tally[IngestResult.BLOCKED_ROBOTS.value] == 1
    assert not db.query(Article).filter(Article.url.contains("members")).count()


# --- the preflight's homepage ping obeys robots.txt -----------------------------------------------------------------------------------


def test_the_ping_is_not_made_when_robots_disallows_the_homepage(tmp_path):
    s = _Session()
    s.robots(A, _DISALLOW_ALL)
    s.page(f"{A}/")
    rec = _ping(_fetcher(tmp_path, s))
    assert s.fetched == [f"{A}/robots.txt"]
    assert rec["homepage_skipped"] == _SKIPPED_DISALLOWED
    assert rec["robots"] == "disallowed" and rec["verdict"] == "robots_denied"
    assert rec["reachable"] is None and "homepage_status" not in rec and "homepage_error" not in rec


@pytest.mark.parametrize(
    ("answer", "robots", "verdict"),
    [
        (403, "blocked", "robots_denied"),
        (401, "blocked", "robots_denied"),
        (500, "http_500", "unreachable"),
        (503, "http_503", "unreachable"),
        (204, "http_204", "unreachable"),
        ("raise", "unreachable", "unreachable"),
    ],
)
def test_the_ping_is_not_made_when_robots_cannot_be_read(tmp_path, answer, robots, verdict):
    s = _Session()
    s.page(f"{A}/")
    if answer == "raise":

        def boom():
            raise requests.ConnectionError("connection refused")

        s.on[f"{A}/robots.txt"] = boom
    else:
        s.robots(A, "", status=answer)
    rec = _ping(_fetcher(tmp_path, s))
    assert s.fetched == [f"{A}/robots.txt"]
    assert rec["homepage_skipped"] == _SKIPPED_UNREADABLE
    assert rec["robots"] == robots and rec["verdict"] == verdict  # the verdict is the one the base gave: only the ping is gone
    assert rec["reachable"] is None and "homepage_status" not in rec


@pytest.mark.parametrize(
    ("robots", "status", "state"),
    [(_ALLOW_ALL, 200, "allowed"), ("User-agent: *\nDisallow: /private\n", 200, "allowed"), ("", 404, "missing"), ("", 410, "missing")],
)
def test_the_ping_is_made_when_robots_allows_the_homepage_or_is_missing(tmp_path, robots, status, state):
    s = _Session()
    s.robots(A, robots, status=status)
    s.page(f"{A}/")
    rec = _ping(_fetcher(tmp_path, s))
    assert s.fetched == [f"{A}/robots.txt", f"{A}/"]
    assert rec["robots"] == state and rec["homepage_status"] == 200 and rec["reachable"] is True and rec["verdict"] == "ok"
    assert "homepage_skipped" not in rec


def test_the_skip_words_are_fixed_whatever_the_host(tmp_path):
    words = set()
    for domain in ("a.example", "b.example"):
        (tmp_path / domain).mkdir()
        s = _Session()
        s.robots(f"https://{domain}", _DISALLOW_ALL)
        words.add(_ping(_fetcher(tmp_path / domain, s), domain)["homepage_skipped"])
    assert words == {_SKIPPED_DISALLOWED}


def test_the_pings_hop_to_a_disallowed_path_on_its_host_is_not_followed(tmp_path):
    s = _Session()
    s.robots(A, "User-agent: *\nDisallow: /en/\n")
    s.redirect(f"{A}/", "/en/")
    s.page(f"{A}/en/")
    rec = _ping(_fetcher(tmp_path, s))
    # the preflight's own read, the homepage, then the fetcher's read for the hop (its cache is the one a scrape uses)
    assert s.fetched == [f"{A}/robots.txt", f"{A}/", f"{A}/robots.txt"]
    assert rec["homepage_skipped"] == _HOP_DISALLOWED
    # reachable (it answered with a redirect), its own robots.txt allowed it, and the verdict is not "ok": where it sends a crawler is
    # off-limits (steward 3's low 1)
    assert rec["reachable"] is True and rec["robots"] == "allowed" and rec["verdict"] == "robots_denied"
    assert "homepage_status" not in rec and "homepage_error" not in rec


@pytest.mark.parametrize(
    ("answer", "words", "verdict"),
    [
        (_DISALLOW_ALL, _HOP_DISALLOWED, "robots_denied"),
        (403, _HOP_UNREADABLE, "unreachable"),
        (401, _HOP_UNREADABLE, "unreachable"),
        (500, _HOP_UNREADABLE, "unreachable"),
        ("raise", _HOP_UNREADABLE, "unreachable"),
    ],
    ids=["disallow", "403", "401", "500", "raise"],
)
def test_the_pings_hop_to_another_host_is_robots_checked(tmp_path, answer, words, verdict):
    """A hop RobotsDisallowed refuses is "robots_denied"; one RobotsUnavailable refuses (its robots.txt answered 401/403 or 5xx, or
    nothing) is "unreachable", as the fetcher files a 401/403 robots.txt as "refused", never as a policy (steward 3's low 1). The
    homepage's own robots.txt (none, here) stays the record's ``robots``."""
    s = _Session()
    s.redirect(f"{A}/", f"{B}/")
    s.page(f"{B}/")
    if answer == "raise":

        def boom():
            raise requests.ConnectionError("connection refused")

        s.on[f"{B}/robots.txt"] = boom
    elif isinstance(answer, int):
        s.robots(B, "", status=answer)
    else:
        s.robots(B, answer)
    rec = _ping(_fetcher(tmp_path, s))
    assert s.fetched == [f"{A}/robots.txt", f"{A}/", f"{B}/robots.txt"]
    assert rec["homepage_skipped"] == words and rec["reachable"] is True
    assert rec["verdict"] == verdict and rec["robots"] == "missing"


def test_the_pings_hop_to_the_other_scheme_reads_that_schemes_robots(tmp_path):
    """The ping asks https://domain/ itself; a hop to http on the same host reads the http robots.txt, which disallows it."""
    s = _Session()
    s.robots(H, _DISALLOW_ALL)
    s.redirect(f"{A}/", f"{H}/")
    s.page(f"{H}/")
    rec = _ping(_fetcher(tmp_path, s))
    assert s.fetched == [f"{A}/robots.txt", f"{A}/", f"{H}/robots.txt"]
    assert rec["homepage_skipped"] == _HOP_DISALLOWED and rec["verdict"] == "robots_denied"


def test_the_pings_allowed_hop_is_followed_and_takes_no_lock_and_no_wait(tmp_path):
    events: list = []
    s, clock = _Session(events), _Clock(events)
    s.redirect(f"{A}/", f"{B}/")
    s.page(f"{B}/")
    f = _fetcher(tmp_path, s, interval=5.0, clock=clock)
    held: list[bool] = []
    s.on[f"{B}/"] = lambda: held.append(f._host_lock("b.example").locked() or f._host_lock("a.example").locked())
    rec = _ping(f)
    assert rec["homepage_status"] == 200 and "homepage_skipped" not in rec
    assert s.fetched == [f"{A}/robots.txt", f"{A}/", f"{B}/robots.txt", f"{B}/"]
    assert held == [False] and clock.slept == []


def test_the_pings_own_robots_txt_that_redirects_off_the_host_is_followed_without_a_robots_read_there(tmp_path):
    s = _Session()
    s.redirect(f"{A}/robots.txt", f"{C}/rules.txt")
    s.page(f"{C}/rules.txt", _DISALLOW_ALL, content_type="text/plain")
    s.page(f"{A}/")
    rec = _ping(_fetcher(tmp_path, s))
    assert s.fetched == [f"{A}/robots.txt", f"{C}/rules.txt"]  # no c.example robots.txt (no recursion), and no ping
    assert rec["robots"] == "disallowed" and rec["homepage_skipped"] == _SKIPPED_DISALLOWED


def test_a_stop_during_the_pings_hop_robots_read_is_skipped_offline_not_a_skipped_ping(tmp_path):
    s = _Session()
    s.redirect(f"{A}/", f"{B}/")
    s.page(f"{B}/")

    def stop_then_cut():
        activate_kill_switch()
        raise requests.ConnectionError("cut off by the socket guard")

    s.on[f"{B}/robots.txt"] = stop_then_cut
    rec = _ping(_fetcher(tmp_path, s))
    assert rec["verdict"] == "skipped_offline" and rec["skipped_offline"] is True
    assert "homepage_skipped" not in rec and f"{B}/" not in s.fetched


def test_the_feed_preflights_robots_read_that_redirects_reads_no_robots_on_its_hop(tmp_path):
    """feed_preflight.py's own read (a robots read, never a ping): its hop is followed with no robots.txt read there."""
    s = _Session()
    s.redirect(f"{A}/robots.txt", f"{C}/rules.txt")
    s.page(f"{C}/rules.txt", _DISALLOW_ALL, content_type="text/plain")
    rec = _bounded(lambda: _check_host_robots(_fetcher(tmp_path, s), "a.example"))
    assert rec["robots"] == "disallowed"
    assert s.fetched == [f"{A}/robots.txt", f"{C}/rules.txt"]


def test_a_sweep_logs_the_skipped_ping_and_keeps_the_learned_verdicts(db, tmp_path, monkeypatch):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    db.add(Source(name="Ok", domain="ok.example", language="en", enabled=True))
    db.commit()
    s = _Session()
    s.robots(G, _DISALLOW_ALL)
    s.page(f"{G}/")
    s.robots(OK, _ALLOW_ALL)
    s.page(f"{OK}/")
    summary = _bounded(lambda: preflight.preflight_sources(db, _fetcher(tmp_path, s), limit=10))
    assert summary["complete"] is True and summary["robots_denied"] == ["good.example"] and summary["ok"] == 1
    assert f"{G}/" not in s.fetched and f"{OK}/" in s.fetched
    rows = {r["domain"]: r for r in preflight.recent_results()}
    assert rows["good.example"]["homepage_skipped"] == _SKIPPED_DISALLOWED and rows["good.example"]["reachable"] is None
    assert "homepage_skipped" not in rows["ok.example"]
    good = db.query(Source).filter_by(domain="good.example").one()
    assert db.query(SourceMetadata).filter_by(source_id=good.id).one().robots_allowed is False


def test_a_sweep_counts_a_refused_ping_hop_as_its_verdict_and_records_the_homepages_own_robots(db, tmp_path, monkeypatch):
    """Steward 3's low 1, through the whole sweep: a ping whose hop robots.txt disallows is counted in ``robots_denied``, one whose hop
    robots.txt cannot be read in ``unreachable``, and neither as ``ok``. ``robots_allowed`` follows the record's ``robots``, which is
    the source's own robots.txt read for its homepage, so it is True for both: what that robots.txt allows is what was learned."""
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    for name in ("ok", "un"):
        db.add(Source(name=name, domain=f"{name}.example", language="en", enabled=True))
    db.commit()
    s = _Session()
    s.robots(G, "User-agent: *\nDisallow: /en/\n")
    s.redirect(f"{G}/", "/en/")
    s.page(f"{G}/en/")
    s.page(f"{OK}/")
    s.redirect("https://un.example/", f"{B}/")
    s.robots(B, "", status=500)
    s.page(f"{B}/")
    summary = _bounded(lambda: preflight.preflight_sources(db, _fetcher(tmp_path, s), limit=10))
    assert summary["complete"] is True and summary["checked"] == 3
    assert summary["ok"] == 1 and summary["robots_denied"] == ["good.example"] and summary["unreachable"] == ["un.example"]
    assert f"{G}/en/" not in s.fetched and f"{B}/" not in s.fetched
    rows = {r["domain"]: r for r in preflight.recent_results()}
    assert rows["good.example"]["homepage_skipped"] == _HOP_DISALLOWED and rows["good.example"]["robots"] == "allowed"
    assert rows["un.example"]["homepage_skipped"] == _HOP_UNREADABLE and rows["un.example"]["robots"] == "missing"
    assert rows["good.example"]["reachable"] is True and rows["un.example"]["reachable"] is True
    for domain in ("good.example", "ok.example", "un.example"):
        src = db.query(Source).filter_by(domain=domain).one()
        assert db.query(SourceMetadata).filter_by(source_id=src.id).one().robots_allowed is True, domain


def test_a_refusal_of_the_pings_hop_while_the_switch_is_engaged_is_skipped_offline(tmp_path):
    """The preflight's rule for a check that fails while the switch is engaged (it is read as the switch's) holds for a robots
    refusal of the ping's hop too: the hop's robots.txt answers 500 as the Stop is pressed."""
    s = _Session()
    s.redirect(f"{A}/", f"{B}/")
    s.page(f"{B}/")
    s.robots(B, "", status=500)
    s.on[f"{B}/robots.txt"] = activate_kill_switch
    rec = _ping(_fetcher(tmp_path, s))
    assert rec["verdict"] == "skipped_offline" and "homepage_skipped" not in rec
    assert f"{B}/" not in s.fetched


def test_a_ping_hop_the_redirect_bound_will_not_request_reads_no_robots(tmp_path):
    """Five same-host hops (checked: the fetcher's own read of a.example's robots.txt, once, then its cache), then a sixth Location to
    another host, never requested: no robots.txt is read there, and the ping fails as too many redirects, as before."""
    s = _Session()
    s.redirect(f"{A}/", "/r1")
    for n in range(1, 5):
        s.redirect(f"{A}/r{n}", f"/r{n + 1}")
    s.redirect(f"{A}/r5", f"{B}/x")
    s.page(f"{B}/x")
    rec = _ping(_fetcher(tmp_path, s))
    assert [u for u in s.fetched if urlsplit(u).hostname == "b.example"] == []
    assert s.robots_reads() == [f"{A}/robots.txt", f"{A}/robots.txt"]  # the preflight's own read, then the fetcher's
    assert rec["reachable"] is False and rec["homepage_error"].startswith("too many redirects for ")
    assert "homepage_skipped" not in rec


def test_an_upgrade_waits_no_crawl_delay_that_only_its_https_robots_declares(tmp_path):
    """The interval rule is per host and unchanged (R636 adds robots only): the chain's wait is the first request's, read from the
    first address's robots.txt, so a longer Crawl-delay declared only in the https robots.txt is not waited on the upgrade hop. It
    governs the next request asked for over https, as before."""
    events: list = []
    s, clock = _Session(events), _Clock(events)
    s.robots(H, _ALLOW_ALL)
    s.robots(A, "User-agent: *\nCrawl-delay: 30\n")
    s.page(f"{H}/0")
    s.redirect(f"{H}/x", f"{A}/x", status=301)
    s.page(f"{A}/x")
    s.page(f"{A}/next")
    f = _fetcher(tmp_path, s, interval=1.0, clock=clock)
    _fetch(f, f"{H}/0")
    clock.t += 1.0
    assert _fetch(f, f"{H}/x").final_url == f"{A}/x"
    assert clock.slept == []
    _fetch(f, f"{A}/next")
    assert clock.slept == [30.0]


def test_a_same_host_hop_to_an_empty_path_and_a_query_is_checked_as_the_root(tmp_path):
    """R636's re-check goes through ``_enforce_robots``, which checks an empty path as the "/" requests asks for (R629's fold): a hop
    from /x to https://a.example?x is judged as /?x, which "Disallow: /" covers, where ``can_fetch`` alone reads "?x" and allows it."""
    s = _Session()
    s.robots(A, "User-agent: *\nAllow: /x\nDisallow: /\n")
    s.redirect(f"{A}/x", f"{A}?x")
    s.page(f"{A}?x")
    s.page(f"{A}/?x")
    f = _fetcher(tmp_path, s)
    with pytest.raises(RobotsDisallowed) as caught:
        _fetch(f, f"{A}/x")
    assert record_text(caught.value, typed=False) == f"robots.txt disallows {A}?x {_NOTE}"
    assert s.fetched == [f"{A}/robots.txt", f"{A}/x"]


# --- a ValueError while a hop's robots decision is taken again (Steward 3's note at the R622 rebase) --------------------------------


def _hop_robots_raises_value_error(f):
    real = f._enforce_robots

    def check(url, host_key, parsed, *, hop=False):
        if hop:
            raise ValueError("planted inside the hop's robots check")
        return real(url, host_key, parsed, hop=hop)

    f._enforce_robots = check  # type: ignore[method-assign]


def test_a_value_error_in_a_same_host_hops_robots_check_is_the_unreadable_redirect_failure(tmp_path):
    """Since R622, ``_recheck_hop_robots`` runs inside the redirect loop's outer ``except ValueError``. A ValueError raised while a
    same-host hop's robots decision is taken again is R622's FetchFailed, ``redirect to a URL that cannot be read, from <the URL
    that answered the redirect>``, raised with no context, and the hop is never requested. No real input is known to raise one
    there; this pins what the fetch says if one ever does."""
    s = _Session()
    s.robots(A, _ALLOW_ALL)
    s.redirect(f"{A}/x", f"{A}/y")
    s.page(f"{A}/y")
    f = _fetcher(tmp_path, s)
    _hop_robots_raises_value_error(f)
    with pytest.raises(FetchFailed) as caught:
        _fetch(f, f"{A}/x")
    assert type(caught.value) is FetchFailed
    assert str(caught.value) == f"redirect to a URL that cannot be read, from {A}/x"
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    assert f"{A}/y" not in s.fetched
    _no_lock_held(f, "a.example")


def test_a_value_error_in_the_ping_hops_robots_check_is_recorded_as_the_unreadable_redirect(tmp_path):
    """The homepage ping's hop takes the same check (``hop_robots``): a ValueError there is the same FetchFailed, which the ping
    records as its homepage error (unreachable, the hop never asked), never a bare ValueError out of the sweep."""
    s = _Session()
    s.robots(A, _ALLOW_ALL)
    s.redirect(f"{A}/", f"{A}/home")
    s.page(f"{A}/home")
    f = _fetcher(tmp_path, s)
    _hop_robots_raises_value_error(f)
    rec = _ping(f)
    assert rec["homepage_error"] == f"redirect to a URL that cannot be read, from {A}/"
    assert rec["reachable"] is False and rec["verdict"] == "unreachable"
    assert f"{A}/home" not in s.fetched
