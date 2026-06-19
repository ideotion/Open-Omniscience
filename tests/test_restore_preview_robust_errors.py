"""Restore preview/commit must ALWAYS answer with JSON, never a plain-text 500.

P0-3 (field test 2026-06-19, #O-3): two older-version backups failed to preview with
"JSON.parse: unexpected character at line 1 column 1" — the SPA calls res.json() on
the response, and an unhandled exception in the restore path returned Starlette's
plain-text 500. These tests pin (1) an old/incompatible artifact yields a clean JSON
error naming the version gap, (2) any other restore failure returns a JSON 500, and
(3) the global handler returns JSON for ANY unhandled error (the whole class).
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


def _rewrite_manifest(blob: bytes, **manifest_patch) -> bytes:
    """Return the artifact zip with manifest fields overwritten (simulates an older
    or incompatible backup). Signature will no longer match — but the schema check
    runs first, which is exactly the path we exercise."""
    zin = zipfile.ZipFile(io.BytesIO(blob))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "manifest.json":
                env = json.loads(data)
                env["manifest"].update(manifest_patch)
                data = json.dumps(env).encode("utf-8")
            zout.writestr(item, data)
    return out.getvalue()


def test_old_schema_backup_preview_returns_json_naming_the_version_gap(client):
    r = client.post("/api/backup/v2", json={"plaintext": True})
    assert r.status_code == 200
    old = _rewrite_manifest(r.content, backup_schema="oo-backup-1")

    prev = client.post(
        "/api/backup/v2/restore/preview",
        files={"file": ("old.oobak", old, "application/octet-stream")},
    )
    assert prev.status_code == 400
    assert prev.headers["content-type"].startswith("application/json")
    detail = prev.json()["detail"]
    assert "schema" in detail.lower() and "oo-backup-1" in detail  # names the gap


def test_run_restore_failure_in_preview_returns_json_500_not_plaintext(client, monkeypatch):
    """The actual P0-3 bug: an exception escaping run_restore used to re-raise into a
    plain-text 500. It must now be a JSON {detail}."""
    import src.api.backup_v2 as bv2

    r = client.post("/api/backup/v2", json={"plaintext": True})
    assert r.status_code == 200

    def boom(*a, **k):
        raise RuntimeError("staged migration failed on an ancient corpus")

    monkeypatch.setattr(bv2, "run_restore", boom)
    prev = client.post(
        "/api/backup/v2/restore/preview",
        files={"file": ("b.oobak", r.content, "application/octet-stream")},
    )
    assert prev.status_code == 500
    assert prev.headers["content-type"].startswith("application/json")
    detail = prev.json()["detail"]
    assert "incompatible version" in detail and "ancient corpus" in detail


def test_global_handler_turns_unhandled_errors_into_json():
    """Any otherwise-unhandled exception under the API returns JSON, not plain text —
    so the SPA never trips on JSON.parse again."""
    from src.api.main import app, unhandled_exception_handler
    from starlette.requests import Request

    assert Exception in app.exception_handlers, "global JSON exception handler is not registered"

    scope = {"type": "http", "method": "GET", "path": "/api/whatever", "headers": []}
    # The handler is async; run it on a fresh event loop.
    import asyncio

    resp = asyncio.new_event_loop().run_until_complete(
        unhandled_exception_handler(Request(scope), ValueError("kaboom"))
    )
    assert resp.status_code == 500
    assert resp.media_type == "application/json"
    assert b"kaboom" in resp.body
    # NB: we deliberately do NOT add a throwaway route to the shared app singleton to
    # test this end-to-end — that pollutes src.api.main.app.routes and has caused CI
    # flakiness (ledger lesson). The unit call above proves the handler's response, and
    # test_run_restore_failure_in_preview_returns_json_500_not_plaintext proves a real
    # endpoint error reaches the client as JSON.
