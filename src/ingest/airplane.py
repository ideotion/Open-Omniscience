"""Socket-level airplane-mode backstop — the airtight half of the kill switch.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The global kill switch (``src.ingest.activate_kill_switch`` / airplane mode) is
checked at the top of every *known* fetch path (the EthicalFetcher, the guarded
session factory, the Ollama client, the stats fetcher…). That is the loud,
user-friendly refusal layer. But a per-call convention is only as airtight as our
memory: a future code path, a third-party library, a stray ``urllib`` call, or a
DNS prefetch could egress while the operator believes the app is offline. The
field test of 0.09 reported exactly this suspicion — "internet traffic even after
clicking Not now" — so airplane mode must be a HARD guarantee, not a promise.

This module installs a process-wide backstop: while the kill switch is engaged,
``socket.getaddrinfo`` / ``socket.create_connection`` / ``socket.socket.connect``
refuse any **non-loopback** target. Loopback (127.0.0.0/8, ::1, ``localhost``) and
local IPC (AF_UNIX) are always allowed — that is the app's own server, the local
LLM (Ollama is loopback-only by construction), and the file-backed database, none
of which leave the machine. The guard is **transparent when online** (kill switch
cleared): it delegates straight to the real socket calls, so it costs nothing and
changes no behaviour during normal collection.

This is honesty by construction: with airplane mode engaged, no packet can reach
the network from this process, whatever the code path. The per-call refusals stay
as the friendly, explanatory layer; this is the net beneath them.

PROXIED connections (transversal audit 09, 2026-07-25) are a distinct case worth
naming: a SOCKS proxy (Tor's recommended ``socks5h://`` scheme, PySocks/
``requests[socks]``) or a plain HTTP CONNECT-tunnel proxy (``src/safety/
settings.py``'s ``http_proxy``, e.g. ``http://127.0.0.1:8118``) both connect to
the *proxy* over an already-guarded loopback socket, then negotiate the *real*
destination at an application-protocol layer the four functions above never see
(PySocks' own ``sendall``, or the stdlib's CONNECT verb) — live-reproduced as a
real bypass of this guard. Two more patches close it: PySocks' ``socksocket.
connect`` (best-effort — PySocks is an operator-installed extra, absent means
nothing to patch since no SOCKS proxying is even possible) and the stdlib's own
``http.client.HTTPConnection._tunnel`` (always available) are ALSO guarded on
their own real-destination argument, before either negotiates anything.

A PLAIN ``http://`` URL through an HTTP proxy is the third shape (R619, from a
security read of R616, 2026-11-08, live-reproduced first): urllib3 and the
stdlib's ``urllib.request`` send no CONNECT for it at all. They open the loopback
proxy socket (allowed) and write an ABSOLUTE-FORM request line,
``GET http://example.com/x HTTP/1.1``, which the proxy then forwards. ``_tunnel``
is never called, so a loopback listener standing in for Privoxy received the
whole request while airplane mode was engaged. The real destination exists only
in that request target, so ``http.client.HTTPConnection.putrequest`` -- the one
place every http.client-based client (requests/urllib3 call it through
``super()``) hands the target over, before a byte is written -- refuses, while
airplane mode is engaged, ANY target that names its own destination
(absolute-form, or a ``CONNECT`` authority). The host in it is not parsed and
a loopback name there is not exempt: a forwarding proxy chained upstream
forwards ``http://localhost/`` like any other name, and any parse that could
answer "loopback" is one a proxy can read differently. An origin-form
``/path`` goes to the host the connect guard already saw, so it is left alone.
Not covered: an HTTP client that does not sit on
``http.client`` (httpx/httpcore) -- in this tree those are the loopback-only
LLM clients, which refuse a non-loopback base URL themselves.

Disable with ``OO_AIRPLANE_SOCKET_GUARD=0`` (e.g. an exotic deployment that proxies
loopback). The guard never blocks while the kill switch is OFF.

ONE narrow exemption exists: an open EGRESS WINDOW (``src.ingest.egress_window``,
the operator-consented "install the local AI without starting the collector"
state). It is needed because the Ollama installer's resolve-and-verify step is an
IN-PROCESS HTTPS fetch, which this guard would otherwise refuse before the
installer's own gate ever ran.

That exemption is scoped as narrowly as it can be: it applies only on the THREAD
currently inside an exempted ``GuardedSession`` request, only for the duration of
that request, and only while a window is live. It is NOT process-wide -- the first
version was, on the reasoning that every real fetch path checks the kill switch
itself, and that reasoning was wrong: ``src/monitoring/preflight.py`` reaches the
network through ``EthicalFetcher``'s side doors and its plain ``requests.Session``,
meeting neither gate, so this backstop was the only thing refusing it. A
process-wide lift let an AI-install window resolve and fetch scraped-source hosts.
Thread scoping keeps the backstop in force for every thread but the installing
one.

It is deliberately NOT a host allowlist either: nearly all install traffic happens
in child processes this guard cannot see at all, so a host filter here would
police two HTTP requests while multiple GB flowed past it -- a boundary that reads
as protection without being one. See that module's docstring for the full ledger
of what is guaranteed and what is not.
"""

