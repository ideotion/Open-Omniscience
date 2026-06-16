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
from pathlib import Path

from fastapi.testclient import TestClient

from src.api.main import app

_API = Path(__file__).resolve().parents[1] / "src" / "api"
_MAIN = (_API / "main.py").read_text(encoding="utf-8")
_WIRING = (_API / "_wiring.py").read_text(encoding="utf-8")

# A spread of routers that must be wired (their modules + a known GET path each).
_SPINE = ["system", "briefing", "scheduler", "wiki", "jobs", "unlock",
          "source_management", "search_omni", "timemap", "reporting", "custody", "safety"]


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
    for path in ("/api/scheduler/status", "/api/system/network", "/api/briefing"):
        assert c.get(path).status_code != 404, f"{path} is not wired (got 404)"
