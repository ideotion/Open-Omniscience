"""NET-01: the SSRF check that runs at CONNECT time, not only at guard time.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``EthicalFetcher._guard_target`` resolves the target and refuses a non-public
answer. ``requests``/``urllib3`` then resolve the SAME name again inside
``create_connection`` and connect to whatever that second answer says, so a name
whose authoritative server answers differently the second time walked straight
past the guard. LIVE-REPRODUCED against the real fetcher before the fix (a real
``requests.Session``, a resolver answering ``93.184.216.34`` at guard time and
``127.0.0.1`` at connect time): the fetch returned a loopback HTTP server's body
as a clean 200.

The file drives the SHIPPED path throughout -- the real ``EthicalFetcher``, the
real patched socket functions, the real scope -- rather than the checker
functions in isolation, because a test of a helper is not a test of its wiring.
Both mechanisms (the resolution check and the connect check) get their own
driver, because the earlier one covers the later one on the ordinary path and
would otherwise leave it unexercised.
"""

from __future__ import annotations

import http.server
import socket
import threading
from collections.abc import Iterator

import pytest

import src.ingest.airplane as ap
from src.ingest import BlockedTarget, EthicalFetcher, clear_kill_switch
from src.ingest.ssrf_guard import (
    BlockedConnectTarget,
    check_connect_target,
    check_resolution,
    connect_scope,
    current_scope,
)

_PUBLIC = "93.184.216.34"


# --------------------------------------------------------------------------- #
# harness
# --------------------------------------------------------------------------- #


#: Every request line the loopback server saw, so a proxied test can prove the
#: request really travelled through the proxy (an absolute-form request line)
#: rather than passing for some other reason.
_REQUEST_LINES: list[str] = []


class _Handler(http.server.BaseHTTPRequestHandler):
    """Answers anything, including an absolute-form request line (proxy style)."""

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        _REQUEST_LINES.append(self.path)
        if "redirect" in self.path:
            self.send_response(302)
            self.send_header("Location", "http://internal.test/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = b"<html><body>INTERNAL SERVICE SECRET</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # silence the test log
        return


@pytest.fixture
def loopback_server() -> Iterator[int]:
    """A real HTTP server on 127.0.0.1 -- the 'internal service' an SSRF reaches."""
    _REQUEST_LINES.clear()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(srv.server_address[1])
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


@pytest.fixture
def rebinding_dns(loopback_server: int):
    """A resolver that answers PUBLIC once and then LOOPBACK -- DNS rebinding.

    Installed as ``airplane._orig_getaddrinfo`` rather than over
    ``socket.getaddrinfo`` directly, so the production hook stays in place and
    calls it: replacing ``socket.getaddrinfo`` itself would DELETE the very hook
    under test and the run would pass for the wrong reason.
    """
    was_installed = ap.is_installed()
    saved = ap._orig_getaddrinfo
    calls: list[tuple[str, object]] = []

    def _resolver(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
        if host == "rebind.test":
            calls.append((host, port))
            answer = _PUBLIC if len(calls) == 1 else "127.0.0.1"
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (answer, port or 0))]
        if host == "internal.test":
            # Always loopback: the redirect target an SSRF chases.
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port or 0))]
        return saved(host, port, *args, **kwargs)

    ap._orig_getaddrinfo = _resolver  # type: ignore[assignment]
    ap.ensure_connect_guard_installed()
    clear_kill_switch()
    try:
        yield calls
    finally:
        ap._orig_getaddrinfo = saved  # type: ignore[assignment]
        if not was_installed:
            ap.uninstall_airplane_socket_guard()


def _fetcher(**kw: object) -> EthicalFetcher:
    return EthicalFetcher(respect_robots=False, min_interval_s=0.0, timeout=5, **kw)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# the defect itself
# --------------------------------------------------------------------------- #


