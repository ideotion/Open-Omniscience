"""
A Stop through a loopback HTTP proxy is read as the Stop, and a URL's credentials never reach the failure sentence (R620).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

(a) Over a loopback HTTP proxy (Privoxy chained to Tor) the socket guard refuses the real destination in the CONNECT tunnel, which
urllib3 opens after ``_new_conn`` returned, so the text is not the pool sentence R616 reads but "request error for <url>:
('Connection aborted.', AirplaneModeError(...))", and it read as ``connect``. ``fetch_verdict._OFFLINE_RE`` now has a fourth
alternative spelled from its first word with no gap; the real shape comes from the REAL guard through REAL requests/urllib3 and a
proxy started here, and the forged ones are what a host or a proxy can make the fetcher say. The claim the alternative rests on (a
host's words sit inside the quotes after a class name the host cannot choose) is checked against the libraries, not assumed.

(b) ``failure_url`` masks the authority's userinfo (``https://alice:hunter2@host`` is written ``https://***@host``), keeps
everything else as it did, and never raises: an input it cannot read is withheld whole.

(c) The inert ``re.DOTALL`` is gone; tests/test_kill_switch_refusal_constant.py pins the new flags.

The credentials here are fake (``alice:hunter2``), and no test sends a packet off the machine: the real hosts are loopback, the
``*.example`` targets are refused by the guard or reached only as a CONNECT line at a loopback proxy.
"""

from __future__ import annotations

import ast
import contextlib
import http.client
import os
import pathlib
import random
import re
import socket
import threading
import urllib.error
import urllib.parse

import pytest
import requests
import urllib3
import urllib3.exceptions
from urllib3.exceptions import ProtocolError
from urllib3.util import parse_url

from src.ingest import (
    EthicalFetcher,
    FetchFailed,
    activate_kill_switch,
    clear_kill_switch,
    fetch_verdict,
    kill_switch_active,
)
from src.ingest.airplane import AirplaneModeError
from src.ingest.fetch_verdict import (
    KILL_SWITCH_REFUSAL,
    UNREADABLE_URL,
    USERINFO_MASK,
    classify_fetch_failure,
    failure_url,
    is_kill_switch_refusal,
)
from src.monitoring.secret_scrub import record_text

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_GUARD_WORDS = "airplane mode is engaged: refusing a network connection"
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy")

#: The reader as R616 left it (5c5e9e117), copied so each real shape below is shown to be read BECAUSE of the new alternative.
_R616_OFFLINE_RE = re.compile(
    r"^\s*(?:[\w.]+:\s*)?(?:network kill switch is active|airplane mode is engaged: refusing a network connection)\b"
    r"|^\s*request error for \S+: (?:SOCKS)?HTTPS?ConnectionPool\(host='[^'\s\\]*', port=\d+\): Max retries exceeded with url: \S* "
    r"\(Caused by (?:ProxyError\('Unable to connect to proxy', )?NewConnectionError\([\"'](?:SOCKS(?:HTTPS)?|HTTPS?)Connection\(host='[^'\s\\]*', port=\d+\): "
    r"Failed to establish a new connection: "
    r"airplane mode is engaged: refusing a network connection"
    r"|^\s*cannot resolve host (?:'[^'\s\\]*'|\"[^\"\s\\]*\"): airplane mode is engaged: refusing a network connection",
    re.IGNORECASE | re.DOTALL,
)


@pytest.fixture(autouse=True)
def _armed(monkeypatch):
    """The guard armed as boot arms it (put back as found), no proxy from the environment, the switch clear around each case."""
    from src.ingest import airplane

    # every "*_proxy" variable, not only the usual ones: requests reads them all (``getproxies``), and a sandbox can set a dozen
    for var in {*_PROXY_VARS, *(v for v in os.environ if v.lower().endswith("_proxy")), "OO_FETCH_MODE", "OO_HTTP_PROXY", "OO_HTTP_PROXIES"}:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(airplane, "_airplane_armed", airplane._airplane_armed)  # restored at teardown
    assert airplane.install_airplane_socket_guard()
    clear_kill_switch()
    yield
    clear_kill_switch()


