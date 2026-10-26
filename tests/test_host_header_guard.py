"""DNS-rebinding / Host-header guard (release-0.1 blocker).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A hostile website can rebind its own domain's DNS to 127.0.0.1, so the victim's
browser sends what it believes are same-origin requests to this loopback API —
bypassing CORS entirely. The reliable tell is the Host header: a rebound request
carries the ATTACKER's hostname, never a loopback name. The guard middleware in
src/api/main.py rejects such requests with 421 (Misdirected Request); the
OO_ALLOWED_HOSTS env (comma-separated hostnames) is the explicit escape hatch
for LAN self-hosters. Starlette's TestClient stamps ``Host: testserver``; the app does
not serve that name by default (R226: a name nobody owns is a rebinding target on a LAN),
so ``tests/conftest.py`` lists it through ``OO_ALLOWED_HOSTS`` the way an operator would.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.main import _host_without_port, app


def _get(host: str | None = None):
    c = TestClient(app)
    headers = {"Host": host} if host is not None else None
    return c.get("/api/health", headers=headers)


def test_the_testclient_host_is_served_only_because_the_suite_lists_it(monkeypatch):
    """R226: the app serves the loopback names and the operator's own, and nothing else by default. ``tests/conftest.py`` lists
    ``testserver`` (Starlette's TestClient name) the way an operator lists a name; without that it is refused like any other. It is a
    single-label name nobody owns: a same-LAN attacker can answer it (LLMNR / NetBIOS), lure the user to it and rebind it to loopback,
    and the page is then same-origin with this API."""
    assert _get().status_code == 200  # the suite's OO_ALLOWED_HOSTS
    monkeypatch.delenv("OO_ALLOWED_HOSTS")
    assert _get().status_code == 421
    assert _get("testserver:8000").status_code == 421
    assert _get("TESTSERVER").status_code == 421
    assert _get("localhost:8000").status_code == 200  # the loopback names are still served without it


def test_without_the_env_testserver_is_not_a_name_a_state_change_may_come_from_either(monkeypatch):
    """The CSRF middleware is the outer one: a POST naming ``testserver`` as its Host or as its Origin is refused (403) before the Host guard."""
    monkeypatch.delenv("OO_ALLOWED_HOSTS")
    c = TestClient(app)
    for host, origin in (
        ("testserver:8000", "http://testserver:8000"),
        ("testserver", "http://testserver"),
        ("localhost:8000", "http://testserver:8000"),
    ):
        r = c.post("/api/briefing/refresh", headers={"Host": host, "Origin": origin})
        assert r.status_code == 403, (host, origin, r.status_code)


def test_loopback_hosts_are_accepted_with_and_without_port():
    for host in (
        "localhost",
        "localhost:8000",
        "127.0.0.1",
        "127.0.0.1:8000",
        "[::1]",
        "[::1]:8000",
    ):
        r = _get(host)
        assert r.status_code == 200, f"loopback Host {host!r} was refused: {r.status_code}"


def test_rebound_host_is_rejected_with_421():
    r = _get("evil.example.com")
    assert r.status_code == 421
    assert "Host header" in r.json()["detail"]
    # With a port too, and case-insensitively.
    assert _get("evil.example.com:8000").status_code == 421
    assert _get("EVIL.EXAMPLE.COM").status_code == 421


def test_missing_or_empty_host_is_rejected():
    # An empty Host names no server we serve — refuse (uvicorn/HTTP/1.1 clients
    # always send one; only hostile or ancient clients omit it).
    assert _get("").status_code == 421


def test_oo_allowed_hosts_escape_hatch(monkeypatch):
    # Without the env: refused.
    assert _get("myhost.lan:8000").status_code == 421
    # With it (comma-separated, whitespace tolerated): accepted, port-insensitive.
    monkeypatch.setenv("OO_ALLOWED_HOSTS", " myhost.lan , other.box ")
    assert _get("myhost.lan:8000").status_code == 200
    assert _get("myhost.lan").status_code == 200
    assert _get("other.box").status_code == 200
    # The env widens, never narrows: loopback + a still-unlisted name behave as before.
    assert _get("127.0.0.1:8000").status_code == 200
    assert _get("evil.example.com").status_code == 421


def test_host_without_port_handles_ipv6_and_odd_values():
    assert _host_without_port("localhost:8000") == "localhost"
    assert _host_without_port("127.0.0.1") == "127.0.0.1"
    assert _host_without_port("[::1]:8000") == "[::1]"
    assert _host_without_port("[::1]") == "[::1]"
    # A raw (unbracketed) IPv6 literal must not be mangled by port-stripping.
    assert _host_without_port("::1") == "::1"
    assert _host_without_port("Foo.Example:80") == "foo.example"
