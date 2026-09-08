"""
Router wiring decomposition (audit PR H): main.py delegates every include_router
call to src/api/_wiring.py:wire().

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Guards are anchored to IMMUTABLE sources — the ``_wiring``/``main`` module source and
each router's OWN ``router.routes`` — plus robust TestClient dispatch (an HTTP call,
exactly as the rest of the suite does). They NEVER assert positive facts against the
shared ``src.api.main.app`` ``.routes`` singleton (that process-global read made an
earlier guard flaky in CI).
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

from fastapi.testclient import TestClient

from src.api.main import app

_API = Path(__file__).resolve().parents[1] / "src" / "api"
_MAIN = (_API / "main.py").read_text(encoding="utf-8")
_WIRING = (_API / "_wiring.py").read_text(encoding="utf-8")

# A spread of routers that must be wired (their modules + a known GET path each).
_SPINE = ["system", "briefing", "scheduler", "wiki", "jobs", "unlock", "llm",
          "source_management", "search_omni", "timemap", "reporting", "custody", "safety", "library"]


def test_main_delegates_all_wiring_to_wire():
    """main.py calls wire(app) and holds NO inline include_router calls itself."""
    assert "from src.api._wiring import wire" in _MAIN
    assert "wire(app)" in _MAIN
    assert "app.include_router(" not in _MAIN, (
        "every include_router call must live in _wiring.py, not main.py (PR H)"
    )


def test_wiring_module_imports_and_includes_each_router():
    """_wiring.py imports each spine router and iterates include_router; the optional
    analysis block is preserved."""
    for mod in _SPINE:
        assert f"from src.api.{mod} import router" in _WIRING, f"_wiring must import {mod}"
    assert "app.include_router(router)" in _WIRING, "_wiring must iterate include_router"
    assert "from src.api.commodity import router" in _WIRING, (
        "_wiring must preserve the optional [analysis] router block"
    )
    # framing is genuinely [analysis]-only (needs numpy/scipy/vaderSentiment via
    # its dependencies) and cannot join _SPINE because a core-only install
    # legitimately does not mount it.
    assert "from src.api.framing import router" in _WIRING, (
        "_wiring must import the optional framing router"
    )
    # keyword_management has ZERO ML dependency (keyword_extractor/text_processor
    # are pure stdlib) — it cannot join _SPINE only because it is not a spine
    # router by convention, NOT because it needs [analysis]. See the dedicated
    # decoupling test below (P1 fix, previously it was wrongly bundled into the
    # analysis-only try/except and silently disabled by an unrelated ImportError).
    assert "from src.api.keyword_management import router" in _WIRING, (
        "_wiring must import the keyword_management router"
    )


def test_keyword_management_import_is_not_inside_the_analysis_try_block():
    """Regression pin for the P1 finding ("core install loses keyword endpoints"):
    keyword_management_router has zero ML dependency and must be imported and
    included OUTSIDE the try/except that guards the genuinely ML-dependent
    analysis/commodity/framing/keyword_analysis routers. Before the fix, all five
    imports shared one try block, so an ImportError raised importing any of the
    first four (all legitimately [analysis]-gated) silently took keyword_management
    down with it too, even though it needs nothing from that extra.
    """
    km_match = re.search(r"from src\.api\.keyword_management import router", _WIRING)
    assert km_match, "keyword_management import not found in _wiring.py"

    try_match = re.search(
        r"try:\s*\n\s*from src\.api\.analysis import router", _WIRING
    )
    assert try_match, "the analysis-only try block was not found in _wiring.py"

    assert km_match.start() < try_match.start(), (
        "keyword_management's import must sit BEFORE (and structurally outside) "
        "the analysis-only try/except block, so a broken analysis/commodity/"
        "framing/keyword_analysis import can never disable it"
    )


def test_every_wired_router_defines_routes():
    """Each wired router defines its OWN routes (immutable source of truth)."""
    for mod in _SPINE:
        router = importlib.import_module(f"src.api.{mod}").router
        assert router.routes, f"src.api.{mod}.router defines no routes"


def test_wired_endpoints_dispatch_not_404():
    """Runtime proof that wire() actually mounted the routers: a GET to a known
    endpoint from several routers dispatches (any status but 404 = the route exists).
    This is an HTTP call through the app (robust), not an app.routes singleton read."""
    c = TestClient(app)
    for path in ("/api/scheduler/status", "/api/system/network", "/api/briefing",
                 "/api/llm/prompts"):
        assert c.get(path).status_code != 404, f"{path} is not wired (got 404)"


def test_keyword_management_endpoints_dispatch_regardless_of_analysis_extra():
    """Runtime pin for the P1 fix: every keyword_management endpoint dispatches on
    the ACTUAL production app, whether or not the [analysis] extra (numpy/scikit-
    learn) happens to be installed in this environment — unlike commodity/analysis/
    framing, keyword_management has no ML dependency to require it for. An HTTP
    dispatch through the real app (not a positive app.routes singleton read, per
    the documented flakiness lesson) is the robust check here too."""
    c = TestClient(app)
    for path in (
        "/api/keywords/extract?text=hello",
        "/api/keywords/extract/article",
        "/api/keywords/categories",
        "/api/keywords/categorize?text=hello",
        "/api/keywords/top?text=hello",
        "/api/keywords/phrases?text=hello",
        "/api/keywords/statistics?text=hello",
        "/api/keywords/process?text=hello",
        "/api/keywords/frequencies?text=hello",
    ):
        status = c.get(path).status_code
        assert status != 404, f"{path} is not wired (got 404) — keyword_management " \
            "must never be disabled by an unrelated [analysis] import failure"
