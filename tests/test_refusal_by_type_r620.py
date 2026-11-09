"""
The fetcher reads the socket guard's refusal by TYPE, never by words, and reports it as the switch's whole sentence (R620, Steward 3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``EthicalFetcher`` walks the live ``requests`` exception for an ``airplane.AirplaneModeError`` instance (``__cause__``, the
exceptions among ``args``, urllib3's ``MaxRetryError.reason``; bounded, never through text) and, when it finds one, raises
``FetchFailed(KILL_SWITCH_REFUSAL)`` at once: no retry and no host's text. The class has one constructor, ``airplane._guard``, which
raises only while the switch is engaged, so a host cannot produce an instance; it can only write words. The walk does NOT follow
``__context__`` (the independent read's S1): that link is whatever the CALLER was handling when the request raised, so a fetch made
inside the handler of a Stopped fetch or of a bare guard refusal, with the switch clear, stays its own host's failure.

The shapes come from the REAL guard through REAL requests and urllib3 and a proxy on 127.0.0.1: directly (R616's), at a loopback
proxy's CONNECT (R620's, in tests/test_refusal_r620.py), and a plain ``http://`` request line to a loopback proxy (R619's, PR #1855:
driven through R619's REAL ``putrequest`` guard, and skipped on a branch whose socket guard has no such patch point; the shape is
also built from the real classes below, measured at #1855's head b4d743668). A proxy that answers in the guard's words, a class that
is only named like the guard's, and an ordinary ``OSError`` stay request errors. The credentials are fake (``alice:hunter2``);
nothing leaves the machine.
"""

from __future__ import annotations

import http.client
import os
import socket

import pytest
import requests
import urllib3
from urllib3.exceptions import MaxRetryError, ProtocolError

import src.ingest as ingest
from src.ingest import (
    EthicalFetcher,
    FetchFailed,
    activate_kill_switch,
    airplane,
    clear_kill_switch,
    kill_switch_active,
)
from src.ingest.airplane import AirplaneModeError
from src.ingest.fetch_verdict import (
    KILL_SWITCH_REFUSAL,
    KILL_SWITCH_REFUSAL_HEAD,
    USERINFO_MASK,
    classify_fetch_failure,
    failure_url,
    is_kill_switch_refusal,
)
from src.ingest.pipeline import _failure_reason
from src.monitoring.secret_scrub import record_text
from tests.test_refusal_r620 import _GUARD_WORDS, _PROXY_VARS, _loopback_proxy

_URL = "https://alice:hunter2@a.example/story"


@pytest.fixture(autouse=True)
def _armed(monkeypatch):
    """The guard armed as boot arms it (put back as found), no proxy from the environment, the switch clear around each case."""
    for var in {*_PROXY_VARS, *(v for v in os.environ if v.lower().endswith("_proxy")), "OO_FETCH_MODE", "OO_HTTP_PROXY", "OO_HTTP_PROXIES"}:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(airplane, "_airplane_armed", airplane._airplane_armed)  # restored at teardown
    assert airplane.install_airplane_socket_guard()
    clear_kill_switch()
    yield
    clear_kill_switch()


class _Robots:
    status_code, text, headers = 200, "User-agent: *\nAllow: /\n", {"Content-Type": "text/plain"}

    def __init__(self, url: str) -> None:
        self.url = url

    def close(self) -> None:
        pass


def _fetch(tmp_path, url: str, *, proxy: str | None, engage: int = 1, max_retries: int = 0) -> tuple[str, list[BaseException], int, int]:
    """``EthicalFetcher.fetch(url)`` with the robots read answered here and the switch engaged around the first ``engage`` page requests
    (after the fetcher's own check passed, so the real guard is what refuses). Returns the sentence, the live requests exceptions, the
    number of page requests and the number of back-off sleeps."""
    f = EthicalFetcher(proxy=proxy, min_interval_s=0, retry_backoff_s=0, max_retries=max_retries, robots_cache_path=tmp_path / "robots.json")
    f._guard_target = lambda *_a, **_k: None  # type: ignore[method-assign]  # no lookup: the host is *.example
    real_get = f.session.get
    raised: list[BaseException] = []
    pages: list[str] = []
    sleeps: list[float] = []

    def get(target, **kw):
        if target.endswith("/robots.txt"):
            return _Robots(target)
        pages.append(target)
        if len(pages) <= engage:
            activate_kill_switch()
        try:
            return real_get(target, **kw)
        except requests.RequestException as exc:
            raised.append(exc)
            raise
        finally:
            clear_kill_switch()

    f.session.get = get  # type: ignore[method-assign,assignment]
    f._sleep = sleeps.append  # type: ignore[method-assign,assignment]
    with pytest.raises(FetchFailed) as caught:
        f.fetch(url, require_html=False)
    assert not kill_switch_active()
    return record_text(caught.value, typed=False), raised, len(pages), len(sleeps)


