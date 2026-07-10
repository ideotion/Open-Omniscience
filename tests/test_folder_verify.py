"""A6: standalone verify for the FOLDER backup (the volumes backup already had one).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Every manifest-listed file must be present with the exact recorded size; the content-
addressed Ollama model blobs (blobs/sha256-<hex>) are also content-hashed against their
name. Wiki dumps / OSM extracts carry no stored checksum (immutable public downloads) so
they are size-verified only. Pinned: a clean backup passes; a deleted / truncated / content-
corrupted file is caught honestly; a hostile manifest path is traversal-refused; a missing
manifest is an honest verdict, never a crash.
"""

from __future__ import annotations

import hashlib
import json

from src.backup.folder_backup import (
    MANIFEST_NAME,
    BackupItem,
    get_folder_manager,
    verify_folder_backup,
    write_folder_backup,
)


def _write(p, data: bytes):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _items(src):
    return [
        BackupItem("wiki_dumps", "enwiki/a.bz2", _write(src / "a.bz2", b"a" * 100), 100),
        BackupItem("osm_regions", "europe.pbf", _write(src / "c.pbf", b"c" * 200), 200),
    ]


def _blob_item(src, content: bytes):
    """A content-addressed model blob named after the sha256 of its content."""
    hexd = hashlib.sha256(content).hexdigest()
    rel = f"blobs/sha256-{hexd}"
    return BackupItem("models", rel, _write(src / f"blob-{hexd[:8]}", content), len(content)), rel


def test_verify_ok_on_a_fresh_backup(tmp_path):
    src, dest = tmp_path / "src", tmp_path / "dest"
    write_folder_backup(dest, _items(src))
    rep = verify_folder_backup(dest)
    assert rep["manifest_found"] is True
    assert rep["ok"] is True
    assert rep["files_total"] == 2
    assert rep["summary"]["size_only"] == 2  # dumps/maps: size-verified, no stored checksum
    assert rep["problems"] == []


def test_verify_catches_a_missing_file(tmp_path):
    src, dest = tmp_path / "src", tmp_path / "dest"
    write_folder_backup(dest, _items(src))
    (dest / "wiki_dumps" / "enwiki" / "a.bz2").unlink()
    rep = verify_folder_backup(dest)
    assert rep["ok"] is False
    assert rep["summary"]["missing"] == 1
    assert any(p["status"] == "missing" and p["rel"] == "enwiki/a.bz2" for p in rep["problems"])


def test_verify_catches_a_size_mismatch(tmp_path):
    src, dest = tmp_path / "src", tmp_path / "dest"
    write_folder_backup(dest, _items(src))
    (dest / "osm_regions" / "europe.pbf").write_bytes(b"c" * 199)  # truncated by one byte
    rep = verify_folder_backup(dest)
    assert rep["ok"] is False
    assert rep["summary"]["size_mismatch"] == 1
    bad = next(p for p in rep["problems"] if p["status"] == "size_mismatch")
    assert bad["expected_size"] == 200 and bad["actual_size"] == 199


def test_verify_model_blob_content_hash(tmp_path):
    src, dest = tmp_path / "src", tmp_path / "dest"
    item, rel = _blob_item(src, b"MODELDATA")
    write_folder_backup(dest, [item])
    rep = verify_folder_backup(dest)
    assert rep["ok"] is True
    assert rep["files_checksummed"] == 1  # the blob was content-verified, not size-only
    assert rep["summary"]["ok"] == 1

    # Corrupt the blob's CONTENT but keep its SIZE: size passes, the content hash fails.
    (dest / "models" / rel).write_bytes(b"XXXXXXXXX")  # same 9 bytes, different content
    rep2 = verify_folder_backup(dest)
    assert rep2["ok"] is False
    assert rep2["summary"]["checksum_mismatch"] == 1


def test_verify_refuses_a_traversal_manifest(tmp_path):
    """A folder backup on an external drive is untrusted input: a manifest whose rel escapes
    the backup dir must be refused, never stat/hashed at that arbitrary path."""
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / MANIFEST_NAME).write_text(
        json.dumps(
            {
                "schema": "oo-folder-backup-1",
                "categories": {"wiki_dumps": [{"rel": "../../etc/passwd", "size": 1}]},
            }
        ),
        encoding="utf-8",
    )
    rep = verify_folder_backup(dest)
    assert rep["ok"] is False
    assert rep["summary"]["traversal_refused"] == 1


