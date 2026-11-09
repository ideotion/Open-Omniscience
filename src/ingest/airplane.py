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
``/path`` goes to the host the connect guard already saw -- when that
connection was opened.

A KEEP-ALIVE connection opened before the Stop is the fourth shape (R638, from
an independent read of R636, 2026-11-09, probed first): the connect guard met it
while it was still transparent, and every later request on it is an origin-form
write with no resolve, connect or tunnel left to refuse it, so a pooled
``requests`` session kept fetching from the same host after airplane mode was
engaged. The same ``putrequest`` point therefore also refuses, while the switch
is engaged, a request on a connection whose OWN destination is not local
(its socket's peer must be a loopback address and its ``self.host`` a loopback
name; any tunnelling or SOCKS-proxied connection counts as not local),
and ``activate_kill_switch`` closes the pooled connections of every
``EthicalFetcher`` and ``GuardedSession`` so none is left idle to be reused. Not covered: a
library that writes to a socket without ``http.client`` (see ``docs/SECURITY.md``
for the list checked, and for why the raw socket ``send`` is not patched).
Also not covered: an HTTP client that does not sit on
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

# R643: on Windows the stdlib's proactor loop (what ``loop="asyncio"`` gives there) connects through ``_overlapped.ConnectEx`` and sends
# datagrams through ``WSASendTo``, never through ``socket.socket.connect``/``sendto``, and an IP-literal target skips ``getaddrinfo``:
# its two entry points are patched with the same rules. The module exists only on Windows (it imports ``_overlapped``), where asyncio
# itself imports it at start, so this import costs nothing there and is absent everywhere else.
try:
    from asyncio import windows_events as _windows_events  # type: ignore[attr-defined,unused-ignore]
except ImportError:
    _windows_events = None  # type: ignore[assignment,unused-ignore]
_proactor_cls: Any = getattr(_windows_events, "IocpProactor", None)


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
# R641: the name-taking calls that resolve in C (libc) and never reach the patched getaddrinfo, and the datagram sends that need no
# connect. ``sendmsg`` does not exist on Windows; the PySocks one only with the extra installed.
_orig_gethostbyname = socket.gethostbyname
_orig_gethostbyname_ex = socket.gethostbyname_ex
_orig_gethostbyaddr = socket.gethostbyaddr
_orig_getnameinfo = socket.getnameinfo
_orig_bind = socket.socket.bind
_orig_sendto = socket.socket.sendto
_orig_sendmsg = getattr(socket.socket, "sendmsg", None)
_orig_socks_sendto = _pysocks.socksocket.sendto if _pysocks is not None else None
_orig_proactor_connect: Any = _proactor_cls.connect if _proactor_cls is not None else None
_orig_proactor_sendto: Any = _proactor_cls.sendto if _proactor_cls is not None else None
#: The same real calls, never reassigned: a test swaps ``_orig_*`` for spies, and a call that has the stdlib's own function back in it
#: is "the guard was removed" whether or not a spy is standing in ``_orig_*`` at that moment.
_REAL_AT_IMPORT = (
    _orig_getaddrinfo,
    _orig_create_connection,
    _orig_connect,
    _orig_connect_ex,
    _orig_tunnel,
    _orig_putrequest,
    _orig_gethostbyname,
    _orig_gethostbyname_ex,
    _orig_gethostbyaddr,
    _orig_getnameinfo,
    _orig_bind,
    _orig_sendto,
    # Last, because these are the points that may be absent: the zip in removed_while_installed pairs these with _patch_points by
    # position, and both lists leave out an absent one the same way.
    *((_orig_sendmsg,) if _orig_sendmsg is not None else ()),
    *((_orig_socks_connect, _orig_socks_sendto) if _orig_socks_connect is not None else ()),
    *((_orig_proactor_connect, _orig_proactor_sendto) if _orig_proactor_connect is not None else ()),
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


#: The one name ``_guard`` is handed for a lookup of a localhost ALIAS in airplane mode (R639). Fixed words, never the name.
_ALIAS_LOOKUP_TARGET = "a localhost alias that may be answered by DNS (in airplane mode only localhost and loopback literals are looked up)"


def _lookup_exempt(host: object) -> bool:
    """True for the only names a lookup may be made for while airplane mode is engaged (R639): no name at all (``None`` or empty: a
    bind, or the local service), exactly ``localhost``, or a loopback LITERAL (an IPv6 one may carry a zone id).

    Narrower than :func:`_is_local_host` on purpose. ``localhost.localdomain`` and ``ip6-localhost`` are local only if
    ``/etc/hosts`` says so: where it does not (this project's CI container lists neither alias; Debian and Qubes lack
    ``localhost.localdomain``), the resolver asks DNS, so the QUERY egresses even though the connect to whatever it answers is refused.
    Nothing is stripped or normalised: a name that needs normalising is not one of these.
    """
    if host is None:
        return True
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii")
        except UnicodeDecodeError:
            return False
    if not isinstance(host, str):
        return False
    if host == "" or host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0] if ":" in host else host).is_loopback
    except ValueError:
        return False