from __future__ import annotations

import http.client
import ipaddress
import os
import re
import socket
from collections.abc import Callable
from typing import Any, cast

from src.ingest import kill_switch_active
from src.ingest.egress_window import any_window_open, socket_exempt_here
from src.ingest.ssrf_guard import (
    check_connect_target,
    check_resolution,
)
from src.ingest.ssrf_guard import guard_enabled as ssrf_guard_enabled
from src.monitoring.native_inflight import native_call

try:
    import socks as _pysocks  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - PySocks is an operator-installed extra
    _pysocks = None  # type: ignore[assignment]


class AirplaneModeError(OSError):
    """A non-loopback connection was attempted while airplane mode is engaged.

    Subclasses ``OSError`` so existing network error handling treats it like any
    other connection failure (callers degrade loudly rather than crash).
    """


def _is_local_host(host: object) -> bool:
    """True for a target that never leaves the machine: loopback or ``localhost``.

    ``None`` / empty (a bind, or a getaddrinfo for the local service) is treated as
    local. A bare hostname other than ``localhost`` is treated as remote (we cannot
    classify it without resolving it — and resolving it would itself be the DNS
    traffic we are trying to prevent).
    """
    if host is None:
        return True
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii", "replace")
        except Exception:  # noqa: BLE001 - undecodable -> treat as remote, be safe
            return False
    if not isinstance(host, str):
        return False
    h = host.strip()
    if h == "":
        return True
    if h.lower() in ("localhost", "ip6-localhost", "localhost.localdomain"):
        return True
    # IPv6 literals may carry brackets and a zone id (fe80::1%eth0).
    h = h.strip("[]").split("%", 1)[0]
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False  # a remote hostname


def _guard(host: object) -> None:
    """Raise if the kill switch is engaged and ``host`` is non-loopback.

    Returns immediately unless the AIRPLANE half was armed by
    ``install_airplane_socket_guard`` -- the patch points below are shared with
    the connect-time SSRF guard, which installs them on its own account, and
    ``OO_AIRPLANE_SOCKET_GUARD=0`` must keep meaning exactly what it meant when
    it also prevented the patching.

    The egress-window exemption (see the module docstring) is checked LAST and is
    two conditions, not one: this THREAD must be inside an exempted install
    request, AND a window must still be live. The thread-local read comes first
    because it is the cheaper of the two and is false on every thread but one, so
    the ordinary refusal path costs one attribute lookup and never touches the
    window lock. Both checks are cheap by construction -- this runs on every
    ``getaddrinfo`` and every ``connect`` in the process and must never do real
    work or re-enter anything.
    """
    if not _airplane_armed:
        return
    if not kill_switch_active():
        return
    if _is_local_host(host):
        return
    if socket_exempt_here() and any_window_open():
        return
    raise AirplaneModeError(
        f"airplane mode is engaged: refusing a network connection to {host!r}. "
        "No packet leaves the machine while offline — turn airplane mode off to "
        "go online (the one consent popup)."
    )


