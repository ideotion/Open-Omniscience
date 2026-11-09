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
   ``_shortUrl(current_fetch.url)``) and the task manager's per-source rates serve. The URL is masked now, and the host is the
   fetcher's own host key, so a credentialed and a plain URL to one host are one rate row.
3. The URL log lines of ``services/duckduckgo.py``, ``utils/url_utils.py``, ``utils/security.py`` and
   ``services/link_analyzer/extractor.py`` write the URL through ``failure_url``.
4. The fold of the two security reads. The key is the HOST KEY: capitals, an empty, zero-padded or default port make no second host
   (Steward 3's item 2), and a trailing dot does (an absolute and a relative name can be two hosts); an older build's spelled keys
   leave both files as its credentialed ones do; a bare ``host:443`` stamp still holds for ``host``; the files are scrubbed with
   persistence off (item 4); the preflights' fallback circuit is the host key's (item 3); a merge keeps the later stamp whichever key
   held it, and a non-finite stamp takes no wait away; a credentialed page whose robots.txt answers 401 is refused, the read
   anonymous, and its sentence says so in fixed words (N2); one host is one rate row (N4); duckduckgo's domain lines (S1) and the
   batch redo warning (N1) write no userinfo.

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
from urllib.parse import urlsplit

import pytest

import src.ingest as ingest
from src.ingest import EthicalFetcher, FetchFailed, clear_kill_switch
from src.ingest.fetch_verdict import USERINFO_MASK
from src.monitoring.activity import ActivityMonitor

_USER, _NEEDLE = "alice", "hunter2"
_USERINFO = f"{_USER}:{_NEEDLE}@"
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy")


def _no_needle(text: str) -> None:
    assert _NEEDLE not in text and f"{_USER}:" not in text and _USERINFO not in text, text


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
        f.fetch(f"http://{_USERINFO}127.0.0.1:{port}/a")
        f.fetch(f"http://127.0.0.1:{port}/b")
    host = f"127.0.0.1:{port}"
    robots = (tmp_path / "robots.json").read_text("utf-8")
    schedule = (tmp_path / "host_schedule.json").read_text("utf-8")
    assert list(json.loads(robots)) == [f"http://{host}"]
    assert list(json.loads(schedule)) == [host]
    _no_needle(robots)
    _no_needle(schedule)
    assert list(f._robots) == [f"http://{host}"]
    assert list(f._host_schedule) == [host]
    assert list(f._last_request) == [host]
    assert list(f._host_locks) == [host]
    assert [p for p, _h, _a in seen].count("/robots.txt") == 1, seen  # one read for the host, not one per userinfo


def test_the_robots_read_goes_to_the_page_urls_scheme_host_and_port_without_its_credentials(tmp_path, monkeypatch):
    with _server() as (port, seen):
        f = _loopback_fetcher(tmp_path, monkeypatch)
        f.fetch(f"http://{_USERINFO}127.0.0.1:{port}/a")
    robots = [(h, a) for p, h, a in seen if p == "/robots.txt"]
    page = [(h, a) for p, h, a in seen if p == "/a"]
    assert robots == [(f"127.0.0.1:{port}", None)], seen  # same host and port, no Authorization header
    # the page request itself is unchanged: requests still sends the URL's own credentials to the page
    assert page and page[0][0] == f"127.0.0.1:{port}" and page[0][1] and page[0][1].startswith("Basic ")


@pytest.mark.parametrize("url", [f"https://{_USERINFO}example.org:8443/x", f"http://{_USERINFO}example.org/x", f"https://{_USER}@example.org/x"])
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
        assert f.declared_sitemaps(f"http://{_USERINFO}127.0.0.1:{port}/") == ["http://example.org/sitemap.xml"]
        f.fetch(f"http://127.0.0.1:{port}/b")
    assert [(p, a) for p, _h, a in seen] == [("/robots.txt", None), ("/b", None)]
    assert list(json.loads((tmp_path / "robots.json").read_text("utf-8"))) == [f"http://127.0.0.1:{port}"]


def test_a_credentialed_and_a_plain_url_wait_out_one_politeness_interval(tmp_path):
    clock = [100.0]
    slept: list[float] = []
    f = _stub_fetcher(tmp_path, min_interval_s=5.0)
    f._now = lambda: clock[0]  # type: ignore[method-assign]
    f._sleep = slept.append  # type: ignore[method-assign]
    f.fetch(f"https://{_USERINFO}example.org/a")
    clock[0] = 101.0
    f.fetch("https://example.org/b")
    assert slept == [pytest.approx(4.0)]  # one host, one interval: the second fetch waits the rest of it


def test_a_credentialed_url_rides_the_hosts_own_circuit_and_names_no_credential_to_the_proxy(tmp_path):
    s = _Session()
    f = _stub_fetcher(tmp_path, s, proxy="socks5h://127.0.0.1:9050")
    f.fetch(f"https://{_USERINFO}example.org/a")
    f.fetch("https://example.org/b")
    proxies = [kw.get("proxies") for _u, kw in s.calls]
    assert len(proxies) == 3 and all(p == proxies[0] for p in proxies), proxies  # robots, /a, /b: one circuit
    assert proxies[0] and urlsplit(proxies[0]["https"]).username == "example.org"  # the circuit is named on the host alone
    _no_needle(json.dumps(proxies))
    assert "alicehunter2" not in json.dumps(proxies)


def test_crawl_delay_for_and_forget_robots_find_the_hosts_one_entry_from_a_credentialed_url(tmp_path):
    f = _stub_fetcher(tmp_path, _Session(robots=b"User-agent: *\nCrawl-delay: 7\n"))
    f.fetch("https://example.org/a")
    assert f.crawl_delay_for(f"https://{_USERINFO}example.org/x") == 7.0
    assert f.crawl_delay_for(f"{_USERINFO}example.org") == 7.0
    assert f.forget_robots(f"https://{_USERINFO}example.org") == 1
    assert f._robots == {}


def test_the_persistence_failure_lines_name_the_host_and_not_its_credentials(tmp_path, monkeypatch, caplog):
    f = EthicalFetcher(session=_Session(robots=b"User-agent: *\nCrawl-delay: 2\n"), min_interval_s=0, retry_backoff_s=0, max_retries=0,
                       robots_cache_path=tmp_path / "missing" / "robots.json")  # the directory does not exist: both writes fail
    f._sleep = lambda _s: None  # type: ignore[method-assign]
    caplog.set_level(logging.DEBUG, logger="src.ingest")
    f.fetch(f"https://{_USERINFO}example.org/a")
    lines = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("robots cache persistence failed for https://example.org:") for m in lines), lines
    assert any(m.startswith("host schedule persistence failed for example.org:") for m in lines), lines
    _no_needle(caplog.text)