def _readers(text: str) -> tuple:
    """What each reader of the fetcher's sentence makes of it: the fetch-reason bucket, the pipeline's reading, and the head read that
    R614's ``refused_by_name`` (the robots read) and law/track's offline check make."""
    return classify_fetch_failure(text), _failure_reason(text), text.startswith(KILL_SWITCH_REFUSAL_HEAD)


def _r619_guard() -> object | None:
    """R619's ``putrequest`` wrapper when the socket guard patches that call on this branch (PR #1855), else ``None``: read from the
    guard's own list of patch points, so the test below drives the real one wherever it exists and never a stand-in."""
    for owner, attr, wrapper, *_ in airplane._patch_points():
        if owner is http.client.HTTPConnection and attr == "putrequest":
            return wrapper
    return None


def _real_refusal() -> AirplaneModeError:
    """An instance the real guard made: the one way to get one."""
    activate_kill_switch()
    try:
        airplane._guard("a.example")
    except AirplaneModeError as exc:
        return exc
    finally:
        clear_kill_switch()
    raise AssertionError("premise: the armed guard refuses a remote host while the switch is engaged")


# --- the real shapes, through the fetcher ------------------------------------------------------------------------------------------------


def test_a_plain_http_request_line_refused_at_a_loopback_proxy_is_the_whole_refusal_sentence(tmp_path):
    """R619's shape, through R619's REAL ``putrequest`` guard. No NewConnectionError and no "Connection aborted.": urllib3 wraps the
    refusal as a proxy failure (it came before the connection to the proxy was made) inside MaxRetryError, and requests raises its
    ProxyError. No reader's words read it; its type does. Until #1855 lands the guard has no ``putrequest`` point and this skips; the
    shape test built from the real classes (below) holds the walk to it meanwhile."""
    wrapper = _r619_guard()
    if wrapper is None:
        pytest.skip("R619's putrequest guard (PR #1855) is not among airplane._patch_points() on this branch")
    assert http.client.HTTPConnection.putrequest is wrapper, "premise: the armed guard has R619's wrapper in place"
    url = "http://alice:hunter2@a.example/story"
    with _loopback_proxy() as (proxy, seen):
        text, raised, pages, _ = _fetch(tmp_path, url, proxy=proxy)
    assert seen == [], f"premise: nothing reached the proxy: {seen}"
    assert pages == 1 and len(raised) == 1, (pages, raised)
    live = raised[0]
    assert type(live) is requests.exceptions.ProxyError, type(live)
    retried = live.args[0]
    assert type(retried) is MaxRetryError and type(retried.reason) is urllib3.exceptions.ProxyError, retried
    assert type(retried.reason.args[1]) is AirplaneModeError and retried.reason.args[1].args[0].startswith(_GUARD_WORDS)
    words = f"request error for {failure_url(url)}: {record_text(live, typed=False)}"
    assert "(Caused by ProxyError('Unable to connect to proxy', AirplaneModeError(" in words, f"premise: {words}"
    assert not is_kill_switch_refusal(words) and classify_fetch_failure(words) == "connect", "premise: no alternative reads its words"
    assert text == KILL_SWITCH_REFUSAL, text
    assert _readers(text) == ("offline", "offline", True)


