"""R641: the name-taking calls that resolve in C, and the datagram sends that need no connect, meet R639's rule in airplane mode.

``socket.gethostbyname``/``gethostbyname_ex``, ``gethostbyaddr`` (and ``getfqdn``, which calls it), ``getnameinfo``, a ``bind`` handed a
host NAME and a ``sendto``/``sendmsg`` handed one all resolve through libc and never reach the patched ``getaddrinfo``; a datagram to a
remote address needs no connect, so no other guard point saw it. While the kill switch is engaged: no name, exactly ``localhost`` and
a loopback literal pass (``localhost`` answered from its literal); a localhost alias is refused in R639's fixed words; anything else is
refused; and a datagram to a non-loopback destination is refused. No real network: the real calls are replaced by recorders, and the
datagram tests that do reach the real call send only to loopback.
"""

from __future__ import annotations

import socket

import pytest

import src.ingest.airplane as ap
from src.ingest import activate_kill_switch, clear_kill_switch
from src.ingest.airplane import AirplaneModeError

_NAMES = (
    "gethostbyname",
    "gethostbyname_ex",
    "gethostbyaddr",
    "getnameinfo",
    "bind",
    "sendto",
    "sendmsg",
)


@pytest.fixture
def reached():
    """The guard installed and armed, with recorders standing in for the real calls this file covers. The real ones are put back
    BEFORE the uninstall, which copies ``_orig_*`` back onto ``socket``."""
    was_installed, was_armed = ap.is_installed(), ap._airplane_armed
    assert ap.install_airplane_socket_guard(), (
        "the guard is disabled here (OO_AIRPLANE_SOCKET_GUARD=0?)"
    )
    saved = {name: getattr(ap, f"_orig_{name}") for name in _NAMES}
    calls: list[tuple[str, object]] = []

    def recorder(name):
        def _f(*a, **k):
            # The address-bearing argument: the first for the lookups, the last positional (or keyword) for the socket methods.
            arg = (
                a[0]
                if name.startswith(("get",))
                else (k.get("address") if "address" in k else a[-1])
            )
            calls.append((name, arg))
            return {
                "gethostbyname_ex": ("x", [], []),
                "gethostbyaddr": ("x", [], []),
                "getnameinfo": ("x", "0"),
            }.get(name, 0)

        return _f

    for name in _NAMES:
        if saved[name] is not None:
            setattr(ap, f"_orig_{name}", recorder(name))
    clear_kill_switch()
    try:
        yield calls
    finally:
        for name, real in saved.items():
            setattr(ap, f"_orig_{name}", real)
        clear_kill_switch()
        ap.uninstall_airplane_socket_guard()
        if was_installed:
            ap._install_patches()
        ap._airplane_armed = was_armed


_REMOTE = ("example.com", "93.184.215.14", "2606:2800:21f:cb07:6820:80da:af6b:8b2c")
_ALIASES = ("localhost.localdomain", "ip6-localhost", " localhost")


# --- the lookups --------------------------------------------------------------------------------------------------------------------


def _lookup(name: str, host: str):
    if name == "getnameinfo":
        return socket.getnameinfo((host, 80), 0)
    return getattr(socket, name)(host)


@pytest.mark.parametrize(
    "name", ["gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo"]
)
@pytest.mark.parametrize("host", _REMOTE)
def test_a_remote_lookup_is_refused_before_libc(reached, name, host):
    activate_kill_switch()
    with pytest.raises(AirplaneModeError):
        _lookup(name, host)
    assert reached == [], "the real call (and so libc's resolver) was reached for a remote target"


@pytest.mark.parametrize(
    "name", ["gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo"]
)
@pytest.mark.parametrize("host", _ALIASES)
def test_a_localhost_alias_lookup_is_refused_in_fixed_words(reached, name, host):
    activate_kill_switch()
    with pytest.raises(AirplaneModeError) as exc:
        _lookup(name, host)
    assert reached == []
    assert ap._ALIAS_LOOKUP_TARGET in str(exc.value) and repr(host) not in str(exc.value)


def test_localhost_is_answered_from_its_literal(reached):
    activate_kill_switch()
    assert socket.gethostbyname("localhost") == "127.0.0.1"
    assert socket.gethostbyname("LocalHost") == "127.0.0.1"
    assert socket.gethostbyname_ex("localhost") == ("localhost", [], ["127.0.0.1"])
    assert socket.gethostbyaddr("localhost") == ("localhost", [], ["127.0.0.1"])
    assert socket.getnameinfo(("localhost", 80), 0)[0] == "localhost"
    assert reached == [("getnameinfo", ("127.0.0.1", 80))], (
        "localhost was handed to libc as a name, or its reverse lookup reached libc"
    )