def test_the_clock_corrected_stamp_line_names_the_host_and_not_its_credentials(tmp_path, caplog):
    far = time.time() + 5000
    (tmp_path / "host_schedule.json").write_text(json.dumps({"example.org": {"not_before": far, "delay_s": 1.0}}), "utf-8")
    slept: list[float] = []
    f = _stub_fetcher(tmp_path, min_interval_s=1.0)
    f._sleep = slept.append  # type: ignore[method-assign]
    caplog.set_level(logging.INFO, logger="src.ingest")
    f.fetch(f"https://{_USERINFO}example.org/a")
    assert any(r.getMessage().startswith("politeness stamp for example.org lay ") for r in caplog.records), caplog.text
    assert slept == [pytest.approx(1.0)]  # the host's own stamp was found for the credentialed URL, clamped to its delay
    _no_needle(caplog.text)


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
        f"https://{_USERINFO}example.org": _robots_entry("User-agent: *\nDisallow: /\n"),
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
        f"{_USERINFO}example.org": {"not_before": now + 500, "delay_s": 30.0},
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
    _no_needle(path.read_text("utf-8"))
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
    _no_needle(path.read_text("utf-8"))
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
    _no_needle(json.dumps(loaded))


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
    tok = m.fetch_started(f"https://{_USERINFO}example.org/feed")
    m.fetch_bytes(100, tok)
    snap = m.snapshot()
    assert snap["current_fetch"]["url"] == f"https://{USERINFO_MASK}example.org/feed"  # the top bar reads this through _shortUrl
    assert [r["host"] for r in m.per_host_rates()] == ["example.org"]  # the task manager's per-source rates: the fetcher's host key (N4)
    m.fetch_finished(tok)
    assert m.snapshot()["last_url"] == f"https://{USERINFO_MASK}example.org/feed"
    _no_needle(json.dumps([snap, m.snapshot(), m.per_host_rates()]))


