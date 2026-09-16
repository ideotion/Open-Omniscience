"""The export-folder and export-summary endpoints (S04-03; R4, R5, Q208–Q213).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Two endpoints exist because the export has two phases and ONE folder: the folder is
allocated once, before either phase, and the summary is written once, after both. The
tests that matter here are the refusals — a summary must not be written into a folder
no export wrote to, and a route must actually be reachable at the path the frontend
calls (a wiring test that compares two strings side by side passed once while a
prefix mismatch 404'd in the field).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


def _composed_paths() -> set[str]:
    """Routes as the CLIENT sees them: the router's own prefix + each decorator path.

    Read off the router definition rather than the shared mutable app singleton, whose
    ``.routes`` a process-global read has made flaky before.
    """
    from src.api.backup_v2 import router

    return {r.path for r in router.routes}


def test_the_frontend_calls_paths_that_actually_exist():
    paths = _composed_paths()
    app_js = (Path(__file__).resolve().parents[1] / "src/static/app-backup.js").read_text(
        encoding="utf-8"
    )
    for called in ("/api/backup/export-folder", "/api/backup/export-summary"):
        assert called in app_js, f"the export dialog no longer calls {called}"
        assert called in paths, f"{called} is called but not served"


def test_allocating_returns_a_fresh_dated_folder(client, tmp_path):
    r = client.post("/api/backup/export-folder", json={"parent": str(tmp_path)})
    assert r.status_code == 200, r.text
    body = r.json()
    d = Path(body["dir"])
    assert d.is_dir() and list(d.iterdir()) == []
    assert d.parent == tmp_path and body["name"] == d.name
    assert d.name.endswith("_OpenOmniscience_Backup")

    again = client.post("/api/backup/export-folder", json={"parent": str(tmp_path)})
    assert Path(again.json()["dir"]) != d, "a second export must not be handed the first's folder"


def test_an_unusable_parent_is_a_400_not_a_500(client, tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("x", encoding="utf-8")
    r = client.post("/api/backup/export-folder", json={"parent": str(blocker / "under")})
    assert r.status_code == 400
    assert blocker.read_text(encoding="utf-8") == "x"


def test_reading_a_summary_never_writes_one(client, tmp_path):
    d = Path(client.post("/api/backup/export-folder", json={"parent": str(tmp_path)}).json()["dir"])
    r = client.get("/api/backup/export-summary", params={"dir": str(d)})
    assert r.status_code == 200
    assert not (d / "BACKUP_SUMMARY.md").exists(), "a READ wrote a file"
    # An empty folder is described honestly rather than refused: no corpus, no verdict.
    facts = r.json()
    assert facts["corpus_included"] is False
    assert facts["verify"]["state"] == "unknown"
    assert facts["tables"] == []


def test_writing_a_summary_into_a_folder_no_export_wrote_to_is_REFUSED(client, tmp_path):
    """A summary file describes the export that made a folder. Writing one into a
    folder nothing exported to would produce a document whose every fact is about
    something else — so the endpoint refuses rather than writing an honest-looking
    file full of dashes."""
    stranger = tmp_path / "somebody-elses-folder"
    stranger.mkdir()
    (stranger / "their-notes.txt").write_text("mine", encoding="utf-8")

    r = client.post("/api/backup/export-summary", json={"dir": str(stranger)})
    assert r.status_code == 400
    assert "not the destination of a backup" in r.json()["detail"]
    assert sorted(p.name for p in stranger.iterdir()) == ["their-notes.txt"]


def test_the_write_is_allowed_for_the_folder_a_backup_job_actually_used(client, tmp_path):
    """The other side of the refusal: the real path must not be blocked by its own guard."""
    from src.backup.folder_backup import get_folder_manager

    d = Path(client.post("/api/backup/export-folder", json={"parent": str(tmp_path)}).json()["dir"])
    mgr = get_folder_manager()
    before_dest, before_mode = mgr._dest, mgr._mode
    try:
        mgr._dest, mgr._mode = str(d), "backup"
        r = client.post("/api/backup/export-summary", json={"dir": str(d)})
        assert r.status_code == 200, r.text
        written = Path(r.json()["summary_path"])
        assert written.name == "BACKUP_SUMMARY.md" and written.parent == d
        assert written.read_text(encoding="utf-8").startswith("# Open Omniscience")
        assert r.json()["facts"]["destination"] == str(d)
    finally:
        mgr._dest, mgr._mode = before_dest, before_mode


def test_verify_after_write_rides_the_start_body_and_defaults_on(client):
    from src.api.backup_v2 import VolumeBackupBody

    body = VolumeBackupBody(dest="/tmp/x", passphrase="p")
    assert body.verify_after_write is True
    assert VolumeBackupBody(dest="/tmp/x", passphrase="p", verify_after_write=False).verify_after_write is False
    app_js = (Path(__file__).resolve().parents[1] / "src/static/app-backup.js").read_text(
        encoding="utf-8"
    )
    assert "verify_after_write: verifyAfterWrite" in app_js, (
        "the dialog's verify choice must reach the job"
    )