# Real implementations, captured once so re-install is idempotent and uninstall
# restores exactly what was there.
_orig_getaddrinfo = socket.getaddrinfo
_orig_create_connection = socket.create_connection
_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex
# _tunnel is a private stdlib method typeshed does not declare; capturing and
# restoring it is the whole point of this backstop.
_orig_tunnel = http.client.HTTPConnection._tunnel  # type: ignore[attr-defined]
_orig_putrequest = http.client.HTTPConnection.putrequest
_orig_socks_connect = _pysocks.socksocket.connect if _pysocks is not None else None
#: The same real calls, never reassigned: a test swaps ``_orig_*`` for spies, and a call that has the stdlib's own function back in it
#: is "the guard was removed" whether or not a spy is standing in ``_orig_*`` at that moment.
_REAL_AT_IMPORT = (
    _orig_getaddrinfo,
    _orig_create_connection,
    _orig_connect,
    _orig_connect_ex,
    _orig_tunnel,
    _orig_putrequest,
    # Last, because it is the one point that may be absent: the zip in removed_while_installed pairs these with _patch_points by position.
    _orig_socks_connect,
)

_installed = False
#: True only when ``install_airplane_socket_guard`` armed the AIRPLANE refusal.
#: The patch points are shared, so "patched" and "airplane is in force" are two
#: different facts and one flag could not carry both.
_airplane_armed = False


def _addr_host(address: object) -> object:
    """The host component of a connect()/create_connection() address argument."""
    if isinstance(address, (tuple, list)) and address:
        return address[0]
    return address


def _guarded_getaddrinfo(host, *args, **kwargs):  # type: ignore[no-untyped-def]
    _guard(host)
    with native_call("dns"):
        infos = _orig_getaddrinfo(host, *args, **kwargs)
    # The SSRF half checks the ANSWER, not the question: inside a guarded fetch a
    # name that resolves to an internal address is refused here, which is the
    # only place a destination lookup performed by a library that then hands the
    # address to a proxy is visible at all.
    check_resolution(host, infos)
    return infos


def _guarded_create_connection(address, *args, **kwargs):  # type: ignore[no-untyped-def]
    _guard(_addr_host(address))
    check_connect_target(address)
    return _orig_create_connection(address, *args, **kwargs)


def _guarded_connect(self, address):  # type: ignore[no-untyped-def]
    # AF_UNIX is local IPC (a filesystem path) — never network; always allow.
    if getattr(self, "family", None) != getattr(socket, "AF_UNIX", object()):
        _guard(_addr_host(address))
        check_connect_target(address)
    with native_call("connect"):
        return _orig_connect(self, address)


def _guarded_connect_ex(self, address):  # type: ignore[no-untyped-def]
    if getattr(self, "family", None) != getattr(socket, "AF_UNIX", object()):
        _guard(_addr_host(address))
        check_connect_target(address)
    with native_call("connect"):
        return _orig_connect_ex(self, address)


def _guarded_tunnel(self):  # type: ignore[no-untyped-def]
    """Guard the stdlib's HTTP CONNECT-tunnel handshake (a plain ``http://``
    proxy scheme, e.g. Privoxy chained to Tor). The proxy TCP connect already
    went through ``_guarded_connect`` above (loopback — allowed); ``_tunnel()``
    is what actually asks the proxy to relay to the REAL destination, known
    here as ``self._tunnel_host`` before any CONNECT bytes are sent.

    A LOOPBACK tunnel host is no exemption (R619, second security read): ``CONNECT localhost:80`` goes to the proxy, and a proxy
    chained upstream forwards that name like any other, so in airplane mode every tunnel is refused. A remote host is still named in
    the refusal; a loopback one gets the neutral proxied-target words.
    """
    _guard(_proxied_destination(self._tunnel_host))
    return _orig_tunnel(self)


#: The one name ``_guard`` is handed for a request line that names its own destination. It is never local, so the refusal (and the
#: egress-window exemption) apply exactly as for a remote connect; it names no part of the target, which may carry userinfo or a signed
#: query string that must not reach a log (R142).
_PROXIED_TARGET = "a destination named in a request line (sent through a proxy)"


#: An RFC 7230 method token. Anything else (a space, a DEL) lets the METHOD carry a request target of its own:
#: ``putrequest("GET http://example.com", "/")`` writes ``GET http://example.com / HTTP/1.1``, and the stdlib rejects only \x00-\x1f.
_METHOD_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")


def _proxied_destination(host: object) -> object:
    """What ``_guard`` is handed for a destination a PROXY will reach: the host itself when it is remote (so the refusal names it, as
    it always did), the neutral marker when it is loopback, because a loopback name handed to a proxy is not local."""
    return _PROXIED_TARGET if _is_local_host(host) else host


