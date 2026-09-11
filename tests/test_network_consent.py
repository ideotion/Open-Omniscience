"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com

---

T2 — the network toggle batch (maintainer-ruled 2026-06-12): airplane-mode
semantics, the online-consent popup's data source (LOCAL interface addresses,
never a network call), network state riding scheduler responses for the
immediate repaint, and the socket-importer ratchet (kill-switch reliability:
no NEW module may open its own way to the network).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_SRC = Path(__file__).resolve().parents[1] / "src"


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


def test_interfaces_endpoint_is_local_only(client):
    """The consent popup's address list comes from kernel tables — the
    response must carry the method saying so, and the endpoint must work
    with the kill switch ACTIVE (proof it makes no network call)."""
    from src.ingest import activate_kill_switch, clear_kill_switch

    activate_kill_switch()
    try:
        r = client.get("/api/system/interfaces")
        assert r.status_code == 200
        body = r.json()
        assert "psutil.net_if_addrs" in body["method"]
        for entry in body["interfaces"]:
            assert entry["addresses"], "an interface without addresses must be omitted"
            for ip in entry["addresses"]:
                assert not ip.startswith(("127.", "169.254.", "fe80"))
                assert ip != "::1"
    finally:
        clear_kill_switch()


def test_scheduler_status_carries_network_state(client):
    from src.ingest import activate_kill_switch, clear_kill_switch

    clear_kill_switch()
    assert client.get("/api/scheduler/status").json()["online"] is True
    activate_kill_switch()
    try:
        assert client.get("/api/scheduler/status").json()["online"] is False
    finally:
        clear_kill_switch()


def test_scheduler_stop_reports_offline_immediately(client):
    """The stop response itself must carry online=False — the UI repaints from
    it instead of waiting for the next poll (the ruled immediate repaint)."""
    from src.ingest import clear_kill_switch

    try:
        body = client.post("/api/scheduler/stop").json()
        assert body["online"] is False
    finally:
        clear_kill_switch()


# --------------------------------------------------------------------------- #
# Kill-switch reliability: the socket-importer RATCHET. The kill switch can
# only be airtight if every outbound path is known. This pins the exact set of
# modules that import an HTTP client; adding a new one fails the build until
# it is consciously routed through the guarded fetch path (or justified here).
# --------------------------------------------------------------------------- #
_ALLOWED_HTTP_IMPORTERS = {
    "src/ingest/__init__.py",  # THE fetch path (EthicalFetcher + kill switch)
    "src/llm/ollama.py",  # loopback-only by construction (localhost Ollama)
    "src/llm/vllm_client.py",  # loopback-only by construction (localhost vLLM server)
    "src/safety/fetcher.py",  # the ONE guarded session factory (kill switch + proxy + UA)
    # NOTE: wiki/dumps, wiki/client, wiki/ores and services/duckduckgo were
    # removed from this allowlist when they were routed through guarded_session
    # (src/safety/fetcher) -- they no longer import requests directly, so the
    # kill switch and protected-mode proxy now cover them by construction.
}


def test_no_new_socket_importers():
    pattern = re.compile(r"^\s*(import (requests|httpx)\b|from (requests|httpx)\b)", re.M)
    offenders = set()
    for py in _SRC.rglob("*.py"):
        rel = py.relative_to(_SRC.parent).as_posix()
        if pattern.search(py.read_text(encoding="utf-8", errors="replace")):
            offenders.add(rel)
    new = offenders - _ALLOWED_HTTP_IMPORTERS
    assert not new, (
        f"new module(s) import an HTTP client directly: {sorted(new)} — route "
        "outbound traffic through the guarded fetch path (src/ingest) or add a "
        "reviewed justification to _ALLOWED_HTTP_IMPORTERS"
    )
    gone = _ALLOWED_HTTP_IMPORTERS - offenders
    assert not gone, f"allowlist is stale (no longer importers): {sorted(gone)}"


# --------------------------------------------------------------------------- #
# The WIDER ratchet: any socket-capable library, not only an HTTP client.
# --------------------------------------------------------------------------- #
# CLAUDE.md invariant #14f recorded this gap when the OpenTimestamps consent
# gates shipped: the ratchet above matches only `requests`/`httpx`, so it "was
# and remains blind to opentimestamps.calendar's import shape", and it named a
# future session widening it as the fix. It is equally blind to imaplib, poplib,
# http.client and bare `socket` -- every one of which can open an outbound
# connection without touching the guarded fetch path.
#
# The premise this protects is the kill switch's: it "can only be airtight if
# every outbound path is KNOWN". Airplane mode is enforced at the socket layer
# (src/ingest/airplane.py), so a module reaching the network by some other
# library is still refused while offline -- but it is refused by the net beneath,
# not by anyone having thought about it. This ratchet is the thinking.
_SOCKET_CAPABLE_MODULES = (
    "requests", "httpx", "urllib.request", "urllib3", "http.client", "aiohttp",
    "websockets", "ftplib", "smtplib", "imaplib", "poplib", "telnetlib",
    "socket", "opentimestamps", "paramiko", "pycurl",
)