@contextlib.contextmanager
def _loopback_proxy(answer: bytes | None = None):
    """A stand-in for Privoxy on 127.0.0.1: each connection is accepted, what it sends up to the end of its head is kept, ``answer`` is
    written back if it sent anything, and it is closed. Yields the proxy URL and the list of what each connection sent."""
    srv = socket.create_server(("127.0.0.1", 0))
    srv.settimeout(0.2)
    seen: list[bytes] = []
    stop = threading.Event()

    def serve() -> None:
        while True:
            try:
                conn, _ = srv.accept()
            except TimeoutError:
                if stop.is_set():
                    return  # only once no connection is waiting, so none a test made is left unread
                continue
            except OSError:
                return
            with conn:
                conn.settimeout(5)
                data = b""
                with contextlib.suppress(OSError):
                    while b"\r\n\r\n" not in data:
                        chunk = conn.recv(65536)
                        if not chunk:
                            break
                        data += chunk
                seen.append(data)
                if answer is not None and data:
                    with contextlib.suppress(OSError):
                        conn.sendall(answer)

    t = threading.Thread(target=serve, name="loopback-proxy", daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.getsockname()[1]}", seen
    finally:
        stop.set()
        t.join(5)
        srv.close()


def _sentence(url: str, exc: BaseException) -> str:
    """The fetcher's own construction (``_fetch_locked`` in src/ingest/__init__.py)."""
    return f"request error for {failure_url(url)}: {record_text(exc, typed=False)}"


def _through(url: str, proxy: str, *, engaged: bool) -> str:
    """What the fetcher reports for ``url`` asked of ``proxy``, the switch engaged (after the fetcher's own check) or clear."""
    if engaged:
        activate_kill_switch()
    try:
        with pytest.raises(requests.RequestException) as caught:
            requests.Session().get(url, timeout=5, proxies={"http": proxy, "https": proxy})
    finally:
        clear_kill_switch()
    return _sentence(url, caught.value)


# --- (a) THE REAL SHAPE ----------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "quote"),
    [
        ("https://a.example/story", '"'),
        ("https://a.example:8443/x?q=1", '"'),
        ("https://[2001:db8::1]/feed.xml", '"'),
        ("https://o'k.example/x", "'"),  # a host holding a single quote: repr writes the message in single quotes
    ],
)
def test_a_stop_through_a_loopback_http_proxy_is_read_as_the_stop(url, quote):
    with _loopback_proxy() as (proxy, seen):
        text = _through(url, proxy, engaged=True)
    assert text.startswith(f"request error for {failure_url(url)}: ('Connection aborted.', AirplaneModeError({quote}{_GUARD_WORDS} to "), (
        f"premise: the real shape: {text}"
    )
    assert seen == [b""], f"premise: the proxy was reached and sent nothing, not even the CONNECT: {seen}"
    assert is_kill_switch_refusal(text), text
    assert classify_fetch_failure(text) == "offline", text
    assert not _R616_OFFLINE_RE.match(text), "the reader before R620 did not read it, so the new alternative is what reads it"


class _Robots:
    status_code, text, url, headers = 200, "User-agent: *\nAllow: /\n", "https://a.example/robots.txt", {"Content-Type": "text/plain"}

    def close(self) -> None:
        pass