def test_a_name_that_rebinds_to_loopback_is_refused_end_to_end(
    loopback_server: int, rebinding_dns: list
):
    """The reproduction, inverted. Before the fix this returned the loopback
    server's body with status 200 -- the guard had validated a DIFFERENT answer
    than the one the connection used."""
    fetcher = _fetcher()
    with pytest.raises(BlockedTarget) as excinfo:
        fetcher.fetch(f"http://rebind.test:{loopback_server}/")
    assert "non-public address" in str(excinfo.value)
    assert "127.0.0.1" in str(excinfo.value)
    # Anti-vacuity: the refusal must come from the SECOND lookup, i.e. the guard
    # really did pass on the first one. A single call would mean the pre-fetch
    # check refused it and this test proves nothing about connect time.
    assert len(rebinding_dns) >= 2, f"only {len(rebinding_dns)} resolution(s): {rebinding_dns}"
    assert rebinding_dns[0][1] is None, "the first lookup is _guard_target's own"


def test_the_refusal_is_the_public_blocked_target_type(loopback_server: int, rebinding_dns: list):
    """Callers already catch ``FetchError``/``BlockedTarget``; a connect-time
    refusal must not arrive as a different, unhandled type, and must not be
    dressed up as a transient network error the retry loop would re-attempt."""
    from src.ingest import FetchError

    with pytest.raises(FetchError):
        _fetcher().fetch(f"http://rebind.test:{loopback_server}/")


def test_the_operator_opt_out_really_opts_out(
    loopback_server: int, rebinding_dns: list, monkeypatch
):
    """``OO_SSRF_CONNECT_GUARD=0`` must genuinely disable the guard. A flag that
    quietly does nothing is worse than no flag: an operator who sets it to
    diagnose a refusal would conclude the refusal came from somewhere else."""
    monkeypatch.setenv("OO_SSRF_CONNECT_GUARD", "0")
    result = _fetcher().fetch(f"http://rebind.test:{loopback_server}/")
    assert result.status_code == 200
    assert "INTERNAL SERVICE SECRET" in result.content


# --------------------------------------------------------------------------- #
# each mechanism gets its own driver
# --------------------------------------------------------------------------- #


def test_the_resolution_check_is_what_fires_on_the_ordinary_path(
    loopback_server: int, rebinding_dns: list
):
    """Which of the two nets caught it is a fact worth pinning: on the direct
    path the resolution check sees the bad answer BEFORE any socket is opened,
    so no connection to the internal service is ever attempted -- not even a
    completed TCP handshake that is then dropped."""
    seen: dict[str, object] = {}
    fetcher = _fetcher()
    real_get = fetcher.session.get

    def _spy(*a, **k):  # noqa: ANN002, ANN003
        seen["scope_before"] = current_scope()
        return real_get(*a, **k)

    fetcher.session.get = _spy  # type: ignore[method-assign]
    with pytest.raises(BlockedTarget):
        fetcher.fetch(f"http://rebind.test:{loopback_server}/")
    scope = seen["scope_before"]
    assert scope is not None, "the fetch never entered a connect scope"
    assert scope.stood_down == "", f"the guard stood down: {scope.stood_down!r}"
    assert scope.resolutions_checked >= 1, "the resolution hook was never reached"
    assert scope.connects_checked == 0, (
        "a socket was opened toward the internal address before it was refused"
    )


def test_the_connect_check_refuses_through_the_real_patched_socket():
    """The connect check's own driver. The resolution check covers the ordinary
    path, so without this the LAST gate -- the one that validates the address
    actually handed to the kernel, whatever produced it -- would ship
    unexercised. Driven through the shipped ``socket.socket.connect`` patch, not
    by calling the checker."""
    was_installed = ap.is_installed()
    ap.ensure_connect_guard_installed()
    try:
        with connect_scope(enabled=True, proxies=None) as scope:
            sock = socket.socket()
            try:
                with pytest.raises(BlockedConnectTarget):
                    sock.connect(("127.0.0.1", 9))
            finally:
                sock.close()
            assert scope.connects_checked >= 1
            assert scope.refusals
    finally:
        if not was_installed:
            ap.uninstall_airplane_socket_guard()