def _is_localhost_name(host: object) -> bool:
    """Exactly ``localhost`` (any ASCII case, text or bytes)."""
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii")
        except UnicodeDecodeError:
            return False
    return isinstance(host, str) and host.lower() == "localhost"


def _localhost_in_process(args: tuple[Any, ...], kwargs: dict[str, Any]) -> list[Any]:
    """Answer ``localhost`` from its loopback LITERALS, in airplane mode only (R639, security read A's follow-up).

    ``localhost`` is exempt from the airplane refusal, but libc still consults ``/etc/hosts`` and then DNS: where the file has no entry
    for the family asked for (a container listing only ``127.0.0.1 localhost``, asked for ``AF_INET6``), the query went to the
    configured nameservers. Resolving the literals instead is numeric, so no query can leave; RFC 6761 reserves the name for loopback.
    IPv4 first for an unspecified family, the order the app's own server and a loopback Ollama listen on. A literal the host cannot
    use (no IPv6) is skipped; none usable is the resolver's own "name unknown" error.
    """
    family = args[1] if len(args) > 1 else kwargs.get("family", 0)
    literals = {socket.AF_INET: ("127.0.0.1",), socket.AF_INET6: ("::1",)}.get(family, ("127.0.0.1", "::1"))
    infos: list[Any] = []
    for literal in literals:
        try:
            infos.extend(_orig_getaddrinfo(literal, *args, **kwargs))
        except socket.gaierror:
            continue
    if not infos:
        raise socket.gaierror(socket.EAI_NONAME, "localhost has no loopback address of the requested family")
    return infos


def _guarded_getaddrinfo(host, *args, **kwargs):  # type: ignore[no-untyped-def]
    # A name the connect guard would call local but that is not exempt from a lookup (a localhost alias) is refused in fixed words
    # before any lookup (R639); every other name meets _guard as it always has, so its refusal sentence is unchanged.
    if _is_local_host(host) and not _lookup_exempt(host):
        _guard(_ALIAS_LOOKUP_TARGET)
    _guard(host)
    with native_call("dns"):
        if _airplane_armed and kill_switch_active() and _is_localhost_name(host):
            infos = _localhost_in_process(args, kwargs)
        else:
            infos = _orig_getaddrinfo(host, *args, **kwargs)
    # The SSRF half checks the ANSWER, not the question: inside a guarded fetch a
    # name that resolves to an internal address is refused here, which is the
    # only place a destination lookup performed by a library that then hands the
    # address to a proxy is visible at all.
    check_resolution(host, infos)
    return infos


