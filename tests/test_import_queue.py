"""A multi-backup folder is ONE import: one window, one Stop, per-item identity.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field remarks 2026-07-29 remark 2 + rulings 10/13/15/16. The sequencing used to live
in the browser, which made four things structurally impossible: a Stop (nothing on the
server owned "the run"), per-item identity (every item wrote into one bar), survival of
a page reload, and a single exclusive collection window (collection resumed between
every backup). Each of those is pinned here.
"""

from __future__ import annotations

import threading
import time

import pytest

from src.backup.import_queue import ImportQueueManager


class _FakeJob:
    """Stands in for one sub-manager (volume/folder/newsletter): the queue only ever
    drives them through start/status/cancel, so the seam is small and real."""

    def __init__(self, *, states: list[str] | None = None) -> None:
        self.started: list[tuple] = []
        self.cancelled = 0
        self._states = states or ["running", "done"]
        self._i = 0
        self.release = threading.Event()
        self.release.set()

    def start(self, *a, **kw):
        self.started.append((a, kw))
        self._i = 0
        return {}

    def status(self):
        self.release.wait(timeout=5)
        st = self._states[min(self._i, len(self._states) - 1)]
        self._i += 1
        return {"state": st, "summary": {"report": {"plan": {}}}, "progress": {"phase": st}}

    def cancel(self):
        self.cancelled += 1
        self._states = ["cancelled"]
        self.release.set()


@pytest.fixture()
def queue(tmp_path, monkeypatch):
    """A manager with an isolated state file and NO scheduler side effects."""
    calls: dict[str, int] = {"pause": 0, "resume": 0}
    import src.scheduler.runner as R

    monkeypatch.setattr(R, "pause_for_exclusive_operation", lambda *a, **k: calls.__setitem__("pause", calls["pause"] + 1) or True)
    monkeypatch.setattr(R, "resume_after_exclusive_operation", lambda *a, **k: calls.__setitem__("resume", calls["resume"] + 1))
    mgr = ImportQueueManager(state_path=tmp_path / "q.json")
    mgr._calls = calls  # type: ignore[attr-defined]
    return mgr