@pytest.mark.parametrize("via_proxy", [False, True], ids=["direct", "loopback-proxy"])
def test_the_fetchers_report_of_a_stop_is_offline_and_carries_no_credential(tmp_path, via_proxy):
    """Through ``EthicalFetcher.fetch`` (its FetchFailed text, the one the recorders read) for a ``user:pass@`` URL. The switch is engaged
    after the fetcher's own check passed (engaged before it, the fetcher answers with its own sentence, which names no URL), so the real
    guard refuses the request and nothing leaves the machine: directly (R616's shape) or at the CONNECT a loopback proxy is asked for
    (R620's). The robots read is answered here, so the page request is the one cut. The fetcher finds the guard's refusal by TYPE in the
    live exception and reports the switch's whole sentence (R620); the text requests made of it is still read as the switch's by words,
    the net under the typed read."""
    url = "https://alice:hunter2@a.example/story"
    with contextlib.ExitStack() as stack:
        proxy = None
        if via_proxy:
            proxy, seen = stack.enter_context(_loopback_proxy())
        f = EthicalFetcher(proxy=proxy, min_interval_s=0, retry_backoff_s=0, max_retries=0, robots_cache_path=tmp_path / "robots.json")
        f._guard_target = lambda *_a, **_k: None  # type: ignore[method-assign]  # no lookup: the host is *.example
        real_get = f.session.get
        asked: list[tuple[str, object]] = []
        raised: list[BaseException] = []

        def get(target, **kw):
            asked.append((target, kw.get("proxies")))
            if target.endswith("/robots.txt"):
                return _Robots()
            activate_kill_switch()
            try:
                return real_get(target, **kw)
            except requests.RequestException as exc:
                raised.append(exc)
                raise
            finally:
                clear_kill_switch()

        f.session.get = get  # type: ignore[method-assign,assignment]
        with pytest.raises(FetchFailed) as caught:
            f.fetch(url, require_html=False)
    assert not kill_switch_active()
    assert asked[-1][0] == url, f"premise: the page was asked for with its credentials: {asked}"
    if via_proxy:
        assert asked[-1][1] == {"http": proxy, "https": proxy} and seen == [b""], f"premise: through the proxy, no CONNECT sent: {seen}"
    assert len(raised) == 1, raised
    shape = record_text(raised[0], typed=False)
    tail = "('Connection aborted.', AirplaneModeError(" if via_proxy else "HTTPSConnectionPool(host='a.example', port=443): "
    assert shape.startswith(tail), f"premise: the real guard refused this request: {shape}"
    words = f"request error for {failure_url(url)}: {shape}"
    assert "hunter2" not in words and is_kill_switch_refusal(words), words
    text = record_text(caught.value, typed=False)
    assert text == KILL_SWITCH_REFUSAL, text
    assert is_kill_switch_refusal(text) and classify_fetch_failure(text) == "offline", text


# --- (a) WHAT A HOST OR A PROXY CAN MAKE THE FETCHER SAY -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        # the whole construction as the proxy's status line (single quotes only, so repr writes it with no backslash)
        f"('Connection aborted.', AirplaneModeError('{_GUARD_WORDS} to x",
        # the class name and the guard's words
        f"AirplaneModeError(\"{_GUARD_WORDS} to 'x'\")",
        # the guard's words alone
        f"{_GUARD_WORDS} to 'x'",
    ],
    ids=["construction", "class-and-words", "words"],
)
def test_a_proxy_whose_status_line_writes_the_guards_words_is_its_own_failure(line):
    """Live: the switch clear, the CONNECT reaches the loopback proxy, which answers with the guard's words as its status line."""
    with _loopback_proxy((line + "\r\n\r\n").encode()) as (proxy, seen):
        text = _through("https://a.example/story", proxy, engaged=False)
    assert seen and seen[0].startswith(b"CONNECT a.example:443 "), f"premise: the CONNECT reached the proxy: {seen}"
    assert "('Connection aborted.', BadStatusLine(" in text and _GUARD_WORDS in text, f"premise: the line reached the report: {text}"
    assert not is_kill_switch_refusal(text), text
    assert classify_fetch_failure(text) == "connect", text


