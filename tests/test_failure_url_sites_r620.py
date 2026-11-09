"""
Every failure sentence the fetcher writes about a caller's URL writes it through ``failure_url`` (R620, the wider mask).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``failure_url`` first masked only "request error for <url>". A credentialed URL that got a 401 still landed raw in
"HTTP 401 for <url>", and the same held for every other sentence the fetcher raises with the caller's URL in it. Each sentence
here is produced by the REAL ``EthicalFetcher`` against a server on 127.0.0.1 where that can be done (a 401, a 404, a non-HTML
type, an oversize body declared and streamed, a slow body, a redirect loop, a redirect to another scheme, a robots.txt disallow
and an unreadable robots.txt), and through a seam where it cannot (the size check on a body an injected session already holds,
the archive backfill's log line, the fetcher's log line about the proxies the environment names). For each one: a ``user:pass@``
URL comes out masked, an ordinary URL comes out exactly as before, and the readers of the sentence (``classify_fetch_failure``,
the pipeline's ``_failure_reason``, the markets classifier and the law verdict) read the masked sentence as they read the old one.
Where an exception's own words follow the URL and quote it (requests writes "Failed to parse: https://u:pw@..."), the URL's userinfo
is taken out of those words too (``userinfo_secrets``, Steward 3 #1), and the two DEBUG lines about the robots cache and the host
schedule write their key masked (Steward 3 #2).

The credentials are fake (``alice:hunter2``). Nothing leaves the machine: the server is loopback, and ``files.example`` only ever
appears in a redirect the fetcher refuses before it connects. Two guards are stood down for the loopback server, and only in
the tests that reach it: ``_guard_target`` is stubbed on the fetcher instance and ``OO_SSRF_CONNECT_GUARD=0`` is set, because
both exist to refuse exactly this (a fetch reaching 127.0.0.1), and here 127.0.0.1 stands in for a public host.
"""

from __future__ import annotations

import contextlib
import http.server
import logging
import os
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
import requests

import src.ingest as ingest
from src.ingest import (
    EthicalFetcher,
    FetchError,
    FetchFailed,
    RobotsDisallowed,
    RobotsUnavailable,
    clear_kill_switch,
)
from src.ingest.fetch_verdict import (
    USERINFO_MASK,
    classify_fetch_failure,
    failure_netloc,
    failure_url,
    is_kill_switch_refusal,
    userinfo_secrets,
)
from src.monitoring.secret_scrub import REDACTED, record_text

_CRED = "alice:hunter2@"
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy")
_ROBOTS = b"User-agent: *\nDisallow: /private\n"
_MAX = 1024


@pytest.fixture(autouse=True)
def _offline_env(monkeypatch):
    """No proxy from the environment (requests reads every "*_proxy" variable, and a sandbox can set a dozen, so the loopback server
    is reached directly), the switch clear around each case."""
    for var in {*_PROXY_VARS, *(v for v in os.environ if v.lower().endswith("_proxy")), "OO_FETCH_MODE", "OO_HTTP_PROXY", "OO_HTTP_PROXIES"}:
        monkeypatch.delenv(var, raising=False)
    clear_kill_switch()
    yield
    clear_kill_switch()