def test_the_fetcher_hands_the_monitor_nothing_it_shows_raw(tmp_path, monkeypatch):
    m = ActivityMonitor()
    monkeypatch.setattr(ingest, "activity_monitor", m)
    _stub_fetcher(tmp_path).fetch(f"https://{_USERINFO}example.org/a")
    assert m.snapshot()["last_url"] == f"https://{USERINFO_MASK}example.org/a"
    assert [r["host"] for r in m.per_host_rates()] == ["example.org"]  # the fetcher's own host key (N4)


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
    return _BAD.format(c=_USERINFO if cred else "")


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
    shown = bad.replace(_USERINFO, USERINFO_MASK)
    assert d._clean_url(bad) is None  # the redirect unwrap (unparseable) and the validation line
    assert d._extract_domain(bad) == ""
    assert d._clean_url(f"ftp://{_USERINFO if cred else ''}files.example/x") is None  # the non-http(s) line
    assert d._unwrap_search_redirect(f"https://{_USERINFO if cred else ''}duckduckgo.com/l/?x=1") is None  # no target
    target = f"ftp://{_USERINFO if cred else ''}files.example/y"
    assert d._unwrap_search_redirect(f"https://duckduckgo.com/l/?uddg={target}") is None  # a target that is not http(s)
    assert d._resolve_url("/rss", bad) is None
    assert d._resolve_url(f"//{_USERINFO if cred else ''}cdn.example/rss", bad) is None  # a protocol-relative path carries its own
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
        _no_needle(caplog.text)


@pytest.mark.parametrize("cred", [True, False], ids=["credentialed", "control"])
def test_duckduckgo_discovery_lines(caplog, cred):
    from src.ingest import FetchError

    d = _ddg()  # first, for the same reason
    caplog.set_level(logging.DEBUG, logger="duckduckgo")
    url = f"https://{_USERINFO if cred else ''}news.example/"
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
        _no_needle(caplog.text)


@pytest.mark.parametrize("cred", [True, False], ids=["credentialed", "control"])
def test_url_utils_lines(caplog, cred):
    from src.utils import url_utils

    caplog.set_level(logging.DEBUG, logger="src.utils.url_utils")
    bad = _bad(cred)
    shown = bad.replace(_USERINFO, USERINFO_MASK)
    assert url_utils.canonicalize_url(bad) == bad  # the caller's value is returned as it came, as before
    assert url_utils.get_domain_from_url(bad) is None
    assert url_utils.get_base_url(bad) is None
    msgs = _messages(caplog)
    for head in (f"Error canonicalizing URL {shown}: ", f"Error extracting domain from {shown}: ", f"Error getting base URL from {shown}: "):
        assert any(x.startswith(head) for x in msgs), (head, msgs)
    if cred:
        _no_needle(caplog.text)


@pytest.mark.parametrize("cred", [True, False], ids=["credentialed", "control"])
def test_security_lines(caplog, cred):
    from src.utils.security import safe_href, sanitize_url

    caplog.set_level(logging.DEBUG, logger="src.utils.security")
    bad = _bad(cred)
    shown = bad.replace(_USERINFO, USERINFO_MASK)
    assert sanitize_url(bad) == ""
    assert safe_href(bad) == ""
    msgs = _messages(caplog)
    for head in (f"sanitize_url: unparseable URL {shown!r} dropped: ", f"safe_href: unparseable URL {shown!r} dropped: "):
        assert any(x.startswith(head) for x in msgs), (head, msgs)
    if cred:
        _no_needle(caplog.text)


@pytest.mark.parametrize("cred", [True, False], ids=["credentialed", "control"])
def test_link_analyzer_lines(caplog, cred):
    from src.services.link_analyzer import LinkExtractor

    caplog.set_level(logging.DEBUG, logger="src.services.link_analyzer.extractor")
    bad = _bad(cred)
    shown = bad.replace(_USERINFO, USERINFO_MASK)
    x = LinkExtractor()
    assert x.normalize_url(bad) == ""
    rel = f"//{_USERINFO if cred else ''}cdn.example/x"  # a protocol-relative link carries its own
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
        _no_needle(caplog.text)


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
    and a backslash before the ``@`` (``urlparse`` reads good.example, urllib3 evil.test) is still refused, neither parser's
    host requested. CHANGED twice, stated: before R621 the robots URL carried the same authority and was the request refused,
    so the page failed as RobotsUnavailable (``unreachable``, cached for the hostile key); R622 runs
    ``_refuse_parser_mismatch`` before the SSRF guard and before R621's host key is taken, so the URL is now refused as a
    BlockedTarget before ANY request, the robots read's included."""
    s = _Session()
    f = _stub_fetcher(tmp_path, s)
    with pytest.raises(FetchFailed) as exc:
        f.fetch(f"ftp://{_USERINFO}example.org/x")
    _no_needle(str(exc.value))
    with pytest.raises(ingest.BlockedTarget):
        f.fetch("https://evil.test\\@good.example/x")
    assert s.calls == [], s.calls  # refused before any robots read (R622's order kept under R621's key)