def test_a_stop_cut_directly_is_the_whole_refusal_sentence(tmp_path):
    """R616's shape (NewConnectionError, the refusal as its ``__cause__``), for an http URL as well as the https one R620's file covers."""
    text, raised, pages, _ = _fetch(tmp_path, "http://alice:hunter2@a.example/story", proxy=None)
    assert pages == 1 and record_text(raised[0], typed=False).startswith("HTTPConnectionPool(host='a.example', port=80): "), raised
    assert text == KILL_SWITCH_REFUSAL, text


def test_the_typed_refusal_is_never_retried(tmp_path):
    """Retries allowed and the switch cleared after the first request: the refusal is raised at once, with no back-off and no second
    request (which would go out under a clear the person made after this request was refused)."""
    with _loopback_proxy() as (proxy, seen):
        text, raised, pages, sleeps = _fetch(tmp_path, _URL, proxy=proxy, max_retries=2)
    assert text == KILL_SWITCH_REFUSAL, text
    assert pages == 1 and sleeps == 0 and seen == [b""], (pages, sleeps, seen)


def test_an_ordinary_connection_failure_stays_a_request_error_and_is_retried(tmp_path):
    """The proxy closes the CONNECT without a word: an OSError chain with no refusal in it, read as the host's (``connect``), retried
    as a transient failure, and written with the URL masked."""
    with _loopback_proxy() as (proxy, seen):
        text, raised, pages, sleeps = _fetch(tmp_path, _URL, proxy=proxy, engage=0, max_retries=1)
    assert pages == 2 and sleeps == 1 and len(seen) == 2, (pages, sleeps, seen)
    assert not any(ingest._carries_airplane_refusal(e) for e in raised)
    assert text.startswith(f"request error for https://{USERINFO_MASK}a.example/story: "), text
    assert "hunter2" not in text and not is_kill_switch_refusal(text) and classify_fetch_failure(text) == "connect", text


def _closed_port() -> int:
    """A loopback port nothing listens on: a connect to it is a real ECONNREFUSED, a host's failure and nobody's switch."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _reaches(exc: BaseException, target: BaseException) -> bool:
    """Premise only: whether ``target`` stands anywhere in ``exc``'s chain when ``__context__`` IS followed (bounded, by identity)."""
    todo: list[object] = [exc]
    seen: set[int] = set()
    while todo and len(seen) < 256:
        node = todo.pop()
        if not isinstance(node, BaseException) or id(node) in seen:
            continue
        if node is target:
            return True
        seen.add(id(node))
        todo += [node.__cause__, node.__context__, *node.args, getattr(node, "reason", None)]
    return False


def _host_failure_inside_a_handler(tmp_path, monkeypatch, held: BaseException) -> None:
    """Called from inside an ``except`` that holds ``held``: a fetch of a closed loopback port with the switch CLEAR, retried once. The
    connect-time SSRF guard is stood down (``OO_SSRF_CONNECT_GUARD=0``) and the pre-fetch check stubbed in ``_fetch``, because both
    exist to refuse 127.0.0.1, which stands in here for a host that refuses the connection."""
    monkeypatch.setenv("OO_SSRF_CONNECT_GUARD", "0")
    url = f"http://alice:hunter2@127.0.0.1:{_closed_port()}/story"
    text, raised, pages, sleeps = _fetch(tmp_path, url, proxy=None, engage=0, max_retries=1)
    assert raised and all(_reaches(e, held) for e in raised), "premise: the handled exception is in each request error's __context__"
    assert pages == 2 and sleeps == 1, (pages, sleeps)
    assert not any(ingest._carries_airplane_refusal(e) for e in raised)
    assert text.startswith(f"request error for {failure_url(url)}: HTTPConnectionPool(host='127.0.0.1', "), text
    assert "hunter2" not in text and not is_kill_switch_refusal(text) and classify_fetch_failure(text) == "connect", text
    assert _readers(text) == ("connect", "connect", False), (text, _readers(text))


