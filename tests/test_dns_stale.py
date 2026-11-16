"""Row 72 (field test 2026-11-14, P10/R15): a Wikimedia name survives a resolver blip.

A last good answer is handed back ONLY for EAI_AGAIN, only for the Wikimedia family, only for
a few minutes, never in airplane mode, and BEHIND the SSRF guard: a remembered answer meets
check_resolution exactly as a fresh one does. Driven through the shipped getaddrinfo hook
(airplane._guarded_getaddrinfo via airplane._orig_getaddrinfo), never by calling the cache alone.
"""

from __future__ import annotations

import socket

import pytest

from src.ingest import activate_kill_switch, clear_kill_switch, dns_stale
from src.ingest import airplane as ap
from src.ingest.ssrf_guard import BlockedConnectTarget, connect_scope

_PUBLIC = "198.51.100.7"  # documentation range; never dialled here


def _row(ip: str, port: int = 443) -> tuple:
    return (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))


@pytest.fixture
def resolver():
    """A scripted resolver installed UNDER the production hook, restored BEFORE the uninstall
    so the uninstall copies the true stdlib call back (tests/test_airplane_socket_guard.py)."""
    script: list = []
    calls: list = []

    def fake(host, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(host)
        out = script.pop(0)
        if isinstance(out, BaseException):
            raise out
        return out

    saved = ap._orig_getaddrinfo
    ap._orig_getaddrinfo = fake  # type: ignore[assignment]
    ap.install_airplane_socket_guard()
    clear_kill_switch()
    dns_stale.clear()
    try:
        yield script, calls
    finally:
        clear_kill_switch()
        dns_stale.clear()
        ap._orig_getaddrinfo = saved  # type: ignore[assignment]
        ap.uninstall_airplane_socket_guard()


def _again() -> socket.gaierror:
    return socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution")


def test_a_blip_gets_the_last_good_answer(resolver):
    script, calls = resolver
    script += [[_row(_PUBLIC)], _again()]
    assert ap._guarded_getaddrinfo("en.wikipedia.org", 443) == [_row(_PUBLIC)]
    assert ap._guarded_getaddrinfo("en.wikipedia.org", 443) == [_row(_PUBLIC)]
    assert len(calls) == 2, "the resolver is always asked first"
    assert dns_stale.status()["served"] == {"en.wikipedia.org": 1}


def test_a_fresh_answer_always_wins(resolver):
    script, _ = resolver
    script += [[_row(_PUBLIC)], [_row("198.51.100.8")]]
    ap._guarded_getaddrinfo("stream.wikimedia.org", 443)
    assert ap._guarded_getaddrinfo("stream.wikimedia.org", 443) == [_row("198.51.100.8")]


@pytest.mark.parametrize("err", [socket.gaierror(socket.EAI_NONAME, "no such name"), socket.gaierror(socket.EAI_FAIL, "x"), OSError("other")])
def test_only_a_temporary_failure_is_answered(resolver, err):
    script, _ = resolver
    script += [[_row(_PUBLIC)], err]
    ap._guarded_getaddrinfo("en.wikipedia.org", 443)
    with pytest.raises(type(err)):
        ap._guarded_getaddrinfo("en.wikipedia.org", 443)


def test_other_names_are_never_remembered(resolver):
    script, _ = resolver
    script += [[_row(_PUBLIC)], _again()]
    ap._guarded_getaddrinfo("example.org", 443)
    with pytest.raises(socket.gaierror):
        ap._guarded_getaddrinfo("example.org", 443)
    assert not dns_stale.applies_to("notwikipedia.org") and dns_stale.applies_to("fr.wikipedia.org.")


def test_an_old_answer_is_not_handed_back():
    dns_stale.clear()
    dns_stale.remember("en.wikipedia.org", (443,), {}, [_row(_PUBLIC)], now=0.0)
    assert dns_stale.recall("en.wikipedia.org", (443,), {}, temporary=True, now=dns_stale.MAX_AGE_SECONDS - 1)
    assert dns_stale.recall("en.wikipedia.org", (443,), {}, temporary=True, now=dns_stale.MAX_AGE_SECONDS + 1) is None
    dns_stale.clear()


def test_a_different_call_shape_is_a_different_answer():
    dns_stale.clear()
    dns_stale.remember("en.wikipedia.org", (443,), {}, [_row(_PUBLIC)], now=0.0)
    assert dns_stale.recall("en.wikipedia.org", (80,), {}, temporary=True, now=1.0) is None
    dns_stale.clear()


def test_the_memory_is_bounded():
    dns_stale.clear()
    for i in range(dns_stale.MAX_ENTRIES + 10):
        dns_stale.remember(f"x{i}.wikipedia.org", (443,), {}, [_row(_PUBLIC)], now=0.0)
    assert dns_stale.status()["remembered"] == dns_stale.MAX_ENTRIES
    dns_stale.clear()


def test_off_switch(resolver, monkeypatch):  # monkeypatch only sets an env var
    script, _ = resolver
    monkeypatch.setenv("OO_DNS_STALE", "0")
    script += [[_row(_PUBLIC)], _again()]
    ap._guarded_getaddrinfo("en.wikipedia.org", 443)
    with pytest.raises(socket.gaierror):
        ap._guarded_getaddrinfo("en.wikipedia.org", 443)


def test_airplane_mode_refuses_before_the_memory(resolver):
    script, calls = resolver
    script += [[_row(_PUBLIC)]]
    ap._guarded_getaddrinfo("en.wikipedia.org", 443)
    activate_kill_switch()
    try:
        with pytest.raises(ap.AirplaneModeError):
            ap._guarded_getaddrinfo("en.wikipedia.org", 443)
    finally:
        clear_kill_switch()
    assert calls == ["en.wikipedia.org"] and dns_stale.status()["served"] == {}


def test_a_remembered_answer_still_meets_the_ssrf_guard(resolver):
    """BEHIND the guard: an answer remembered outside a fetch that is non-public is refused
    inside one, exactly as a fresh answer would be."""
    script, _ = resolver
    script += [[_row("127.0.0.1")], _again()]
    ap._guarded_getaddrinfo("en.wikipedia.org", 443)  # outside a fetch: no scope, remembered
    with connect_scope(enabled=True, proxies=None) as scope, pytest.raises(BlockedConnectTarget):
        ap._guarded_getaddrinfo("en.wikipedia.org", 443)
    assert scope.refusals == ["127.0.0.1"]
