"""
oo-backup-2 endpoints: artifact download + merge-restore preview/commit.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The deep merge semantics live in tests/test_db_reliability_torture.py (the
acceptance suite, subprocess-isolated). These tests cover the HTTP contract:
explicit-plaintext rule, manifest shape, preview token flow, self-merge safety.
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


def test_backup_v2_requires_explicit_choice(client):
    r = client.post("/api/backup/v2", json={})
    assert r.status_code == 400
    assert "passphrase" in r.json()["detail"]


def test_backup_v2_plaintext_manifest_shape(client):
    r = client.post("/api/backup/v2", json={"plaintext": True})
    assert r.status_code == 200
    blob = r.content
    assert blob[:4] == b"PK\x03\x04"
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        env = json.loads(zf.read("manifest.json"))
        m = env["manifest"]
        assert m["backup_schema"] == "oo-backup-2"
        assert m["keys_included"] is False  # D2: plaintext never carries keys
        assert not any(x["role"] == "keys" for x in m["members"])
        assert "corpus.db" in zf.namelist()
        assert env["algorithm"] == "ed25519" and env["signature"]


def test_backup_v2_encrypted_roundtrip_and_self_merge(client):
    r = client.post("/api/backup/v2", json={"passphrase": "api-pw-123"})
    assert r.status_code == 200
    blob = r.content
    assert blob[:6] == b"OOENC1"

    before = client.get("/api/backup/v2/batches").json()
    prev = client.post(
        "/api/backup/v2/restore/preview",
        files={"file": ("b.oobak.ooenc", blob)},
        data={"passphrase": "api-pw-123"},
    )
    assert prev.status_code == 200, prev.text
    rep = prev.json()
    assert rep["committed"] is False and rep["verification"]["ok"] is True
    # Self-merge: everything is a duplicate of itself; nothing new anywhere.
    news = {k: v["new"] for k, v in rep["plan"].items() if isinstance(v, dict) and v.get("new")}
    assert news == {}
    token = rep["commit_token"]

    com = client.post("/api/backup/v2/restore/commit", data={"token": token})
    assert com.status_code == 200, com.text
    rep2 = com.json()
    assert rep2["committed"] is True and rep2["verification"]["ok"] is True

    # The token is single-use.
    again = client.post("/api/backup/v2/restore/commit", data={"token": token})
    assert again.status_code == 409

    after = client.get("/api/backup/v2/batches").json()
    assert len(after["batches"]) == len(before["batches"]) + 1
    assert after["batches"][0]["status"] == "merged"


def test_restore_preview_wrong_passphrase_is_loud(client):
    r = client.post("/api/backup/v2", json={"passphrase": "right-pw"})
    assert r.status_code == 200
    bad = client.post(
        "/api/backup/v2/restore/preview",
        files={"file": ("b.ooenc", r.content)},
        data={"passphrase": "wrong-pw"},
    )
    assert bad.status_code == 400
    assert "decryption failed" in bad.json()["detail"]


def test_restore_rejects_garbage(client):
    bad = client.post(
        "/api/backup/v2/restore/preview",
        files={"file": ("x.bin", b"this is not a backup at all")},
    )
    assert bad.status_code == 400


def test_backup_v2_unexpected_error_returns_json_detail(client, monkeypatch):
    """An UNEXPECTED builder failure (not BackupError/ArtifactError -- e.g. a full
    temp volume raising sqlite3.OperationalError during the snapshot) must surface
    as a JSON {detail} 500, never a plain-text 'Internal Server Error'. The browser
    does res.json() on the error body, so a plain-text 500 shows the user only the
    useless 'JSON.parse: unexpected character at line 1 column 1'."""
    import src.backup.artifact as artifact

    def boom(*_a, **_k):
        raise RuntimeError("simulated full temp volume")

    # The endpoint imports write_backup_v2 from the module at call time.
    monkeypatch.setattr(artifact, "write_backup_v2", boom)
    r = client.post("/api/backup/v2", json={"plaintext": True})
    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/json")
    assert "simulated full temp volume" in r.json()["detail"]
