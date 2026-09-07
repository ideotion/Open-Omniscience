"""Connect-time SSRF validation — the half ``_guard_target`` structurally cannot do.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``EthicalFetcher._guard_target`` resolves the target hostname and refuses any
answer that is loopback / RFC1918 / link-local / reserved (CWE-918). That check
is correct and it is not sufficient, because it is not the resolution the
connection uses: ``requests``/``urllib3`` resolve the same name AGAIN inside
``create_connection`` and connect to whatever THAT answer says. A name whose
authoritative server hands out a public address on the first lookup and
``127.0.0.1`` on the second — DNS rebinding, a 0-TTL round-robin, or simply an
attacker who controls the zone — walks straight past the guard.

LIVE-REPRODUCED before this module existed (2026-09-07): a real ``EthicalFetcher``
with a real ``requests.Session``, against a resolver that answered ``93.184.216.34``
for the guard's ``getaddrinfo(host, None)`` and ``127.0.0.1`` for urllib3's
``getaddrinfo(host, port, …)``, fetched a loopback HTTP server's body and returned
it as a 200. Two lookups, two answers, no error anywhere.

WHAT THIS MODULE DOES, and why it is not the "pin the validated IP" adapter the
plan named. Pinning means connecting to the IP we validated instead of the name,
which requires taking over urllib3's connection construction and then carrying
the hostname separately for SNI, certificate matching and the ``Host`` header.
That is version-fragile private API, and — the deciding argument — its failure
mode is a **silently weaker TLS verification**, i.e. fabricated security, which
this project refuses outright. Validating the address that is ACTUALLY being
connected to gets the same security property (the threat is reaching an internal
address, not reaching a different public one — CDN anycast and round-robin make a
second, different, public answer entirely normal), touches no TLS state at all,
and rides the socket chokepoint every HTTP client in this process must pass
through, so it cannot be routed around by a library change. A pinning adapter
fails OPEN when urllib3 moves; this fails CLOSED.

THE SCOPE IS THREAD- AND REQUEST-SHAPED, for the reason the egress window records
one module over: a process-wide "refuse private addresses" rule would break the
app's own loopback traffic (its server, the local LLM, the SOCKS proxy). So the
check is inert everywhere except inside an ``EthicalFetcher`` request, entered by
``_guarded_redirect_get`` — the ONE method through which the page fetch, the
robots fetch, every redirect hop and both preflight side doors reach the network.

WHAT IS AND IS NOT COVERED — stated rather than implied:

  * A DIRECT (unproxied) fetch is fully covered: every address urllib3 resolves
    is validated as it comes back, and every address it connects to is validated
    before the syscall.
  * A proxied fetch whose proxy endpoint is an IP LITERAL (``socks5://127.0.0.1:9050``
    — the documented shape) is covered the same way, with that exact
    ``(address, port)`` pair allowlisted: our socket goes to the proxy and
    nowhere else. Under a LOCAL-resolving ``socks5``/``socks4`` scheme PySocks'
    own destination lookup meets the resolution check too — read out of the
    installed library rather than assumed: ``socksocket._write_SOCKS5_address``
    (PySocks 1.7.1) takes its non-``rdns`` branch through
    ``socket.getaddrinfo(host, port, AF_UNSPEC, SOCK_STREAM, IPPROTO_TCP,
    AI_ADDRCONFIG)``, which is the patched function. That path is NOT exercised
    by a test here: PySocks is an operator-installed extra, so a test gated on it
    would skip in every lane that does not install it, which is where an
    environment-gated guard goes to die.
  * A proxied fetch whose proxy endpoint is a HOSTNAME stands the check DOWN for
    that request. Allowlisting it would mean resolving it here, inside a socket
    hook, on every fetch; refusing to guess is better than a guard that can
    break a working configuration. ``_guard_target``'s own policy is unchanged
    there, so such a deployment is exactly as protected as it was before.
  * A REMOTE-resolving proxy (``socks5h``/``socks4a``) never resolves the
    destination in this process at all — the exit does — so there is no local
    answer to validate and nothing here to cover. That is the same reason
    ``_guard_target`` skips its hostname branch under those schemes.
  * An address that is publicly routable but internal to the operator's own
    network perimeter is out of reach of any address-shape rule, here or in
    ``_guard_target``.

``OO_SSRF_CONNECT_GUARD=0`` disables it. The refusal is a plain ``Exception``
subclass on purpose: urllib3's ``create_connection`` catches ``OSError`` and
quietly tries the NEXT address, which would turn a security refusal into a
retry, and ``HTTPConnectionPool.urlopen`` would fold it into a generic
connection error. ``_guarded_redirect_get`` translates it into the public
``BlockedTarget`` at the boundary, so callers keep the exception contract they
already have.
"""

from __future__ import annotations

import ipaddress
import os
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from urllib.parse import urlparse


