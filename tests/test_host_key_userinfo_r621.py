"""
One robots entry, one schedule stamp, one interval per HOST, and a URL's userinfo kept out of the monitor and the logs (R621).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

R621's three parts, each against the real code:

1. The fetcher keyed every per-host record by ``scheme://netloc`` / ``netloc`` WITH the userinfo, so ``http://alice:hunter2@host/a``
   and ``http://host/b`` were two hosts: two robots.txt reads (the first one sending the credentials as Basic auth), two entries in
   robots.json and host_schedule.json (the user name and password written to disk), two politeness intervals, two locks, two Tor
   circuits (the credentials folded into the SOCKS user name). Now one of each, keyed by the host and port; an older build's
   credentialed keys leave both files when they load (the robots entry dropped, the schedule stamp merged into the host's).
2. ``ActivityMonitor.fetch_started`` kept the raw URL and its netloc, which ``/api/system/vitals`` (the top bar's
   ``_shortUrl(current_fetch.url)``) and the task manager's per-source rates serve. Both are masked now.
3. The URL log lines of ``services/duckduckgo.py``, ``utils/url_utils.py``, ``utils/security.py`` and
   ``services/link_analyzer/extractor.py`` write the URL through ``failure_url``.

Every case has its control: an ordinary URL comes out exactly as before. The credentials are fake (``alice:hunter2``). Nothing
leaves the machine: the network cases use a server on 127.0.0.1 (``_guard_target`` is stubbed on the instance and
``OO_SSRF_CONNECT_GUARD=0`` set, because both refuse 127.0.0.1 by design and here it stands in for a public host) or an injected
session that answers in memory.
"""

from __future__ import annotations

import contextlib
import http.server
import json
import logging
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

import src.ingest as ingest
from src.ingest import EthicalFetcher, FetchFailed, clear_kill_switch
from src.ingest.fetch_verdict import USERINFO_MASK
from src.monitoring.activity import ActivityMonitor

_USER, _PASSWORD = "alice", "hunter2"
_CRED = f"{_USER}:{_PASSWORD}@"
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy")


def _no_secret(text: str) -> None:
    assert _PASSWORD not in text and f"{_USER}:" not in text and _CRED not in text, text


@pytest.fixture(autouse=True)
def _offline_env(monkeypatch):
    for var in {*_PROXY_VARS, *(v for v in os.environ if v.lower().endswith("_proxy")), "OO_FETCH_MODE", "OO_HTTP_PROXY", "OO_HTTP_PROXIES"}:
        monkeypatch.delenv(var, raising=False)
    for var in ("OO_ROBOTS_CACHE_PERSIST", "OO_HOST_SCHEDULE_PERSIST", "OO_TOR_STREAM_ISOLATION"):
        monkeypatch.delenv(var, raising=False)
    clear_kill_switch()
    yield
    clear_kill_switch()


# --------------------------------------------------------------------------- #
# A loopback server and an in-memory session
# --------------------------------------------------------------------------- #


class _Handler(http.server.BaseHTTPRequestHandler):
    seen: list[tuple[str, str | None, str | None]]

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - the base class's name
        pass

    def do_GET(self) -> None:  # noqa: N802 - the base class's name
        self.seen.append((self.path, self.headers.get("Host"), self.headers.get("Authorization")))
        if self.path == "/robots.txt":
            body, ctype = b"User-agent: *\nCrawl-delay: 2\nSitemap: http://example.org/sitemap.xml\n", "text/plain"
        else:
            body, ctype = b"<p>ok</p>", "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextlib.contextmanager
def _server() -> Iterator[tuple[int, list]]:
    seen: list = []
    handler = type("Handler", (_Handler,), {"seen": seen})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, name="r621-loopback", daemon=True)
    t.start()
    try:
        yield srv.server_address[1], seen
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(5)