def _name_rule_for_connect(address: object, family: object) -> object:
    """Apply :func:`_guarded_getaddrinfo`'s name rule to a connect target, while airplane mode is engaged (R639, S1's read).

    ``socket.connect``/``connect_ex`` with a host NAME resolve it inside CPython's C code, which calls libc directly and never the
    patched ``socket.getaddrinfo``: ``connect(("localhost.localdomain", 80))`` sent its query to DNS in airplane mode (strace), and so did
    ``localhost`` on an ``AF_INET6`` socket where ``/etc/hosts`` has no ``::1`` line. So here, before the real call: a localhost alias
    that is not exempt from a lookup is refused in fixed words, and exactly ``localhost`` is swapped for the loopback literal of the
    socket's family (``::1`` for ``AF_INET6``, else ``127.0.0.1``), which libc parses without a query. Any other address is returned
    unchanged. Online, and with the airplane half unarmed, nothing changes.
    """
    if not (_airplane_armed and kill_switch_active()):
        return address
    host = _addr_host(address)
    if _is_local_host(host) and not _lookup_exempt(host):
        _guard(_ALIAS_LOOKUP_TARGET)
    if _is_localhost_name(host) and isinstance(address, (tuple, list)):
        literal = "::1" if family == socket.AF_INET6 else "127.0.0.1"
        return (literal, *tuple(address)[1:])
    return address


def _guarded_create_connection(address, *args, **kwargs):  # type: ignore[no-untyped-def]
    # create_connection resolves through the patched getaddrinfo (which refuses an alias and answers localhost itself) and then
    # connects to the numeric answer; the rule is applied here too, so a refusal comes before anything else in the same words. The
    # address handed on is unchanged: getaddrinfo picks the family, so the localhost swap is its to make.
    _name_rule_for_connect(address, None)
    _guard(_addr_host(address))
    check_connect_target(address)
    return _orig_create_connection(address, *args, **kwargs)


def _guarded_connect(self, address):  # type: ignore[no-untyped-def]
    # AF_UNIX is local IPC (a filesystem path) and AF_NETLINK this machine's own kernel (R645) — never network; always allow.
    if not _is_local_family(self):
        address = _name_rule_for_connect(address, getattr(self, "family", None))
        _guard(_addr_host(address))
        check_connect_target(address)
    with native_call("connect"):
        return _orig_connect(self, address)


def _guarded_connect_ex(self, address):  # type: ignore[no-untyped-def]
    if not _is_local_family(self):
        address = _name_rule_for_connect(address, getattr(self, "family", None))
        _guard(_addr_host(address))
        check_connect_target(address)
    with native_call("connect"):
        return _orig_connect_ex(self, address)


def _lookup_rule(host: object) -> None:
    """R639's lookup rule for a call that resolves in C and never reaches the patched ``getaddrinfo`` (R641): while airplane mode is
    engaged, only no name, exactly ``localhost`` and a loopback literal pass. A localhost alias is refused in R639's fixed words, and
    anything else (a remote name, or a remote literal whose reverse lookup would ask DNS) meets ``_guard`` and its usual sentence. What
    passes is safe to hand to a FORWARD lookup only: a reverse lookup of a loopback literal is still a PTR query, so the reverse wrappers
    answer it themselves."""
    if _is_local_host(host) and not _lookup_exempt(host):
        _guard(_ALIAS_LOOKUP_TARGET)
    _guard(host)


def _engaged() -> bool:
    return _airplane_armed and kill_switch_active()


def _guarded_gethostbyname(hostname):  # type: ignore[no-untyped-def]
    _lookup_rule(hostname)
    if _engaged() and _is_localhost_name(hostname):
        return "127.0.0.1"  # answered from the literal: libc would consult /etc/hosts, then DNS
    with native_call("dns"):
        return _orig_gethostbyname(hostname)


def _guarded_gethostbyname_ex(hostname):  # type: ignore[no-untyped-def]
    _lookup_rule(hostname)
    if _engaged() and _is_localhost_name(hostname):
        return ("localhost", [], ["127.0.0.1"])
    with native_call("dns"):
        return _orig_gethostbyname_ex(hostname)


