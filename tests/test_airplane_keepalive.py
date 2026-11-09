"""Airplane mode refuses a request on a keep-alive connection opened before the Stop (R638).

The socket guard (``src/ingest/airplane.py``) met every connection at resolve, connect or tunnel time. A pooled keep-alive connection
opened while the switch was clear had already passed those points, so after a Stop an origin-form request written to it went out: the
independent read of R636 probed it with ``requests`` (200, then 200 with the switch engaged, refused only on a new connection).

These tests pin the closure: the request is refused at ``http.client.HTTPConnection.putrequest`` before a byte is written, whatever the
client (http.client, urllib.request, requests/urllib3), including a Stop that lands after the caller's own switch check; a tunnelled
connection is refused whatever name it carries; local destinations still work; and ``activate_kill_switch`` empties the pools of the
fetcher's own sessions. A connection to a remote host is simulated by a connection object NAMED for that host whose socket is a loopback
listener (or, end to end, by treating loopback as remote the way the R636 probe did), so nothing leaves the machine.
"""

from __future__ import annotations

import http.client
import socket
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import src.ingest as ingest
import src.ingest.airplane as ap
from src.ingest import activate_kill_switch, clear_kill_switch, kill_switch_active
from src.ingest.airplane import (
    AirplaneModeError,
    install_airplane_socket_guard,
    uninstall_airplane_socket_guard,
)


class _Recorder:
    """A loopback listener that records every byte any connection sends it and answers each request keep-alive."""

    def __init__(self) -> None:
        self.received = bytearray()
        self._srv = socket.socket()
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(8)
        self._srv.settimeout(0.2)
        self.port = self._srv.getsockname()[1]
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._accept = threading.Thread(target=self._run, daemon=True)
        self._accept.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                c, _ = self._srv.accept()
            except OSError:
                continue
            t = threading.Thread(target=self._serve, args=(c,), daemon=True)
            self._threads.append(t)
            t.start()

    def _serve(self, c: socket.socket) -> None:
        c.settimeout(0.5)
        pending = b""
        try:
            while not self._stop.is_set():
                try:
                    chunk = c.recv(65536)
                except TimeoutError:
                    continue
                if not chunk:
                    return
                self.received += chunk
                pending += chunk
                while b"\r\n\r\n" in pending:
                    _, pending = pending.split(b"\r\n\r\n", 1)
                    c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        except OSError:
            pass
        finally:
            c.close()

    def connected_socket(self) -> socket.socket:
        """A socket already connected to this listener: stands in for a keep-alive connection opened before the Stop."""
        return socket.create_connection(("127.0.0.1", self.port), timeout=2)

    def close(self) -> None:
        self._stop.set()
        self._accept.join(2)
        for t in self._threads:
            t.join(2)
        self._srv.close()


@pytest.fixture
def real_guard():
    """The REAL guard (no spies: the bytes must really not be written); the guard's prior state is put back."""
    was_installed, was_armed = ap.is_installed(), ap._airplane_armed
    install_airplane_socket_guard()
    clear_kill_switch()
    try:
        yield
    finally:
        clear_kill_switch()
        uninstall_airplane_socket_guard()
        if was_installed:
            ap._install_patches()
        ap._airplane_armed = was_armed


@pytest.fixture
def recorder(real_guard):
    r = _Recorder()
    try:
        yield r
    finally:
        r.close()


def _open_connection(recorder: _Recorder, host: str, *, tunnel: str | None = None) -> http.client.HTTPConnection:
    """An http.client connection named for ``host`` whose socket was opened (while online) to the loopback recorder."""
    conn = http.client.HTTPConnection(host, 80, timeout=2)
    if tunnel is not None:
        conn.set_tunnel(tunnel, 443)
    conn.sock = recorder.connected_socket()
    return conn


# --------------------------------------------------------------------------- #
# http.client: the patch point itself
# --------------------------------------------------------------------------- #


def test_a_connection_opened_before_stop_cannot_send_after_it(recorder):
    """The gap as found: the connection works online, and after the Stop the next request on the SAME open connection is refused with
    zero further bytes written."""
    conn = _open_connection(recorder, "example.com")
    conn.request("GET", "/first")
    assert conn.getresponse().read() == b"ok"
    before = bytes(recorder.received)
    assert before.startswith(b"GET /first HTTP/1.1\r\n")

    activate_kill_switch()
    with pytest.raises(AirplaneModeError):
        conn.request("GET", "/second")
    clear_kill_switch()
    conn.close()
    recorder.close()
    assert bytes(recorder.received) == before, "a request went out on a pre-Stop keep-alive connection in airplane mode"