def _loopback_fetcher(tmp_path: Path, monkeypatch, **kw) -> EthicalFetcher:
    monkeypatch.setenv("OO_SSRF_CONNECT_GUARD", "0")
    f = EthicalFetcher(min_interval_s=0, retry_backoff_s=0, max_retries=0, robots_cache_path=tmp_path / "robots.json", **kw)
    f._guard_target = lambda *_a, **_k: None  # type: ignore[method-assign]  # the loopback server stands in for a public host
    f._sleep = lambda _s: None  # type: ignore[method-assign]
    return f


class _Resp:
    def __init__(self, url: str, status: int, body: bytes, ctype: str) -> None:
        self.url, self.status_code, self.content, self.text = url, status, body, body.decode()
        self.headers = {"Content-Type": ctype}

    def close(self) -> None:
        pass


class _Session:
    """An injected session: answers in memory and records every request it was handed."""

    def __init__(self, robots: bytes = b"User-agent: *\n") -> None:
        self.robots = robots
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, **kw):
        self.calls.append((url, kw))
        if url.endswith("/robots.txt"):
            return _Resp(url, 200, self.robots, "text/plain")
        return _Resp(url, 200, b"<p>ok</p>", "text/html")


def _stub_fetcher(tmp_path: Path, session: _Session | None = None, **kw) -> EthicalFetcher:
    kw.setdefault("min_interval_s", 0)
    return EthicalFetcher(session=session or _Session(), retry_backoff_s=0, max_retries=0, robots_cache_path=tmp_path / "robots.json", **kw)


# --------------------------------------------------------------------------- #
# 1. One entry per host
# --------------------------------------------------------------------------- #


def test_a_credentialed_and_a_plain_url_to_one_host_share_one_robots_entry_and_one_schedule_stamp(tmp_path, monkeypatch):
    with _server() as (port, seen):
        f = _loopback_fetcher(tmp_path, monkeypatch)
        f.fetch(f"http://{_CRED}127.0.0.1:{port}/a")
        f.fetch(f"http://127.0.0.1:{port}/b")
    host = f"127.0.0.1:{port}"
    robots = (tmp_path / "robots.json").read_text("utf-8")
    schedule = (tmp_path / "host_schedule.json").read_text("utf-8")
    assert list(json.loads(robots)) == [f"http://{host}"]
    assert list(json.loads(schedule)) == [host]
    _no_secret(robots)
    _no_secret(schedule)
    assert list(f._robots) == [f"http://{host}"]
    assert list(f._host_schedule) == [host]
    assert list(f._last_request) == [host]
    assert list(f._host_locks) == [host]
    assert [p for p, _h, _a in seen].count("/robots.txt") == 1, seen  # one read for the host, not one per userinfo


def test_the_robots_read_goes_to_the_page_urls_scheme_host_and_port_without_its_credentials(tmp_path, monkeypatch):
    with _server() as (port, seen):
        f = _loopback_fetcher(tmp_path, monkeypatch)
        f.fetch(f"http://{_CRED}127.0.0.1:{port}/a")
    robots = [(h, a) for p, h, a in seen if p == "/robots.txt"]
    page = [(h, a) for p, h, a in seen if p == "/a"]
    assert robots == [(f"127.0.0.1:{port}", None)], seen  # same host and port, no Authorization header
    # the page request itself is unchanged: requests still sends the URL's own credentials to the page
    assert page and page[0][0] == f"127.0.0.1:{port}" and page[0][1] and page[0][1].startswith("Basic ")


@pytest.mark.parametrize("url", [f"https://{_CRED}example.org:8443/x", f"http://{_CRED}example.org/x", f"https://{_USER}@example.org/x"])
def test_the_robots_url_keeps_the_scheme_host_and_port_of_the_page_url(tmp_path, url):
    from urllib.parse import urlparse

    s = _Session()
    _stub_fetcher(tmp_path, s).fetch(url)
    robots_url = s.calls[0][0]
    page, robots = urlparse(url), urlparse(robots_url)
    assert robots.path == "/robots.txt"
    assert (robots.scheme, robots.hostname, robots.port) == (page.scheme, page.hostname, page.port)
    assert robots.username is None and robots.password is None
    assert s.calls[1][0] == url  # the page is requested with the URL as given