class _Handler(http.server.BaseHTTPRequestHandler):
    """HTTP/1.0, so a body sent without a Content-Length runs to the close. Routes by path; ``robots_status`` is set per server."""

    robots_status = 200

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - the base class's name
        pass

    def _answer(self, status: int, body: bytes = b"", *, ctype: str = "text/html", length: int | None = None, headers: dict | None = None) -> None:
        with contextlib.suppress(OSError):  # the fetcher hangs up on an oversize or slow body by design
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            if length is not None:
                self.send_header("Content-Length", str(length))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - the base class's name
        path = self.path
        if path == "/robots.txt":
            self._answer(self.robots_status, _ROBOTS if self.robots_status == 200 else b"", ctype="text/plain", length=len(_ROBOTS) if self.robots_status == 200 else 0)
        elif path == "/401":
            self._answer(401, b"no", length=2, headers={"WWW-Authenticate": 'Basic realm="r620"'})
        elif path == "/404":
            self._answer(404, b"no", length=2)
        elif path == "/pdf":
            self._answer(200, b"%PDF-1.4", ctype="application/pdf", length=8)
        elif path == "/declared":
            self._answer(200, b"x" * (4 * _MAX), length=4 * _MAX)
        elif path == "/streamed":
            self._answer(200, b"x" * (4 * _MAX))  # no Content-Length: the size is found only by reading
        elif path == "/slow":
            with contextlib.suppress(OSError):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.flush()
                time.sleep(0.3)
                self.wfile.write(b"<p>late</p>")
        elif path == "/loop":
            self._answer(302, length=0, headers={"Location": "/loop"})
        elif path.startswith("/ftp"):
            target = f"ftp://{_CRED if path == '/ftp-cred' else ''}files.example/x"
            self._answer(302, length=0, headers={"Location": target})
        else:
            self._answer(200, b"<p>ok</p>", length=9)


@contextlib.contextmanager
def _server(robots_status: int = 200) -> Iterator[int]:
    handler = type("Handler", (_Handler,), {"robots_status": robots_status})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, name="r620-loopback", daemon=True)
    t.start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(5)


def _fetcher(tmp_path, **kw) -> EthicalFetcher:
    f = EthicalFetcher(min_interval_s=0, retry_backoff_s=0, max_retries=0, robots_cache_path=tmp_path / "robots.json", **kw)
    f._guard_target = lambda *_a, **_k: None  # type: ignore[method-assign]  # the loopback server stands in for a public host
    return f


#: id -> (path, fetch keyword arguments, fetcher keyword arguments, robots status, exception class, the sentence for a written URL ``{u}``)
_REAL: dict[str, tuple[str, dict[str, Any], dict[str, Any], int, type[FetchError], str]] = {
    "http-401": ("/401", {}, {}, 200, FetchFailed, "HTTP 401 for {u}"),
    "http-404": ("/404", {}, {}, 200, FetchFailed, "HTTP 404 for {u}"),
    "non-html": ("/pdf", {"require_html": True}, {}, 200, FetchFailed, "non-HTML content ('application/pdf') for {u}"),
    "declared-length": ("/declared", {}, {"max_bytes": _MAX}, 200, FetchFailed, f"declared length {4 * _MAX} exceeds {_MAX} bytes for {{u}}"),
    "streamed-size": ("/streamed", {}, {"max_bytes": _MAX}, 200, FetchFailed, f"response exceeds {_MAX} bytes for {{u}}"),
    "slow-body": ("/slow", {}, {"body_deadline_s": 0.05}, 200, FetchFailed, "body read exceeded 0s for {u} (a slow or trickling response)"),
    "redirect-loop": ("/loop", {}, {}, 200, FetchFailed, "too many redirects for {u}"),
    "robots-disallow": ("/private/page", {}, {}, 200, RobotsDisallowed, "robots.txt disallows {u}"),
    "robots-unavailable": ("/page", {}, {}, 500, RobotsUnavailable, "robots.txt for {h} could not be determined (server_error); refusing to fetch"),
}


def _real(tmp_path, monkeypatch, case: str, *, cred: bool) -> tuple[FetchError, str, str]:
    """The exception the real fetcher raises for ``case``, the URL it was asked for and the URL the sentence should write."""
    path, fetch_kw, fetcher_kw, robots_status, _cls, _sentence = _REAL[case]
    monkeypatch.setenv("OO_SSRF_CONNECT_GUARD", "0")  # the connect-time guard refuses 127.0.0.1 by design; here it stands in for a public host
    with _server(robots_status) as port:
        host = f"127.0.0.1:{port}"
        url = f"http://{_CRED if cred else ''}{host}{path}"
        f = _fetcher(tmp_path, **fetcher_kw)
        with pytest.raises(FetchError) as caught:
            f.fetch(url, **fetch_kw)
    written = f"http://{USERINFO_MASK if cred else ''}{host}{path}"
    return caught.value, url, written