# --------------------------------------------------------------------------- #
# 4. The fold of the two security reads (Steward 3's items 2, 3, 4 and 8; the independent read's S1, N1, N2, N4 and its NaN edge)
# --------------------------------------------------------------------------- #

#: Spellings of ONE host and port to urllib.parse (the host the SSRF guard checks) and to urllib3 (the host requests connects to).
_HTTPS_SPELLINGS = ("https://HOST.Example/a", "https://host.example:443/b", "https://Host.example:0443/c", "https://host.example:/d")


def test_spelling_variants_of_one_host_share_one_key_one_robots_read_one_interval_one_lock_and_one_circuit(tmp_path):
    """Steward 3's item 2: capitals, the default port, a zero-padded port and an empty port are one host."""
    clock = [100.0]
    slept: list[float] = []
    s = _Session()
    f = _stub_fetcher(tmp_path, s, min_interval_s=5.0, proxy="socks5h://127.0.0.1:9050")
    f._now = lambda: clock[0]  # type: ignore[method-assign]
    f._sleep = slept.append  # type: ignore[method-assign]
    for i, url in enumerate(_HTTPS_SPELLINGS):
        clock[0] = 100.0 + i
        f.fetch(url)
    assert [u for u, _kw in s.calls].count("https://host.example/robots.txt") == 1, s.calls  # one robots read, to the guard's host
    assert [u for u, _kw in s.calls if u.endswith("/robots.txt")] == ["https://host.example/robots.txt"]
    assert list(f._robots) == ["https://host.example"]
    assert list(f._last_request) == ["host.example"]
    assert list(f._host_locks) == ["host.example"]
    assert slept == [pytest.approx(4.0)] * 3  # one interval: each later spelling waits out the rest of it
    proxies = [kw.get("proxies") for _u, kw in s.calls]
    assert all(p == proxies[0] for p in proxies), proxies  # one circuit
    assert [u for u, _kw in s.calls if not u.endswith("/robots.txt")] == list(_HTTPS_SPELLINGS)  # each page as written


def test_http_spellings_share_the_http_key_and_the_hosts_one_interval(tmp_path):
    s = _Session()
    f = _stub_fetcher(tmp_path, s)
    for url in ("http://Host.Example:080/a", "http://host.example:80/b", "http://host.example:/c", "https://host.example/d"):
        f.fetch(url)
    assert sorted(f._robots) == ["http://host.example", "https://host.example"]  # robots.txt is per scheme, host and port
    assert list(f._last_request) == ["host.example"]  # the interval, as before, is the host's whatever the scheme


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("https://host.example/", "https://host.example:8443/"),  # another port
        ("http://host.example:443/", "https://host.example/"),  # 443 is not http's default
        ("https://host.example:80/", "http://host.example/"),  # nor 80 https's
        ("https://host.example./", "https://host.example/"),  # an absolute and a relative name: the trailing dot stays
        ("https://a.example/", "https://b.example/"),
        ("https://[::1]/", "https://[::2]/"),
        ("http://host.example:8080/", "http://host.example:8081/"),
    ],
)
def test_a_different_host_or_port_never_shares_a_key(tmp_path, a, b):
    from urllib.parse import urlparse

    keys = []
    for url in (a, b):
        p = urlparse(url)
        keys.append(f"{p.scheme}://{ingest._host_netloc(p.netloc, p.scheme)}")
    assert keys[0] != keys[1], keys
    s = _Session()
    f = _stub_fetcher(tmp_path, s)
    f.fetch(a)
    f.fetch(b)
    assert sorted(f._robots) == sorted(keys)
    assert len([u for u, _kw in s.calls if u.endswith("/robots.txt")]) == 2, s.calls  # each host read its own robots.txt


@pytest.mark.parametrize(
    ("netloc", "scheme", "key"),
    [
        ("[::FFFF:1.2.3.4]:443", "https", "[::ffff:1.2.3.4]"),  # an IPv6 literal keeps its brackets
        ("[2606:4700::1]:08443", "https", "[2606:4700::1]:8443"),
        ("alice:hunter2@HOST.example.:0080", "http", "host.example."),  # the userinfo out, the dot kept
        ("host.example:443", "", "host.example:443"),  # no scheme (a bare schedule key): an explicit port stays
        ("host.example:", "", "host.example"),
        ("host.example:99999", "https", "host.example:99999"),  # unreadable: as written after the userinfo
    ],
)
def test_the_host_key(netloc, scheme, key):
    assert ingest._host_netloc(netloc, scheme) == key