def test_a_fetch_inside_the_handler_of_a_stopped_fetch_stays_its_hosts_failure(tmp_path, monkeypatch):
    """S1, the probe made a test: a fallback fetch run in the ``except FetchFailed`` of a Stopped fetch. The Stop's sentence is raised
    ``from None``, which hides the requests error from a traceback but leaves it as ``__context__``, so that error, the refusal inside
    it, sat one ``__context__`` link behind the NEW request's own error."""
    stopped = EthicalFetcher(min_interval_s=0, retry_backoff_s=0, max_retries=0, robots_cache_path=tmp_path / "stopped.json")
    stopped._guard_target = lambda *_a, **_k: None  # type: ignore[method-assign]
    real_get = stopped.session.get

    def get(target, **kw):
        if target.endswith("/robots.txt"):
            return _Robots(target)
        activate_kill_switch()
        try:
            return real_get(target, **kw)
        finally:
            clear_kill_switch()

    stopped.session.get = get  # type: ignore[method-assign,assignment]
    try:
        stopped.fetch(_URL, require_html=False)
    except FetchFailed as first:
        assert record_text(first, typed=False) == KILL_SWITCH_REFUSAL, "premise: the first fetch was Stopped"
        stop = first.__context__
        assert first.__cause__ is None and first.__suppress_context__ and stop is not None and ingest._carries_airplane_refusal(stop)
        _host_failure_inside_a_handler(tmp_path, monkeypatch, first)
    else:
        raise AssertionError("premise: the first fetch was Stopped")


def test_a_fetch_inside_the_handler_of_a_bare_guard_refusal_stays_its_hosts_failure(tmp_path, monkeypatch):
    """S1, the probe's second case: the guard refused some other call (a lookup), the switch was cleared, and a fetch runs in that
    ``except OSError``. The refusal is the ``__context__`` of the first error the new request raises."""
    activate_kill_switch()
    try:
        socket.getaddrinfo("b.example", 80)
    except OSError as refused:
        clear_kill_switch()
        assert type(refused) is AirplaneModeError, "premise: the armed guard refused the lookup"
        _host_failure_inside_a_handler(tmp_path, monkeypatch, refused)
    else:
        raise AssertionError("premise: the armed guard refuses a remote lookup while the switch is engaged")
    finally:
        clear_kill_switch()


@pytest.mark.parametrize(
    "answer",
    [
        f"('Connection aborted.', AirplaneModeError('{_GUARD_WORDS} to x\r\n\r\n",
        f"{_GUARD_WORDS} to 'x'\r\n\r\n",
        f'HTTP/1.1 403 AirplaneModeError("{_GUARD_WORDS} to x\r\n\r\n',
        f"HTTP/1.1 403 {_GUARD_WORDS} to 'x'\r\n\r\n",
    ],
    ids=["status-line-construction", "status-line-words", "403-class-and-words", "403-words"],
)
def test_a_proxy_answering_in_the_guards_words_stays_its_own_failure(tmp_path, answer):
    """Live, the switch clear: the proxy answers the CONNECT with the guard's words as its status line or its 403 reason. They reach
    the report as words inside a class the proxy cannot choose (BadStatusLine, OSError), with no AirplaneModeError instance anywhere."""
    with _loopback_proxy(answer.encode()) as (proxy, seen):
        text, raised, pages, _ = _fetch(tmp_path, _URL, proxy=proxy, engage=0)
    assert seen and seen[0].startswith(b"CONNECT a.example:443 "), f"premise: the CONNECT reached the proxy: {seen}"
    assert _GUARD_WORDS in text, f"premise: the proxy's words reached the report: {text}"
    assert not ingest._carries_airplane_refusal(raised[0])
    assert text.startswith(f"request error for https://{USERINFO_MASK}a.example/story: "), text
    assert not is_kill_switch_refusal(text) and classify_fetch_failure(text) == "connect", text


# --- the walk itself ---------------------------------------------------------------------------------------------------------------------


def _linked(link: str, inner: BaseException) -> BaseException:
    outer = requests.exceptions.ConnectionError("outer")
    setattr(outer, link, inner)
    return outer