def _guarded_gethostbyaddr(ip_address):  # type: ignore[no-untyped-def]
    # Also what socket.getfqdn() calls (it reads the module global), so getfqdn of a remote or unlisted name falls back to the name
    # itself, as it does whenever the lookup fails, instead of asking DNS.
    _lookup_rule(ip_address)
    if _engaged():
        if _is_localhost_name(ip_address):
            ip_address = "127.0.0.1"
        if _is_ip_literal(ip_address):
            # Only loopback is left here, and a REVERSE lookup of a literal is a real PTR query (glibc reads /etc/hosts, then asks
            # DNS: security read A measured it for 127.0.0.2 and ::1), so it is answered here without libc.
            literal = ip_address.decode("ascii") if isinstance(ip_address, bytes) else ip_address
            return ("localhost", [], [literal])
    with native_call("dns"):
        return _orig_gethostbyaddr(ip_address)


def _guarded_getnameinfo(sockaddr, flags):  # type: ignore[no-untyped-def]
    host = _addr_host(sockaddr)
    numeric_only = socket.NI_NUMERICHOST | socket.NI_NUMERICSERV
    if flags & numeric_only == numeric_only and _is_ip_literal(host):
        # R645: both numeric flags on a literal ask libc to format the number it was handed, which makes no lookup of any kind (the
        # forward step CPython takes is AI_NUMERICHOST), so any literal passes while engaged too.
        with native_call("dns"):
            return _orig_getnameinfo(sockaddr, flags)
    _lookup_rule(host)
    if _engaged():
        if _is_localhost_name(host) and isinstance(sockaddr, (tuple, list)):
            sockaddr = ("127.0.0.1", *tuple(sockaddr)[1:])
        # Only a loopback sockaddr is left here. Its host name would be a PTR query and its service name an NSS lookup that can leave
        # the machine, so libc is asked for the numeric forms only and the host is answered as localhost unless the caller asked for
        # the number (security read A measured a DNS query for ("127.0.0.5", 0) and ("::1", 0, 0, 0)).
        answer_as_localhost = not flags & socket.NI_NUMERICHOST
        flags |= socket.NI_NUMERICHOST | socket.NI_NUMERICSERV
        if answer_as_localhost:
            # glibc refuses NI_NAMEREQD beside the forced NI_NUMERICHOST (EAI_NONAME); the name it requires is the "localhost" answered
            # below. A caller who asked for the number AND a name keeps libc's own refusal.
            flags &= ~socket.NI_NAMEREQD
    else:
        answer_as_localhost = False
    with native_call("dns"):
        name, port = _orig_getnameinfo(sockaddr, flags)
    return ("localhost" if answer_as_localhost else name, port)


#: The socket families whose addresses never name a host (R645): AF_UNIX is a filesystem path, AF_NETLINK talks to this machine's own
#: kernel. AF_PACKET (raw frames onto the wire), vsock, CAN and Bluetooth stay refused while engaged.
_LOCAL_FAMILIES = tuple(f for f in (getattr(socket, "AF_UNIX", None), getattr(socket, "AF_NETLINK", None)) if f is not None)


def _is_local_family(sock: object) -> bool:
    return getattr(sock, "family", None) in _LOCAL_FAMILIES


def _is_ip_literal(host: object) -> bool:
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii")
        except UnicodeDecodeError:
            return False
    if not isinstance(host, str):
        return False
    try:
        ipaddress.ip_address(host.split("%", 1)[0] if ":" in host else host)
    except ValueError:
        return False
    return True