def _names_its_own_destination(method: object, url: object) -> bool:
    """True unless the request target is origin-form (``/path``, never ``//``), exactly ``*``, or empty (``putrequest`` writes ``/``).

    The rule lists the SAFE forms and refuses the rest, rather than listing dangerous ones: ``//example.com/x``, ``example.com:80``,
    ``http:/example.com/``, ``http:example.com/`` and ``CONNECT `` with a trailing space all reached a loopback listener through a
    rule that looked for ``scheme://`` (second security read, 2026-11-08).

    Everything else -- an absolute-form ``http://host/x``, a ``CONNECT host:port`` authority, or a target that is neither -- names a
    destination for whatever is at the other end of the socket, which is only ever a proxy, to reach. Its host is deliberately NOT
    parsed: a loopback name or literal in it is not local either, because a forwarding proxy chained upstream (Privoxy with
    ``forward-socks5t``, tinyproxy with ``upstream``) hands ``http://localhost/`` to the next hop like any other name, and every parse
    that could say "loopback" is one a proxy can read differently (``http://127.0.0.1?@example.com/``, ``%2e``, ``[::1]example.com``, found in
    the Opus read of the first version of this guard).
    """
    if isinstance(method, bytes):
        method = method.decode("latin-1")
    if not isinstance(method, str) or not _METHOD_TOKEN.fullmatch(method) or method.upper() == "CONNECT":
        return True
    if isinstance(url, bytes):
        url = url.decode("latin-1")
    if not isinstance(url, str):
        return True
    origin_form = url.startswith("/") and not url.startswith("//")
    return not (url == "" or url == "*" or origin_form)


def _guarded_putrequest(self, method, url, *args, **kwargs):  # type: ignore[no-untyped-def]
    """Guard a destination named IN the request line (R619): a plain ``http://`` URL through an HTTP proxy is written as an
    absolute-form ``GET http://host/...`` to an already-allowed loopback socket, with no CONNECT and so no ``_tunnel`` call. In airplane
    mode every such target is refused, whatever host it names; an origin-form target goes to the peer the connect guard already saw.
    This runs before ``putrequest`` buffers anything, so a refusal leaves zero request bytes on the wire."""
    if _names_its_own_destination(method, url):
        _guard(_PROXIED_TARGET)
    return _orig_putrequest(self, method, url, *args, **kwargs)


def _guarded_socks_connect(self, dest_pair, *args, **kwargs):  # type: ignore[no-untyped-def]
    """Guard PySocks' own ``connect()``. ``dest_pair`` is its first argument and
    IS the real destination (host, port), known synchronously before any I/O —
    guard it here so a SOCKS-proxied connection is refused exactly like a direct
    one, before the proxy TCP connect (already guarded) even happens.
    """
    host = _addr_host(dest_pair)
    # Through a proxy, a loopback destination is the PROXY's to reach (the same reason as ``_guarded_tunnel``); with no proxy set, a
    # socksocket is a plain socket and loopback stays local.
    proxy = getattr(self, "proxy", None)
    proxied = isinstance(proxy, tuple) and bool(proxy) and proxy[0] is not None
    _guard(_proxied_destination(host) if proxied else host)
    # Only installed when the real connect exists (see install_...), so this is
    # never the None branch -- the checker cannot see that from here.
    return cast(Callable[..., Any], _orig_socks_connect)(self, dest_pair, *args, **kwargs)


def _patch_points() -> list[tuple[Any, str, Any, Any]]:
    """Each patched call as (owner, attribute, our wrapper, the real call we saved)."""
    points: list[tuple[Any, str, Any, Any]] = [
        (socket, "getaddrinfo", _guarded_getaddrinfo, _orig_getaddrinfo),
        (socket, "create_connection", _guarded_create_connection, _orig_create_connection),
        (socket.socket, "connect", _guarded_connect, _orig_connect),
        (socket.socket, "connect_ex", _guarded_connect_ex, _orig_connect_ex),
        (http.client.HTTPConnection, "_tunnel", _guarded_tunnel, _orig_tunnel),
        (http.client.HTTPConnection, "putrequest", _guarded_putrequest, _orig_putrequest),
    ]
    if _orig_socks_connect is not None:
        points.append((_pysocks.socksocket, "connect", _guarded_socks_connect, _orig_socks_connect))
    return points


