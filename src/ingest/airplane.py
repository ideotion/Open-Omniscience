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
import socket
from collections.abc import Callable
from typing import Any, cast

from src.ingest import kill_switch_active
from src.ingest.egress_window import any_window_open, socket_exempt_here

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

    The egress-window exemption (see the module docstring) is checked LAST and is
    two conditions, not one: this THREAD must be inside an exempted install
    request, AND a window must still be live. The thread-local read comes first
    because it is the cheaper of the two and is false on every thread but one, so
    the ordinary refusal path costs one attribute lookup and never touches the
    window lock. Both checks are cheap by construction -- this runs on every
    ``getaddrinfo`` and every ``connect`` in the process and must never do real
    work or re-enter anything.
    """
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
_orig_socks_connect = _pysocks.socksocket.connect if _pysocks is not None else None

_installed = False


def _addr_host(address: object) -> object:
    """The host component of a connect()/create_connection() address argument."""
    if isinstance(address, (tuple, list)) and address:
        return address[0]
    return address


def _guarded_getaddrinfo(host, *args, **kwargs):  # type: ignore[no-untyped-def]
    _guard(host)
    return _orig_getaddrinfo(host, *args, **kwargs)


def _guarded_create_connection(address, *args, **kwargs):  # type: ignore[no-untyped-def]
    _guard(_addr_host(address))
    return _orig_create_connection(address, *args, **kwargs)


def _guarded_connect(self, address):  # type: ignore[no-untyped-def]
    # AF_UNIX is local IPC (a filesystem path) — never network; always allow.
    if getattr(self, "family", None) != getattr(socket, "AF_UNIX", object()):
        _guard(_addr_host(address))
    return _orig_connect(self, address)


def _guarded_connect_ex(self, address):  # type: ignore[no-untyped-def]
    if getattr(self, "family", None) != getattr(socket, "AF_UNIX", object()):
        _guard(_addr_host(address))
    return _orig_connect_ex(self, address)


def _guarded_tunnel(self):  # type: ignore[no-untyped-def]
    """Guard the stdlib's HTTP CONNECT-tunnel handshake (a plain ``http://``
    proxy scheme, e.g. Privoxy chained to Tor). The proxy TCP connect already
    went through ``_guarded_connect`` above (loopback — allowed); ``_tunnel()``
    is what actually asks the proxy to relay to the REAL destination, known
    here as ``self._tunnel_host`` before any CONNECT bytes are sent.
    """
    _guard(self._tunnel_host)
    return _orig_tunnel(self)


def _guarded_socks_connect(self, dest_pair, *args, **kwargs):  # type: ignore[no-untyped-def]
    """Guard PySocks' own ``connect()``. ``dest_pair`` is its first argument and
    IS the real destination (host, port), known synchronously before any I/O —
    guard it here so a SOCKS-proxied connection is refused exactly like a direct
    one, before the proxy TCP connect (already guarded) even happens.
    """
    _guard(_addr_host(dest_pair))
    # Only installed when the real connect exists (see install_...), so this is
    # never the None branch -- the checker cannot see that from here.
    return cast(Callable[..., Any], _orig_socks_connect)(self, dest_pair, *args, **kwargs)


def install_airplane_socket_guard() -> bool:
    """Install the process-wide backstop. Idempotent; honoured by all later sockets.

    Returns True if installed (or already installed), False if disabled by env.
    Safe to call at every boot — transparent while online.
    """
    global _installed
    if os.getenv("OO_AIRPLANE_SOCKET_GUARD", "1") == "0":
        return False
    if _installed:
        return True
    socket.getaddrinfo = _guarded_getaddrinfo  # type: ignore[assignment]
    socket.create_connection = _guarded_create_connection  # type: ignore[assignment]
    socket.socket.connect = _guarded_connect  # type: ignore[assignment]
    socket.socket.connect_ex = _guarded_connect_ex  # type: ignore[assignment]
    http.client.HTTPConnection._tunnel = _guarded_tunnel  # type: ignore[attr-defined]
    if _orig_socks_connect is not None:
        _pysocks.socksocket.connect = _guarded_socks_connect  # type: ignore[union-attr]
    _installed = True
    return True


def uninstall_airplane_socket_guard() -> None:
    """Restore the real socket calls (used by tests for isolation)."""
    global _installed
    if not _installed:
        return
    socket.getaddrinfo = _orig_getaddrinfo  # type: ignore[assignment]
    socket.create_connection = _orig_create_connection  # type: ignore[assignment]
    socket.socket.connect = _orig_connect  # type: ignore[assignment]
    socket.socket.connect_ex = _orig_connect_ex  # type: ignore[assignment]
    http.client.HTTPConnection._tunnel = _orig_tunnel  # type: ignore[attr-defined]
    if _orig_socks_connect is not None:
        _pysocks.socksocket.connect = _orig_socks_connect  # type: ignore[union-attr]
    _installed = False


def is_installed() -> bool:
    return _installed
