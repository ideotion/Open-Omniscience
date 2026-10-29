"""A start that cannot make its worker thread leaves no phantom job and no manager that refuses every later start.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why it exists. ``threading.Thread.start()`` raises ``RuntimeError("can't start new thread")`` when the process or the machine is out of
threads. Five managers set their job to "running" (the import queue and the search re-index also SAVE it) and then called ``start()``
with nothing around it, so the failure left a job that is running and has no worker: the Task Manager listed it as running, with a Pause
and a Cancel that act on nothing. The volume-backup manager and the import queue were worse: the next start joins the previous thread
before it reuses the manager, and joining a thread that was never started raises ``RuntimeError("cannot join thread before it is
started")``, so EVERY later export, import, verify or queued import was refused for the life of the process (measured 2026-10-28 and
2026-10-29; ``wal-lane/measure-start-failure-g-sites-2026-10-29.md``).

What it pins, per manager: the start that fails raises what ``start()`` raised (the API turns a ``RuntimeError`` into a 409 with its
text), the job is not "running" afterwards, what was saved says so, and the next start is accepted and runs. The volume manager and the
folder backup say "error" and name the exception's CLASS (no text: a start's arguments carry a passphrase); the import queue puts back
the run it had before (a half-built queue of items that never began would be read as "skipped", and ``items_committed`` counts
"skipped"); the search re-index says "error" with the same code its worker uses, which ``resume`` and ``start`` both accept.

Only an ``Exception`` is caught (R393): an interrupt that lands while ``start()`` waits for the new thread leaves the OS thread created
and about to run the worker, and calling that job "error" would let a second start run a second worker beside it.

The failure is injected in the module under test (its ``threading`` is replaced by one whose ``Thread`` refuses to start), never on the
process-wide ``threading.Thread``, so a thread another test or the runner starts is not touched.
"""

from __future__ import annotations

import json
import threading

import pytest

from src.backup import folder_backup, import_queue, volume_job
from src.database import fts_reindex
from tests.wallclock_helpers import wait_until

_CANNOT_START = "can't start new thread"
_SECRET = "correct-horse-battery-staple"
#: What a job that could not start says about itself: the exception's class and nothing it said.
_ERROR = "RuntimeError: could not start the worker thread"


class _Threading:
    """What a module sees as ``threading``: the real one, except that the first ``fail_first`` threads it makes refuse to start."""

    def __init__(self, fail_first: int = 1, error: BaseException | None = None) -> None:
        self.refusals_left = fail_first
        self.error = error
        outer = self

        class Thread(threading.Thread):
            def start(self) -> None:
                if outer.refusals_left > 0:
                    outer.refusals_left -= 1
                    raise outer.error or RuntimeError(_CANNOT_START)
                super().start()

        self.Thread = Thread

    def __getattr__(self, name: str):
        return getattr(threading, name)


def _cannot_start(monkeypatch, module, fail_first: int = 1, error: BaseException | None = None) -> _Threading:
    shim = _Threading(fail_first, error)
    monkeypatch.setattr(module, "threading", shim)
    return shim


# --------------------------------------------------------------------------- #
#  the volume-backup manager: export, import, verify
# --------------------------------------------------------------------------- #
def _start_volume(mgr, kind: str, folder) -> dict:
    folder.mkdir(exist_ok=True)
    if kind == "export":
        return mgr.start_backup(str(folder), _SECRET, _backup_fn=lambda *a, **k: {"volumes": 1})
    if kind == "import":
        return mgr.start_restore(str(folder), _SECRET, _restore_fn=lambda *a, **k: {"ok": True})
    return mgr.start_verify(str(folder), _SECRET, _verify_fn=lambda *a, **k: {"ok": True})


@pytest.mark.parametrize("kind", ["export", "import", "verify"])
def test_volume_manager_start_that_cannot_make_a_thread_is_an_error_not_a_wedge(monkeypatch, tmp_path, kind):
    mgr = volume_job.VolumeBackupManager()
    _cannot_start(monkeypatch, volume_job)
    with pytest.raises(RuntimeError, match=_CANNOT_START):
        _start_volume(mgr, kind, tmp_path / "set")
    st = mgr.status()
    assert st["state"] == "error"
    assert st["running"] is False
    assert st["error"] == _ERROR
    assert _SECRET not in json.dumps(st, default=str)
    # the next start is accepted and runs to its end: before, it joined a thread that was never started and raised
    _start_volume(mgr, kind, tmp_path / "set")
    assert wait_until(lambda: mgr.status()["state"] == "done"), mgr.status()
    assert mgr.status()["error"] is None