def _guarded_bind(self, address):  # type: ignore[no-untyped-def]
    # A bind sends nothing, so any LITERAL address (or none) is left alone; only a host NAME, which C resolves through libc, meets the
    # lookup rule, with exactly ``localhost`` swapped for the family's loopback literal like a connect (R641).
    if _engaged() and not _is_local_family(self):
        host = _addr_host(address)
        if host not in (None, "", b"") and not _is_ip_literal(host):
            address = _name_rule_for_connect(address, getattr(self, "family", None))
            _lookup_rule(_addr_host(address))
    return _orig_bind(self, address)


def _datagram_rule(sock: object, address: object) -> object:
    """A datagram to ``address`` needs no connect, so no other guard point sees it (R641): while airplane mode is engaged a host NAME
    meets the connect name rule (alias refused, ``localhost`` swapped for the literal) and any non-loopback destination is refused."""
    if not _engaged() or address is None or _is_local_family(sock):
        return address
    address = _name_rule_for_connect(address, getattr(sock, "family", None))
    _guard(_addr_host(address))
    return address


def _guarded_sendto(self, data, *args):  # type: ignore[no-untyped-def]
    # sendto(data, address) or sendto(data, flags, address): the address is always the last argument.
    if args:
        args = (*args[:-1], _datagram_rule(self, args[-1]))
    return _orig_sendto(self, data, *args)


def _guarded_sendmsg(self, buffers, *args):  # type: ignore[no-untyped-def]
    # sendmsg(buffers[, ancdata[, flags[, address]]]), positional only like the C call: no address is a connected socket, which its
    # connect already met.
    if len(args) >= 3:
        args = (*args[:2], _datagram_rule(self, args[2]), *args[3:])
    return cast(Callable[..., Any], _orig_sendmsg)(self, buffers, *args)


def _guarded_socks_sendto(self, data, *args):  # type: ignore[no-untyped-def]
    """PySocks' UDP ``sendto`` wraps the datagram for the proxy's relay and sends it on a socket CONNECTED to that relay, so the real
    destination, its last argument, is checked here: through a proxy any destination is the proxy's to reach (R641)."""
    proxy = getattr(self, "proxy", None)
    proxied = isinstance(proxy, tuple) and bool(proxy) and proxy[0] is not None
    if proxied and args and _engaged():
        _guard(_proxied_destination(_addr_host(args[-1])))
    return cast(Callable[..., Any], _orig_socks_sendto)(self, data, *args)


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


#: The one name ``_guard`` is handed for a request on a connection whose OWN destination is not local (R638). Fixed words, never
#: ``self.host``: a caller can build an ``HTTPConnection`` from a string that still carries userinfo, and that must not reach a log (R142).
_CONNECTION_TARGET = "a non-local host over a connection already open (opened before airplane mode was engaged)"


def _connection_destination(conn: object) -> object:
    """What ``_guard`` is handed for the OPEN connection a request is about to be written to (R638), or ``None`` when that is local.

    Only a connection that already holds a socket is classified: a fresh one (``sock is None``) connects lazily inside ``send``, where the
    connect guard reads the switch itself and refuses a remote target exactly as it always has (same words, same wrapping).

    Not local, whatever name the connection carries:
    - a connection that TUNNELS (``_tunnel_host`` set: a CONNECT through an HTTP proxy) -- the same rule ``_guarded_tunnel`` applies;
    - a urllib3 SOCKS connection (``_socks_options`` set), or a socket carrying a PySocks ``proxy`` -- read from the CONNECTION as well as
      the socket, because over HTTPS ``sock`` is an ``ssl.SSLSocket`` built anew from the PySocks socket and the attribute is gone
      (both security reads of R638);
    - a socket whose PEER is not a loopback address -- the name alone is not enough (urllib3 reports ``localhost.`` as ``localhost``, and
      ``localhost.localdomain`` may be resolved by DNS); a peer that cannot be read fails closed;
    - a connection whose ``host`` is missing, not text, or not a loopback name or literal.
    """
    sock = getattr(conn, "sock", None)
    if sock is None:
        return None
    if getattr(conn, "_tunnel_host", None):
        return _PROXIED_TARGET
    if getattr(conn, "_socks_options", None):
        return _PROXIED_TARGET
    sock_proxy = getattr(sock, "proxy", None)
    if isinstance(sock_proxy, tuple) and sock_proxy and sock_proxy[0] is not None:
        return _PROXIED_TARGET
    if getattr(sock, "family", None) != getattr(socket, "AF_UNIX", object()):
        try:
            peer = sock.getpeername()
        except Exception:  # noqa: BLE001 - an unreadable peer is not local
            return _CONNECTION_TARGET
        if not _is_loopback_peer(peer):
            return _CONNECTION_TARGET
    host = getattr(conn, "host", None)
    if isinstance(host, (str, bytes)) and host and _is_local_host(host):
        return None
    return _CONNECTION_TARGET