def test_a_proxy_that_refuses_the_connect_in_the_guards_words_is_its_own_failure():
    """Live: the proxy refuses the CONNECT with a 403 whose reason phrase is the class and the guard's words. http.client raises
    ``OSError('Tunnel connection failed: 403 <its words>')``, a class name the proxy cannot choose, after closing the connection, which
    clears urllib3's "connected to the proxy" flag, so the pool reports it as a proxy failure (measured: no "Connection aborted.")."""
    answer = f'HTTP/1.1 403 AirplaneModeError("{_GUARD_WORDS} to x\r\n\r\n'.encode()
    with _loopback_proxy(answer) as (proxy, seen):
        text = _through("https://a.example/story", proxy, engaged=False)
    assert seen and seen[0].startswith(b"CONNECT a.example:443 "), f"premise: the CONNECT reached the proxy: {seen}"
    assert "(Caused by ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 AirplaneModeError(" in text, (
        f"premise: {text}"
    )
    assert not is_kill_switch_refusal(text), text
    assert classify_fetch_failure(text) == "connect", text


def _aborted(cause: BaseException, url: str = "https://h.example/") -> str:
    """The fetcher's report of ``cause`` as urllib3's pool wraps it (``ProtocolError("Connection aborted.", cause)``) and requests
    re-raises it, built from the REAL exception objects."""
    return _sentence(url, requests.exceptions.ConnectionError(ProtocolError("Connection aborted.", cause)))


class AirplaneModeErrors(OSError):
    """A class whose name only STARTS with ours."""


class NotAirplaneModeError(OSError):
    """A class whose name only ENDS with ours."""


#: A feed item's link that holds spaces and goes on in the real construction.
_FORGED_LINK = f"https://evil.example/x: ('Connection aborted.', AirplaneModeError(\"{_GUARD_WORDS} to 'a'"

_FORGED = {
    # the class name and the guard's words in a host's status line
    "status-line-class-and-words": _aborted(http.client.BadStatusLine(f"AirplaneModeError(\"{_GUARD_WORDS} to 'x'\")")),
    # the guard's words alone in a status line
    "status-line-words": _aborted(http.client.BadStatusLine(f"{_GUARD_WORDS} to 'x'")),
    # the whole construction in a status line (single quotes only, so repr writes it with no backslash)
    "status-line-construction": _aborted(http.client.BadStatusLine(f"('Connection aborted.', AirplaneModeError('{_GUARD_WORDS} to x")),
    # the same led by ": ", as if the URL token went on into it
    "status-line-colon-construction": _aborted(http.client.BadStatusLine(f"x: ('Connection aborted.', AirplaneModeError('{_GUARD_WORDS} to x")),
    # an OSError carrying a proxy's reason phrase (a refused CONNECT really arrives in the pool sentence, measured live above)
    "oserror-proxy-reason": _aborted(OSError(f"Tunnel connection failed: 403 AirplaneModeError(\"{_GUARD_WORDS}")),
    # another class carrying the guard's words first
    "oserror-words": _aborted(OSError(f"{_GUARD_WORDS} to 'x'")),
    "reset-words": _aborted(ConnectionResetError(f"{_GUARD_WORDS} to 'x'")),
    "disconnected-words": _aborted(http.client.RemoteDisconnected(f"{_GUARD_WORDS} to 'x'")),
    # a class whose name holds ours
    "class-name-longer": _aborted(AirplaneModeErrors(f"{_GUARD_WORDS} to 'x'")),
    "class-name-prefixed": _aborted(NotAirplaneModeError(f"{_GUARD_WORDS} to 'x'")),
    # our class with words before the guard's, quoted (no writer says this: the alternative reads the words right after the quote, so
    # nothing may stand between the class and them)
    "ours-words-later": _aborted(AirplaneModeError(f"no packet left: '{_GUARD_WORDS} to x'")),
    # the link with spaces, behind the host's own closed connection: through failure_url (as the fetcher writes it) the URL token is the
    # whole link, so what follows the first ": " is urllib3's
    "link-with-spaces": _aborted(http.client.RemoteDisconnected("Remote end closed connection without response"), url=_FORGED_LINK),
}


@pytest.mark.parametrize("text", list(_FORGED.values()), ids=list(_FORGED))
def test_a_host_writing_the_proxied_refusal_is_not_the_persons_airplane_mode(text):
    assert not is_kill_switch_refusal(text), text
    assert classify_fetch_failure(text) != "offline", text