def _expected(case: str, written: str) -> str:
    host_key = "/".join(written.split("/")[:3])  # scheme://netloc of the written URL
    return _REAL[case][5].format(u=written, h=host_key)


@pytest.mark.parametrize("case", list(_REAL))
def test_the_real_fetcher_masks_a_credentialed_url_in_the_sentence(tmp_path, monkeypatch, case):
    exc, url, written = _real(tmp_path, monkeypatch, case, cred=True)
    assert type(exc) is _REAL[case][4], f"{case}: {type(exc).__name__}: {record_text(exc, typed=False)}"
    text = record_text(exc, typed=False)
    assert text == _expected(case, written), text
    assert "alice" not in text and "hunter2" not in text, text


@pytest.mark.parametrize("case", list(_REAL))
def test_the_real_fetcher_writes_an_ordinary_url_as_it_always_did(tmp_path, monkeypatch, case):
    exc, url, written = _real(tmp_path, monkeypatch, case, cred=False)
    assert written == url
    assert type(exc) is _REAL[case][4]
    assert record_text(exc, typed=False) == _expected(case, url)


def _readers(exc: FetchError) -> tuple:
    """What each reader of a fetcher sentence makes of it: the fetch-reason bucket, the pipeline's reading, the markets classifier's
    verdict and retry flag, the law board's verdict on the row track.py would write, and the anchored refusal read."""
    from src.api.law import _verdict_of
    from src.ingest.pipeline import _failure_reason
    from src.markets.csv_feeds import classify_fetch_failure as markets_verdict

    text = record_text(exc, typed=False)
    verdict, _note, retry = markets_verdict(exc)
    return classify_fetch_failure(text), _failure_reason(text), verdict, retry, _verdict_of(f"fetch error: {text}"), is_kill_switch_refusal(text)


def _raw_twin(exc: FetchError, masked_url: str, raw_url: str) -> FetchError:
    """The same exception with the sentence the fetcher wrote before R620's wider mask (the raw URL in place of the masked one)."""
    text = record_text(exc, typed=False)
    assert text.count(masked_url) == 1, text
    if isinstance(exc, RobotsUnavailable):
        return RobotsUnavailable(text.replace(masked_url, raw_url), cause=exc.cause)
    return type(exc)(text.replace(masked_url, raw_url))


@pytest.mark.parametrize("case", list(_REAL))
def test_every_reader_reads_the_masked_sentence_as_it_read_the_raw_one(tmp_path, monkeypatch, case):
    exc, url, written = _real(tmp_path, monkeypatch, case, cred=True)
    if case == "robots-unavailable":
        url, written = url.rsplit("/", 1)[0], written.rsplit("/", 1)[0]
    (tmp_path / "plain").mkdir()
    plain_exc, _, _ = _real(tmp_path / "plain", monkeypatch, case, cred=False)
    seen = _readers(exc)
    assert seen == _readers(_raw_twin(exc, written, url)), "the mask changed what a reader makes of the sentence"
    assert seen == _readers(plain_exc), "a credentialed URL reads differently from an ordinary one"
    assert seen[0] == {
        "http-401": "http_401", "http-404": "http_4xx", "non-html": "not_html", "declared-length": "too_large",
        "streamed-size": "too_large", "slow-body": "slow_body", "redirect-loop": "bad_url",
        "robots-disallow": "other", "robots-unavailable": "other",
    }[case]


# --- sentences that need no server: the URL is refused before any connection ---------------------------------------------------------