def test_volume_manager_a_refused_start_after_a_failed_one_is_still_an_ordinary_refusal(monkeypatch, tmp_path):
    """The failed start must not make the NEXT start's guard lie: a worker that is really running still refuses a second job."""
    mgr = volume_job.VolumeBackupManager()
    _cannot_start(monkeypatch, volume_job)
    with pytest.raises(RuntimeError, match=_CANNOT_START):
        _start_volume(mgr, "verify", tmp_path / "set")
    release = threading.Event()
    (tmp_path / "set").mkdir(exist_ok=True)
    mgr.start_verify(str(tmp_path / "set"), None, _verify_fn=lambda *a, **k: release.wait(20) and {"ok": True})
    try:
        with pytest.raises(RuntimeError, match="already running"):
            mgr.start_verify(str(tmp_path / "set"), None, _verify_fn=lambda *a, **k: {"ok": True})
    finally:
        release.set()
        wait_until(lambda: not mgr.status()["running"])


# --------------------------------------------------------------------------- #
#  the import queue
# --------------------------------------------------------------------------- #
@pytest.fixture()
def queue(tmp_path, monkeypatch):
    """A manager with an isolated state file and no scheduler side effects."""
    import src.scheduler.runner as R

    monkeypatch.setattr(R, "pause_for_exclusive_operation", lambda *a, **k: True)
    monkeypatch.setattr(R, "resume_after_exclusive_operation", lambda *a, **k: None)
    mgr = import_queue.ImportQueueManager(state_path=tmp_path / "q.json")
    monkeypatch.setattr(mgr, "_run_corpus", lambda item, *, hold=False: {"ok": item["label"]})
    return mgr


_ITEMS = [{"kind": "corpus", "path": "/b/one", "label": "one"}, {"kind": "corpus", "path": "/b/two", "label": "two"}]


def test_import_queue_start_that_cannot_make_a_thread_puts_back_the_run_it_had(queue, monkeypatch, tmp_path):
    queue.start(_ITEMS[:1])
    assert wait_until(lambda: queue.status()["state"] == "done")
    before = queue.status()
    run_id = queue._run_id
    assert before["state"] == "done" and run_id is not None
    _cannot_start(monkeypatch, import_queue)
    with pytest.raises(RuntimeError, match=_CANNOT_START):
        queue.start(_ITEMS, passphrase=_SECRET)
    # as if the start had not happened: the earlier run is still the one on show, nothing of the new one is
    assert queue.status() == before
    assert queue._run_id == run_id
    assert queue._passphrase == ""
    # what was saved says the same: a restart would otherwise read "running" and call a run that never began "interrupted"
    saved = json.loads((tmp_path / "q.json").read_text(encoding="utf-8"))
    assert saved["state"] == "done"
    assert [i["label"] for i in saved["items"]] == ["one"]
    assert _SECRET not in (tmp_path / "q.json").read_text(encoding="utf-8")
    # and the next start is accepted: before, it joined a thread that was never started and raised
    queue.start(_ITEMS)
    assert wait_until(lambda: queue.status()["state"] == "done" and queue.status()["items_total"] == 2), queue.status()


def test_import_queue_puts_back_the_cursor_and_the_window_flag_of_the_run_it_had(queue, monkeypatch, tmp_path):
    """The two fields a finished run leaves at the values a start sets: a run a restart read back as interrupted keeps its cursor (the item
    it was on), and a run whose exclusive window could not be established keeps the flag the dialog reads."""
    items = [
        {"id": "0-corpus", "kind": "corpus", "path": "/b/one", "label": "one", "state": "done"},
        {"id": "1-corpus", "kind": "corpus", "path": "/b/two", "label": "two", "state": "running"},
    ]
    (tmp_path / "q.json").write_text(json.dumps({"state": "running", "items": items, "cursor": 1}), encoding="utf-8")
    interrupted = import_queue.ImportQueueManager(state_path=tmp_path / "q.json")
    interrupted._collection_window_failed = True
    before = interrupted.status()
    assert before["state"] == "interrupted" and before["current"]["label"] == "two" and before["collection_window_failed"] is True
    _cannot_start(monkeypatch, import_queue)
    with pytest.raises(RuntimeError, match=_CANNOT_START):
        interrupted.start(_ITEMS)
    assert interrupted.status() == before


