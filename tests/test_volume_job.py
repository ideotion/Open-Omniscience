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


def test_restore_failure_gets_the_honest_classified_detail(tmp_path):
    """Field bug (2026-07-15): a real data-merge conflict (a UNIQUE constraint hit
    merging a large backup) used to surface as the bare str(exc) -- e.g. an
    unqualified "UNIQUE constraint failed:" -- instead of the same honest
    classification /api/backup/v2/restore's single-shot path already applies
    (_restore_error / classify_restore_error, P0-2). The job's error must go
    through the same classifier regardless of which restore surface hit it."""
    import sqlite3

    src = tmp_path / "src"
    src.mkdir()

    def fake_restore(s, pw):
        raise sqlite3.IntegrityError("UNIQUE constraint failed: law_revisions.document_id, law_revisions.content_hash")

    mgr = VolumeBackupManager()
    mgr.start_restore(str(src), "pw", _restore_fn=fake_restore)
    st = _wait(mgr)
    assert st["state"] == "error"
    # The classified, honest detail -- not the bare exception string.
    assert "data-merge issue, not a version mismatch" in st["error"]
    assert "UNIQUE constraint failed" in st["error"]  # the original detail is kept, not lost


def test_restore_merge_error_keeps_its_own_message(tmp_path):
    """A MergeError is an intentional, well-formed refusal (the live DB stays
    untouched) -- it must surface as-is, not run through the generic classifier
    (which would misdescribe a deliberate refusal as a data conflict)."""
    from src.backup.merge import MergeError

    src = tmp_path / "src"
    src.mkdir()

    def fake_restore(s, pw):
        raise MergeError("refusing: an unverified backup requires allow_unverified")

    mgr = VolumeBackupManager()
    mgr.start_restore(str(src), "pw", _restore_fn=fake_restore)
    st = _wait(mgr)
    assert st["state"] == "error"
    assert st["error"] == "refusing: an unverified backup requires allow_unverified"


def test_sequential_restores_do_not_collide(tmp_path):
    # Field report 2026-07-02: importing several archives one after another hit "A
    # volume backup/restore is already running". Each restore is awaited to "done"
    # before the next; back-to-back starts must all succeed.
    src = tmp_path / "src"
    src.mkdir()
    calls: list[str] = []

    def fake_restore(s, pw):
        calls.append(str(s))
        return {"report": {"ok": True}}

    mgr = VolumeBackupManager()
    for _ in range(3):
        mgr.start_restore(str(src), "pw", _restore_fn=fake_restore)
        assert _wait(mgr)["state"] == "done"
    assert len(calls) == 3


def test_reap_allows_next_after_a_lingering_finished_thread(tmp_path):
    # The race directly: a finished job whose thread object still lingers (state is
    # terminal) must NOT block the next start — _reap_or_reject reaps it. A genuinely
    # running job (alive + state "running") still rejects.
    import threading

    mgr = VolumeBackupManager()
    dead = threading.Thread(target=lambda: None)
    dead.start()
    dead.join()
    mgr._thread, mgr._state = dead, "done"  # simulate the teardown window
    src = tmp_path / "s"
    src.mkdir()
    mgr.start_restore(str(src), "pw", _restore_fn=lambda s, pw: {"report": {"ok": True}})
    assert _wait(mgr)["state"] == "done"
