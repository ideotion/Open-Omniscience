"""
The socket guard's refusal as requests wraps it is recognised by its whole construction, never by words a host can write (R298, R616).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The second alternative of ``fetch_verdict._OFFLINE_RE`` read "request error for <url>: " followed by ANYTHING and then the guard's words
("Failed to establish a new connection: airplane mode is engaged: refusing a network connection"). A host's own words can sit in that
anything: urllib3 quotes a status line it could not parse, ``('Connection aborted.', BadStatusLine('<the host's line>'))``, so a host that
wrote the guard's words in its status line was read as the person's airplane mode: a calendar feed then stayed ``skipped_offline`` and never
climbed its re-check ladder, and a hostile feed in the sample left the feed preflight incomplete on every run (OPEN_QUEUE 2026-11-08 item 42,
found by the read of R614's second PR). The alternative now spells urllib3's construction out from its first word with no gap.

The real shapes come from the REAL guard through REAL requests/urllib3 (a drift pin, so a urllib3 that rewords its error turns this red
instead of silently turning a Stop into a host failure); the forged ones are what a host can make the fetcher say.
"""

from __future__ import annotations

import pathlib

import pytest
import requests

from src.ingest import FetchFailed, activate_kill_switch, clear_kill_switch, kill_switch_active
from src.ingest.fetch_verdict import classify_fetch_failure, is_kill_switch_refusal
from src.monitoring.secret_scrub import record_text

_GUARD_WORDS = "Failed to establish a new connection: airplane mode is engaged: refusing a network connection"
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