def _standing_calls() -> list[Any]:
    """What each patch point holds right now, in the order of :func:`_patch_points`. A point that cannot be read (a private attribute a
    newer Python renamed) reads as ``None``, which is neither a real function nor a stand-in we know, so it is left alone, not healed."""
    calls: list[Any] = [
        getattr(socket, "getaddrinfo", None),
        getattr(socket, "create_connection", None),
        getattr(socket.socket, "connect", None),
        getattr(socket.socket, "connect_ex", None),
        getattr(http.client.HTTPConnection, "_tunnel", None),
        getattr(http.client.HTTPConnection, "putrequest", None),
    ]
    if _orig_socks_connect is not None:
        calls.append(getattr(_pysocks.socksocket, "connect", None))
    return calls


def removed_while_installed() -> list[tuple[Any, str, Any]]:
    """The patch points (owner, attribute, our wrapper) that hold a REAL function although the guard is flagged installed: whoever wrote the
    real call over our wrapper (a ``monkeypatch`` undo that recorded it before the install did exactly that to ``socket.getaddrinfo``,
    leaving ``_installed`` True with DNS unguarded) removed the guard without telling us. Only the real function (the saved one, or the
    stdlib's own) counts; anything else standing there is somebody's deliberate stand-in. Empty when the guard is not installed."""
    if not _installed:
        return []
    return [
        (owner, attr, wrapper)
        for (owner, attr, wrapper, real), at_import, standing in zip(_patch_points(), _REAL_AT_IMPORT, _standing_calls(), strict=False)
        if standing is real or standing is at_import
    ]


def _install_patches() -> None:
    """Patch the socket chokepoints. Idempotent, and the ONLY place they are
    patched -- both gates ride the same layer so a call site cannot meet one and
    miss the other, and an uninstall can never leave half of it behind.

    Once installed, a call that has the real function back in it is patched again (:func:`removed_while_installed`): a flag that says
    "installed" must not outlive a write that removed the guard."""
    global _installed
    if _installed:
        for owner, attr, wrapper in removed_while_installed():
            setattr(owner, attr, wrapper)
        return
    for owner, attr, wrapper, _real in _patch_points():
        setattr(owner, attr, wrapper)
    _installed = True


def install_airplane_socket_guard() -> bool:
    """Install the process-wide backstop. Idempotent; honoured by all later sockets.

    Returns True if installed (or already installed), False if disabled by env.
    Safe to call at every boot — transparent while online.
    """
    global _airplane_armed
    if os.getenv("OO_AIRPLANE_SOCKET_GUARD", "1") == "0":
        return False
    _install_patches()
    _airplane_armed = True
    return True


def ensure_connect_guard_installed() -> bool:
    """Install the same patch points for the connect-time SSRF guard alone.

    Called by ``EthicalFetcher`` when it enters a guarded fetch, so the SSRF half
    works in a CLI, a script, a test and a boot that never ran the app's own
    startup -- the airplane installer runs only from ``run_deferred_startup``, and
    a security guard whose presence depends on an unrelated boot path is a guard
    that is absent wherever nobody thought about it.

    NOT gated on ``OO_AIRPLANE_SOCKET_GUARD``: that flag is an opt-out from
    AIRPLANE MODE's refusal for a deployment that proxies loopback, and it keeps
    working exactly as before because ``_guard`` returns early unless
    ``install_airplane_socket_guard`` armed it. The SSRF half has its own opt-out
    (``OO_SSRF_CONNECT_GUARD=0``), read where the scope is entered.
    """
    if not ssrf_guard_enabled():
        return False
    _install_patches()
    return True


def uninstall_airplane_socket_guard() -> None:
    """Restore the real socket calls (used by tests for isolation)."""
    global _installed, _airplane_armed
    _airplane_armed = False
    if not _installed:
        return
    socket.getaddrinfo = _orig_getaddrinfo  # type: ignore[assignment]
    socket.create_connection = _orig_create_connection  # type: ignore[assignment]
    socket.socket.connect = _orig_connect  # type: ignore[assignment]
    socket.socket.connect_ex = _orig_connect_ex  # type: ignore[assignment]
    http.client.HTTPConnection._tunnel = _orig_tunnel  # type: ignore[attr-defined]
    http.client.HTTPConnection.putrequest = _orig_putrequest  # type: ignore[method-assign]
    if _orig_socks_connect is not None:
        _pysocks.socksocket.connect = _orig_socks_connect  # type: ignore[union-attr]
    _installed = False


def is_installed() -> bool:
    return _installed