def test_declared_sitemaps_reads_the_hosts_one_entry_without_the_credentials(tmp_path, monkeypatch):
    with _server() as (port, seen):
        f = _loopback_fetcher(tmp_path, monkeypatch)
        assert f.declared_sitemaps(f"http://{_CRED}127.0.0.1:{port}/") == ["http://example.org/sitemap.xml"]
        f.fetch(f"http://127.0.0.1:{port}/b")
    assert [(p, a) for p, _h, a in seen] == [("/robots.txt", None), ("/b", None)]
    assert list(json.loads((tmp_path / "robots.json").read_text("utf-8"))) == [f"http://127.0.0.1:{port}"]


def test_a_credentialed_and_a_plain_url_wait_out_one_politeness_interval(tmp_path):
    clock = [100.0]
    slept: list[float] = []
    f = _stub_fetcher(tmp_path, min_interval_s=5.0)
    f._now = lambda: clock[0]  # type: ignore[method-assign]
    f._sleep = slept.append  # type: ignore[method-assign]
    f.fetch(f"https://{_CRED}example.org/a")
    clock[0] = 101.0
    f.fetch("https://example.org/b")
    assert slept == [pytest.approx(4.0)]  # one host, one interval: the second fetch waits the rest of it


def test_a_credentialed_url_rides_the_hosts_own_circuit_and_names_no_credential_to_the_proxy(tmp_path):
    s = _Session()
    f = _stub_fetcher(tmp_path, s, proxy="socks5h://127.0.0.1:9050")
    f.fetch(f"https://{_CRED}example.org/a")
    f.fetch("https://example.org/b")
    proxies = [kw.get("proxies") for _u, kw in s.calls]
    assert len(proxies) == 3 and all(p == proxies[0] for p in proxies), proxies  # robots, /a, /b: one circuit
    assert proxies[0] and "example.org" in proxies[0]["https"]
    _no_secret(json.dumps(proxies))
    assert "alicehunter2" not in json.dumps(proxies)


def test_crawl_delay_for_and_forget_robots_find_the_hosts_one_entry_from_a_credentialed_url(tmp_path):
    f = _stub_fetcher(tmp_path, _Session(robots=b"User-agent: *\nCrawl-delay: 7\n"))
    f.fetch("https://example.org/a")
    assert f.crawl_delay_for(f"https://{_CRED}example.org/x") == 7.0
    assert f.crawl_delay_for(f"{_CRED}example.org") == 7.0
    assert f.forget_robots(f"https://{_CRED}example.org") == 1
    assert f._robots == {}


def test_the_persistence_failure_lines_name_the_host_and_not_its_credentials(tmp_path, monkeypatch, caplog):
    f = EthicalFetcher(session=_Session(robots=b"User-agent: *\nCrawl-delay: 2\n"), min_interval_s=0, retry_backoff_s=0, max_retries=0,
                       robots_cache_path=tmp_path / "missing" / "robots.json")  # the directory does not exist: both writes fail
    f._sleep = lambda _s: None  # type: ignore[method-assign]
    caplog.set_level(logging.DEBUG, logger="src.ingest")
    f.fetch(f"https://{_CRED}example.org/a")
    lines = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("robots cache persistence failed for https://example.org:") for m in lines), lines
    assert any(m.startswith("host schedule persistence failed for example.org:") for m in lines), lines
    _no_secret(caplog.text)