def test_a_stop_between_the_callers_switch_read_and_the_send_is_refused(recorder):
    """The caller checked the switch (clear) and then the Stop landed before it wrote the request: the request is still refused, because
    the switch is read again where the request is written."""
    conn = _open_connection(recorder, "example.com")
    assert not kill_switch_active()  # the caller's own check
    activate_kill_switch()  # the Stop lands here
    with pytest.raises(AirplaneModeError):
        conn.request("GET", "/x")
    clear_kill_switch()
    conn.close()
    recorder.close()
    assert bytes(recorder.received) == b""


@pytest.mark.parametrize("tunnel_host", ["example.com", "localhost", "127.0.0.1"])
def test_a_tunnelled_connection_is_refused_whatever_it_names(recorder, tunnel_host):
    """A connection that tunnels through a loopback proxy reaches a destination only the proxy knows; once the tunnel is up, its requests
    are origin-form on an allowed loopback socket, so the destination is the tunnel host and, through a proxy, never local."""
    conn = _open_connection(recorder, "127.0.0.1", tunnel=tunnel_host)
    activate_kill_switch()
    with pytest.raises(AirplaneModeError):
        conn.request("GET", "/x")
    clear_kill_switch()
    conn.close()
    recorder.close()
    assert bytes(recorder.received) == b""


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_local_destinations_still_work_in_airplane_mode(recorder, host):
    """The app's own server and a loopback Ollama are local: a keep-alive connection to one keeps working with airplane mode engaged."""
    conn = _open_connection(recorder, host)
    activate_kill_switch()
    conn.request("GET", "/local")
    assert conn.getresponse().read() == b"ok"
    conn.close()
    assert bytes(recorder.received).startswith(b"GET /local HTTP/1.1\r\n")


def test_the_refusal_names_no_part_of_the_host(recorder):
    """Fixed words (R142): a connection built from a string that still carries userinfo must not put it in a log."""
    conn = _open_connection(recorder, "user:secret@example.com")
    activate_kill_switch()
    with pytest.raises(AirplaneModeError) as exc:
        conn.request("GET", "/x")
    conn.close()
    assert "secret" not in str(exc.value) and "example.com" not in str(exc.value)
    assert "airplane mode is engaged" in str(exc.value)


def test_a_connection_with_no_readable_host_fails_closed(real_guard):
    """An unreadable destination is not local."""

    class _Odd(http.client.HTTPConnection):
        pass

    conn = _Odd("example.com")
    conn.host = None  # type: ignore[assignment]
    assert ap._connection_destination(conn) == ap._CONNECTION_TARGET
    conn.host = b"localhost"  # type: ignore[assignment]
    assert ap._connection_destination(conn) is None


def test_a_socks_proxied_socket_is_not_local():
    """A connection whose socket is a PySocks socket with a proxy set is proxied, whatever host the connection names."""

    class _Sock:
        proxy = (2, "127.0.0.1", 9050, True, None, None)

    conn = http.client.HTTPConnection("localhost")
    conn.sock = _Sock()  # type: ignore[assignment]
    assert ap._connection_destination(conn) == ap._PROXIED_TARGET
    _Sock.proxy = (None, None, None, True, None, None)  # PySocks' "no proxy set"
    assert ap._connection_destination(conn) is None


def test_the_check_is_transparent_while_online(recorder):
    conn = _open_connection(recorder, "example.com")
    conn.request("GET", "/x")
    assert conn.getresponse().read() == b"ok"
    conn.close()


def test_without_the_destination_check_the_request_goes_out(recorder, monkeypatch):
    """Remove the guard, a test fails: with the connection-destination check answering "local", the pre-Stop connection sends again."""
    monkeypatch.setattr(ap, "_connection_destination", lambda conn: None)
    conn = _open_connection(recorder, "example.com")
    activate_kill_switch()
    conn.request("GET", "/leak")
    conn.getresponse().read()
    clear_kill_switch()
    conn.close()
    assert b"GET /leak HTTP/1.1\r\n" in bytes(recorder.received)


# --------------------------------------------------------------------------- #
# End to end: requests/urllib3 and urllib.request over a real pooled connection
# --------------------------------------------------------------------------- #


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    seen: list[str] = []

    def do_GET(self) -> None:  # noqa: N802 - the stdlib's name
        type(self).seen.append(self.path)
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a: object) -> None:
        pass


