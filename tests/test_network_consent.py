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

import ast
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_SRC = Path(__file__).resolve().parents[1] / "src"


def _imported_names(source: str) -> set[str]:
    """Every module name ``source`` imports, read from its AST rather than from line starts.

    The line-start regex this replaces (audit recheck P9, 2026-11-13; guards G8) could not see
    ``import os, socket``, ``from urllib import request``, ``from http import client``, an import
    behind ``;`` or ``importlib.import_module("socket")``. ``from X import y`` yields both ``X`` and
    ``X.y`` (``y`` may be a submodule); a call to ``import_module``/``__import__`` with a literal
    name counts as an import of it."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            fn = node.func
            called = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if called in ("import_module", "__import__") and isinstance(node.args[0].value, str):
                names.add(node.args[0].value)
    return names


def _imports_any(source: str, modules: tuple[str, ...]) -> bool:
    return any(n == m or n.startswith(m + ".") for n in _imported_names(source) for m in modules)


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
    "src/llm/loopback.py",  # R767: THE loopback rule; its httpx transport only scopes requests to loopback
    "src/safety/fetcher.py",  # the ONE guarded session factory (kill switch + proxy + UA)
    # NOTE: wiki/dumps, wiki/client, wiki/ores and services/duckduckgo were
    # removed from this allowlist when they were routed through guarded_session
    # (src/safety/fetcher) -- they no longer import requests directly, so the
    # kill switch and protected-mode proxy now cover them by construction.
}


def test_no_new_socket_importers():
    offenders = set()
    for py in _SRC.rglob("*.py"):
        rel = py.relative_to(_SRC.parent).as_posix()
        if _imports_any(py.read_text(encoding="utf-8", errors="replace"), ("requests", "httpx")):
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
    "src/llm/loopback.py":
        "R767: THE loopback rule for the local AI; its one connect is a port probe whose every answer is "
        "checked loopback on the socket (loopback_only), and its httpx transport only adds that scope",
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
    "src/tui/panel.py":
        "the launcher window's terminal panel (R600). http.client to the literal HOST "
        "127.0.0.1 on the app's own port, never read from argv or the environment; "
        "it POSTs only scheduler/stop (toward offline) and system/shutdown, never a "
        "move online (R601). Pinned by tests/test_terminal_panel.py",
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
    offenders = set()
    for py in _SRC.rglob("*.py"):
        if _imports_any(py.read_text(encoding="utf-8", errors="replace"), _SOCKET_CAPABLE_MODULES):
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


# --------------------------------------------------------------------------- #
# The same ratchet over scripts/ (row 129, from the 2026-11-17 egress audit).
# --------------------------------------------------------------------------- #
# A script runs in its OWN process: the app's kill switch and its socket guard
# are installed on app boot only, so a script that imports a socket-capable
# library reaches the network with neither, and reads no robots.txt unless it
# goes through the EthicalFetcher itself. The scripts that need the network
# for a user or operator (stat_news_check.py, thesaurus_build.py,
# build_place_gazetteer.py, bloc_roster_check.py, and build_city_gazetteer.py
# since row 132) import the guarded path from src/ and so are not listed here. Everything below was read before it was listed; docs/SECURITY.md
# names the egressing ones ("Maintainer build scripts").
_SCRIPTS = _SRC.parent / "scripts"

_ALLOWED_SCRIPT_SOCKET_IMPORTERS: dict[str, str] = {
    # -- real egress, maintainer-run; the output is a committed repository file --
    "scripts/build_world_news_catalog.py":
        "maintainer build: requests to query.wikidata.org (SPARQL) for news-outlet "
        "candidates into configs/world_news_sources.yml (not committed; the app seeds "
        "it beside the catalogue when present). No kill switch, no robots (an API)",
    "scripts/enrich_sources_wikidata.py":
        "maintainer build: urllib to www.wikidata.org (Action API) to fill source_type "
        "in configs/sources.yml. No kill switch, no robots (an API)",
    "scripts/generate_wikidata_elections.py":
        "maintainer build: ONE urllib SPARQL request to query.wikidata.org for the "
        "election snapshot, a committed repo file. No kill switch",
    "scripts/generate_wikidata_rings.py":
        "maintainer build: urllib to www.wikidata.org (Action API) for keyword-ring "
        "labels, a committed repo file. No kill switch",
    "scripts/build_country_polygons.py":
        "maintainer build: urllib download of Natural Earth GeoJSON from "
        "raw.githubusercontent.com, a committed data file. No kill switch",
    "scripts/build_disputed_areas.py":
        "maintainer build: urllib download of Natural Earth GeoJSON from "
        "raw.githubusercontent.com, a committed data file. No kill switch",
    "scripts/build_world_outline.py":
        "maintainer build: urllib download of Natural Earth GeoJSON from "
        "raw.githubusercontent.com, a committed data file. No kill switch",
    "scripts/build_ip_geo.py":
        "maintainer build: urllib download of the DB-IP country lite table from "
        "download.db-ip.com (mirror raw.githubusercontent.com), a bundled data file",
    "scripts/verify_worldbank_indicators.py":
        "maintainer check: urllib to api.worldbank.org to verify the curated "
        "indicator codes; writes nothing the app reads. No kill switch",
    "scripts/check_upstream_updates.py":
        "the weekly freshness CI job: urllib to api.github.com per registry "
        "upstream_check; runs on a CI runner, never on a user's machine",
    "scripts/analysis/phase2_verifier.py":
        "maintainer analysis: requests HEAD/GET of the URLs in an extracted references file, to check they "
        "resolve (loopback skipped). No kill switch, no robots; never run by the app",
    "scripts/analysis/run_stage_a.py":
        "maintainer catalogue kit run on the maintainer's own machine: an "
        "informational urllib GET of four fixed hosts (PROBE_HOSTS) and a child pip "
        "install from PyPI when its requirements stamp changes; the feed "
        "judging itself goes through verify_candidate_feeds' EthicalFetcher",
    # -- loopback only, or no connection at all --
    "scripts/apply_update.py":
        "self-update helper: a TCP connect to 127.0.0.1/::1 on the app's port to "
        "see if it answers, no request sent. Its git fetch is a child process, gated "
        "before the helper starts (App updates row in docs/SECURITY.md)",
    "scripts/fault_harness.py":
        "crash-pipeline test harness: binds a free 127.0.0.1 port and polls the "
        "throwaway app it started there over loopback; nothing leaves the machine",
    "scripts/ui_clickthrough_run.py":
        "UI walk harness: urllib to the seeded app instances on 127.0.0.1:8000-8003 "
        "only; Playwright drives the same loopback pages",
    "scripts/analytics45_generate.py":
        "imports socket only to INSTALL a tripwire that refuses every non-loopback "
        "connection, lookup and datagram for the whole run; the guard, not a way out",
}


def test_no_new_socket_capable_importers_in_scripts():
    """Row 129: scripts/ was outside both ratchets. A script has no app kill
    switch and no socket guard, so a new one that reaches the network must be
    a decision, written down here and in docs/SECURITY.md, not an accident."""
    offenders = set()
    for py in _SCRIPTS.rglob("*.py"):
        if _imports_any(py.read_text(encoding="utf-8", errors="replace"), _SOCKET_CAPABLE_MODULES):
            offenders.add(py.relative_to(_SRC.parent).as_posix())

    new = offenders - set(_ALLOWED_SCRIPT_SOCKET_IMPORTERS)
    assert not new, (
        f"new script(s) import a socket-capable library: {sorted(new)} -- a script "
        "has no app kill switch, socket guard or robots read. Use the guarded path "
        "(src.safety.fetcher.guarded_session or the EthicalFetcher via make_fetcher, "
        "behind an --online flag, as scripts/stat_news_check.py does), or add an "
        "entry to _ALLOWED_SCRIPT_SOCKET_IMPORTERS stating WHY, having read it, and "
        "name it in docs/SECURITY.md"
    )
    gone = set(_ALLOWED_SCRIPT_SOCKET_IMPORTERS) - offenders
    assert not gone, f"script allowlist is stale (no longer importers): {sorted(gone)}"


def test_every_script_socket_allowance_states_a_reason_and_is_documented():
    security = (_SRC.parent / "docs" / "SECURITY.md").read_text(encoding="utf-8")
    start = security.index("maintainer build scripts reach the network directly (row 129)")
    end = security.find("\n\n", start)
    paragraph = security[start:end if end != -1 else None]
    for path, reason in _ALLOWED_SCRIPT_SOCKET_IMPORTERS.items():
        assert len(reason.strip()) > 30, f"{path}: justification too thin: {reason!r}"
        assert f"`{path}`" in paragraph, (
            f"{path} is allowed to reach the network but the scripts paragraph of "
            "docs/SECURITY.md does not name it"
        )


@pytest.mark.parametrize(
    "source",
    [
        "import os, socket",
        "from urllib import request",
        "from http import client as c",
        "x = 1; import imaplib",
        "import importlib\nimportlib.import_module('socket')",
        "__import__('http.client')",
        "if True:\n    from urllib3.util import Retry",
    ],
)
def test_the_scanner_sees_the_import_forms_a_line_regex_missed(source: str) -> None:
    """Red before 2026-11-13: each form passed the line-start regex (guards G8)."""
    assert _imports_any(source, _SOCKET_CAPABLE_MODULES), source


@pytest.mark.parametrize("source", ["import socketserver", "from src.ingest import airplane", "import os", "# import socket"])
def test_the_scanner_does_not_widen_to_lookalikes(source: str) -> None:
    assert not _imports_any(source, _SOCKET_CAPABLE_MODULES), source


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


def test_every_consent_call_names_its_action():
    """Invariant #14: the ONE popup "names the action". Called bare, it reads "This
    action needs the network:" and then nothing -- Governments' "Load standard country
    data" did exactly that (delegated click-through 2026-09-26, row L). Every call site
    in the UI modules must pass the action as its first argument."""
    from tests.js_source_helper import strip_comments

    bare: list[str] = []
    seen = 0
    for path in sorted((_SRC / "static").glob("*.js")):
        code = strip_comments(path.read_text(encoding="utf-8"))
        for m in re.finditer(r"(?<![\w.])ensureOnline\(\s*(\S)", code):
            if code[max(0, m.start() - 9):m.start()] == "function ":
                continue                       # the definition, not a call
            seen += 1
            if m.group(1) in (")", ","):
                line = code.count("\n", 0, m.start()) + 1
                bare.append(f"{path.name}:~{line}")
    assert seen >= 10, f"only {seen} ensureOnline calls found -- the scan stopped matching"
    assert not bare, f"ensureOnline called without naming the action: {bare}"


def test_the_french_consent_popup_keeps_each_colon_with_its_word():
    """French puts a space before ':' and it must be a NO-BREAK one: with a plain space
    the colon of "Votre machine présente ces adresses réseau locales :" wrapped alone
    onto its own line in the popup (delegated click-through 2026-09-26, row H)."""
    import json

    fr = json.loads((_SRC / "static" / "locales" / "fr.json").read_text(encoding="utf-8"))
    headings = (
        "This action needs the network:", "Where this will let the app connect:",
        "Your machine presents these local network addresses:",
        "Runs on every collection pass:", "Only when you ask for it:",
        "Switched off right now:", "Could not read whether these are on:",
    )
    for key in headings:
        value = fr[key]
        assert value.endswith(":"), (key, value)
        assert value[-2] in (" ", " "), (
            f"fr {key!r} ends {value[-2:]!r}: the colon can wrap alone onto its own line"
        )
