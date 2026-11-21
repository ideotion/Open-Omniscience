"""The loopback-only connect scope (R767): inside it, every connect this thread makes must reach a loopback address.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Checked by the socket layer in :mod:`src.ingest.airplane` -- the one patch layer the airplane and SSRF gates already
share -- so the address checked is the address the connection is actually handed, after the name was resolved. Entered
by the local-AI clients (``src.llm.loopback``): ``localhost`` is a name, and a name answers with whatever the resolver
says, so its answer is checked here rather than trusted. Holds no socket of its own.
"""

from __future__ import annotations

import ipaddress
import threading
from collections.abc import Iterator
from contextlib import contextmanager


class LoopbackConnectRefused(OSError):
    """A connect inside :func:`loopback_only` to an address that is not on this computer.

    An ``OSError`` on purpose: ``socket.create_connection`` then tries the next answer, which is how a name with a
    loopback answer and another answer still connects to the loopback one, and every caller already treats an
    ``OSError`` as "could not connect". Nothing is ever connected past it."""


LOOPBACK_NAME = "localhost"
_state = threading.local()


def _depth() -> int:
    return int(getattr(_state, "depth", 0))


def in_scope() -> bool:
    return _depth() > 0


@contextmanager
def loopback_only() -> Iterator[None]:
    """Every connect this thread makes inside the block must reach a loopback address. Installs the socket checks
    first (not gated on ``OO_AIRPLANE_SOCKET_GUARD`` or ``OO_SSRF_CONNECT_GUARD``: those are opt-outs of other gates)."""
    from src.ingest.airplane import ensure_loopback_guard_installed

    base = _depth()
    try:
        ensure_loopback_guard_installed()
        _state.depth = base + 1
        yield
    finally:
        _state.depth = base  # idempotent: an interrupt anywhere above leaves the depth as it was found (R161 shape)


def _literal(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        ip = ipaddress.ip_address(host)  # never stripped: "[127.0.0.1]" or "127.0.0.1%x" is a NAME to the resolver
    except ValueError:
        return None
    return ip


def check_loopback_connect(address: object, *, name_allowed: bool = False) -> None:
    """Refuse, inside :func:`loopback_only`, a connect to anything but a loopback address.

    ``name_allowed`` is for ``socket.create_connection``'s outer call: it resolves the name through the patched
    ``getaddrinfo`` and connects to each NUMERIC answer through ``socket.connect``, where it is checked again. A plain
    ``socket.connect`` handed a name resolves it in C, unseen, so there any name is refused. Fail closed: an address
    that cannot be read is refused."""
    if _depth() <= 0:
        return
    host: object = address[0] if isinstance(address, (tuple, list)) and address else address
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        raise LoopbackConnectRefused(
            "refusing a local-AI connect whose address cannot be read; the local LLM only talks to this computer"
        )
    ip = _literal(host)
    if ip is not None and ip.is_loopback:
        return
    if ip is None and name_allowed and host.lower() == LOOPBACK_NAME:
        return
    raise LoopbackConnectRefused(
        f"refusing to connect to {host!r}: the local LLM only talks to this computer, and this address is not on it"
        + (" (the name localhost answered with it)" if ip is not None else "")
    )


def check_loopback_lookup(host: object) -> None:
    """Refuse, inside :func:`loopback_only`, a name lookup of anything but ``localhost`` or a loopback literal.

    The connect check alone would still let a lookup of another name leave the machine as a DNS query before the
    connect is refused; inside the scope nothing but this computer is ever looked up. Fail closed, as above."""
    if _depth() <= 0:
        return
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if isinstance(host, str):
        if host.lower() == LOOPBACK_NAME:
            return
        ip = _literal(host)
        if ip is not None and ip.is_loopback:
            return
    raise LoopbackConnectRefused(
        f"refusing to look up {host!r}: the local LLM only talks to this computer, and this name is not it"
    )
