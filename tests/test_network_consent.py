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