@pytest.mark.parametrize("name", ["gethostbyname", "gethostbyname_ex"])
@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "127.8.9.10"])
def test_a_forward_lookup_of_a_loopback_literal_reaches_the_real_call(reached, name, host):
    """A forward lookup of a literal is parsed as a number by libc and asks nothing."""
    activate_kill_switch()
    _lookup(name, host)
    assert [n for n, _ in reached] == [name]


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "127.0.0.2", "127.8.9.10"])
def test_a_reverse_lookup_of_a_loopback_literal_never_reaches_libc(reached, host):
    """A reverse lookup of a literal is a PTR query (glibc reads /etc/hosts, then asks DNS; security read A measured it for 127.0.0.2
    and ::1), so while engaged it is answered without the real call, and getfqdn of the literal gets that answer."""
    activate_kill_switch()
    assert socket.gethostbyaddr(host) == ("localhost", [], [host])
    assert socket.getfqdn(host) == "localhost"
    assert reached == []


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "127.8.9.10"])
@pytest.mark.parametrize(
    ("flags", "answer"),
    [(0, "localhost"), (socket.NI_NAMEREQD, "localhost"), (socket.NI_NUMERICHOST, "x")],
)
def test_getnameinfo_of_a_loopback_literal_asks_libc_for_numbers_only(reached, host, flags, answer):
    """libc is handed NI_NUMERICHOST | NI_NUMERICSERV, so it makes neither a PTR query nor a service lookup; the host is answered as
    localhost unless the caller asked for the number."""
    seen: list[int] = []

    def _numeric_only(sockaddr, fl):
        seen.append(fl)
        return ("x", "80")

    recorder, ap._orig_getnameinfo = ap._orig_getnameinfo, _numeric_only  # the fixture puts the real one back
    try:
        activate_kill_switch()
        assert socket.getnameinfo((host, 80), flags) == (answer, "80")
    finally:
        ap._orig_getnameinfo = recorder
    want = socket.NI_NUMERICHOST | socket.NI_NUMERICSERV
    assert seen == [flags | want]


def test_the_real_reverse_lookup_of_a_loopback_literal_makes_no_query():
    """With the REAL calls: the libc entry points are replaced by tripwires, so a reverse lookup that reached them fails the test."""
    was_installed, was_armed = ap.is_installed(), ap._airplane_armed
    assert ap.install_airplane_socket_guard()
    saved = ap._orig_gethostbyaddr

    def _tripwire(*a, **k):
        raise AssertionError("libc's gethostbyaddr was reached")

    ap._orig_gethostbyaddr = _tripwire
    try:
        activate_kill_switch()
        assert socket.gethostbyaddr("::1")[0] == "localhost"
        name, port = socket.getnameinfo(("127.0.0.5", 80), 0)
        assert (name, port) == ("localhost", "80")
    finally:
        ap._orig_gethostbyaddr = saved
        clear_kill_switch()
        ap.uninstall_airplane_socket_guard()
        if was_installed:
            ap._install_patches()
        ap._airplane_armed = was_armed


@pytest.mark.parametrize(
    "name", ["gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo"]
)
def test_online_every_lookup_is_untouched(reached, name):
    _lookup(name, "example.com")
    assert reached == [(name, "example.com" if name != "getnameinfo" else ("example.com", 80))]


def test_getfqdn_falls_back_to_the_name_instead_of_asking_dns(reached):
    """``socket.getfqdn`` calls the module's ``gethostbyaddr``, so it meets the rule and, on the refusal, returns the name itself (its
    own behaviour on any lookup failure) without a query."""
    activate_kill_switch()
    assert socket.getfqdn("some-host.example") == "some-host.example"
    assert reached == []


# --- bind ---------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "address", [("127.0.0.1", 0), ("0.0.0.0", 0), ("", 0), ("93.184.215.14", 0)]
)
def test_a_bind_to_a_literal_or_no_name_is_left_alone(reached, address):
    """A bind sends nothing: any literal, or none, is the real call's to judge."""
    activate_kill_switch()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(address)
    finally:
        s.close()
    assert reached == [("bind", address)]