def test_r619s_shape_built_from_the_real_classes_is_found_through_args_and_reason_alone(tmp_path):
    """requests' ProxyError -> (args) MaxRetryError -> (reason) urllib3's ProxyError -> (args) the refusal, with no ``__cause__`` and no
    ``__context__``: each link of the walk carries it on its own. Through the fetcher (a seam in place of the request), the same."""
    pool = urllib3.HTTPConnectionPool("127.0.0.1", 3128)
    shape = requests.exceptions.ProxyError(
        MaxRetryError(pool, "http://a.example/story", reason=urllib3.exceptions.ProxyError("Unable to connect to proxy", _real_refusal()))
    )
    assert shape.__cause__ is None and shape.__context__ is None and shape.args[0].__cause__ is None
    assert ingest._carries_airplane_refusal(shape)
    f = EthicalFetcher(min_interval_s=0, retry_backoff_s=0, max_retries=2, respect_robots=False, robots_cache_path=tmp_path / "robots.json")
    f._guard_target = lambda *_a, **_k: None  # type: ignore[method-assign]
    calls: list[str] = []

    def http_get(url, **_kw):
        calls.append(url)
        raise shape

    f._http_get = http_get  # type: ignore[method-assign,assignment]
    with pytest.raises(FetchFailed) as caught:
        f.fetch(_URL, require_html=False)
    assert record_text(caught.value, typed=False) == KILL_SWITCH_REFUSAL and calls == [_URL]


def test_the_refusal_is_found_through_cause_alone():
    assert ingest._carries_airplane_refusal(_linked("__cause__", _real_refusal()))
    assert not ingest._carries_airplane_refusal(_linked("__cause__", OSError(f"{_GUARD_WORDS} to 'x'")))


def test_the_context_link_is_not_followed():
    """S1: ``__context__`` is the exception the caller was handling when this one was raised, which can come from outside the request,
    so a real refusal behind it, at the top or deeper, is not this request's."""
    assert not ingest._carries_airplane_refusal(_linked("__context__", _real_refusal()))
    inner = OSError("[Errno 111] Connection refused")
    inner.__context__ = _real_refusal()
    assert not ingest._carries_airplane_refusal(requests.exceptions.ConnectionError(ProtocolError("Connection aborted.", inner)))
    inner.__cause__ = inner.__context__
    assert ingest._carries_airplane_refusal(requests.exceptions.ConnectionError(ProtocolError("Connection aborted.", inner)))


def test_the_walk_stops_at_its_depth_and_ends_on_a_loop():
    def nested(depth: int) -> BaseException:
        node: BaseException = _real_refusal()
        for _ in range(depth):
            node = _linked("__cause__", node)
        return node

    assert ingest._carries_airplane_refusal(nested(ingest._REFUSAL_WALK_DEPTH))
    assert not ingest._carries_airplane_refusal(nested(ingest._REFUSAL_WALK_DEPTH + 1))
    a, b = OSError("a"), OSError("b")
    a.__cause__, b.__cause__ = b, a
    assert not ingest._carries_airplane_refusal(requests.exceptions.ConnectionError(a))


class _Mute(OSError):
    """An exception that cannot be read as text: the walk must not need to."""

    def __str__(self) -> str:
        raise RuntimeError("no text")

    def __repr__(self) -> str:
        raise RuntimeError("no text")


def test_the_walk_reads_type_not_text():
    mute = _Mute()
    mute.__cause__ = _real_refusal()
    assert ingest._carries_airplane_refusal(requests.exceptions.ConnectionError(ProtocolError("Connection aborted.", mute)))

    class AirplaneModeError(OSError):  # named like the guard's on purpose: a name is words too
        pass

    named = AirplaneModeError(f"{_GUARD_WORDS} to 'a.example'")
    assert not ingest._carries_airplane_refusal(requests.exceptions.ConnectionError(ProtocolError("Connection aborted.", named)))


def test_every_reader_reads_the_whole_sentence_as_the_switchs():
    """The sentence the typed read raises, read with the switch clear (so from the sentence, not from the switch): ``_OFFLINE_RE``'s
    first alternative, the pipeline's ``_failure_reason``, and the head read of R614's ``refused_by_name`` and law/track."""
    assert not kill_switch_active()
    assert is_kill_switch_refusal(KILL_SWITCH_REFUSAL)
    assert _readers(KILL_SWITCH_REFUSAL) == ("offline", "offline", True)