def _drain(mgr, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if mgr.status()["state"] != "running":
            return mgr.status()
        time.sleep(0.02)
    raise AssertionError(f"queue never finished: {mgr.status()['state']}")


# --------------------------------------------------------------------------- #
#  per-item identity (the remark itself)
# --------------------------------------------------------------------------- #
def test_every_item_keeps_its_own_identity_state_and_elapsed(queue, monkeypatch):
    """THE reported defect: six backups, one bar, no idea which one was running or
    which had finished."""
    vol = _FakeJob()
    monkeypatch.setattr(queue, "_run_corpus", lambda item: {"ok": item["label"]})
    queue.start([
        {"kind": "corpus", "path": "/b/one", "label": "one"},
        {"kind": "corpus", "path": "/b/two", "label": "two"},
    ])
    st = _drain(queue)
    assert st["state"] == "done"
    assert [i["label"] for i in st["items"]] == ["one", "two"]
    assert [i["state"] for i in st["items"]] == ["done", "done"]
    assert all(i["elapsed_s"] is not None for i in st["items"]), "per-item real timings"
    assert st["items_done"] == 2 and st["items_total"] == 2
    assert vol.started == [], "the stub replaced the real manager"


def test_the_run_reports_no_fabricated_overall_eta(queue, monkeypatch):
    """The items are different kinds of work over different units, so extrapolating a
    whole-run ETA from one of them would be an invented number."""
    monkeypatch.setattr(queue, "_run_corpus", lambda item: {})
    queue.start([{"kind": "corpus", "path": "/b/one"}])
    st = _drain(queue)
    blob = repr(st).lower()
    assert "eta" not in blob and "remaining_s" not in blob


# --------------------------------------------------------------------------- #
#  ONE exclusive window across the WHOLE run (ruling item 10)
# --------------------------------------------------------------------------- #
def test_collection_is_paused_once_for_the_whole_run_not_per_item(queue, monkeypatch):
    """The defect ruling item 10 names: a 6-backup run paused and RESUMED five times
    mid-import, re-opening the very race the pause exists to close."""
    monkeypatch.setattr(queue, "_run_corpus", lambda item: {})
    queue.start([{"kind": "corpus", "path": f"/b/{i}"} for i in range(4)])
    _drain(queue)
    assert queue._calls["pause"] == 1, "one window, not one per backup"
    assert queue._calls["resume"] == 1


def test_the_status_states_that_collection_is_paused(queue, monkeypatch):
    """Ruling item 12: the UI states that collection is paused for the import — it
    must not be something the user has to infer."""
    monkeypatch.setattr(queue, "_run_corpus", lambda item: {})
    queue.start([{"kind": "corpus", "path": "/b/one"}])
    st = _drain(queue)
    assert "paused" in st["collection_note"].lower()


# --------------------------------------------------------------------------- #
#  Stop (ruling item 15)
# --------------------------------------------------------------------------- #
def test_stop_cancels_the_running_item_and_every_queued_one(queue, monkeypatch):
    """A queued item left as "queued" after a stop would read as work still pending."""
    gate = threading.Event()

    def _slow(item):
        gate.wait(timeout=5)
        return {}

    monkeypatch.setattr(queue, "_run_corpus", _slow)
    queue.start([{"kind": "corpus", "path": f"/b/{i}"} for i in range(3)])
    for _ in range(200):
        if queue.status()["cursor"] == 0:
            break
        time.sleep(0.01)
    queue.stop()
    gate.set()
    st = _drain(queue)
    assert st["state"] == "stopped"
    assert [i["state"] for i in st["items"][1:]] == ["cancelled", "cancelled"]


def test_stop_reaches_the_sub_job_through_its_own_cancel(queue, monkeypatch):
    """The queue must not merely stop LOOPING — the item in flight has to be told."""
    seen = {"n": 0}
    monkeypatch.setattr(queue, "_cancel_volume", lambda: seen.__setitem__("n", seen["n"] + 1))
    monkeypatch.setattr(queue, "_cancel_folder", lambda: None)
    monkeypatch.setattr(queue, "_cancel_newsletters", lambda: None)
    queue.stop()
    assert seen["n"] == 1


def test_one_manager_refusing_to_cancel_never_blocks_the_others(queue, monkeypatch):
    seen = {"folder": 0, "news": 0}

    def _boom():
        raise RuntimeError("nope")

    monkeypatch.setattr(queue, "_cancel_volume", _boom)
    monkeypatch.setattr(queue, "_cancel_folder", lambda: seen.__setitem__("folder", 1))
    monkeypatch.setattr(queue, "_cancel_newsletters", lambda: seen.__setitem__("news", 1))
    queue.stop()
    assert seen == {"folder": 1, "news": 1}


# --------------------------------------------------------------------------- #
#  one bad item never loses the rest
# --------------------------------------------------------------------------- #
def test_a_failing_item_is_recorded_and_the_run_continues(queue, monkeypatch):
    def _run(item):
        if item["label"] == "bad":
            raise RuntimeError("that archive is corrupt")
        return {}

    monkeypatch.setattr(queue, "_run_corpus", _run)
    queue.start([
        {"kind": "corpus", "path": "/b/1", "label": "bad"},
        {"kind": "corpus", "path": "/b/2", "label": "good"},
    ])
    st = _drain(queue)
    assert st["items"][0]["state"] == "error"
    assert "corrupt" in st["items"][0]["error"]
    assert st["items"][1]["state"] == "done", "a bad archive must not lose the rest"
    assert st["state"] == "error", "and the run says so"


# --------------------------------------------------------------------------- #
#  persistence (ruling item 16) + the passphrase
# --------------------------------------------------------------------------- #
def test_the_run_survives_a_page_reload(queue, monkeypatch, tmp_path):
    """A reload used to decapitate the sequencing. The state now lives on the server,
    so a fresh reader sees the same run."""
    monkeypatch.setattr(queue, "_run_corpus", lambda item: {})
    queue.start([{"kind": "corpus", "path": "/b/1", "label": "one"}])
    _drain(queue)
    fresh = ImportQueueManager(state_path=tmp_path / "q.json")
    st = fresh.status()
    assert st["state"] == "done"
    assert [i["label"] for i in st["items"]] == ["one"]


def test_the_passphrase_is_never_written_to_disk(queue, monkeypatch, tmp_path):
    """A queue file sits on the same disk as the encrypted corpus. Writing the key
    beside the lock would defeat at-rest encryption entirely."""
    monkeypatch.setattr(queue, "_run_corpus", lambda item: {})
    queue.start([{"kind": "corpus", "path": "/b/1"}], passphrase="correct horse battery")
    _drain(queue)
    assert "correct horse battery" not in (tmp_path / "q.json").read_text(encoding="utf-8")


def test_a_run_killed_with_the_process_reads_as_interrupted_not_running(tmp_path):
    """Reporting it as still "running" would be a bar that never moves again — and
    it genuinely cannot be resumed, because the passphrase was never stored."""
    (tmp_path / "q.json").write_text(
        '{"state": "running", "cursor": 0, "items": ['
        '{"id": "0-corpus", "kind": "corpus", "path": "/b/1", "label": "one", '
        '"state": "running", "started_at": 1.0, "ended_at": null, "error": null, '
        '"summary": null}]}',
        encoding="utf-8",
    )
    mgr = ImportQueueManager(state_path=tmp_path / "q.json")
    st = mgr.status()
    assert st["state"] == "interrupted"
    assert st["items"][0]["state"] == "interrupted"


def test_a_corrupt_state_file_is_simply_no_previous_run(tmp_path):
    (tmp_path / "q.json").write_text("{not json", encoding="utf-8")
    assert ImportQueueManager(state_path=tmp_path / "q.json").status()["state"] == "idle"


# --------------------------------------------------------------------------- #
#  refusals
# --------------------------------------------------------------------------- #
def test_two_runs_at_once_are_refused(queue, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(queue, "_run_corpus", lambda item: gate.wait(timeout=5))
    queue.start([{"kind": "corpus", "path": "/b/1"}])
    with pytest.raises(RuntimeError):
        queue.start([{"kind": "corpus", "path": "/b/2"}])
    gate.set()
    _drain(queue)


def test_an_unknown_kind_is_refused_before_anything_starts(queue):
    with pytest.raises(ValueError):
        queue.start([{"kind": "not-a-kind", "path": "/b/1"}])
    assert queue.status()["state"] == "idle"


def test_clear_refuses_while_a_run_is_in_flight(queue, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(queue, "_run_corpus", lambda item: gate.wait(timeout=5))
    queue.start([{"kind": "corpus", "path": "/b/1"}])
    with pytest.raises(RuntimeError):
        queue.clear()
    gate.set()
    _drain(queue)


# --------------------------------------------------------------------------- #
#  the sub-manager contract the sequencer depends on
# --------------------------------------------------------------------------- #
def test_every_sub_manager_is_running_before_its_worker_is_spawned():
    """Load-bearing and non-obvious: ``_await`` polls the sub-manager immediately
    after start() and treats "idle" as terminal, so a manager that spawned its thread
    FIRST and set its state afterwards would be raced straight past -- the queue would
    mark the item done and begin the next one while the first was still writing.

    Every manager currently sets ``_state = "running"`` inside its lock before
    ``Thread.start()``, which is what makes the sequencer safe. Pinned here rather than
    left as an assumption, because the failure mode is silent (two importers running
    at once) rather than an exception."""
    from pathlib import Path as _P

    root = _P(__file__).resolve().parents[1] / "src"
    for rel, fn in (
        ("backup/volume_job.py", "start_restore"),
        ("backup/folder_backup.py", "start"),
        ("ingest/import_job.py", "start"),
    ):
        src = (root / rel).read_text(encoding="utf-8")
        body = src.split(f"def {fn}(", 1)[1].split("\n    def ", 1)[0]
        run_at = body.index('self._state')
        spawn_at = body.index("self._thread.start()")
        assert run_at < spawn_at, (
            f"{rel}:{fn} spawns its worker before publishing its state — the import "
            "queue would race past it"
        )