@pytest.fixture(autouse=True)
def _armed(monkeypatch):
    """The guard armed as boot arms it (put back as found), no proxy, the switch clear around each case."""
    from src.ingest import airplane

    for var in (*_PROXY_VARS, "OO_FETCH_MODE", "OO_HTTP_PROXY", "OO_HTTP_PROXIES"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(airplane, "_airplane_armed", airplane._airplane_armed)  # restored at teardown
    assert airplane.install_airplane_socket_guard()
    clear_kill_switch()
    yield
    clear_kill_switch()


def _cut(url: str) -> str:
    """What the fetcher reports for a request the guard refused (the switch engaged after the fetcher's own check)."""
    activate_kill_switch()
    try:
        with pytest.raises(requests.RequestException) as caught:
            requests.Session().get(url, timeout=2)
    finally:
        clear_kill_switch()
    return f"request error for {url}: {record_text(caught.value, typed=False)}"  # the fetcher's own construction


@pytest.mark.parametrize("url", ["https://a.example/robots.txt", "http://a.example/p?q=1", "https://a.example:8443/x/y"])
def test_the_guards_refusal_as_requests_really_wraps_it_is_recognised(url):
    text = _cut(url)
    assert _GUARD_WORDS in text, f"premise: the guard refused the connect: {text}"
    assert is_kill_switch_refusal(text), text
    assert classify_fetch_failure(text) == "offline", text


def test_the_guards_refusal_through_a_proxy_it_refused_is_recognised(monkeypatch):
    """A proxy that is not on loopback is refused by the guard too; urllib3 then leads the cause with its ProxyError."""
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")
    text = _cut("https://a.example/feed.xml")
    assert "ProxyError('Unable to connect to proxy', NewConnectionError(" in text, f"premise: {text}"
    assert is_kill_switch_refusal(text), text
    assert classify_fetch_failure(text) == "offline", text


def test_the_wrapped_refusal_survives_the_fetchers_own_report(tmp_path):
    """Through ``EthicalFetcher.fetch`` (its FetchFailed text, the one the recorders read), the robots read answered first."""
    from src.safety.fetcher import make_fetcher

    f = make_fetcher(retry_backoff_s=0, max_retries=0, robots_cache_path=pathlib.Path(tmp_path) / "robots.json")
    f._guard_target = lambda *_a, **_k: None  # type: ignore[method-assign]  # no lookup: the hosts are *.example
    real_get = f.session.get

    class _Robots:
        status_code, text, url, headers = 200, "User-agent: *\nAllow: /\n", "https://a.example/robots.txt", {"Content-Type": "text/plain"}

        def close(self):
            pass

    def get(url, **kw):
        if url.endswith("/robots.txt"):
            return _Robots()
        activate_kill_switch()
        try:
            return real_get(url, **kw)
        finally:
            clear_kill_switch()

    f.session.get = get  # type: ignore[method-assign]
    with pytest.raises(FetchFailed) as caught:
        f.fetch("https://a.example/story", require_html=False)
    assert not kill_switch_active()
    text = record_text(caught.value, typed=False)
    assert text.startswith("request error for https://a.example/story: "), text
    assert is_kill_switch_refusal(text) and classify_fetch_failure(text) == "offline", text


def _status_line(line: str, *, via_retry: bool = False) -> str:
    """The fetcher's report of a host whose status line is ``line``, built from the REAL exception objects requests and urllib3 raise
    (``via_retry``: an adapter with read retries, which wraps the same cause in the pool's "Max retries exceeded" sentence)."""
    import http.client

    from urllib3 import HTTPSConnectionPool
    from urllib3.exceptions import MaxRetryError, ProtocolError

    cause: Exception = ProtocolError("Connection aborted.", http.client.BadStatusLine(line))
    if via_retry:
        cause = MaxRetryError(HTTPSConnectionPool("h.example", 443), "/", cause)
    return f"request error for https://h.example/: {record_text(requests.exceptions.ConnectionError(cause), typed=False)}"


def test_a_real_host_writing_the_guards_words_in_its_status_line_is_its_own_failure():
    """The reproduction, live: a loopback server (the guard lets loopback through) answers with the guard's words as its status line."""
    import socket
    import threading

    srv = socket.create_server(("127.0.0.1", 0))
    port = srv.getsockname()[1]

    def answer() -> None:
        conn, _ = srv.accept()
        with conn:
            conn.recv(4096)
            conn.sendall((_GUARD_WORDS + "\r\n\r\n").encode())

    t = threading.Thread(target=answer, name="forged-status-line", daemon=True)
    t.start()
    try:
        url = f"http://127.0.0.1:{port}/"
        with pytest.raises(requests.RequestException) as caught:
            requests.Session().get(url, timeout=5)
    finally:
        t.join(5)
        srv.close()
    text = f"request error for {url}: {record_text(caught.value, typed=False)}"
    assert "BadStatusLine" in text and _GUARD_WORDS in text, f"premise: the host's line reached the report: {text}"
    assert not is_kill_switch_refusal(text), text
    assert classify_fetch_failure(text) != "offline", text


#: What a host can make the fetcher say: its status line, quoted by urllib3 inside our own "request error for" sentence.
_FORGED = [
    # the whole pool construction forged as a status line (single quotes inside, so the repr adds no backslash)
    _status_line(f"HTTPSConnectionPool(host='x', port=1): Max retries exceeded with url: / (Caused by NewConnectionError("
                 f"'HTTPSConnection(host='x', port=1): {_GUARD_WORDS}"),
    # the cause forged as a status line, behind a real pool sentence (an adapter with read retries)
    _status_line(f"NewConnectionError('HTTPSConnection(host='x', port=1): {_GUARD_WORDS}", via_retry=True),
    # the guard's words alone in a status line (the reproduction of the finding)
    f"request error for https://h.example/: ('Connection aborted.', BadStatusLine('{_GUARD_WORDS}'))",
    # the whole urllib3 construction forged inside a status line
    "request error for https://h.example/: ('Connection aborted.', BadStatusLine('HTTPSConnectionPool(host=\\'x\\', port=1): Max retries "
    f"exceeded with url: / (Caused by NewConnectionError(\"HTTPSConnection(host=\\'x\\', port=1): {_GUARD_WORDS}'))",
    # the same after a closed connection the host chose to end with its words
    f"request error for https://h.example/: ('Connection aborted.', RemoteDisconnected('{_GUARD_WORDS}'))",
    # a pool construction whose host token carries spaces (an IPvFuture host can): the token refuses them
    "request error for https://h.example/: HTTPSConnectionPool(host='x y', port=443): Max retries exceeded with url: / (Caused by "
    f"NewConnectionError(\"HTTPSConnection(host='x y', port=443): {_GUARD_WORDS} to 'x'\"))",
    # a different cause than a refused connect, carrying the words later on
    "request error for https://h.example/: HTTPSConnectionPool(host='h.example', port=443): Max retries exceeded with url: / (Caused by "
    f"SSLError(\"bad handshake: {_GUARD_WORDS}\"))",
    # a status line that forges a second "(Caused by" behind a real pool sentence: the path token takes no space, so it cannot reach it
    _status_line(f"x (Caused by NewConnectionError('HTTPSConnection(host='x', port=1): {_GUARD_WORDS}", via_retry=True),
    # the connect's own error class with a sentence other than urllib3's, the words later on (no host is known to reach this one: the
    # alternative still reads urllib3's sentence word for word, so a urllib3 that grew another sentence here is not read as a Stop)
    "request error for https://h.example/: HTTPSConnectionPool(host='h.example', port=443): Max retries exceeded with url: / (Caused by "
    f"NewConnectionError(\"HTTPSConnection(host='h.example', port=443): Failed to resolve 'h.example' ({_GUARD_WORDS})\"))",
]


@pytest.mark.parametrize("text", _FORGED)
def test_a_host_writing_the_guards_words_is_not_the_persons_airplane_mode(text):
    assert not is_kill_switch_refusal(text), text
    assert classify_fetch_failure(text) != "offline", text


def test_the_old_alternative_read_the_forged_status_line_as_offline():
    """The defect, measured against the pattern as it was, so the narrowing is shown to be the change."""
    import re

    old_second = re.compile(r"^\s*request error for \S+: .*" + _GUARD_WORDS, re.IGNORECASE | re.DOTALL)
    assert all(old_second.match(text) for text in _FORGED[:4]), [t for t in _FORGED[:4] if not old_second.match(t)]