def test_verify_no_manifest_is_an_honest_verdict(tmp_path):
    dest = tmp_path / "empty"
    dest.mkdir()
    rep = verify_folder_backup(dest)
    assert rep["manifest_found"] is False
    assert rep["ok"] is False
    assert "reason" in rep  # honest, never a crash


def _write_manifest(dest, obj):
    dest.mkdir(exist_ok=True)
    (dest / MANIFEST_NAME).write_text(json.dumps(obj), encoding="utf-8")


def test_verify_malformed_categories_is_an_honest_verdict_not_a_crash(tmp_path):
    """Skeptic finding: a manifest whose 'categories' is not an object (a JSON array/string/
    number/null) is UNTRUSTED external input — it must yield ok=False honestly, NEVER raise
    (the function's 'never raises' contract)."""
    for bad in ([1, 2, 3], "broken", 5, None):
        dest = tmp_path / f"m-{type(bad).__name__}"
        _write_manifest(dest, {"schema": "oo-folder-backup-1", "categories": bad})
        rep = verify_folder_backup(dest)  # must not raise
        assert rep["manifest_found"] is True
        assert rep["ok"] is False
        assert "reason" in rep


def test_verify_corrupted_but_parseable_manifest_is_not_a_false_ok(tmp_path):
    """Skeptic finding: a parseable manifest whose category VALUES are non-lists (or whose
    entries are non-dicts) must NOT report ok=True (files_total=0 would fake an 'all clear')."""
    dest = tmp_path / "corrupt"
    _write_manifest(
        dest,
        {"categories": {"wiki_dumps": "BROKEN", "models": [42, {"rel": "x", "size": "y"}]}},
    )
    rep = verify_folder_backup(dest)
    assert rep["ok"] is False  # structural damage is a failure, never a silent OK
    assert rep["summary"]["malformed_entries"] >= 2

    # A genuinely EMPTY (but well-formed) backup is still a legitimate ok=True.
    empty = tmp_path / "genuinely-empty"
    _write_manifest(empty, {"categories": {"wiki_dumps": [], "osm_regions": [], "models": []}})
    assert verify_folder_backup(empty)["ok"] is True

    # A manifest with NO categories key at all is a damaged/foreign manifest, not "empty".
    nokey = tmp_path / "nokey"
    _write_manifest(nokey, {"schema": "oo-folder-backup-1"})
    assert verify_folder_backup(nokey)["ok"] is False


def test_manager_verify_mode_surfaces_the_verdict(tmp_path):
    """The verify runs as the (single) folder job so it is visible/cancellable in /api/jobs;
    the verdict rides status()['verify']."""
    src, dest = tmp_path / "src", tmp_path / "dest"
    write_folder_backup(dest, _items(src))
    mgr = get_folder_manager()
    mgr.start(str(dest), ["wiki_dumps", "osm_regions", "models"], mode="verify")
    mgr._thread.join(timeout=10)  # type: ignore[union-attr]
    st = mgr.status()
    assert st["mode"] == "verify"
    assert st["state"] == "done"
    assert st["verify"]["ok"] is True
    assert st["verify"]["schema"] == "oo-folder-verify-1"


def test_verify_endpoint_starts_the_job_and_rejects_a_bad_path(tmp_path):
    """POST /api/backup/folder/verify starts a verify job (400 on a non-dir path). Minimal
    app (just the backup router) so the test never needs the full app wiring."""
    import src.backup.folder_backup as fb
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.backup_v2 import router as backup_router

    fb._FOLDER_MANAGER = None  # fresh singleton
    app = FastAPI()
    app.include_router(backup_router)
    client = TestClient(app)

    missing = tmp_path / "does-not-exist"
    assert client.post("/api/backup/folder/verify", json={"src": str(missing)}).status_code == 400

    src, dest = tmp_path / "src", tmp_path / "dest"
    write_folder_backup(dest, _items(src))
    r = client.post("/api/backup/folder/verify", json={"src": str(dest)})
    assert r.status_code == 200
    assert r.json()["mode"] == "verify"
    fb.get_folder_manager()._thread.join(timeout=10)  # type: ignore[union-attr]
    assert fb.get_folder_manager().status()["verify"]["ok"] is True