def test_the_clock_corrected_stamp_line_names_the_host_and_not_its_credentials(tmp_path, caplog):
    far = time.time() + 5000
    (tmp_path / "host_schedule.json").write_text(json.dumps({"example.org": {"not_before": far, "delay_s": 1.0}}), "utf-8")
    slept: list[float] = []
    f = _stub_fetcher(tmp_path, min_interval_s=1.0)
    f._sleep = slept.append  # type: ignore[method-assign]
    caplog.set_level(logging.INFO, logger="src.ingest")
    f.fetch(f"https://{_CRED}example.org/a")
    assert any(r.getMessage().startswith("politeness stamp for example.org lay ") for r in caplog.records), caplog.text
    assert slept == [pytest.approx(1.0)]  # the host's own stamp was found for the credentialed URL, clamped to its delay
    _no_secret(caplog.text)


def test_control_an_ordinary_url_keeps_its_keys(tmp_path):
    s = _Session()
    f = _stub_fetcher(tmp_path, s)
    f.fetch("https://example.org:8443/a")
    assert list(f._robots) == ["https://example.org:8443"]
    assert list(f._last_request) == ["example.org:8443"]
    assert [u for u, _kw in s.calls] == ["https://example.org:8443/robots.txt", "https://example.org:8443/a"]


# --------------------------------------------------------------------------- #
# 1b. An older build's credentialed keys, at load
# --------------------------------------------------------------------------- #


def _robots_entry(body: str = "User-agent: *\nDisallow: /p\n", **kw) -> dict:
    return {"kind": "parsed", "body": body, "fetched_at": time.time(), "cause": None, "fails": 0, "ttl": 3600.0, **kw}


def _old_robots(tmp_path: Path) -> tuple[Path, dict]:
    raw = {
        f"https://{_CRED}example.org": _robots_entry("User-agent: *\nDisallow: /\n"),
        "https://example.org": _robots_entry(),
        "https://other.example": {"kind": "disallow_all", "body": None, "fetched_at": time.time(), "cause": "refused", "fails": 2, "ttl": 7200.0},
        f"http://{_USER}@solo.example:8080": {"kind": "disallow_all", "body": None, "fetched_at": time.time(), "cause": "unreachable", "fails": 3, "ttl": 9000.0},
    }
    path = tmp_path / "robots.json"
    path.write_text(json.dumps(raw), "utf-8")
    return path, raw


def _old_schedule(tmp_path: Path) -> tuple[Path, float]:
    now = time.time()
    raw = {
        f"{_CRED}example.org": {"not_before": now + 500, "delay_s": 30.0},
        "example.org": {"not_before": now + 100, "delay_s": 60.0},
        f"{_USER}@solo.example:8080": {"not_before": now + 300, "delay_s": 20.0},
        "other.example": {"not_before": now + 200, "delay_s": 10.0},
    }
    path = tmp_path / "host_schedule.json"
    path.write_text(json.dumps(raw), "utf-8")
    return path, now


def test_an_older_builds_credentialed_robots_keys_leave_the_file_and_memory_on_load(tmp_path):
    path, raw = _old_robots(tmp_path)
    f = _stub_fetcher(tmp_path)
    on_disk = json.loads(path.read_text("utf-8"))
    assert on_disk == {k: raw[k] for k in ("https://example.org", "https://other.example")}  # the clean entries stay, unchanged
    _no_secret(path.read_text("utf-8"))
    assert "solo.example" not in path.read_text("utf-8")  # DROPPED, not folded into a host key
    assert sorted(f._robots) == ["https://example.org", "https://other.example"]
    assert f._robots_cause == {"https://other.example": "refused"}
    assert f._robots_fails == {"https://other.example": 2}
    # the host's own (anonymous) decision is the one kept: /p is disallowed, / is not
    assert f._robots["https://example.org"][0].can_fetch(f.user_agent, "https://example.org/x")