@pytest.mark.parametrize(("url", "written"), [("ftp://alice:hunter2@files.example/x", "ftp://***@files.example/x"), ("ftp://files.example/x", "ftp://files.example/x")])
def test_an_unsupported_url_is_written_masked_inside_its_repr(tmp_path, url, written):
    with pytest.raises(FetchFailed) as caught:
        _fetcher(tmp_path).fetch(url)
    text = record_text(caught.value, typed=False)
    assert text == f"unsupported or malformed URL: {written!r}", text
    assert classify_fetch_failure(text) == "bad_url"


@pytest.mark.parametrize("cred", [True, False], ids=["credentialed", "ordinary"])
def test_a_redirect_to_another_scheme_is_written_masked_inside_its_repr(tmp_path, monkeypatch, cred):
    """The URL in this sentence is the redirect's, not the caller's: a host can hand back a Location carrying a user and password."""
    monkeypatch.setenv("OO_SSRF_CONNECT_GUARD", "0")  # as above: the loopback server stands in for a public host
    with _server() as port, pytest.raises(FetchFailed) as caught:
        _fetcher(tmp_path).fetch(f"http://127.0.0.1:{port}/{'ftp-cred' if cred else 'ftp-plain'}")
    text = record_text(caught.value, typed=False)
    assert text == f"redirect to unsupported URL: {'ftp://***@files.example/x' if cred else 'ftp://files.example/x'!r}", text
    assert classify_fetch_failure(text) == "bad_url"


# --- seams: a path the real session never takes, and two log lines ---------------------------------------------------------------------


class _Held:
    """A response an injected (non-``requests``) session already holds in full: the fetcher checks its size without streaming."""

    def __init__(self, url: str, body: bytes, ctype: str = "text/html") -> None:
        self.status_code, self.url, self.content, self.headers = 200, url, body, {"Content-Type": ctype}
        self.text, self.encoding = body.decode(), "utf-8"

    def close(self) -> None:
        pass


class _InjectedSession:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}

    def get(self, url: str, **_kw: object) -> _Held:
        return _Held(url, _ROBOTS, "text/plain") if url.endswith("/robots.txt") else _Held(url, b"x" * (4 * _MAX))


@pytest.mark.parametrize(("url", "written"), [("https://alice:hunter2@a.example/big", "https://***@a.example/big"), ("https://a.example/big", "https://a.example/big")])
def test_a_held_body_over_the_cap_is_written_masked(tmp_path, url, written):
    f = EthicalFetcher(min_interval_s=0, retry_backoff_s=0, max_retries=0, max_bytes=_MAX, session=_InjectedSession(), robots_cache_path=tmp_path / "robots.json")  # type: ignore[arg-type]
    assert not f._real_session, "premise: the injected path, where the body is checked whole"
    with pytest.raises(FetchFailed) as caught:
        f.fetch(url)
    assert record_text(caught.value, typed=False) == f"response exceeds {_MAX} bytes for {written}"


@pytest.mark.parametrize(("url", "written"), [("https://alice:hunter2@example.com/a0", "https://***@example.com/a0"), ("https://example.com/a0", "https://example.com/a0")])
def test_the_archive_backfill_logs_a_failed_url_masked_inside_its_repr(tmp_path, caplog, url, written):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base, Source
    from src.ingest.archive_backfill import advance_backfill, enqueue_source

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    try:
        source = Source(name="Example News", domain="example.com", enabled=True)
        db.add(source)
        db.commit()
        state = tmp_path / "state.json"
        enqueue_source(source.id, state_path=state)

        def discover(fetcher, src, *, full_history):
            return [url]

        def ingest(session, src, u, *, fetcher):
            raise RuntimeError(f"store failed for {u}")  # an error that quotes the URL it was handed

        advance_backfill(db, fetcher=object(), per_pass=1, state_path=state, ingest_fn=ingest, discover_fn=discover)  # enumerates
        with caplog.at_level(logging.WARNING, logger="src.ingest.archive_backfill"):
            out = advance_backfill(db, fetcher=object(), per_pass=1, state_path=state, ingest_fn=ingest, discover_fn=discover)
    finally:
        db.close()
    assert out["tally"] == {"error": 1}
    lines = [r.getMessage() for r in caplog.records if r.name == "src.ingest.archive_backfill"]
    assert len(lines) == 1 and lines[0].startswith(f"archive backfill: fetching {written!r} failed: "), lines
    assert "hunter2" not in lines[0] and "alice" not in lines[0]
    quoted = url.replace("alice:hunter2", REDACTED)
    assert f"RuntimeError: store failed for {quoted}" in lines[0], lines[0]