def test_import_queue_first_start_that_cannot_make_a_thread_leaves_nothing_to_restart_as_interrupted(queue, monkeypatch, tmp_path):
    _cannot_start(monkeypatch, import_queue)
    with pytest.raises(RuntimeError, match=_CANNOT_START):
        queue.start(_ITEMS, passphrase=_SECRET)
    st = queue.status()
    assert st["state"] == "idle"
    assert st["items"] == []
    assert queue._passphrase == ""
    # a process that starts next reads the file: before, "running" with queued items, which it called "interrupted"
    reborn = import_queue.ImportQueueManager(state_path=tmp_path / "q.json")
    assert reborn.status()["state"] == "idle"
    assert reborn.status()["items"] == []


# --------------------------------------------------------------------------- #
#  the folder backup
# --------------------------------------------------------------------------- #
def test_folder_backup_start_that_cannot_make_a_thread_is_not_a_running_job(monkeypatch, tmp_path):
    from src.api import jobs

    mgr = folder_backup.FolderBackupManager()
    monkeypatch.setattr(mgr, "_run_verify", lambda *a, **k: None)
    monkeypatch.setattr(folder_backup, "get_folder_manager", lambda: mgr)
    (tmp_path / "set").mkdir()
    _cannot_start(monkeypatch, folder_backup)
    with pytest.raises(RuntimeError, match=_CANNOT_START):
        mgr.start(str(tmp_path / "set"), [], mode="verify")
    st = mgr.status()
    assert st["state"] == "error"
    assert st["running"] is False
    assert st["error"] == _ERROR
    # the Task Manager's row: before, "running" with a Pause and a Cancel that act on nothing
    rows = jobs._folder_backup_jobs()
    assert [r["state"] for r in rows] == ["failed"]
    assert rows[0]["error"] == _ERROR
    assert "pause" not in rows[0]["actions"]
    # Resume starts it again, from the destination and mode the failed start recorded
    mgr.resume()
    assert wait_until(lambda: not mgr.status()["running"])


# --------------------------------------------------------------------------- #
#  the search re-index
# --------------------------------------------------------------------------- #
def test_search_reindex_start_that_cannot_make_a_thread_is_saved_as_an_error_that_resume_accepts(monkeypatch, tmp_path):
    state_file = tmp_path / "reindex.json"
    mgr = fts_reindex.SearchReindexJobManager(state_path=state_file, report_path=tmp_path / "report.json")
    monkeypatch.setattr(mgr, "_run", lambda: None)
    _cannot_start(monkeypatch, fts_reindex)
    with pytest.raises(RuntimeError, match=_CANNOT_START):
        mgr.start()
    st = mgr.status()
    assert st["state"] == "error"
    assert st["running"] is False
    assert st["error"] == "failed"
    # what was saved: before, "running" for a run with no worker
    assert json.loads(state_file.read_text(encoding="utf-8"))["state"] == "error"
    mgr.join(0.1)  # joining the thread that was never started raised
    mgr.resume()  # refused with "nothing paused" while the state said running
    assert wait_until(lambda: not mgr.status()["running"])


# --------------------------------------------------------------------------- #
#  an interrupt is not "the thread never ran" (R393)
# --------------------------------------------------------------------------- #
def _volume_start(tmp_path):
    mgr = volume_job.VolumeBackupManager()
    return mgr, volume_job, lambda: _start_volume(mgr, "verify", tmp_path / "set")


def _queue_start(tmp_path):
    mgr = import_queue.ImportQueueManager(state_path=tmp_path / "q.json")
    return mgr, import_queue, lambda: mgr.start(_ITEMS)


def _folder_start(tmp_path):
    mgr = folder_backup.FolderBackupManager()
    (tmp_path / "set").mkdir(exist_ok=True)
    return mgr, folder_backup, lambda: mgr.start(str(tmp_path / "set"), [], mode="verify")


def _reindex_start(tmp_path):
    mgr = fts_reindex.SearchReindexJobManager(state_path=tmp_path / "reindex.json", report_path=tmp_path / "report.json")
    return mgr, fts_reindex, lambda: mgr.start()


@pytest.mark.parametrize("make", [_volume_start, _queue_start, _folder_start, _reindex_start])
def test_an_interrupt_during_start_is_not_taken_for_a_thread_that_never_ran(monkeypatch, tmp_path, make):
    """``Thread.start()`` waits for the new thread to report in; an interrupt that lands there leaves the OS thread created and about to run
    the worker. Calling that job "error" (or putting the old run back) would let a second start run a second worker beside it, so only an
    ``Exception`` is taken and the job stays "running"."""
    mgr, module, start = make(tmp_path)
    _cannot_start(monkeypatch, module, error=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        start()
    assert mgr.status()["state"] == "running"