def test_an_older_builds_credentialed_schedule_keys_are_merged_into_the_hosts_on_load(tmp_path):
    path, now = _old_schedule(tmp_path)
    f = _stub_fetcher(tmp_path)
    on_disk = json.loads(path.read_text("utf-8"))
    _no_secret(path.read_text("utf-8"))
    assert sorted(on_disk) == ["example.org", "other.example", "solo.example:8080"]
    assert on_disk["example.org"] == {"not_before": now + 500, "delay_s": 60.0}  # the later stamp and the larger delay win
    assert on_disk["solo.example:8080"] == {"not_before": now + 300, "delay_s": 20.0}  # a credentialed-only host keeps its stamp
    assert on_disk["other.example"] == {"not_before": now + 200, "delay_s": 10.0}
    assert f._host_schedule["example.org"] == (now + 500, 60.0)
    assert f._host_schedule["solo.example:8080"] == (now + 300, 20.0)
    assert sorted(f._host_schedule) == ["example.org", "other.example", "solo.example:8080"]


def test_the_loaders_leave_credentialed_keys_out_even_when_the_file_was_not_rewritten(tmp_path):
    path, _raw = _old_robots(tmp_path)
    assert sorted(ingest._load_persisted_robots(path, now_monotonic=time.monotonic)) == ["https://example.org", "https://other.example"]
    assert ingest._persisted_robots_fails(path) == {"https://other.example": 2}
    assert ingest._persisted_robots_causes(path) == {"https://other.example": "refused"}
    spath, now = _old_schedule(tmp_path)
    loaded = ingest._load_host_schedule(spath)
    assert sorted(loaded) == ["example.org", "other.example", "solo.example:8080"]
    assert loaded["example.org"] == (now + 500, 60.0)
    _no_secret(json.dumps(loaded))


def test_a_write_never_carries_an_older_builds_credentialed_key_forward(tmp_path):
    path, _raw = _old_robots(tmp_path)
    ingest._persist_robots_entry(path, "https://new.example", kind="allow_all", body=None)
    assert sorted(json.loads(path.read_text("utf-8"))) == ["https://example.org", "https://new.example", "https://other.example"]
    spath, now = _old_schedule(tmp_path)
    ingest._persist_host_schedule(spath, "new.example", now + 50, 5.0)
    on_disk = json.loads(spath.read_text("utf-8"))
    assert sorted(on_disk) == ["example.org", "new.example", "other.example", "solo.example:8080"]
    assert on_disk["example.org"] == {"not_before": now + 500, "delay_s": 60.0}


def test_control_a_file_without_a_credentialed_key_is_not_rewritten(tmp_path):
    now = time.time()
    robots = json.dumps({"https://example.org": _robots_entry()}, indent=1)
    schedule = json.dumps({"example.org": {"not_before": now + 100, "delay_s": 60.0}}, indent=1)
    (tmp_path / "robots.json").write_text(robots, "utf-8")
    (tmp_path / "host_schedule.json").write_text(schedule, "utf-8")
    f = _stub_fetcher(tmp_path)
    assert (tmp_path / "robots.json").read_text("utf-8") == robots  # byte for byte: no rewrite
    assert (tmp_path / "host_schedule.json").read_text("utf-8") == schedule
    assert list(f._robots) == ["https://example.org"] and f._host_schedule == {"example.org": (now + 100, 60.0)}


# --------------------------------------------------------------------------- #
# 2. The activity monitor (the top bar and the task manager)
# --------------------------------------------------------------------------- #


def test_fetch_started_keeps_the_url_and_the_host_masked():
    m = ActivityMonitor()
    tok = m.fetch_started(f"https://{_CRED}example.org/feed")
    m.fetch_bytes(100, tok)
    snap = m.snapshot()
    assert snap["current_fetch"]["url"] == f"https://{USERINFO_MASK}example.org/feed"  # the top bar reads this through _shortUrl
    assert [r["host"] for r in m.per_host_rates()] == [f"{USERINFO_MASK}example.org"]  # the task manager's per-source rates
    m.fetch_finished(tok)
    assert m.snapshot()["last_url"] == f"https://{USERINFO_MASK}example.org/feed"
    _no_secret(json.dumps([snap, m.snapshot(), m.per_host_rates()]))