def test_a_public_address_passes_both_checks_and_is_counted():
    """The negative-space twin at the check level: an over-eager guard that
    refused public addresses would look 'conservative' while breaking every
    fetch. The counters prove the checks RAN rather than that they were absent."""
    with connect_scope(enabled=True, proxies=None) as scope:
        check_connect_target((_PUBLIC, 443))
        check_resolution(
            "news.example",
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (_PUBLIC, 443))],
        )
    assert scope.connects_checked == 1
    assert scope.resolutions_checked == 1
    assert scope.refusals == []


# --------------------------------------------------------------------------- #
# the guard may not break a working configuration
# --------------------------------------------------------------------------- #


def test_a_proxied_fetch_through_a_loopback_proxy_still_works(
    loopback_server: int, rebinding_dns: list
):
    """The documented protected-mode shape (``127.0.0.1:9050``) is loopback, so a
    naive 'refuse non-public addresses during a fetch' rule would refuse Tor
    itself. The proxy endpoint is allowlisted and the fetch completes -- driven
    end to end with a real proxy-style HTTP server on loopback."""
    fetcher = _fetcher(proxy=f"http://127.0.0.1:{loopback_server}")
    result = fetcher.fetch("http://rebind.test/")
    assert result.status_code == 200
    assert "INTERNAL SERVICE SECRET" in result.content
    # Anti-vacuity: an absolute-form request line is what an HTTP proxy receives,
    # so this proves the request really went THROUGH the allowlisted endpoint
    # rather than reaching the server by some other route.
    assert any(line.startswith("http://rebind.test") for line in _REQUEST_LINES), _REQUEST_LINES


def test_a_redirect_hop_to_an_internal_host_refuses_as_a_blocked_target(
    loopback_server: int, rebinding_dns: list
):
    """A redirect hop re-runs ``_guard_target``, and that runs INSIDE the scope --
    so the resolution check fires from within it and the refusal has to be
    translated there too. Scoping the translation to the GET alone let this one
    escape as a ``BlockedConnectTarget``, a type no caller catches, on a path
    that is refused for exactly the same reason. Found by the negative-space
    pass, not by any test written for the happy path."""
    fetcher = _fetcher(proxy=f"http://127.0.0.1:{loopback_server}")
    with pytest.raises(BlockedTarget):
        fetcher.fetch("http://rebind.test/?redirect=1")
    # Anti-vacuity: the first hop must really have been served, or this is just
    # the pre-fetch check refusing and the redirect path is untested.
    assert any("redirect=1" in line for line in _REQUEST_LINES), _REQUEST_LINES


def test_the_proxy_allowlist_is_keyed_on_the_PORT_not_just_the_address():
    """Allowlisting a loopback proxy by ADDRESS alone would open every port on
    the machine -- which is most of what an SSRF is for."""
    with connect_scope(enabled=True, proxies={"http": "http://127.0.0.1:9050"}) as scope:
        check_connect_target(("127.0.0.1", 9050))  # the proxy itself: allowed
        with pytest.raises(BlockedConnectTarget):
            check_connect_target(("127.0.0.1", 9051))  # one port over: refused
    assert scope.refusals == ["127.0.0.1:9051"]


def test_a_proxy_that_comes_only_from_the_ENVIRONMENT_is_allowlisted_too(
    loopback_server: int, rebinding_dns: list, monkeypatch
):
    """``session.proxies`` is NOT the answer to "what will requests connect to".
    ``Session.merge_environment_settings`` folds in ``HTTP(S)_PROXY`` whenever
    ``trust_env`` is set, which is the default -- so a guard that read only the
    session would refuse the proxy connection of every operator whose proxy comes
    from their environment, which is a security guard breaking a working
    configuration. Measured in this sandbox, which is itself such an environment."""
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{loopback_server}")
    fetcher = _fetcher()
    assert fetcher.session.proxies == {}, "this must be the ENVIRONMENT path, not the session one"
    result = fetcher.fetch("http://rebind.test/")
    assert result.status_code == 200
    assert any(line.startswith("http://rebind.test") for line in _REQUEST_LINES), _REQUEST_LINES