@pytest.mark.parametrize(("url", "written"), [("https://alice:hunter2@a.example/x", "https://***@a.example/x"), ("https://a.example/x", "https://a.example/x")])
def test_the_fetchers_log_of_an_unreadable_proxy_environment_is_masked_inside_its_repr(tmp_path, monkeypatch, caplog, url, written):
    def unreadable(u: str, *_a: object, **_k: object) -> dict:
        raise RuntimeError(f"environment unreadable for {u}")  # an error that quotes the URL it was handed

    monkeypatch.setattr(requests.utils, "get_environ_proxies", unreadable)
    f = EthicalFetcher(min_interval_s=0, robots_cache_path=tmp_path / "robots.json")
    with caplog.at_level(logging.DEBUG, logger="src.ingest"):
        assert f._request_proxy_endpoints(url, None) == {}
    lines = [r.getMessage() for r in caplog.records if r.name == "src.ingest" and "environment proxies" in r.getMessage()]
    assert len(lines) == 1 and lines[0].startswith(f"could not read environment proxies for {written!r}: "), lines
    assert "hunter2" not in lines[0] and "alice" not in lines[0]
    assert f"RuntimeError: environment unreadable for {url.replace('alice:hunter2', REDACTED)}" in lines[0], lines[0]


class _RobotsOk:
    status_code, text, headers = 200, "User-agent: *\nAllow: /\n", {"Content-Type": "text/plain"}

    def __init__(self, url: str) -> None:
        self.url = url

    def close(self) -> None:
        pass


def _unpreparable(tmp_path, url: str) -> tuple[FetchFailed, list[BaseException]]:
    """The fetcher's failure for a URL requests cannot prepare, and the live requests exceptions behind it."""
    f = _fetcher(tmp_path)
    f._refuse_parser_mismatch = lambda *_a, **_k: None  # type: ignore[method-assign]
    real_get = f.session.get
    raised: list[BaseException] = []

    def get(target, **kw):
        if target.endswith("/robots.txt"):
            return _RobotsOk(target)
        try:
            return real_get(target, **kw)
        except requests.RequestException as exc:
            raised.append(exc)
            raise

    f.session.get = get  # type: ignore[method-assign,assignment]
    with pytest.raises(FetchFailed) as caught:
        f.fetch(url, require_html=False)
    return caught.value, raised


@pytest.mark.parametrize(
    ("url", "tail"),
    [
        ("https://alice:hunter2@a.example:99999/story", f"Failed to parse: https://{REDACTED}@a.example:99999/story"),
        ("https://a.example:99999/story", "Failed to parse: https://a.example:99999/story"),
    ],
    ids=["credentialed", "ordinary"],
)
def test_requests_quoting_a_url_it_cannot_prepare_has_the_userinfo_taken_out(tmp_path, url, tail):
    """The REAL ``InvalidURL`` requests raises for a port out of range, whose words quote the whole URL it was given. The live fetcher
    refuses this URL before any request (``_refuse_parser_mismatch``: urllib3 cannot parse it), so that refusal is stubbed here to let
    requests write its own words, the case the secrets exist for; no connection is attempted (requests fails while preparing)."""
    caught, raised = _unpreparable(tmp_path, url)
    assert [type(e) for e in raised] == [requests.exceptions.InvalidURL], f"premise: requests' own InvalidURL: {raised}"
    assert record_text(caught, typed=False) == f"request error for {failure_url(url)}: {tail}"