def test_crawl_delay_for_and_forget_robots_find_the_one_entry_from_any_spelling(tmp_path):
    f = _stub_fetcher(tmp_path, _Session(robots=b"User-agent: *\nCrawl-delay: 7\n"))
    f.fetch("https://example.org/a")
    for asked in ("https://EXAMPLE.org:443/x", "Example.ORG:443", "example.org:0443", f"{_USERINFO}Example.org"):
        assert f.crawl_delay_for(asked) == 7.0, asked
    assert f.forget_robots("https://Example.org:0443") == 1
    assert f._robots == {}


def test_declared_sitemaps_keys_by_the_host_key(tmp_path):
    s = _Session(robots=b"User-agent: *\nSitemap: https://example.org/s.xml\n")
    f = _stub_fetcher(tmp_path, s)
    assert f.declared_sitemaps("https://EXAMPLE.org:443/") == ["https://example.org/s.xml"]
    f.fetch("https://example.org/a")
    assert list(f._robots) == ["https://example.org"]
    assert [u for u, _kw in s.calls] == ["https://example.org/robots.txt", "https://example.org/a"]


def _spelled_robots(tmp_path: Path) -> tuple[Path, dict]:
    raw = {
        "https://example.org": _robots_entry(),
        "https://EXAMPLE.org": _robots_entry("User-agent: *\nDisallow: /\n"),
        "https://example.org:443": _robots_entry("User-agent: *\nDisallow: /\n"),
        "http://example.org:080": _robots_entry("User-agent: *\nDisallow: /\n"),
        "http://example.org:": _robots_entry("User-agent: *\nDisallow: /\n"),
        "http://example.org:443": _robots_entry(),  # 443 is not http's default: its own host key, kept
        "https://example.org.": _robots_entry(),  # the trailing dot stays: its own host key, kept
    }
    path = tmp_path / "robots.json"
    path.write_text(json.dumps(raw), "utf-8")
    return path, raw


def test_an_older_builds_spelled_robots_keys_leave_the_file_and_memory_on_load(tmp_path):
    path, raw = _spelled_robots(tmp_path)
    kept = ["http://example.org:443", "https://example.org", "https://example.org."]
    assert sorted(ingest._load_persisted_robots(path, now_monotonic=time.monotonic)) == kept  # the loader alone, before any rewrite
    f = _stub_fetcher(tmp_path)
    assert json.loads(path.read_text("utf-8")) == {k: raw[k] for k in kept}  # DROPPED from the file, the normal keys unchanged
    assert sorted(f._robots) == kept
    assert f._robots["https://example.org"][0].can_fetch(f.user_agent, "https://example.org/x")  # the host key's own decision


def test_an_older_builds_spelled_schedule_keys_are_merged_into_the_host_key(tmp_path):
    now = time.time()
    raw = {
        "HOST.example": {"not_before": now + 500, "delay_s": 30.0},
        "host.example:": {"not_before": now + 100, "delay_s": 90.0},
        "host.example": {"not_before": now + 200, "delay_s": 10.0},
        "host.example:08080": {"not_before": now + 300, "delay_s": 5.0},
        "host.example.": {"not_before": now + 50, "delay_s": 1.0},  # the trailing dot stays
    }
    path = tmp_path / "host_schedule.json"
    path.write_text(json.dumps(raw), "utf-8")
    assert ingest._load_host_schedule(path)["host.example"] == (now + 500, 90.0)  # the loader alone, before any rewrite
    f = _stub_fetcher(tmp_path)
    on_disk = json.loads(path.read_text("utf-8"))
    assert sorted(on_disk) == ["host.example", "host.example.", "host.example:8080"]
    assert on_disk["host.example"] == {"not_before": now + 500, "delay_s": 90.0}  # the later stamp and the larger delay win
    assert on_disk["host.example:8080"] == {"not_before": now + 300, "delay_s": 5.0}
    assert f._host_schedule["host.example"] == (now + 500, 90.0)
    assert sorted(f._host_schedule) == ["host.example", "host.example.", "host.example:8080"]


def test_a_write_never_carries_a_spelled_key_forward(tmp_path):
    path, _raw = _spelled_robots(tmp_path)
    ingest._persist_robots_entry(path, "https://new.example", kind="allow_all", body=None)
    assert sorted(json.loads(path.read_text("utf-8"))) == ["http://example.org:443", "https://example.org", "https://example.org.", "https://new.example"]
    now = time.time()
    spath = tmp_path / "host_schedule.json"
    spath.write_text(json.dumps({"Example.org:080": {"not_before": now + 400, "delay_s": 40.0}}), "utf-8")
    ingest._persist_host_schedule(spath, "new.example", now + 50, 5.0)
    assert json.loads(spath.read_text("utf-8")) == {
        "example.org:80": {"not_before": now + 400, "delay_s": 40.0},
        "new.example": {"not_before": now + 50, "delay_s": 5.0},
    }


