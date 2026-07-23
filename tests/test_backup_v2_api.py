"""
oo-backup-2 endpoints: merge-restore preview/commit.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The size-capped single-file CREATE endpoint (POST /api/backup/v2) was retired
(2026-07-01) — backups are made by the unified volume/folder export. These tests
now build a single-file artifact via write_backup_v2 (the internal builder, still
used by the torture suite) and cover the RESTORE HTTP contract: manifest shape,
preview token flow, self-merge safety. The deep merge semantics live in
tests/test_db_reliability_torture.py (the acceptance suite, subprocess-isolated).
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


def _build_backup(passphrase=None) -> bytes:
    """Build a single-file oo-backup-2 artifact via the internal builder + return its
    bytes (replaces the retired POST /api/backup/v2 create endpoint in tests). Must run
    while the app/DB is up (the ``client`` fixture)."""
    import os
    import tempfile
    from pathlib import Path

    from src.backup.artifact import write_backup_v2

    fd, tmp = tempfile.mkstemp(suffix=".oobak")
    os.close(fd)
    dest = Path(tmp)
    dest.unlink(missing_ok=True)
    write_backup_v2(dest, passphrase=passphrase)
    try:
        return dest.read_bytes()
    finally:
        dest.unlink(missing_ok=True)


def test_plaintext_artifact_manifest_shape(client):
    blob = _build_backup()  # plaintext (no passphrase)
    assert blob[:4] == b"PK\x03\x04"
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        env = json.loads(zf.read("manifest.json"))
        m = env["manifest"]
        assert m["backup_schema"] == "oo-backup-2"
        assert m["keys_included"] is False  # D2: plaintext never carries keys
        assert not any(x["role"] == "keys" for x in m["members"])
        assert "corpus.db" in zf.namelist()
        assert env["algorithm"] == "ed25519" and env["signature"]


def test_persisted_import_reports_ride_the_backup_export(client):
    """S3.5 (field-feedback A1): a persisted import/restore report under
    data_dir()/import_reports/ must be carried by the oo-backup-2 export (never
    silently dropped), while a fresh install with NO reports yet never crashes."""
    from src.backup.import_reports import persist_import_report

    path = persist_import_report("restore", {"kind": "restore", "plan": {}}, run_id="t1")
    blob = _build_backup()
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        env = json.loads(zf.read("manifest.json"))
        m = env["manifest"]
        rel = f"import_reports/{path.name}"
        assert rel in zf.namelist()
        assert any(x["name"] == rel and x["role"] == "import_reports" for x in m["members"])


def test_import_reports_list_and_download_endpoints(client):
    from src.backup.import_reports import persist_import_report

    path = persist_import_report(
        "restore", {"kind": "restore", "tally": {"new": 5}}, run_id="ep1"
    )
    listing = client.get("/api/backup/import-reports").json()["reports"]
    assert any(r["filename"] == path.name for r in listing)

    as_json = client.get(f"/api/backup/import-reports/{path.name}")
    assert as_json.status_code == 200
    assert as_json.json()["tally"]["new"] == 5

    as_md = client.get(f"/api/backup/import-reports/{path.name}", params={"format": "md"})
    assert as_md.status_code == 200
    assert "text/markdown" in as_md.headers["content-type"]
    assert "5 new articles" in as_md.text

    assert client.get("/api/backup/import-reports/does-not-exist.json").status_code == 404
    assert client.get(f"/api/backup/import-reports/{path.name}?format=xml").status_code == 400
    # path traversal must never leak outside the reports directory
    assert client.get("/api/backup/import-reports/..%2F..%2Fetc%2Fpasswd").status_code in (404, 400)


def test_encrypted_roundtrip_and_self_merge(client):
    blob = _build_backup("api-pw-123")
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
    blob = _build_backup("right-pw")
    bad = client.post(
        "/api/backup/v2/restore/preview",
        files={"file": ("b.ooenc", blob)},
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


def test_legacy_restore_from_server_side_path_is_additive(client, tmp_path):
    # The unified Import dialog restores a legacy single-file backup it discovered on
    # disk via a SERVER-SIDE path (a folder may hold several). Additive self-merge:
    # committed, a per-table plan is returned (the import-summary source), nothing new.
    from pathlib import Path

    from src.backup.artifact import write_backup_v2

    dest = Path(tmp_path) / "open-omniscience-20260702.oobak"
    write_backup_v2(dest, passphrase="legacy-pw")

    r = client.post(
        "/api/backup/legacy/restore",
        json={"path": str(dest), "passphrase": "legacy-pw"},
    )
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["committed"] is True and rep["verification"]["ok"] is True
    assert "plan" in rep  # per-table new/duplicate counts the summary renders
    news = {k: v["new"] for k, v in rep["plan"].items() if isinstance(v, dict) and v.get("new")}
    assert news == {}  # self-merge adds nothing


def test_legacy_restore_missing_file_is_honest_400(client):
    r = client.post(
        "/api/backup/legacy/restore",
        json={"path": "/nonexistent/nope.oobak", "passphrase": ""},
    )
    assert r.status_code == 400
    assert "not a file" in r.json()["detail"]