class BlockedConnectTarget(Exception):
    """A socket inside a guarded fetch tried to reach a non-public address.

    Deliberately NOT an ``OSError``: urllib3's ``create_connection`` loops over
    the addresses ``getaddrinfo`` returned and swallows an ``OSError`` to try the
    next one, so an ``OSError`` here would let a host that resolves to
    ``127.0.0.1`` *and* a public address be fetched anyway — while
    ``_guard_target`` refuses that same host outright. The two must agree.
    """


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for any address an external fetch should never reach (SSRF, CWE-918).

    Blocks loopback, RFC1918/ULA private, link-local (incl. 169.254.169.254 cloud
    metadata), reserved, multicast and the unspecified address.

    ONE definition, read by both halves of the guard: ``_guard_target``'s
    resolve-time check imports it from here, and so does the connect-time check
    below. Two copies of this predicate would be two answers to one question.
    """
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _as_ip(host: object) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """``host`` as an IP address, or ``None`` when it is not an IP literal.

    Never resolves: this runs inside the socket hooks, where a lookup would be
    both re-entrant and itself egress.
    """
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii", "strict")
        except UnicodeDecodeError:
            return None
    if not isinstance(host, str):
        return None
    h = host.strip().strip("[]").split("%", 1)[0]  # IPv6 brackets + zone id
    if not h:
        return None
    try:
        return ipaddress.ip_address(h)
    except ValueError:
        return None


@dataclass
class _Scope:
    """One in-flight guarded fetch on one thread."""

    #: Exact ``(address, port)`` proxy endpoints this request may reach even
    #: though they are non-public, and the bare addresses of those endpoints.
    #: The PAIR is what the connect check consults -- allowlisting a loopback
    #: proxy by address alone would open every port on the machine, which is
    #: most of what an SSRF is for. The bare-address set is consulted ONLY
    #: against the host a resolution ASKED ABOUT (resolving 127.0.0.1 answers
    #: 127.0.0.1, and refusing that would refuse the proxy itself), never
    #: against the addresses a resolution ANSWERS WITH: a hostname that resolves
    #: to the proxy's own address is precisely the attack, and skipping it there
    #: made the resolution check inert on any machine with a loopback proxy in
    #: its environment -- measured, in this sandbox, before it was fixed.
    allowed: frozenset[tuple[str, int]] = frozenset()
    allowed_hosts: frozenset[str] = frozenset()
    #: Why the check is standing down for this request, or "" when it is live.
    stood_down: str = ""
    #: Counters, so a test can prove the hook was REACHED rather than infer it
    #: from an absence. An anti-vacuity signal, never a measurement of safety.
    connects_checked: int = 0
    resolutions_checked: int = 0
    refusals: list[str] = field(default_factory=list)


_STATE = threading.local()


def guard_enabled() -> bool:
    """The operator opt-out, read once per fetch (never inside a socket hook).

    Separate from ``OO_AIRPLANE_SOCKET_GUARD``: that flag exists for a deployment
    that proxies loopback and must not be refused while offline, which says
    nothing about whether an external fetch may reach an internal address.
    """
    return os.getenv("OO_SSRF_CONNECT_GUARD", "1") != "0"


def current_scope() -> _Scope | None:
    """The scope this thread is inside, or ``None``.

    A bare thread-local attribute read: this is called from the socket hooks on
    every connect and every resolution in the process, so it must not lock,
    import, or re-enter anything. It is ``None`` on every thread but the ones
    actually fetching.
    """
    stack: list[_Scope] | None = getattr(_STATE, "stack", None)
    return stack[-1] if stack else None


_DEFAULT_PROXY_PORTS = {"http": 80, "https": 443, "socks5": 1080, "socks5h": 1080,
                        "socks4": 1080, "socks4a": 1080}


def _proxy_endpoints(proxies: object) -> tuple[frozenset[tuple[str, int]], str]:
    """``(allowed endpoints, stand-down reason)`` for a request's proxy mapping.

    A proxy endpoint given as an IP LITERAL is allowlisted as an exact
    ``(address, port)`` pair — our socket is supposed to reach it, and it is
    normally loopback. A proxy endpoint given as a HOSTNAME stands the whole
    check down for this request: allowlisting it would mean resolving it from
    inside a socket hook on every fetch, and a security guard may not break a
    working configuration in order to protect it.
    """
    if not isinstance(proxies, dict) or not proxies:
        return frozenset(), ""
    allowed: set[tuple[str, int]] = set()
    for key, value in proxies.items():
        # ``requests.utils.get_environ_proxies`` strips the ``_proxy`` suffix off
        # every matching environment variable, so ``NO_PROXY`` arrives as the key
        # ``no`` carrying a comma-separated host list -- not a proxy endpoint.
        if not value or str(key).lower() in ("no", "no_proxy"):
            continue
        try:
            parts = urlparse(str(value))
            host, port = parts.hostname, parts.port
        except ValueError:
            return frozenset(), "proxy endpoint could not be parsed"
        if not host:
            continue
        ip = _as_ip(host)
        if ip is None:
            return frozenset(), f"proxy endpoint {host!r} is a hostname, not an address"
        if port is None:
            port = _DEFAULT_PROXY_PORTS.get((parts.scheme or "").lower(), 0)
        allowed.add((str(ip), int(port)))
    return frozenset(allowed), ""


@contextmanager
def connect_scope(*, enabled: bool, proxies: object = None) -> Iterator[_Scope]:
    """Guard every socket this THREAD opens for the duration of one fetch.

    ``enabled`` mirrors ``EthicalFetcher._real_session``: an injected test double
    performs no real network I/O, and tests legitimately use loopback stand-in
    hosts, so the guard stands down there exactly as ``_guard_target`` does.

    Re-entrant (a nested scope pushes its own frame) and unwound on any
    exception, so a refusal can never leave the guard armed on a pooled thread.
    """
    allowed, reason = _proxy_endpoints(proxies)
    if not guard_enabled():
        reason = "disabled by OO_SSRF_CONNECT_GUARD=0"
    elif not enabled:
        reason = reason or "injected session: no real socket to guard"
    scope = _Scope(
        allowed=allowed,
        allowed_hosts=frozenset(addr for addr, _ in allowed),
        stood_down=reason,
    )
    stack: list[_Scope] = getattr(_STATE, "stack", [])
    if not stack:
        _STATE.stack = stack
    stack.append(scope)
    try:
        yield scope
    finally:
        stack.pop()


def _live_scope() -> _Scope | None:
    scope = current_scope()
    if scope is None or scope.stood_down:
        return None
    return scope


def check_connect_target(address: object) -> None:
    """Refuse a connect to a non-public address from inside a guarded fetch.

    Called by the socket backstop in :mod:`src.ingest.airplane` — ONE patch layer
    for both gates, so a call site cannot meet one and miss the other. Inert
    unless this thread is inside a live scope.

    ``address`` is the argument the socket call was given: a ``(host, port…)``
    tuple, or a bare host. A non-literal host is left alone — only
    ``socket.create_connection``'s outer call can carry a name, and the
    ``socket.socket.connect`` it performs underneath carries the numeric
    address, which IS checked.
    """
    scope = _live_scope()
    if scope is None:
        return
    host: object = address
    port = -1
    if isinstance(address, (tuple, list)) and address:
        host = address[0]
        if len(address) > 1:
            raw_port = address[1]
            # A service NAME ("http") is legal in a stdlib address and would
            # leave the sentinel in place, refusing a proxy endpoint that is
            # perfectly legitimate. Coerce what can be coerced; anything else
            # keeps the sentinel, which fails closed.
            if isinstance(raw_port, int):
                port = raw_port
            elif isinstance(raw_port, str) and raw_port.isdigit():
                port = int(raw_port)
    ip = _as_ip(host)
    if ip is None:
        return
    scope.connects_checked += 1
    if (str(ip), port) in scope.allowed:
        return
    if is_blocked_ip(ip):
        scope.refusals.append(f"{ip}:{port}")
        raise BlockedConnectTarget(
            f"refusing to connect to a non-public address ({ip}) during a fetch: "
            "the name resolved to a public address when it was checked and to this "
            "one when the connection was made"
        )


def check_resolution(host: object, infos: Sequence[object]) -> None:
    """Refuse a resolution that answers with a non-public address, mid-fetch.

    The second net, and the only one that can see a destination lookup performed
    by a library that then hands the address to a proxy rather than connecting to
    it itself (PySocks under a LOCAL-resolving ``socks5``/``socks4`` scheme).
    The allowlist is consulted against the host being ASKED ABOUT and never
    against the answers: resolving the proxy literal ``127.0.0.1`` answers
    ``127.0.0.1`` and must pass, while a NAME that answers ``127.0.0.1`` is the
    attack itself. Skipping answers instead made this check inert on every
    machine whose environment names a loopback proxy.
    """
    scope = _live_scope()
    if scope is None:
        return
    queried = _as_ip(host)
    if queried is not None and str(queried) in scope.allowed_hosts:
        return
    scope.resolutions_checked += 1
    for info in infos:
        if not isinstance(info, (tuple, list)) or len(info) < 5:
            continue
        sockaddr = info[4]
        if not isinstance(sockaddr, (tuple, list)) or not sockaddr:
            continue
        ip = _as_ip(sockaddr[0])
        if ip is None:
            continue
        if is_blocked_ip(ip):
            scope.refusals.append(str(ip))
            raise BlockedConnectTarget(
                f"refusing {host!r}: it resolved to a non-public address ({ip}) "
                "during the fetch, after passing the pre-fetch check"
            )