def test_a_hostname_proxy_stands_the_guard_down_with_a_stated_reason():
    """Allowlisting a hostname endpoint would mean resolving it from inside a
    socket hook on every fetch. Standing down is the honest answer, and the
    REASON has to be readable -- a silent stand-down is indistinguishable from a
    guard that is simply not working."""
    with connect_scope(enabled=True, proxies={"http": "socks5://tor.lan:9050"}) as scope:
        check_connect_target(("127.0.0.1", 9050))  # no refusal while stood down
    assert "hostname" in scope.stood_down
    assert scope.connects_checked == 0


def test_an_injected_session_stands_the_guard_down():
    """``_guard_target`` already exempts an injected test double (no real socket,
    and tests legitimately use loopback stand-in hosts). The two must agree, or a
    suite that passes ``session=`` would start failing on the loopback URLs it
    has always used."""
    with connect_scope(enabled=False, proxies=None) as scope:
        check_connect_target(("127.0.0.1", 80))
    assert scope.stood_down
    assert scope.connects_checked == 0


def test_the_scope_is_unwound_even_when_the_fetch_raises(
    loopback_server: int, rebinding_dns: list
):
    """A refusal must not leave the guard armed on a pooled worker thread, or the
    next unrelated request on that thread would be judged by a stale scope."""
    with pytest.raises(BlockedTarget):
        _fetcher().fetch(f"http://rebind.test:{loopback_server}/")
    assert current_scope() is None


def test_the_scope_is_re_entrant():
    """A nested scope pushes its own frame; leaving it restores the outer one."""
    with connect_scope(enabled=True, proxies={"http": "http://127.0.0.1:9050"}) as outer:
        with connect_scope(enabled=False, proxies=None) as inner:
            assert current_scope() is inner
        assert current_scope() is outer


# --------------------------------------------------------------------------- #
# the two gates share ONE patch layer -- and stay independent
# --------------------------------------------------------------------------- #


def test_installing_for_ssrf_does_not_arm_airplane_mode(monkeypatch):
    """``OO_AIRPLANE_SOCKET_GUARD=0`` is an opt-out for a deployment that proxies
    loopback. The SSRF guard installs the SAME patch points on its own account,
    so airplane's refusal has to be armed separately -- otherwise that opt-out
    would silently stop working the day this guard shipped."""
    from src.ingest import activate_kill_switch

    was_installed = ap.is_installed()
    was_armed = ap._airplane_armed
    try:
        ap.uninstall_airplane_socket_guard()
        monkeypatch.setenv("OO_AIRPLANE_SOCKET_GUARD", "0")
        assert ap.install_airplane_socket_guard() is False
        assert ap.ensure_connect_guard_installed() is True
        assert ap.is_installed() is True, "the SSRF guard did not install the patches"
        assert ap._airplane_armed is False, "airplane mode armed itself through the opt-out"
        activate_kill_switch()
        # Patched, kill switch engaged, and STILL no airplane refusal: exactly
        # what the operator asked for by setting the flag.
        try:
            socket.getaddrinfo("localhost", 80)
        except ap.AirplaneModeError:  # pragma: no cover - the regression
            pytest.fail("OO_AIRPLANE_SOCKET_GUARD=0 no longer disables the refusal")
    finally:
        clear_kill_switch()
        ap.uninstall_airplane_socket_guard()
        if was_installed:
            monkeypatch.undo()
            ap.install_airplane_socket_guard()
            ap._airplane_armed = was_armed