def test_a_bare_default_port_stamp_also_holds_for_the_portless_host_key(tmp_path):
    """An older build wrote ``host:443`` for ``https://host:443``, which is now keyed ``host``: the stamp still holds there, and it
    is kept under its own key too (it is also this build's key for ``http://host:443``). The file is a normal one: not rewritten."""
    now = time.time()
    text = json.dumps({"host.example:443": {"not_before": now + 400, "delay_s": 40.0}, "host.example": {"not_before": now + 100, "delay_s": 60.0},
                       "other.example:80": {"not_before": now + 300, "delay_s": float("nan")}})
    path = tmp_path / "host_schedule.json"
    path.write_text(text, "utf-8")
    f = _stub_fetcher(tmp_path)
    assert path.read_text("utf-8") == text
    assert f._host_schedule["host.example:443"] == (now + 400, 40.0)
    assert f._host_schedule["host.example"] == (now + 400, 60.0)  # the later stamp and the larger delay
    assert f._host_schedule["other.example"] == (now + 300, 0.0)  # a delay that is not a number lends none


def test_a_merge_where_the_plain_stamp_is_the_later_one_keeps_it(tmp_path):
    """Steward 3's item 8: the merge is the max of each field, not "the credentialed key wins"."""
    now = time.time()
    raw = {f"{_USERINFO}example.org": {"not_before": now + 100, "delay_s": 90.0}, "example.org": {"not_before": now + 500, "delay_s": 10.0}}
    assert ingest._merge_unkeyed_stamps(raw) == {"example.org": {"not_before": now + 500, "delay_s": 90.0}}
    raw = {"example.org": {"not_before": now + 500, "delay_s": 10.0}, f"{_USERINFO}example.org": {"not_before": now + 100, "delay_s": 90.0}}
    assert ingest._merge_unkeyed_stamps(raw) == {"example.org": {"not_before": now + 500, "delay_s": 90.0}}  # whatever the order


@pytest.mark.parametrize("clean", [float("nan"), float("inf"), "soon", None])
def test_a_clean_stamp_that_is_not_a_finite_number_never_makes_the_credentialed_wait_disappear(clean):
    now = time.time()
    raw = {"example.org": {"not_before": clean, "delay_s": 10.0}, f"{_USERINFO}example.org": {"not_before": now + 500, "delay_s": 30.0}}
    assert ingest._merge_unkeyed_stamps(raw) == {"example.org": {"not_before": now + 500, "delay_s": 30.0}}


def test_a_delay_that_is_not_a_finite_number_reads_as_none_in_the_merge():
    now = time.time()
    raw = {"example.org": {"not_before": now + 100, "delay_s": float("nan")}, f"{_USERINFO}example.org": {"not_before": now + 50, "delay_s": 30.0}}
    assert ingest._merge_unkeyed_stamps(raw) == {"example.org": {"not_before": now + 100, "delay_s": 30.0}}


def test_the_fallback_mapping_rides_the_host_keys_circuit(tmp_path):
    """Steward 3's item 3: ``_guarded_redirect_get`` called without a mapping (the preflights) builds it from the host key."""
    s = _Session()
    f = _stub_fetcher(tmp_path, s, proxy="socks5h://127.0.0.1:9050")
    f._guarded_redirect_get(f"https://{_USERINFO}Example.org:443/robots.txt")
    f.fetch("https://example.org/a")
    proxies = [kw.get("proxies") for _u, kw in s.calls]
    assert all(p == proxies[0] for p in proxies), proxies  # the fallback's circuit is the host's own
    _no_needle(json.dumps(proxies))
    assert "alicehunter2" not in json.dumps(proxies)


@pytest.mark.parametrize("off", ["OO_ROBOTS_CACHE_PERSIST", "OO_HOST_SCHEDULE_PERSIST"])
def test_the_files_are_scrubbed_with_persistence_off_and_nothing_new_is_written(tmp_path, monkeypatch, off):
    """Steward 3's item 4."""
    monkeypatch.setenv(off, "0")
    rpath, _raw = _old_robots(tmp_path)
    spath, _now = _old_schedule(tmp_path)
    f = _stub_fetcher(tmp_path)
    _no_needle(rpath.read_text("utf-8"))
    _no_needle(spath.read_text("utf-8"))
    before = (rpath.read_text("utf-8"), spath.read_text("utf-8"))
    persisted = rpath if off == "OO_ROBOTS_CACHE_PERSIST" else spath
    f.fetch("https://fresh.example/a")
    assert "fresh.example" not in persisted.read_text("utf-8")  # the switched-off file gains nothing
    assert persisted.read_text("utf-8") == before[0 if off == "OO_ROBOTS_CACHE_PERSIST" else 1]


