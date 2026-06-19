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

Disable with ``OO_AIRPLANE_SOCKET_GUARD=0`` (e.g. an exotic deployment that proxies
loopback). The guard never blocks while the kill switch is OFF.
"""

from __future__ import annotations

import ipaddress
import os
import socket

from src.ingest import kill_switch_active


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
    """Raise if the kill switch is engaged and ``host`` is non-loopback."""
    if not kill_switch_active():
        return
    if _is_local_host(host):
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
    _installed = False


def is_installed() -> bool:
    return _installed