@pytest.mark.parametrize(
    ("family", "literal"), [(socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")]
)
def test_a_bind_to_localhost_is_handed_the_familys_literal(reached, family, literal):
    activate_kill_switch()

    class _Sock:  # a stand-in carrying the family, so the IPv6 case runs where the host has no IPv6
        pass

    sock = _Sock()
    sock.family = family  # type: ignore[attr-defined]
    ap._guarded_bind(sock, ("localhost", 0))
    assert reached == [("bind", (literal, 0))]


@pytest.mark.parametrize("host", ["example.com", *_ALIASES])
def test_a_bind_to_any_other_name_is_refused_before_libc(reached, host):
    activate_kill_switch()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(AirplaneModeError):
            s.bind((host, 0))
    finally:
        s.close()
    assert reached == []


def test_online_a_bind_to_a_name_is_untouched(reached):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("example.com", 0))
    finally:
        s.close()
    assert reached == [("bind", ("example.com", 0))]


# --- datagrams ----------------------------------------------------------------------------------------------------------------------


def _send(method: str, sock: socket.socket, address, flags: bool):
    if method == "sendto":
        return sock.sendto(b"x", 0, address) if flags else sock.sendto(b"x", address)
    return sock.sendmsg([b"x"], [], 0, address) if flags else sock.sendmsg([b"x"], (), 0, address)


_METHODS = [
    "sendto",
    pytest.param(
        "sendmsg",
        marks=pytest.mark.skipif(not hasattr(socket.socket, "sendmsg"), reason="no sendmsg"),
    ),
]


@pytest.mark.parametrize("method", _METHODS)
@pytest.mark.parametrize("flags", [False, True])
@pytest.mark.parametrize("host", ["93.184.215.14", "example.com", *_ALIASES])
def test_a_datagram_to_a_remote_destination_or_name_is_refused(reached, method, flags, host):
    activate_kill_switch()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(AirplaneModeError):
            _send(method, s, (host, 9), flags)
    finally:
        s.close()
    assert reached == [], "the real send was reached"


@pytest.mark.parametrize("method", _METHODS)
@pytest.mark.parametrize(
    ("host", "handed"), [("127.0.0.1", "127.0.0.1"), ("localhost", "127.0.0.1")]
)
def test_a_datagram_to_loopback_reaches_the_real_call(reached, method, host, handed):
    activate_kill_switch()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        _send(method, s, (host, 9), flags=False)
    finally:
        s.close()
    assert reached == [(method, (handed, 9))]


@pytest.mark.parametrize("method", _METHODS)
def test_online_a_datagram_is_untouched(reached, method):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        _send(method, s, ("93.184.215.14", 9), flags=False)
    finally:
        s.close()
    assert reached == [(method, ("93.184.215.14", 9))]


@pytest.mark.skipif(not hasattr(socket.socket, "sendmsg"), reason="no sendmsg")
def test_a_sendmsg_without_an_address_is_a_connected_socket_and_untouched(reached):
    activate_kill_switch()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.sendmsg([b"x"])
    finally:
        s.close()
    assert [n for n, _ in reached] == ["sendmsg"]


def test_the_real_datagram_path_end_to_end():
    """With the REAL calls (no recorders): a datagram to a remote literal is refused and one to a loopback listener arrives."""
    was_installed, was_armed = ap.is_installed(), ap._airplane_armed
    assert ap.install_airplane_socket_guard()
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        rx.bind(("127.0.0.1", 0))
        rx.settimeout(5)
        activate_kill_switch()
        with pytest.raises(AirplaneModeError):
            tx.sendto(b"out", ("192.0.2.1", 9))
        tx.sendto(b"in", ("localhost", rx.getsockname()[1]))
        assert rx.recvfrom(16)[0] == b"in"
    finally:
        clear_kill_switch()
        rx.close()
        tx.close()
        ap.uninstall_airplane_socket_guard()
        if was_installed:
            ap._install_patches()
        ap._airplane_armed = was_armed


def test_every_new_point_is_patched_and_put_back():
    """The new calls are among the guard's patch points (so a removal while installed is healed and reported) and an uninstall puts the
    stdlib's own functions back."""
    was_installed, was_armed = ap.is_installed(), ap._airplane_armed
    owners = {(o, a) for o, a, *_ in ap._patch_points()}
    for name in ("gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo"):
        assert (socket, name) in owners
    for name in ("bind", "sendto") + (("sendmsg",) if hasattr(socket.socket, "sendmsg") else ()):
        assert (socket.socket, name) in owners
    assert len(ap._patch_points()) == len(ap._REAL_AT_IMPORT) == len(ap._standing_calls())
    ap.uninstall_airplane_socket_guard()
    try:
        assert (
            socket.gethostbyname is ap._orig_gethostbyname
            and socket.socket.sendto is ap._orig_sendto
        )
    finally:
        if was_installed:
            ap._install_patches()
        ap._airplane_armed = was_armed