def test_control_with_persistence_off_a_clean_file_is_not_rewritten(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_ROBOTS_CACHE_PERSIST", "0")
    monkeypatch.setenv("OO_HOST_SCHEDULE_PERSIST", "0")
    robots = json.dumps({"https://example.org": _robots_entry()}, indent=1)
    schedule = json.dumps({"example.org": {"not_before": time.time() + 100, "delay_s": 60.0}}, indent=1)
    (tmp_path / "robots.json").write_text(robots, "utf-8")
    (tmp_path / "host_schedule.json").write_text(schedule, "utf-8")
    f = _stub_fetcher(tmp_path)
    assert (tmp_path / "robots.json").read_text("utf-8") == robots
    assert (tmp_path / "host_schedule.json").read_text("utf-8") == schedule
    assert f._robots == {} and f._host_schedule == {}  # persistence off: nothing loaded, as before


class _Robots401(_Handler):
    def do_GET(self) -> None:  # noqa: N802 - the base class's name
        if self.path != "/robots.txt":
            super().do_GET()
            return
        self.seen.append((self.path, self.headers.get("Host"), self.headers.get("Authorization")))
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="r621"')
        self.send_header("Content-Length", "0")
        self.end_headers()


@contextlib.contextmanager
def _server_401() -> Iterator[tuple[int, list]]:
    seen: list = []
    handler = type("Handler", (_Robots401,), {"seen": seen})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, name="r621-loopback-401", daemon=True)
    t.start()
    try:
        yield srv.server_address[1], seen
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(5)


def _refused_by_robots(tmp_path: Path, monkeypatch, *, cred: bool) -> tuple[ingest.RobotsUnavailable, list]:
    with _server_401() as (port, seen):
        f = _loopback_fetcher(tmp_path, monkeypatch)
        with pytest.raises(ingest.RobotsUnavailable) as caught:
            f.fetch(f"http://{_USERINFO if cred else ''}127.0.0.1:{port}/a")
    return caught.value, seen


def test_a_credentialed_page_whose_robots_txt_answers_401_is_refused_and_the_read_sent_no_credentials(tmp_path, monkeypatch):
    """Steward 3's item 8: fail-closed, and the anonymous read is anonymous."""
    exc, seen = _refused_by_robots(tmp_path, monkeypatch, cred=True)
    assert exc.cause == "refused"
    assert [(p, a) for p, _h, a in seen] == [("/robots.txt", None)], seen  # no Authorization, and the page never requested


def test_the_refusal_says_the_robots_read_carried_no_credentials_and_reads_as_before(tmp_path, monkeypatch):
    """The independent read's N2: a fixed caveat after the sentence, for a credentialed page only. Every reader the R620 site
    tests use reads it exactly as it reads the plain refusal, and it names no credential."""
    from src.monitoring.secret_scrub import record_text
    from tests.test_failure_url_sites_r620 import _readers

    exc, seen = _refused_by_robots(tmp_path, monkeypatch, cred=True)
    (tmp_path / "plain").mkdir()
    plain, plain_seen = _refused_by_robots(tmp_path / "plain", monkeypatch, cred=False)
    text, plain_text = record_text(exc, typed=False), record_text(plain, typed=False)
    sentence = "robots.txt for http://{h} could not be determined (refused); refusing to fetch"
    assert plain_text == sentence.format(h=plain_seen[0][1]), plain_text  # control: the plain refusal as it always was
    assert text == sentence.format(h=seen[0][1]) + " (robots.txt is read without the page address's credentials)", text
    assert _readers(exc) == _readers(plain)
    assert exc.cause == plain.cause == "refused"
    _no_needle(text)


def test_control_no_caveat_for_another_cause(tmp_path, monkeypatch):
    s = _Session()
    s.get = lambda url, **kw: (s.calls.append((url, kw)), _Resp(url, 503, b"", "text/plain"))[1]  # type: ignore[method-assign]
    f = _stub_fetcher(tmp_path, s)
    with pytest.raises(ingest.RobotsUnavailable) as caught:
        f.fetch(f"https://{_USERINFO}example.org/a")
    assert str(caught.value) == "robots.txt for https://example.org could not be determined (server_error); refusing to fetch"


