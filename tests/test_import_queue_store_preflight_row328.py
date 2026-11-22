"""Row 328: the import queue refuses a store no restore may enter when the run starts, not item by item inside it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A corpus that a country-code migration left half done (R788) and a writer the restore may not stop (R659, an export:
R712) refuse every restore. Asked only inside the run, each item paused collection first and a refusal in a checkpoint
group discarded the merges it held. The queue now asks both at its start, in ``run_restore``'s order (half-migrated
first), with the same helpers and their fixed words. Pinned here: both refusals start nothing, the order, a job the
restore may stop is never stopped by the start, and a start with nothing to restore asks neither.
"""

from __future__ import annotations

import pytest

import src.backup.merge as MG
from src.backup.import_queue import ImportQueueManager


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    # The other pre-flights read the backup itself; this file pins the store's own.
    monkeypatch.setattr(ImportQueueManager, "_refuse_unreadable_backup_manifests", staticmethod(lambda items: None))
    monkeypatch.setattr(ImportQueueManager, "_refuse_wrong_backup_passphrases", staticmethod(lambda items, p: None))
    monkeypatch.setattr(ImportQueueManager, "_already_merged", staticmethod(lambda p: False))
    return ImportQueueManager(state_path=tmp_path / "q.json")


def _half_migrated():
    raise MG.HalfMigratedStoreRefused("nothing was restored: the half-migrated words")


def test_a_half_migrated_store_refuses_the_start_in_its_own_words(mgr, monkeypatch, tmp_path):
    monkeypatch.setattr(MG, "refuse_half_migrated_store", _half_migrated)
    asked = []
    monkeypatch.setattr(MG, "writer_jobs_refusal", lambda: asked.append(1))
    with pytest.raises(ValueError, match="the half-migrated words"):
        mgr.start([{"kind": "corpus", "path": str(tmp_path / "b")}], passphrase="k")
    assert asked == [], "half-migrated is asked first, as in run_restore"
    assert mgr.status()["state"] != "running"
    assert mgr._passphrase == ""


def test_a_writer_the_restore_may_not_stop_refuses_the_start(mgr, monkeypatch, tmp_path):
    monkeypatch.setattr(MG, "refuse_half_migrated_store", lambda: None)
    monkeypatch.setattr(MG, "writer_jobs_refusal", lambda: "a background job is writing to your corpus (x)")
    with pytest.raises(ValueError, match="a background job is writing"):
        mgr.start([{"kind": "legacy", "path": str(tmp_path / "f.oobak")}])
    assert mgr.status()["state"] != "running"


def test_the_start_never_stops_a_job_the_restore_may_stop(monkeypatch):
    import src.backup.export_job as EJ
    import src.jobs.background as BG

    monkeypatch.setattr(EJ, "running_export_label", lambda: None)
    seen = []
    monkeypatch.setattr(BG, "running_writer_jobs", lambda include_stoppable=True: seen.append(include_stoppable) or [])
    monkeypatch.setattr(BG, "stop_jobs_for_restore", lambda *_a: pytest.fail("the start stopped a job"))
    assert MG.writer_jobs_refusal() is None
    assert seen == [False]


def test_a_start_with_nothing_to_restore_asks_neither(mgr, monkeypatch, tmp_path):
    monkeypatch.setattr(MG, "refuse_half_migrated_store", lambda: pytest.fail("asked"))
    monkeypatch.setattr(MG, "writer_jobs_refusal", lambda: pytest.fail("asked"))
    ImportQueueManager._refuse_a_store_no_restore_may_enter([{"kind": "blobs", "path": str(tmp_path)}])
    monkeypatch.setattr(ImportQueueManager, "_already_merged", staticmethod(lambda p: True))
    ImportQueueManager._refuse_a_store_no_restore_may_enter([{"kind": "corpus", "path": str(tmp_path)}])


def test_a_forced_backup_already_merged_still_asks(mgr, monkeypatch, tmp_path):
    monkeypatch.setattr(ImportQueueManager, "_already_merged", staticmethod(lambda p: True))
    monkeypatch.setattr(MG, "refuse_half_migrated_store", _half_migrated)
    with pytest.raises(ValueError, match="half-migrated"):
        ImportQueueManager._refuse_a_store_no_restore_may_enter([{"kind": "corpus", "path": str(tmp_path), "force": True}])


def test_the_store_is_asked_before_the_backups_are_read():
    import inspect

    src = inspect.getsource(ImportQueueManager.start)
    at = src.index("_refuse_a_store_no_restore_may_enter(")
    assert at < src.index("_refuse_unreadable_backup_manifests(") < src.index("_refuse_wrong_backup_passphrases(")


def test_refuse_while_writer_jobs_run_still_refuses_through_the_shared_words(monkeypatch):
    monkeypatch.setattr(MG, "writer_jobs_refusal", lambda: "the shared words")
    with pytest.raises(MG.WriterJobsRefused, match="the shared words"):
        MG.refuse_while_writer_jobs_run()


def test_a_start_never_stops_a_stoppable_job_end_to_end(mgr, monkeypatch, tmp_path):
    import src.backup.export_job as EJ
    import src.jobs.background as BG

    monkeypatch.setattr(MG, "refuse_half_migrated_store", lambda: None)
    monkeypatch.setattr(EJ, "running_export_label", lambda: None)
    # The re-index drain "runs" and may be stopped by a restore; the start must leave it alone.
    monkeypatch.setattr(BG, "running_writer_jobs", lambda include_stoppable=True: [("reindex", "re-index")] if include_stoppable else [])
    monkeypatch.setattr(BG, "stop_jobs_for_restore", lambda *_a: pytest.fail("the start stopped a job"))
    monkeypatch.setattr(ImportQueueManager, "_run", lambda self: None)
    out = mgr.start([{"kind": "corpus", "path": str(tmp_path / "b")}], passphrase="k")
    assert out["state"] == "running"


def test_a_mixed_start_is_refused_as_a_whole(mgr, monkeypatch, tmp_path):
    monkeypatch.setattr(MG, "refuse_half_migrated_store", _half_migrated)
    with pytest.raises(ValueError, match="half-migrated"):
        mgr.start([{"kind": "corpus", "path": str(tmp_path / "b")}, {"kind": "blobs", "path": str(tmp_path)}])
    assert mgr.status()["state"] != "running"


def test_an_export_is_named_before_a_blocking_writer(monkeypatch):
    import src.backup.export_job as EJ
    import src.jobs.background as BG

    monkeypatch.setattr(EJ, "running_export_label", lambda: "the export")
    monkeypatch.setattr(BG, "running_writer_jobs", lambda include_stoppable=True: pytest.fail("asked the writers first"))
    assert "the export" in MG.writer_jobs_refusal()


def test_a_second_start_while_a_run_is_in_flight_is_told_so_before_any_preflight(mgr, monkeypatch, tmp_path):
    import threading

    monkeypatch.setattr(MG, "refuse_half_migrated_store", _half_migrated)
    gate = threading.Event()
    mgr._state, mgr._thread = "running", threading.Thread(target=gate.wait, daemon=True)
    mgr._thread.start()
    try:
        with pytest.raises(RuntimeError, match="already running"):
            mgr.start([{"kind": "corpus", "path": str(tmp_path / "b")}])
    finally:
        gate.set()
