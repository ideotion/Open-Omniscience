"""
Tests for the custody REST API (src/api/custody.py) and its registration.

Confirms the router is actually wired into the app (the gap that left PR #18's
endpoints dead), that log -> verify round-trips, that the standalone verifier
script accepts an exported bundle, and that an unavailable public-chain anchor
returns a clear 503 rather than a fake success.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Custody DB + signing keys live under the data dir; point it at tmp.
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    with TestClient(app) as c:
        yield c


def test_log_and_verify_roundtrip(client):
    r = client.post("/api/custody/log", json={
        "item_id": "article:1", "item_hash": "a" * 64,
        "action": "ingest", "actor": "tester",
    })
    assert r.status_code == 200, r.text
    entry = r.json()
    assert entry["action"] == "ingest"
    assert entry["entry_hash"]

    client.post("/api/custody/log", json={
        "item_id": "article:1", "item_hash": "a" * 64, "action": "access",
    })

    v = client.get("/api/custody/article:1/verify")
    assert v.status_code == 200
    assert v.json()["verified"] is True

    e = client.get("/api/custody/article:1")
    assert e.json()["entry_count"] == 2


def test_unknown_action_rejected(client):
    r = client.post("/api/custody/log", json={
        "item_id": "x", "item_hash": "b" * 64, "action": "frobnicate",
    })
    assert r.status_code == 400


def test_export_then_offline_verify(client, tmp_path):
    client.post("/api/custody/log", json={
        "item_id": "article:7", "item_hash": "c" * 64, "action": "ingest",
    })
    bundle = client.get("/api/custody/export").json()
    assert bundle["entry_count"] == 1

    # Posted-bundle verify endpoint.
    v = client.post("/api/custody/verify", json={"bundle": bundle})
    assert v.json()["verified"] is True

    # The standalone script verifies the same bundle with no app/DB.
    bundle_file = tmp_path / "custody.json"
    bundle_file.write_text(json.dumps(bundle))
    repo = Path(__file__).resolve().parents[1]
    res = subprocess.run(
        [sys.executable, str(repo / "scripts" / "verify_custody.py"), str(bundle_file)],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "VERIFIED       : True" in res.stdout


def test_providers_listed(client):
    r = client.get("/api/custody/providers")
    assert r.status_code == 200
    provs = r.json()["providers"]
    assert "local" in provs and "ethereum" in provs


def test_local_anchor_via_api(client):
    r = client.post("/api/custody/anchor", json={"merkle_root": "d" * 64, "provider": "local"})
    assert r.status_code == 200, r.text
    assert r.json()["provider"] == "local"


def test_public_chain_anchor_returns_503(client):
    r = client.post("/api/custody/anchor", json={"merkle_root": "e" * 64, "provider": "ethereum"})
    assert r.status_code == 503
    assert "not implemented" in r.json()["detail"].lower()


def test_verify_missing_item_404(client):
    assert client.get("/api/custody/nope/verify").status_code == 404