def _is_loopback_peer(peer: object) -> bool:
    """True when a ``getpeername()`` answer is a loopback ADDRESS (never a name: a peer is always numeric)."""
    host = _addr_host(peer)
    if not isinstance(host, str):
        return False
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _guarded_putrequest(self, method, url, *args, **kwargs):  # type: ignore[no-untyped-def]
    """Guard every request written over http.client while airplane mode is engaged, before ``putrequest`` buffers anything, so a
    refusal leaves zero request bytes on the wire. Two checks:

    1. A destination named IN the request line (R619): a plain ``http://`` URL through an HTTP proxy is written as an absolute-form
       ``GET http://host/...`` to an already-allowed loopback socket, with no CONNECT and so no ``_tunnel`` call. Every such target is
       refused, whatever host it names.
    2. The connection's OWN destination (R638): a keep-alive connection opened BEFORE the Stop met the connect guard while it was still
       transparent, so an origin-form ``/path`` written to it afterwards would reach a remote host with no connect, resolve or tunnel to
       stop it (``requests``/urllib3 reuse pooled connections exactly so). While the switch is engaged, a request on a connection whose
       destination is not local (:func:`_connection_destination`) is refused. A fresh connection is left to the connect guard, which
       reads the switch when its lazy connect runs; a local one (the app's own server, a loopback Ollama) is untouched. The switch is read at the moment the request is written, so a Stop that lands after a caller's own check is still met.

    The ordinary path (switch clear) costs one flag read and one ``Event.is_set``: the destination is only classified while airplane
    mode is engaged."""
    if _names_its_own_destination(method, url):
        _guard(_PROXIED_TARGET)
    if _airplane_armed and kill_switch_active():
        destination = _connection_destination(self)
        if destination is not None:
            _guard(destination)
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


def _guarded_proactor_connect(self, conn, address):  # type: ignore[no-untyped-def]
    """R643: ``IocpProactor.connect`` (``ConnectEx`` for a stream, ``WSAConnect`` for a datagram socket) meets the same rule as
    ``socket.socket.connect``: an alias refused, ``localhost`` swapped for the family's literal, any non-loopback target refused before
    the overlapped call, and the SSRF connect check."""
    if not _is_local_family(conn):
        address = _name_rule_for_connect(address, getattr(conn, "family", None))
        _guard(_addr_host(address))
        check_connect_target(address)
    return _orig_proactor_connect(self, conn, address)


def _guarded_proactor_sendto(self, conn, buf, flags=0, addr=None):  # type: ignore[no-untyped-def]
    """R643: ``IocpProactor.sendto`` (``WSASendTo``: ``loop.sock_sendto`` and an unconnected datagram transport) meets the datagram rule
    of ``socket.socket.sendto``. No address is a connected socket, whose connect already met the rule."""
    return _orig_proactor_sendto(self, conn, buf, flags, _datagram_rule(conn, addr))