#: Every module that may import one, and WHY. Each was read before being listed
#: -- an allowlist filled in from a failing run rather than from the code is the
#: ratchet rubber-stamping itself.
_ALLOWED_SOCKET_IMPORTERS: dict[str, str] = {
    "src/ingest/__init__.py":
        "THE fetch path: EthicalFetcher + the kill switch itself",
    "src/safety/fetcher.py":
        "the ONE guarded session factory (kill switch + proxy + UA)",
    "src/llm/ollama.py":
        "loopback-only by construction (localhost Ollama), _require_loopback-gated",
    "src/llm/vllm_client.py":
        "loopback-only by construction (localhost vLLM server)",
    "src/ingest/airplane.py":
        "IS the socket guard -- it patches getaddrinfo/create_connection/connect, "
        "so importing socket and http.client is the mechanism, not a bypass",
    "src/ingest/email.py":
        "the live mailbox pull (imaplib/poplib). REAL egress to a user-named host, "
        "and gated: both readers call _refuse_if_offline() before connecting "
        "(ruling #11). Not routable through EthicalFetcher -- IMAP/POP are not HTTP",
    "src/custody/timestamp.py":
        "OpenTimestamps calendar submission (invariant #14f). REAL egress to three "
        "public Bitcoin calendars, revealing IP + timing; consent-gated on all three "
        "reachable paths and ots_stamp() refuses by name when the kill switch is on",
    "src/api/system.py":
        "CONSTANTS ONLY -- socket.AF_INET/AF_INET6 to filter psutil.net_if_addrs() "
        "when listing LOCAL interface IPs for the consent popup (invariant #14). "
        "No socket is constructed and nothing connects",
    "src/llm/vllm_lifecycle.py":
        "a port probe (connect_ex) against the CONFIGURED vLLM URL, defaulting to "
        "127.0.0.1. A remote URL would egress here, which the airplane socket guard "
        "refuses while offline -- listed so that is a known property, not a surprise",
}


def test_no_new_socket_capable_importers():
    """Widened per invariant #14f: an HTTP client is not the only way out.

    imaplib, poplib, http.client, opentimestamps and bare `socket` all reach the
    network, and the narrow ratchet above sees none of them.
    """
    alt = "|".join(m.replace(".", r"\.") for m in _SOCKET_CAPABLE_MODULES)
    pattern = re.compile(rf"^\s*(?:import\s+({alt})\b|from\s+({alt})\b)", re.M)
    offenders = set()
    for py in _SRC.rglob("*.py"):
        if pattern.search(py.read_text(encoding="utf-8", errors="replace")):
            offenders.add(py.relative_to(_SRC.parent).as_posix())

    new = offenders - set(_ALLOWED_SOCKET_IMPORTERS)
    assert not new, (
        f"new module(s) import a socket-capable library: {sorted(new)} -- route "
        "outbound traffic through the guarded fetch path (src/ingest), or add an "
        "entry to _ALLOWED_SOCKET_IMPORTERS stating WHY, having read what it does. "
        "The kill switch is airtight only while every outbound path is known."
    )
    gone = set(_ALLOWED_SOCKET_IMPORTERS) - offenders
    assert not gone, (
        f"allowlist is stale (no longer importers): {sorted(gone)} -- drop them, so "
        "the list keeps meaning 'these, and only these, can reach the network'"
    )


def test_every_socket_importer_allowance_states_a_reason():
    """A bare path in the allowlist is a rubber stamp. Each entry must say why,
    because the next reader's only defence against a silently-added exemption is
    that adding one requires writing a sentence they can disagree with."""
    for path, reason in _ALLOWED_SOCKET_IMPORTERS.items():
        assert len(reason.strip()) > 30, f"{path}: justification too thin: {reason!r}"


def test_the_narrow_http_ratchet_is_a_subset_of_the_wide_one():
    """The two lists must not drift apart: every HTTP-client importer is also a
    socket-capable importer, so the narrow allowlist has to be contained in the
    wide one. Without this they are two hand-maintained lists that agree only by
    luck, and the wider guard could be quietly weakened by editing the wrong one."""
    missing = _ALLOWED_HTTP_IMPORTERS - set(_ALLOWED_SOCKET_IMPORTERS)
    assert not missing, (
        f"in the HTTP allowlist but not the socket allowlist: {sorted(missing)}"
    )