def test_a_user_under_the_scrubs_floor_withholds_the_errors_words(tmp_path):
    """A user name of three characters cannot be taken out of free text (``MIN_SECRET_CHARS``), so the scrub withholds the whole
    of an error's words that hold it, as it does for any short secret: the URL token is still masked and the sentence still reads."""
    caught, raised = _unpreparable(tmp_path, "https://bob:hunter2@a.example:99999/story")
    assert [type(e) for e in raised] == [requests.exceptions.InvalidURL], f"premise: requests' own InvalidURL: {raised}"
    text = record_text(caught, typed=False)
    assert text.startswith("request error for https://***@a.example:99999/story: "), text
    assert "bob" not in text and "hunter2" not in text and "Failed to parse" not in text, text


def test_userinfo_secrets_are_the_whole_userinfo_and_each_part():
    assert userinfo_secrets("https://alice:hunter2@a.example/x") == ("alice:hunter2", "alice", "hunter2")
    assert userinfo_secrets("https://tok3n123@a.example/x") == ("tok3n123",)
    assert userinfo_secrets("https://al\tice:hunter2@a.example/x") == ("al\tice:hunter2", "al\tice", "hunter2", "alice:hunter2", "alice")
    assert userinfo_secrets("https://a.example/x") == () and userinfo_secrets("mailto:a@b") == ()
    assert userinfo_secrets(None) == ()  # type: ignore[arg-type]  # never raises


@pytest.mark.parametrize(("key", "written"), [("https://alice:hunter2@a.example", "https://***@a.example"), ("https://a.example", "https://a.example")])
def test_the_robots_cache_log_writes_its_key_masked(tmp_path, caplog, key, written):
    """An unwritable sidecar (its directory is a regular file named for the credentialed host, so the error's own words quote the
    credentials): the DEBUG line writes the key masked and takes the userinfo out of the error."""
    blocker = tmp_path / "alice:hunter2@a.example"
    blocker.write_text("")
    with caplog.at_level(logging.DEBUG, logger="src.ingest"):
        ingest._persist_robots_entry(blocker / "robots.json", key, kind="allow", body="")
    lines = [r.getMessage() for r in caplog.records if r.name == "src.ingest" and "robots cache persistence" in r.getMessage()]
    assert len(lines) == 1 and lines[0].startswith(f"robots cache persistence failed for {written}: NotADirectoryError: "), lines
    assert ("hunter2" not in lines[0] and "alice" not in lines[0]) if key != written else "alice:hunter2@a.example" in lines[0], lines


@pytest.mark.parametrize(("netloc", "written"), [("alice:hunter2@a.example:8443", "***@a.example:8443"), ("a.example:8443", "a.example:8443")])
def test_the_host_schedule_log_writes_its_netloc_masked(tmp_path, caplog, netloc, written):
    blocker = tmp_path / "alice:hunter2@a.example"
    blocker.write_text("")
    with caplog.at_level(logging.DEBUG, logger="src.ingest"):
        ingest._persist_host_schedule(blocker / "host_schedule.json", netloc, 1.0, 2.0)
    lines = [r.getMessage() for r in caplog.records if r.name == "src.ingest" and "host schedule persistence" in r.getMessage()]
    assert len(lines) == 1 and lines[0].startswith(f"host schedule persistence failed for {written}: NotADirectoryError: "), lines
    assert ("hunter2" not in lines[0] and "alice" not in lines[0]) if netloc != written else "alice:hunter2@a.example" in lines[0], lines
    assert failure_netloc(netloc) == written


def test_each_masked_url_is_failure_urls_own_answer():
    """The sentences above write exactly what ``failure_url`` makes of the URL, so the 23 shapes its own tests pin (a backslash before
    the @, an @ in the path, whitespace, a URL it cannot read) hold for every one of these sentences too."""
    for url in ("http://alice:hunter2@127.0.0.1:8080/401", "ftp://alice:hunter2@files.example/x", "https://a.example/big"):
        assert failure_url(url) == url.replace(_CRED, USERINFO_MASK)