def test_the_link_with_spaces_would_be_read_without_failure_url():
    """Why the URL token matters to this alternative too: the same link written raw continues in our construction."""
    raw = f"request error for {_FORGED_LINK}: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))"
    assert fetch_verdict._OFFLINE_RE.match(raw), "premise: written raw, the link is read as the Stop"
    assert not is_kill_switch_refusal(_FORGED["link-with-spaces"])


# --- (a) THE CLAIM, CHECKED AGAINST THE LIBRARIES ---------------------------------------------------------------------------------------


def test_urllib3_writes_connection_aborted_in_one_place_for_an_oserror_or_an_http_exception():
    """The tuple's second item is ``new_e``, which the line before limits to an OSError or an ``http.client.HTTPException``; urllib3
    writes the words nowhere else, and requests nowhere at all."""
    pool = (pathlib.Path(str(urllib3.__file__)).parent / "connectionpool.py").read_text(encoding="utf-8")
    site = 'new_e = ProtocolError("Connection aborted.", new_e)'
    assert pool.count(site) == 1, "urllib3 moved or doubled the construction the fourth alternative reads"
    assert pool[: pool.index(site)].rstrip().endswith("elif isinstance(new_e, (OSError, HTTPException)):"), "urllib3 widened what it wraps"
    holders = [
        p.relative_to(pathlib.Path(str(pkg.__file__)).parent.parent).as_posix()
        for pkg in (urllib3, requests)
        for p in pathlib.Path(str(pkg.__file__)).parent.rglob("*.py")
        if "Connection aborted" in p.read_text(encoding="utf-8", errors="replace")
    ]
    assert holders == ["urllib3/connectionpool.py"], holders


def _fetch_path_classes() -> set[type]:
    """Every OSError and ``http.client.HTTPException`` subclass defined by the fetch path: the standard library, urllib3, requests,
    PySocks where present and this app (a class a test defines is not on it)."""
    import ssl  # noqa: F401 - its classes join the walk
    import urllib.error  # noqa: F401

    import src.ingest.ssrf_guard  # noqa: F401
    import src.safety.fetcher  # noqa: F401

    with contextlib.suppress(ImportError):
        import socks  # type: ignore[import-untyped]  # noqa: F401

    libraries = {"builtins", "io", "shutil", "signal", "socket", "ssl", "http", "urllib", "urllib3", "requests", "socks"}
    out: set[type] = set()
    stack: list[type] = [OSError, http.client.HTTPException]
    while stack:
        cls = stack.pop()
        if cls not in out:
            out.add(cls)
            stack.extend(cls.__subclasses__())
    return {c for c in out if c.__module__.split(".")[0] in libraries or c.__module__.startswith(("src.ingest", "src.safety"))}


class _Response:
    """What InvalidChunkLength reads of a response."""

    length_remaining = None

    def tell(self) -> int:
        return 0


#: The classes on the fetch path that write their own repr, each with an instance whose host-shaped field holds the guard's words.
_OWN_REPR = {
    ("http.client", "IncompleteRead"): lambda: http.client.IncompleteRead(_GUARD_WORDS.encode()),
    ("urllib3.exceptions", "IncompleteRead"): lambda: urllib3.exceptions.IncompleteRead(5, 10),
    ("urllib3.exceptions", "InvalidChunkLength"): lambda: urllib3.exceptions.InvalidChunkLength(_Response(), _GUARD_WORDS.encode()),  # type: ignore[arg-type]
    ("urllib.error", "HTTPError"): lambda: urllib.error.HTTPError("https://h.example/", 403, _GUARD_WORDS, http.client.HTTPMessage(), None),
}


