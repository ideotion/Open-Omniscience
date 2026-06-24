"""Volume backup/restore job manager (src/backup/volume_job.py), slice 1c.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Drives the manager's threading + state machine through an injected backup/restore fn
(no live corpus), pinning: a backup runs to ``done`` (and the secret envelope is stripped
from the summary), a cancel stops it and CLEANS the partial volume set, an error is
surfaced not crashed, only one job runs at a time, an empty passphrase is refused, and a
restore runs to ``done``.
"""

import threading
import time
from pathlib import Path

import pytest

from src.backup.volume_job import VolumeBackupManager
from src.backup.volumes import VolumeStopped


def _wait(mgr: VolumeBackupManager, timeout: float = 5.0) -> dict:
    t0 = time.time()
    while mgr.status()["running"] and time.time() - t0 < timeout:
        time.sleep(0.01)
    return mgr.status()


def test_backup_runs_to_done_and_strips_envelope(tmp_path):
    def fake(dest, pw, *, include_newsletters, parity_fraction, should_stop, progress_cb):
        progress_cb({"phase": "volumes", "volumes_written": 2})
        return {"volumes": 2, "parity_available": True, "dest": str(dest), "envelope": {"k": 1}}

    mgr = VolumeBackupManager()
    mgr.start_backup(str(tmp_path / "d"), "pw", _backup_fn=fake)
    st = _wait(mgr)
    assert st["state"] == "done"
    assert st["summary"]["volumes"] == 2
    assert "envelope" not in st["summary"]  # the signing-key envelope is never leaked to status


def test_cancel_stops_and_cleans_the_partial_set(tmp_path):
    started = threading.Event()
    d = tmp_path / "d"

    def fake(dest, pw, *, should_stop, progress_cb, **k):
        Path(dest).mkdir(parents=True, exist_ok=True)
        (Path(dest) / "vol-00001.ooenc").write_bytes(b"partial")
        (Path(dest) / "volumes.json").write_text("{}", encoding="utf-8")
        started.set()
        while not should_stop():
            time.sleep(0.01)
        raise VolumeStopped("stopped")

    mgr = VolumeBackupManager()
    mgr.start_backup(str(d), "pw", _backup_fn=fake)
    assert started.wait(2)
    mgr.cancel()
    st = _wait(mgr)
    assert st["state"] == "cancelled"
    assert not (d / "vol-00001.ooenc").exists() and not (d / "volumes.json").exists()


def test_error_is_surfaced(tmp_path):
    def fake(dest, pw, **k):
        raise RuntimeError("boom")

    mgr = VolumeBackupManager()
    mgr.start_backup(str(tmp_path / "d"), "pw", _backup_fn=fake)
    st = _wait(mgr)
    assert st["state"] == "error" and "boom" in (st["error"] or "")


def test_only_one_job_at_a_time(tmp_path):
    release, started = threading.Event(), threading.Event()

    def fake(dest, pw, *, should_stop, progress_cb, **k):
        started.set()
        release.wait(3)
        return {"volumes": 1, "dest": str(dest), "envelope": {}}

    mgr = VolumeBackupManager()
    mgr.start_backup(str(tmp_path / "d"), "pw", _backup_fn=fake)
    assert started.wait(2)
    with pytest.raises(RuntimeError):
        mgr.start_backup(str(tmp_path / "e"), "pw", _backup_fn=fake)
    release.set()
    _wait(mgr)


def test_empty_passphrase_refused(tmp_path):
    mgr = VolumeBackupManager()
    with pytest.raises(ValueError):
        mgr.start_backup(str(tmp_path / "d"), "")


def test_restore_runs_to_done(tmp_path):
    src = tmp_path / "src"
    src.mkdir()

    def fake_restore(s, pw):
        return {"report": {"ok": True}}

    mgr = VolumeBackupManager()
    mgr.start_restore(str(src), "pw", _restore_fn=fake_restore)
    st = _wait(mgr)
    assert st["state"] == "done" and st["summary"]["report"]["ok"] is True