def test_the_fetcher_hands_the_monitor_nothing_it_shows_raw(tmp_path, monkeypatch):
    m = ActivityMonitor()
    monkeypatch.setattr(ingest, "activity_monitor", m)
    _stub_fetcher(tmp_path).fetch(f"https://{_CRED}example.org/a")
    assert m.snapshot()["last_url"] == f"https://{USERINFO_MASK}example.org/a"
    assert [r["host"] for r in m.per_host_rates()] == [f"{USERINFO_MASK}example.org"]


def test_control_fetch_started_keeps_an_ordinary_url_as_it_came():
    m = ActivityMonitor()
    tok = m.fetch_started("https://example.org:8443/feed?x=1")
    m.fetch_bytes(10, tok)
    assert m.snapshot()["current_fetch"]["url"] == "https://example.org:8443/feed?x=1"
    assert [r["host"] for r in m.per_host_rates()] == ["example.org:8443"]
    assert m.inflight_hosts() == 1


def test_fetch_started_never_raises_for_a_url_the_mask_leaves_unparseable():
    m = ActivityMonitor()
    tok = m.fetch_started("http://a]@[2606:4700::1/x")  # the userinfo's "]" closed the host's "[" for urlparse
    assert m.snapshot()["current_fetch"]["url"] == f"http://{USERINFO_MASK}[2606:4700::1/x"
    m.fetch_bytes(1, tok)
    assert [r["host"] for r in m.per_host_rates()] == ["?"]


# --------------------------------------------------------------------------- #
# 3. The URL log lines outside the fetcher
# --------------------------------------------------------------------------- #

_BAD = "http://{c}[::1/x"  # urlparse raises "Invalid IPv6 URL" for it, which reaches each module's except branch


def _bad(cred: bool) -> str:
    return _BAD.format(c=_CRED if cred else "")


def _messages(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records]


class _FetchResult:
    def __init__(self, content, content_type: str = "text/html") -> None:
        self.content, self.content_type = content, content_type


class _DiscoveryFetcher:
    """Answers the discovery calls in memory: a page that links one feed, the feed, and nothing for the probed paths."""

    def __init__(self, page_content="<link rel='alternate' type='application/rss+xml' href='/feed.xml'>", fail=None) -> None:
        self.page_content, self.fail = page_content, fail

    def fetch(self, url, require_html=True):
        from src.ingest import FetchError

        if self.fail is not None:
            raise self.fail
        if require_html:
            return _FetchResult(self.page_content)
        if url.endswith("/feed.xml"):
            return _FetchResult("<?xml version='1.0'?><rss/>", "application/rss+xml")
        raise FetchError("HTTP 404")


def _ddg():
    from src.services.duckduckgo import DuckDuckGoSearch

    return DuckDuckGoSearch


