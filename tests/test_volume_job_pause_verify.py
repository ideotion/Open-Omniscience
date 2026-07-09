"""VolumeBackupManager pause/resume + verify modes (P0.1, slice Z3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Cancel keeps its original promise (a cancelled FIRST build's partials are
cleaned, never mistakable for a good backup — pinned in test_volume_job.py).
PAUSE is the new, distinct control: it stops between volumes and KEEPS the
finished volumes + the resume log, so starting the same backup again continues
where it left off. VERIFY runs the end-to-end set verification as a job.
"""

import threading
import time
from pathlib import Path

from src.backup.stream_backup import BUILDING_NAME
from src.backup.volume_job import VolumeBackupManager
from src.backup.volumes import VolumeStopped


def _wait(mgr: VolumeBackupManager, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = mgr.status()
        if st["state"] not in ("running",) and not st["running"]:
            return st
        time.sleep(0.01)
    return mgr.status()


def test_pause_keeps_partials_and_resume_log(tmp_path):
    started = threading.Event()
    d = tmp_path / "d"

    def fake(dest, pw, *, should_stop, progress_cb, **k):
        destp = Path(dest)
        destp.mkdir(parents=True, exist_ok=True)
        (destp / "vol-abc-00000-x1.ooenc").write_bytes(b"finished volume")
        (destp / BUILDING_NAME).write_text('{"kind": "oo-volumes-2-building"}', encoding="utf-8")
        started.set()
        while not should_stop():
            time.sleep(0.01)
        raise VolumeStopped("stopped")

    mgr = VolumeBackupManager()
    mgr.start_backup(str(d), "pw", _backup_fn=fake)
    assert started.wait(2)
    mgr.pause()
    st = _wait(mgr)
    assert st["state"] == "paused"
    # the finished volume + the resume log SURVIVE a pause (unlike cancel)
    assert (d / "vol-abc-00000-x1.ooenc").exists()
    assert (d / BUILDING_NAME).exists()

    # starting again is the resume (the engine reuses the finished volumes)
    def fake_done(dest, pw, **k):
        return {"volumes": 3, "volumes_reused": 1, "resumed": True}

    mgr.start_backup(str(d), "pw", _backup_fn=fake_done)
    st = _wait(mgr)
    assert st["state"] == "done"
    assert st["summary"]["resumed"] is True


def test_pause_is_a_noop_for_a_restore(tmp_path):
    started = threading.Event()
    release = threading.Event()

    def fake_restore(src, pw):
        started.set()
        release.wait(2)
        return {"ok": True}

    mgr = VolumeBackupManager()
    (tmp_path / "s").mkdir()
    mgr.start_restore(str(tmp_path / "s"), "pw", _restore_fn=fake_restore)
    assert started.wait(2)
    mgr.pause()  # must not signal the stop event for a restore
    assert not mgr._stop.is_set()
    release.set()
    assert _wait(mgr)["state"] == "done"


def test_verify_job_reports_the_verification(tmp_path):
    (tmp_path / "v").mkdir()

    def fake_verify(src, passphrase):
        return {"ok": True, "kind": "oo-volumes-2", "bad_volumes": [], "decrypted": False}

    mgr = VolumeBackupManager()
    mgr.start_verify(str(tmp_path / "v"), None, _verify_fn=fake_verify)
    st = _wait(mgr)
    assert st["state"] == "done" and st["mode"] == "verify"
    assert st["summary"]["report"]["ok"] is True


def test_verify_failure_is_surfaced_not_swallowed(tmp_path):
    (tmp_path / "v").mkdir()

    def fake_verify(src, passphrase):
        raise RuntimeError("no volume manifest")

    mgr = VolumeBackupManager()
    mgr.start_verify(str(tmp_path / "v"), "pw", _verify_fn=fake_verify)
    st = _wait(mgr)
    assert st["state"] == "error"
    assert "no volume manifest" in st["error"]


def test_verify_and_pause_endpoints_are_wired(tmp_path):
    """The API routes COMPOSE to the paths the engine expects (the slice-1c 404
    lesson: assert the full route, never the two halves side by side)."""
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as client:
        # verify: a non-folder src is a 400 (the manager's loud refusal)
        res = client.post(
            "/api/backup/v2/volumes/verify",
            json={"src": str(tmp_path / "does-not-exist")},
        )
        assert res.status_code == 400
        # a real (empty) folder starts the job; the missing manifest surfaces as
        # a job ERROR in status — never a silent success
        vdir = tmp_path / "v"
        vdir.mkdir()
        res = client.post("/api/backup/v2/volumes/verify", json={"src": str(vdir)})
        assert res.status_code == 200
        deadline = time.time() + 5
        st = res.json()
        while time.time() < deadline and st["state"] == "running":
            time.sleep(0.05)
            st = client.get("/api/backup/v2/volumes/status").json()
        assert st["state"] == "error" and "manifest" in (st["error"] or "")

        # pause: always answers with the job status (no-op when idle)
        res = client.post("/api/backup/v2/volumes/pause")
        assert res.status_code == 200 and "state" in res.json()

        # the restore body accepts corpus_passphrase (422 would mean a schema gap)
        res = client.post(
            "/api/backup/v2/volumes/restore",
            json={
                "src": str(tmp_path / "nope"),
                "passphrase": "x",
                "corpus_passphrase": "y",
            },
        )
        assert res.status_code == 400  # not-a-folder, past schema validation
