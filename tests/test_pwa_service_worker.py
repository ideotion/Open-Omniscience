"""
Tests for the root-scoped PWA service-worker route (@app.get("/sw.js")).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The static ``/static`` mount caps a service worker at scope ``/static/``; serving the
SAME file at the root ``/sw.js`` with a ``Service-Worker-Allowed: /`` header is what lets
the worker control the whole origin (full offline navigation of "/"). The worker's own
fetch guard is unchanged, so honesty is preserved: it still only touches the static shell,
never an API/data response.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

_SW_PATH = Path(__file__).resolve().parent.parent / "src" / "static" / "sw.js"


def _client():
    from src.api.main import app

    return TestClient(app)


def test_sw_js_served_at_root_with_scope_header():
    client = _client()
    r = client.get("/sw.js")
    assert r.status_code == 200
    # Root scope is granted by this header (what /static cannot do).
    assert r.headers.get("Service-Worker-Allowed") == "/"
    # Must be a JS content type or nosniff refuses to execute it.
    assert r.headers.get("content-type", "").split(";")[0].strip() == "text/javascript"
    # Never pin a stale worker.
    assert "no-cache" in (r.headers.get("cache-control", "").lower())
    # nosniff is applied by the security-headers middleware (regression net).
    assert r.headers.get("X-Content-Type-Options") == "nosniff"


def test_sw_js_is_byte_identical_to_the_static_shell_worker():
    client = _client()
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert r.text == _SW_PATH.read_text(encoding="utf-8")


def test_sw_js_still_caches_only_the_static_shell_not_api():
    # Honesty by construction: the served worker keeps its shell-only fetch guard, so
    # serving it at root scope never lets it cache/replay a stale API/data response.
    client = _client()
    body = client.get("/sw.js").text
    assert 'startsWith("/static/")' in body  # the guard that scopes caching to the shell
    # It must NOT unconditionally cache "/" or "/api/" (would go dangerously stale).
    assert "/api/" in body  # only ever mentioned in the "never touch" guard/comment


def test_sw_js_is_reachable_while_the_store_is_locked(monkeypatch):
    # The worker must register from the unlock screen, so /sw.js is in
    # ALLOWED_WHILE_LOCKED. Prove the lock gate lets it through while blocking others.
    import src.api.unlock as unlock

    monkeypatch.setattr(unlock, "app_lock_state", lambda: "locked")
    client = _client()

    allowed = client.get("/sw.js")
    assert allowed.status_code == 200
    assert allowed.headers.get("Service-Worker-Allowed") == "/"

    # A non-allowlisted API path is refused with the locked 503 in the same state.
    blocked = client.get("/api/insights/top")
    assert blocked.status_code == 503
    assert blocked.json().get("locked") is True
