"""THE loopback rule for the local AI (R762, R767): which addresses it may talk to, and the check on the socket itself.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

R767 (row 235). An address is on this computer when it is

* a loopback LITERAL (``127.0.0.0/8`` or ``::1``), or
* exactly the name ``localhost``.

Every other name is refused, including the aliases ``ip6-localhost``, ``ip6-loopback`` and
``localhost.localdomain``: those are local only when ``/etc/hosts`` says so, and where it does not
the resolver asks DNS and answers with whatever DNS says. The refusal names the literal to use.

``localhost`` itself is a name, so its answer is checked too: a request the local-AI clients send
runs inside :func:`~src.ingest.loopback_scope.loopback_only`, and the socket layer (``src.ingest.airplane``, the one patch layer
the airplane and SSRF gates already share) refuses any connect, inside that scope, to an address that
is not loopback. A connect handed a NAME inside the scope (``socket.connect(("localhost", 80))``,
which resolves in C, out of sight) is refused too, so nothing in the scope connects to an answer
nobody checked. Fail closed: an address that cannot be read as a loopback literal is refused.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

from src.ingest.loopback_scope import LOOPBACK_NAME, LoopbackConnectRefused, loopback_only

#: Names that look local but are only as local as ``/etc/hosts`` says: refused, with the literal to use instead.
_ALIAS_LITERAL = {
    "ip6-localhost": "[::1]",
    "ip6-loopback": "[::1]",
    "localhost.localdomain": "127.0.0.1",
}


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _is_loopback_literal(host: str) -> bool:
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def is_loopback_url(url: str) -> bool:
    """True when ``url``'s host is a loopback literal or exactly ``localhost`` (R767)."""
    host = _host(url)
    return host == LOOPBACK_NAME or _is_loopback_literal(host)


def alias_literal(url: str) -> str | None:
    """The loopback literal to use instead when ``url`` names a refused alias (R767), else ``None``."""
    return _ALIAS_LITERAL.get(_host(url))


def loopback_refusal(url: str, *, setting: str) -> str | None:
    """Why ``url`` is refused for the local AI, or ``None`` when it is on this computer."""
    if is_loopback_url(url):
        return None
    host = _host(url)
    literal = alias_literal(url)
    if literal is not None:
        return (
            f"{setting} names {host!r}, which is local only if this computer's hosts file says so; otherwise it is "
            f"looked up in DNS. Use {literal} instead (or localhost). The local LLM never talks to a remote host."
        )
    return (
        f"{setting} must be loopback (127.0.0.1 / localhost / ::1); got {host!r}. "
        "The local LLM never talks to a remote host."
    )


class LoopbackTransport(httpx.HTTPTransport):
    """An ``httpx`` transport whose every request runs inside :func:`loopback_only`."""

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        with loopback_only():
            return super().handle_request(request)


def connect_ex_loopback(host: str, port: int, *, timeout: float) -> int | None:
    """``connect_ex`` to ``host`` (a loopback literal or ``localhost``) on ``port``, each answer checked loopback.

    Returns 0 when something accepted, the last error number otherwise, or ``None`` when no answer could be tried."""
    last: int | None = None
    with loopback_only():
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError:
            return None
        for family, socktype, proto, _canon, sockaddr in infos:
            try:
                with socket.socket(family, socktype, proto) as s:
                    s.settimeout(timeout)
                    last = s.connect_ex(sockaddr)
            except LoopbackConnectRefused:
                continue
            except OSError:
                continue
            if last == 0:
                return 0
    return last


__all__ = [
    "LOOPBACK_NAME",
    "LoopbackConnectRefused",
    "LoopbackTransport",
    "alias_literal",
    "connect_ex_loopback",
    "is_loopback_url",
    "loopback_only",
    "loopback_refusal",
]