def test_every_exception_on_the_fetch_path_opens_its_repr_with_its_own_name():
    """The claim the fourth alternative rests on: whatever urllib3 puts after ``('Connection aborted.', `` opens with a class name, so a
    host's words (a status line, a proxy's reason phrase) come after a name the host cannot choose. A class that writes its own repr
    must be read before it joins the table above."""
    classes = _fetch_path_classes()
    assert http.client.BadStatusLine in classes and AirplaneModeError in classes, "premise: the walk reaches the fetch path"
    own = {(c.__module__, c.__qualname__) for c in classes if c.__repr__ is not BaseException.__repr__}
    assert own == set(_OWN_REPR), f"a class on the fetch path writes its own repr; read it before adding it: {sorted(own ^ set(_OWN_REPR))}"
    for (_module, name), make in _OWN_REPR.items():
        text = repr(make())
        assert text.startswith((f"{name}(", f"<{name} ")), text
    # BaseException's own repr: the class name, then the arguments
    assert repr(http.client.BadStatusLine(_GUARD_WORDS)) == f"BadStatusLine('{_GUARD_WORDS}')"
    named = [c for c in classes if c.__name__.lower() == "airplanemodeerror"]
    assert named == [AirplaneModeError], f"one class is named AirplaneModeError, and it is ours: {named}"


