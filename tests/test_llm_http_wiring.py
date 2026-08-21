"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

HTTP/wiring coverage for the llm STATUS surfaces (the TEST-05 residue).

test_llm_api.py (0.0.8 WP4) covers the inference half through the documented
dependency overrides, and test_vllm_endpoints.py deliberately calls its route
FUNCTIONS directly — so the model-management/lifecycle half had logic coverage
but no proof it dispatches over HTTP. These tests drive the REAL app (the
routes have no injection seams; they read module singletons), asserting status
+ payload SHAPE only — never machine-dependent VALUES, because a developer box
with a live Ollama and this sandbox must both pass.

Offline-safe by construction: every GET here is a read-only status probe
(loopback-at-most; conftest pins OO_LLM_AUTOSTART=0 so nothing spawns a
daemon), and the one POST exercised is the /uninstall CONFIRM GUARD, which
refuses before anything is touched. TestClient is used WITHOUT the context
manager on purpose: no lifespan, none needed for module-singleton reads (the
S1.1 lesson — the lifespan is a heavyweight global-state fixture).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.llm import router as llm_router
from src.api.main import app

_client = TestClient(app)

# route path (as mounted) -> keys the payload must carry ((), where the shape
# is builder-internal and only dict-ness is machine-independent).
_STATUS_ROUTES: dict[str, tuple[str, ...]] = {
    "/api/llm/activity": (),
    "/api/llm/backend": ("stored_override", "hardware"),
    "/api/llm/pull/status": ("active", "queue", "history"),
    "/api/llm/install/status": ("ollama_present", "platform"),
    "/api/llm/ollama/state": ("installed", "running", "can_launch"),
    "/api/llm/uninstall/plan": (),
    "/api/llm/activation": ("backend", "running", "can_start", "candidates"),
}


def test_status_routes_exist_on_the_router_itself():
    """Immutable-source anchor: the paths below are defined by src.api.llm's OWN
    router (never read off the shared app singleton's .routes)."""
    paths = {r.path for r in llm_router.routes}
    for path in _STATUS_ROUTES:
        assert path in paths, f"{path} is not defined on src.api.llm.router"
    assert "/api/llm/uninstall" in paths


def test_status_routes_dispatch_with_their_documented_shape():
    for path, keys in _STATUS_ROUTES.items():
        r = _client.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:200]}"
        body = r.json()
        assert isinstance(body, dict) and body, f"{path} returned an empty payload"
        for key in keys:
            assert key in body, f"{path} payload dropped {key!r}: {sorted(body)[:12]}"


def test_ollama_state_facts_are_independent_booleans():
    """installed and running are the two INDEPENDENT facts the surface exists to
    separate (field report 2026-07-29) — both must be real booleans, and
    can_launch must be their derived combination, on any machine."""
    body = _client.get("/api/llm/ollama/state").json()
    assert isinstance(body["installed"], bool)
    assert isinstance(body["running"], bool)
    assert body["can_launch"] == (body["installed"] and not body["running"])


def test_uninstall_refuses_without_explicit_confirmation():
    """The destructive route's guard, proven over HTTP: no confirm -> 400 and
    nothing is touched; confirmed-but-unnamed backends -> 400 too. (The
    confirmed happy path deletes real state and is covered at function level —
    deliberately NOT driven here.)"""
    r = _client.post("/api/llm/uninstall", json={"backends": ["vllm"]})
    assert r.status_code == 400
    assert "confirmation" in r.json()["detail"].lower()

    r = _client.post("/api/llm/uninstall", json={"confirm": True, "backends": []})
    assert r.status_code == 400
    assert "backend" in r.json()["detail"].lower()


def test_uninstall_plan_is_read_only_and_names_what_it_cannot_remove():
    """GET /uninstall/plan is the consent surface: calling it twice must be
    idempotent (read-only), and each planned target must say whether it is
    removable rather than implying everything is."""
    first = _client.get("/api/llm/uninstall/plan").json()
    second = _client.get("/api/llm/uninstall/plan").json()
    assert first == second

    def _targets(node):
        if isinstance(node, dict):
            if "removable" in node:
                yield node
            for v in node.values():
                yield from _targets(v)
        elif isinstance(node, list):
            for v in node:
                yield from _targets(v)

    targets = list(_targets(first))
    assert targets, f"uninstall plan carries no removable-annotated targets: {first}"
    for t in targets:
        assert isinstance(t["removable"], bool)