@pytest.mark.parametrize("cred", [True, False], ids=["credentialed", "control"])
def test_duckduckgo_url_parsing_lines(caplog, cred):
    d = _ddg()  # first: its import sets the logger's level (setup_logging), which would undo the one set here
    caplog.set_level(logging.DEBUG, logger="duckduckgo")
    bad = _bad(cred)
    shown = bad.replace(_CRED, USERINFO_MASK)
    assert d._clean_url(bad) is None  # the redirect unwrap (unparseable) and the validation line
    assert d._extract_domain(bad) == ""
    assert d._clean_url(f"ftp://{_CRED if cred else ''}files.example/x") is None  # the non-http(s) line
    assert d._unwrap_search_redirect(f"https://{_CRED if cred else ''}duckduckgo.com/l/?x=1") is None  # no target
    target = f"ftp://{_CRED if cred else ''}files.example/y"
    assert d._unwrap_search_redirect(f"https://duckduckgo.com/l/?uddg={target}") is None  # a target that is not http(s)
    assert d._resolve_url("/rss", bad) is None
    assert d._resolve_url(f"//{_CRED if cred else ''}cdn.example/rss", bad) is None  # a protocol-relative path carries its own
    msgs = _messages(caplog)
    m = USERINFO_MASK if cred else ""
    for head in (
        f"redirect unwrap: unparseable URL {shown!r}, left as-is: ",
        f"URL validation failed for {shown!r}: ",
        f"domain extraction failed for {shown!r}: ",
        f"URL rejected (non-http(s) scheme): {'ftp://' + m + 'files.example/x'!r}",
        f"redirect unwrap: no uddg target in {'https://' + m + 'duckduckgo.com/l/?x=1'!r}",
        f"redirect unwrap: target is not an absolute http(s) URL: {'ftp://' + m + 'files.example/y'!r}",
        f"URL resolve failed for '/rss' on {shown + '/'!r}: ",
        f"URL resolve failed for {'//' + m + 'cdn.example/rss'!r} on {shown + '/'!r}: ",
    ):
        assert any(x.startswith(head) for x in msgs), (head, msgs)
    if cred:
        _no_secret(caplog.text)


@pytest.mark.parametrize("cred", [True, False], ids=["credentialed", "control"])
def test_duckduckgo_discovery_lines(caplog, cred):
    from src.ingest import FetchError

    d = _ddg()  # first, for the same reason
    caplog.set_level(logging.DEBUG, logger="duckduckgo")
    url = f"https://{_CRED if cred else ''}news.example/"
    shown = f"https://{USERINFO_MASK if cred else ''}news.example/"
    assert d.discover_rss_feeds(url, fetcher=_DiscoveryFetcher()) == [url + "feed.xml"]  # the returned feed is data, as it was
    assert d.discover_rss_feeds(url, fetcher=_DiscoveryFetcher(fail=FetchError("robots.txt disallows it"))) == []
    assert d.discover_rss_feeds(url, fetcher=_DiscoveryFetcher(page_content=None)) == []  # an unexpected error
    assert d._validate_rss_feed(url, fetcher=_DiscoveryFetcher(fail=FetchError("HTTP 500"))) is False
    assert d._validate_rss_feed(url, fetcher=_DiscoveryFetcher(fail=RuntimeError("boom"))) is False
    found = d.find_missing_rss_feeds([{"domain": "news.example", "url": url}], fetcher=_DiscoveryFetcher())
    assert found[0]["rss_url"] == url + "feed.xml"
    msgs = _messages(caplog)
    for head in (
        f"Discovered 1 potential RSS feeds for {shown}",
        f"Valid RSS feed found: {shown}feed.xml",
        f"Ethical fetch refused or failed for {shown}: ",
        f"Unexpected error discovering RSS feeds for {shown}: ",
        f"RSS feed validation refused/failed for {shown}: ",
        f"RSS feed validation error for {shown}: ",
        f"Found RSS feed for news.example: {shown}feed.xml",
    ):
        assert any(x.startswith(head) for x in msgs), (head, msgs)
    if cred:
        _no_secret(caplog.text)


@pytest.mark.parametrize("cred", [True, False], ids=["credentialed", "control"])
def test_url_utils_lines(caplog, cred):
    from src.utils import url_utils

    caplog.set_level(logging.DEBUG, logger="src.utils.url_utils")
    bad = _bad(cred)
    shown = bad.replace(_CRED, USERINFO_MASK)
    assert url_utils.canonicalize_url(bad) == bad  # the caller's value is returned as it came, as before
    assert url_utils.get_domain_from_url(bad) is None
    assert url_utils.get_base_url(bad) is None
    msgs = _messages(caplog)
    for head in (f"Error canonicalizing URL {shown}: ", f"Error extracting domain from {shown}: ", f"Error getting base URL from {shown}: "):
        assert any(x.startswith(head) for x in msgs), (head, msgs)
    if cred:
        _no_secret(caplog.text)