def test_the_one_writer_of_an_airplane_mode_error_opens_with_the_guards_words():
    """``_guard`` is the only place under ``src/`` that builds an AirplaneModeError, and its message opens with the words the alternative
    reads right after the quote."""
    sites = []
    for path in (_ROOT / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "AirplaneModeError":
                sites.append((path.relative_to(_ROOT).as_posix(), node))
    assert [s for s, _ in sites] == ["src/ingest/airplane.py"], sites
    message = sites[0][1].args[0]
    assert isinstance(message, ast.JoinedStr) and isinstance(message.values[0], ast.Constant)
    assert message.values[0].value == f"{_GUARD_WORDS} to ", message.values[0].value


# --- (b) THE USERINFO MASK -------------------------------------------------------------------------------------------------------------

_CREDENTIALED = [
    ("https://alice:hunter2@h.example/x", "https://***@h.example/x"),
    ("https://alice@h.example/x", "https://***@h.example/x"),  # a user name alone (a token is often carried there)
    ("https://alice:@h.example/x", "https://***@h.example/x"),  # an empty password
    ("https://al%69ce:hunt%65r2@h.example/x", "https://***@h.example/x"),  # percent-encoded credentials
    ("https://alice%40corp:hunter2@h.example/x", "https://***@h.example/x"),  # an encoded "@" in the user name
    ("https://alice:hun@ter2@h.example/x", "https://***@h.example/x"),  # a raw "@" in the password: the LAST "@" ends the userinfo
    ("https://alice:hunter2@[2001:db8::1]:8443/x", "https://***@[2001:db8::1]:8443/x"),  # an IPv6 host and a port
    ("https://alice:hunter2@h.example:8443/x?q=1#f", "https://***@h.example:8443/x?q=1#f"),  # a port, a query and a fragment
    ("https://alice:hunter2@h.example?q=1", "https://***@h.example?q=1"),  # the authority ended by "?"
    ("https://alice:hunter2@h.example#f", "https://***@h.example#f"),  # and by "#"
    ("HTTP://alice:hunter2@h.example", "HTTP://***@h.example"),
    ("//alice:hunter2@h.example/x", "//***@h.example/x"),  # no scheme, an authority all the same
    (" //alice:hunter2@h.example/x", "%20//***@h.example/x"),  # and after a leading space (urllib.parse strips it)
    ("  https://alice:hunter2@h.example/x", "%20%20https://***@h.example/x"),  # leading spaces (urllib.parse and requests strip them)
    ("\u3000https://alice:hunter2@h.example/x", "%E3%80%80https://***@h.example/x"),  # an ideographic space (requests strips it)
    ("https://ali\tce:hunter2@h.example/x", "https://***@h.example/x"),  # a tab in the userinfo (urllib.parse drops it)
    ("https:/\t/alice:hunter2@h.example/x", "https:/%09/***@h.example/x"),  # a tab inside the "//" (urllib.parse drops it)
    ("https://\talice:hunter2@h.example/x", "https://***@h.example/x"),  # a tab before the userinfo goes with it
    ("https://alice hunter2@h.example/x", "https://***@h.example/x"),  # a space in the userinfo
    ("https://alice:hunter2@[::1/x", "https://***@[::1/x"),  # unbalanced brackets: urlsplit raises, the mask does not
    ("https://alice:hunt\ud800er2@h.example/x", "https://***@h.example/x"),  # a lone surrogate in the password
    ("1https://alice:hunter2@h.example/x", "1https://***@h.example/x"),  # a scheme urlsplit rejects: masked all the same
    ("https://alice:hunter2@", "https://***@"),  # no host
]


@pytest.mark.parametrize(("url", "written"), _CREDENTIALED)
def test_the_userinfo_is_masked(url, written):
    out = failure_url(url)
    assert out == written, repr(out)
    assert re.fullmatch(r"\S+", out), repr(out)
    assert "alice" not in out and "hunt" not in out and "%69" not in out, repr(out)


@pytest.mark.parametrize(("url", "written"), [(u, w) for u, w in _CREDENTIALED if not re.search(r"\s|\ud800|\[::1/|^1|@$", u)])
def test_the_masked_url_keeps_its_host_port_and_path_for_both_parsers(url, written):
    """urlsplit (what the fetcher's checks and requests' Basic credentials read) and urllib3 (what connects) see the same host, port and
    path in the written URL as in the caller's, and the mask where the userinfo was."""
    before, after = urllib.parse.urlsplit(url), urllib.parse.urlsplit(written)
    assert (after.hostname, after.port, after.path, after.query, after.fragment) == (
        before.hostname, before.port, before.path, before.query, before.fragment,
    )
    assert after.username == USERINFO_MASK[:-1] and after.password is None
    theirs, ours = parse_url(url), parse_url(written)
    assert (ours.host, ours.port, ours.path, ours.query, ours.fragment) == (theirs.host, theirs.port, theirs.path, theirs.query, theirs.fragment)
    assert ours.auth == USERINFO_MASK[:-1]


def test_a_backslash_before_the_at_is_masked_the_wider_way():
    """``https://evil.test\\@good.org/`` is ``good.org`` with userinfo ``evil.test\\`` to urlsplit and ``evil.test`` with a path to urllib3
    (the fetcher refuses it before any request, ``_refuse_parser_mismatch``); the mask takes the wider reading, so nothing either parser
    could call a credential is written."""
    assert failure_url("https://evil.test\\@good.org/") == "https://***@good.org/"


@pytest.mark.parametrize(
    "url",
    [
        "https://h.example/a@b",
        "https://h.example/@alice",
        "https://h.example/x?u=alice@h.example",
        "https://h.example#alice@h.example",
        "https://h.example?u=alice@h.example",
        "https://h.example:8443/a@b?c@d#e@f",
        "https://h.example/p;a@b//c@d",
        "mailto:alice@h.example",
        "a:b://c@d",  # scheme "a", path "b://c@d": no authority
        "https://h.example:8443/p%20q/r?x=1&y='\"()[]~@!$*+,;=#frag/\u00e9",
        "",
    ],
)
def test_an_at_that_is_not_the_authoritys_is_left_alone(url):
    assert failure_url(url) == url


class _Hostile(str):
    """A string that cannot be read."""

    def __iter__(self):
        raise RuntimeError("unreadable")


@pytest.mark.parametrize(
    "value",
    [None, b"https://alice:hunter2@h.example/x", bytearray(b"https://alice:hunter2@h/"), 42, _Hostile("https://alice:hunter2@h.example/x")],
    ids=["none", "bytes", "bytearray", "int", "unreadable-str"],
)
def test_a_url_that_cannot_be_read_is_withheld_never_raised_or_written(value):
    out = failure_url(value)  # type: ignore[arg-type]
    assert out == UNREADABLE_URL and re.fullmatch(r"\S+", out)


def _fuzz_inputs(n: int = 4000) -> list[str]:
    """Seeded, so a failure names its input: URL-shaped strings built around an authority, and strings of URL punctuation."""
    rnd = random.Random(620)
    alphabet = "aZ09:/?#@[]\\%.+- \t\r\n\x00\x7f\x85\xa0\u3000\ud800\u00e9"

    def bit(k: int) -> str:
        return "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, k)))

    out = []
    for _ in range(n):
        shape = rnd.randrange(3)
        if shape == 0:
            out.append(bit(40))
        elif shape == 1:
            out.append(rnd.choice(["https", "http", "HTTP", "x+y", "1a", "", " https"]) + rnd.choice(["://", ":/", "//", ":"])
                       + bit(8) + rnd.choice(["@", "", "@@"]) + bit(8) + rnd.choice(["/", "?", "#", ""]) + bit(8))
        else:
            out.append(rnd.choice(["https://", "//"]) + bit(6) + ":" + bit(6) + "@" + rnd.choice(["h.example", "[::1]", "[v1.x", ""])
                       + rnd.choice([":8443", ""]) + rnd.choice(["/a@b", "?q=@", "#@", ""]))
    return out


def test_failure_url_never_raises_and_masks_whatever_either_parser_calls_the_userinfo():
    """Over seeded fuzz: no input raises, no output holds whitespace, and wherever urlsplit or urllib3 reads a userinfo out of the input,
    it reads none but the mask out of the masked URL (the mask is wider than both parsers, never narrower)."""
    read_by_split = read_by_urllib3 = 0
    for url in _fuzz_inputs():
        out = failure_url(url)
        assert isinstance(out, str) and not re.search(r"\s", out), repr(url)
        span = fetch_verdict._userinfo_span(url)
        masked = url if span is None else url[: span[0]] + USERINFO_MASK + url[span[1] :]
        assert failure_url(masked) == out, repr(url)
        try:
            split = urllib.parse.urlsplit(url)
        except ValueError:
            split = None
        if split is not None and "@" in split.netloc:
            read_by_split += 1
            # the span is exactly urlsplit's userinfo and its "@", the characters urlsplit drops aside
            assert span is not None, repr(url)
            assert "".join(ch for ch in url[span[0] : span[1]] if ch not in "\t\r\n") == split.netloc.rpartition("@")[0] + "@", repr(url)
        try:
            # urllib3 as it reads a URL with a scheme (or a leading "/"); one with neither it reads as an authority, see _userinfo_span
            theirs = parse_url(url).auth if re.match(r"(?:[a-zA-Z][a-zA-Z0-9+-]*:|/)", url) else None
        except (urllib3.exceptions.LocationParseError, ValueError):
            theirs = None
        if theirs is not None:
            read_by_urllib3 += 1
            assert span is not None, repr(url)
            with contextlib.suppress(urllib3.exceptions.LocationParseError, ValueError):
                assert parse_url(masked).auth == USERINFO_MASK[:-1], repr(url)
    assert read_by_split > 200 and read_by_urllib3 > 200, f"premise: the fuzz reaches userinfo ({read_by_split}, {read_by_urllib3})"


# --- (c) NO DOTALL ---------------------------------------------------------------------------------------------------------------------


def test_the_reader_lost_nothing_with_dotall():
    """The flag is gone, and the pattern reads every text the same with it: no ``.`` in it stood outside a class or an escape."""
    assert not fetch_verdict._OFFLINE_RE.flags & re.DOTALL
    with_dotall = re.compile(fetch_verdict._OFFLINE_RE.pattern, fetch_verdict._OFFLINE_RE.flags | re.DOTALL)
    texts = [*_FORGED.values(), *(f"{t}\n{t}" for t in _FORGED.values()), f"request error for x:\n{_GUARD_WORDS}", f"{_GUARD_WORDS}\nx", "\n" + _GUARD_WORDS]
    for t in texts:
        assert bool(with_dotall.match(t)) == bool(fetch_verdict._OFFLINE_RE.match(t)), repr(t)