def _patch_points() -> list[tuple[Any, str, Any, Any]]:
    """Each patched call as (owner, attribute, our wrapper, the real call we saved)."""
    points: list[tuple[Any, str, Any, Any]] = [
        (socket, "getaddrinfo", _guarded_getaddrinfo, _orig_getaddrinfo),
        (socket, "create_connection", _guarded_create_connection, _orig_create_connection),
        (socket.socket, "connect", _guarded_connect, _orig_connect),
        (socket.socket, "connect_ex", _guarded_connect_ex, _orig_connect_ex),
        (http.client.HTTPConnection, "_tunnel", _guarded_tunnel, _orig_tunnel),
        (http.client.HTTPConnection, "putrequest", _guarded_putrequest, _orig_putrequest),
        (socket, "gethostbyname", _guarded_gethostbyname, _orig_gethostbyname),
        (socket, "gethostbyname_ex", _guarded_gethostbyname_ex, _orig_gethostbyname_ex),
        (socket, "gethostbyaddr", _guarded_gethostbyaddr, _orig_gethostbyaddr),
        (socket, "getnameinfo", _guarded_getnameinfo, _orig_getnameinfo),
        (socket.socket, "bind", _guarded_bind, _orig_bind),
        (socket.socket, "sendto", _guarded_sendto, _orig_sendto),
    ]
    if _orig_sendmsg is not None:
        points.append((socket.socket, "sendmsg", _guarded_sendmsg, _orig_sendmsg))
    if _orig_socks_connect is not None:
        points.append((_pysocks.socksocket, "connect", _guarded_socks_connect, _orig_socks_connect))
        points.append((_pysocks.socksocket, "sendto", _guarded_socks_sendto, _orig_socks_sendto))
    if _orig_proactor_connect is not None:
        points.append((_proactor_cls, "connect", _guarded_proactor_connect, _orig_proactor_connect))
        points.append((_proactor_cls, "sendto", _guarded_proactor_sendto, _orig_proactor_sendto))
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
        getattr(socket, "gethostbyname", None),
        getattr(socket, "gethostbyname_ex", None),
        getattr(socket, "gethostbyaddr", None),
        getattr(socket, "getnameinfo", None),
        getattr(socket.socket, "bind", None),
        getattr(socket.socket, "sendto", None),
    ]
    if _orig_sendmsg is not None:
        calls.append(getattr(socket.socket, "sendmsg", None))
    if _orig_socks_connect is not None:
        calls.append(getattr(_pysocks.socksocket, "connect", None))
        calls.append(getattr(_pysocks.socksocket, "sendto", None))
    if _orig_proactor_connect is not None:
        calls.append(getattr(_proactor_cls, "connect", None))
        calls.append(getattr(_proactor_cls, "sendto", None))
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
    socket.gethostbyname = _orig_gethostbyname
    socket.gethostbyname_ex = _orig_gethostbyname_ex
    socket.gethostbyaddr = _orig_gethostbyaddr
    socket.getnameinfo = _orig_getnameinfo
    socket.socket.bind = _orig_bind  # type: ignore[method-assign]
    socket.socket.sendto = _orig_sendto  # type: ignore[method-assign]
    if _orig_sendmsg is not None:
        socket.socket.sendmsg = _orig_sendmsg  # type: ignore[method-assign]
    if _orig_socks_connect is not None:
        _pysocks.socksocket.connect = _orig_socks_connect  # type: ignore[union-attr]
        _pysocks.socksocket.sendto = _orig_socks_sendto  # type: ignore[union-attr]
    if _orig_proactor_connect is not None:
        _proactor_cls.connect = _orig_proactor_connect
        _proactor_cls.sendto = _orig_proactor_sendto
    _installed = False


def is_installed() -> bool:
    return _installed


def is_armed() -> bool:
    """True once ``install_airplane_socket_guard`` armed airplane mode's refusal: the patches may be in place for the SSRF half
    alone (``ensure_connect_guard_installed``), which refuses nothing while the kill switch is engaged."""
    return _installed and _airplane_armed