def test_one_host_is_one_rate_row_in_the_task_manager():
    """The independent read's N4: the host slot is the fetcher's host key."""
    m = ActivityMonitor()
    for url in (f"https://{_USERINFO}example.org/a", "https://example.org/b", "https://EXAMPLE.org:443/c"):
        tok = m.fetch_started(url)
        m.fetch_bytes(10, tok)
        m.fetch_finished(tok)
    assert [r["host"] for r in m.per_host_rates()] == ["example.org"]
    assert m.snapshot()["last_url"] == "https://EXAMPLE.org:443/c"  # the URL slot is the masked URL as it came


def test_the_host_slot_falls_back_to_the_masked_form_and_never_raises(monkeypatch):
    def broken(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(ingest, "_readable_host_key", broken)
    m = ActivityMonitor()
    tok = m.fetch_started(f"https://{_USERINFO}example.org/a")
    m.fetch_bytes(10, tok)
    assert [r["host"] for r in m.per_host_rates()] == [f"{USERINFO_MASK}example.org"]


def test_duckduckgo_writes_a_sources_domain_masked(caplog):
    """The independent read's S1: ``find_missing_rss_feeds`` wrote the source's domain (a netloc from ``_extract_domain``, userinfo
    included) as it was. Masked up to and including its LAST ``@``."""
    d = _ddg()
    caplog.set_level(logging.DEBUG, logger="duckduckgo")
    url = f"https://{_USERINFO}news.example/"
    d.find_missing_rss_feeds([{"domain": f"{_USERINFO}news.example", "url": url}], fetcher=_DiscoveryFetcher())
    from src.ingest import FetchError

    none = _DiscoveryFetcher(fail=FetchError("HTTP 404"))
    d.find_missing_rss_feeds([{"domain": f"x@{_USERINFO}quiet.example", "url": url}], fetcher=none)
    d.find_missing_rss_feeds([{"domain": "plain.example", "url": "https://plain.example/"}], fetcher=none)
    msgs = _messages(caplog)
    assert f"Found RSS feed for {USERINFO_MASK}news.example: https://{USERINFO_MASK}news.example/feed.xml" in msgs, msgs
    assert f"No RSS feed found for {USERINFO_MASK}quiet.example" in msgs, msgs
    assert "No RSS feed found for plain.example" in msgs, msgs  # control: a plain domain as it was
    _no_needle(caplog.text)
    assert "x@" not in caplog.text


def test_duckduckgos_domain_label_never_raises_and_encodes_whitespace():
    from src.services.duckduckgo import _logged_domain

    class _Unprintable:
        def __str__(self) -> str:
            raise RuntimeError("boom")

    assert _logged_domain(_Unprintable()) == "<unreadable domain>"
    assert _logged_domain(f"{_USERINFO}news example") == f"{USERINFO_MASK}news%20example"


def test_the_batch_redo_warning_writes_the_url_masked(caplog, monkeypatch):
    """The independent read's N1: ``e.requested_url`` was written raw into a WARNING; the error's own words, which can quote the
    row's parameters, lose the userinfo too."""
    from types import SimpleNamespace

    from src.ingest.batch import ArticleBatch

    url = f"https://{_USERINFO}news.example/story"
    batch = ArticleBatch.__new__(ArticleBatch)
    batch._session = SimpleNamespace(rollback=lambda: None)
    batch._pending = [SimpleNamespace(requested_url=url)]
    batch.tally = {"stored": 0, "duplicate": 0, "errors": 0}

    def flush_fails(_entries):
        raise RuntimeError("batched commit failed")

    def store_fails(_e):
        raise RuntimeError(f"(sqlite3.OperationalError) database is locked [parameters: ('{url}',)]")

    monkeypatch.setattr(batch, "_flush_batched", flush_fails)
    monkeypatch.setattr(batch, "_store_one", store_fails)
    caplog.set_level(logging.WARNING, logger="ingest.batch")
    batch.flush()
    lines = [m for m in _messages(caplog) if m.startswith("collect redo:")]
    assert len(lines) == 1 and lines[0].startswith(f"collect redo: unexpected error storing https://{USERINFO_MASK}news.example/story;"), lines
    assert batch.tally["errors"] == 1
    _no_needle(caplog.text)


def test_crawl_delay_for_reads_the_urls_own_scheme_first_from_any_spelling(tmp_path):
    from urllib.robotparser import RobotFileParser

    f = _stub_fetcher(tmp_path)
    for scheme, delay in (("http", 3), ("https", 7)):
        rp = RobotFileParser()
        rp.parse(["User-agent: *", f"Crawl-delay: {delay}"])
        f._robots[f"{scheme}://example.org"] = (rp, f._now() + 3600)
    assert f.crawl_delay_for("http://EXAMPLE.org/x") == 3.0  # its own scheme's entry first, not the https one
    assert f.crawl_delay_for("https://Example.org:0443/x") == 7.0