@pytest.fixture
def server(real_guard, monkeypatch):
    """A keep-alive loopback HTTP server, with loopback treated as a REMOTE host for the guard (the R636 probe's method), so a new
    connection to it would be refused by the connect guard exactly as a remote one is. Nothing leaves the machine."""
    for name in ("no_proxy", "NO_PROXY", "http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)
    _Handler.seen = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    real_is_local = ap._is_local_host
    monkeypatch.setattr(ap, "_is_local_host", lambda host: False)
    try:
        yield srv.server_address[1]
    finally:
        monkeypatch.setattr(ap, "_is_local_host", real_is_local)
        srv.shutdown()
        srv.server_close()


def test_requests_pooled_connection_is_refused_after_stop(server):
    """The R636 probe, made a test: a plain ``requests.Session`` (not a fetcher's, so nothing closes its pool) reuses its keep-alive
    connection after the Stop, and the request is refused before the server sees it."""
    import requests

    with requests.Session() as s:
        s.trust_env = False
        assert s.get(f"http://127.0.0.1:{server}/robots.txt", timeout=5).status_code == 200
        activate_kill_switch()
        with pytest.raises(requests.exceptions.ConnectionError, match="airplane mode is engaged"):
            s.get(f"http://127.0.0.1:{server}/x", timeout=5)
    clear_kill_switch()
    assert _Handler.seen == ["/robots.txt"]


def test_requests_stop_inside_the_adapter_send_is_refused(server):
    """The race end to end: the Stop lands after requests has prepared the request and taken the decision to send it (inside the
    adapter's ``send``, before urllib3 writes), so every switch check above the socket said "clear"."""
    import requests
    from requests.adapters import HTTPAdapter

    class _StopThenSend(HTTPAdapter):
        armed = False

        def send(self, request, *args, **kwargs):  # type: ignore[no-untyped-def,override]
            if self.armed:
                activate_kill_switch()
            return super().send(request, *args, **kwargs)

    adapter = _StopThenSend()
    with requests.Session() as s:
        s.trust_env = False
        s.mount("http://", adapter)
        assert s.get(f"http://127.0.0.1:{server}/first", timeout=5).status_code == 200
        adapter.armed = True
        assert not kill_switch_active()
        with pytest.raises(requests.exceptions.ConnectionError, match="airplane mode is engaged"):
            s.get(f"http://127.0.0.1:{server}/second", timeout=5)
    clear_kill_switch()
    assert _Handler.seen == ["/first"]


def test_urllib_keepalive_connection_is_refused_after_stop(server):
    """urllib.request opens a connection per request, so its keep-alive case is an http.client connection held by the caller; the same
    patch point refuses it."""
    conn = http.client.HTTPConnection("127.0.0.1", server, timeout=5)
    conn.request("GET", "/first")
    assert conn.getresponse().read() == b"ok"
    activate_kill_switch()
    with pytest.raises(AirplaneModeError):
        conn.request("GET", "/second")
    with pytest.raises(OSError, match="airplane mode is engaged"):
        urllib.request.urlopen(f"http://127.0.0.1:{server}/third", timeout=5)
    clear_kill_switch()
    conn.close()
    assert _Handler.seen == ["/first"]


def test_stop_closes_the_pooled_connections_of_the_fetchers_sessions(server):
    """``activate_kill_switch`` empties the pools of every EthicalFetcher session, so no keep-alive connection is left idle to reuse;
    the closed session stays usable once the switch is cleared."""
    from src.ingest import EthicalFetcher

    fetcher = EthicalFetcher(respect_robots=False)
    fetcher.session.trust_env = False
    assert fetcher.session in ingest._FETCHER_SESSIONS
    assert fetcher.session.get(f"http://127.0.0.1:{server}/first", timeout=5).status_code == 200
    adapter = fetcher.session.get_adapter("http://127.0.0.1/")
    assert len(adapter.poolmanager.pools) == 1

    activate_kill_switch()
    assert len(adapter.poolmanager.pools) == 0, "the fetcher session kept a pooled connection after the Stop"
    clear_kill_switch()

    assert fetcher.session.get(f"http://127.0.0.1:{server}/after", timeout=5).status_code == 200
    assert _Handler.seen == ["/first", "/after"]


def test_closing_a_session_that_raises_does_not_stop_the_stop(monkeypatch):
    """The Stop completes whatever one session does."""
    import requests

    class _Boom(requests.Session):
        def close(self) -> None:
            raise RuntimeError("boom")

    good = requests.Session()
    bad = _Boom()
    monkeypatch.setattr(ingest, "_FETCHER_SESSIONS", type(ingest._FETCHER_SESSIONS)())
    ingest._register_fetcher_session(bad)
    ingest._register_fetcher_session(good)
    try:
        activate_kill_switch()
        assert kill_switch_active()
        assert ingest._close_fetcher_pools() == 1
    finally:
        clear_kill_switch()