@pytest.mark.parametrize("cred", [True, False], ids=["credentialed", "control"])
def test_security_lines(caplog, cred):
    from src.utils.security import safe_href, sanitize_url

    caplog.set_level(logging.DEBUG, logger="src.utils.security")
    bad = _bad(cred)
    shown = bad.replace(_CRED, USERINFO_MASK)
    assert sanitize_url(bad) == ""
    assert safe_href(bad) == ""
    msgs = _messages(caplog)
    for head in (f"sanitize_url: unparseable URL {shown!r} dropped: ", f"safe_href: unparseable URL {shown!r} dropped: "):
        assert any(x.startswith(head) for x in msgs), (head, msgs)
    if cred:
        _no_secret(caplog.text)


@pytest.mark.parametrize("cred", [True, False], ids=["credentialed", "control"])
def test_link_analyzer_lines(caplog, cred):
    from src.services.link_analyzer import LinkExtractor

    caplog.set_level(logging.DEBUG, logger="src.services.link_analyzer.extractor")
    bad = _bad(cred)
    shown = bad.replace(_CRED, USERINFO_MASK)
    x = LinkExtractor()
    assert x.normalize_url(bad) == ""
    rel = f"//{_CRED if cred else ''}cdn.example/x"  # a protocol-relative link carries its own
    assert x.extract_links(f'<a href="rel">t</a><a href="{rel}">u</a>', base_url=bad + "/") == []  # urljoin raises on the base
    assert x._extract_links_with_regex(f"<a href='{bad}'>t</a>", None, None) == []  # the malformed link is skipped
    msgs = _messages(caplog)
    for head in (
        f"Could not normalise URL {shown!r}: ",
        f"Error resolving relative URL rel with base {shown}/: ",
        f"Error resolving relative URL //{USERINFO_MASK if cred else ''}cdn.example/x with base {shown}/: ",
        f"Skipping malformed link URL {shown!r}: ",
    ):
        assert any(x.startswith(head) for x in msgs), (head, msgs)
    if cred:
        _no_secret(caplog.text)


def test_the_four_modules_import_failure_url_on_use_only():
    """A top-level import would load ``src.ingest`` wherever these modules are, and the services package puts duckduckgo.py in
    every keyword pass (src/analytics/engine_identity.py). The probe is a fresh interpreter."""
    import subprocess
    import sys

    code = (
        f"import sys; sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})\n"
        "import src.services.duckduckgo, src.utils.url_utils, src.utils.security, src.services.link_analyzer.extractor\n"
        "print('src.ingest' in sys.modules)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=Path(__file__).resolve().parents[1])
    assert out.stdout.strip().splitlines()[-1] == "False", out.stdout + out.stderr


def test_a_refused_url_with_credentials_is_still_refused(tmp_path):
    """The fetcher's refusals stand: a credentialed URL of another scheme is refused without its credentials in the sentence,
    and a backslash before the ``@`` (``urlparse`` reads good.example, urllib3 evil.test) is still refused, the other parser's
    host never requested. CHANGED, stated: before, the robots URL carried the same authority and was the request refused, so
    the page failed as RobotsUnavailable (``unreachable``, cached for the hostile key); now the robots read is the host's
    anonymous one (good.example, the host the SSRF guard checks) and the page itself is refused as a BlockedTarget."""
    s = _Session()
    f = _stub_fetcher(tmp_path, s)
    with pytest.raises(FetchFailed) as exc:
        f.fetch(f"ftp://{_CRED}example.org/x")
    _no_secret(str(exc.value))
    with pytest.raises(ingest.BlockedTarget):
        f.fetch("https://evil.test\\@good.example/x")
    assert [u for u, _kw in s.calls] == ["https://good.example/robots.txt"], s.calls
