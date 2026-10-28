"""A restore confirms the collector has left the corpus before it copies it (R360 item 1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``exclusive_window`` stops the collector by signalling its loop and joining it for a BOUNDED time, so a pass
deep in a write outlives the join (``runner.resume_after_exclusive_operation`` records one that took 39
minutes), and a pass started by "Run now" before the window opened is not touched at all. The restore read the
window's return as "collection is paused" and copied the corpus; whatever that pass committed to the live file
after the copy was discarded by the swap. These tests drive the REAL ``run_restore`` up to its working-copy
snapshot (the pattern of ``test_restore_settings_before_snapshot``) against a REAL ``BackgroundScheduler``
whose pass blocks, and read what the scheduler looks like AT the snapshot.
"""

from __future__ import annotations

import ast
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.backup.collector_exit as collector_exit
import src.scheduler.runner as runner_mod
from src.scheduler.runner import BackgroundScheduler
from tests.wallclock_helpers import HANG_GUARD_S, SteppedClock, quiet_pass_tail, wait_until

_MERGE_PY = Path(__file__).resolve().parents[1] / "src" / "backup" / "merge.py"


class _FakeSettings:
    def __init__(self):
        self.continuous = True
        self.interval_minutes = 1
        self.mode = "rss"

    def to_dict(self) -> dict:
        return {"continuous": True, "interval_minutes": 1, "mode": "rss"}


class _Stop(Exception):
    """Raised by the stand-in snapshot so nothing after it runs."""


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    quiet_pass_tail(monkeypatch)
    monkeypatch.setattr(runner_mod, "_ensure_storage_supervisor", lambda: None)
    # The window's exit would otherwise restart the loop a finished test has stopped: the kill switch is the
    # documented "stand down" answer of the resume (_start_or_stand_down), and it starts nothing.
    import src.ingest as ingest

    monkeypatch.setattr(ingest, "kill_switch_active", lambda: True)
    # The wait looks every 10 ms here; the bound stays the shipped 600 s, which no passing run comes near.
    monkeypatch.setattr(collector_exit, "COLLECTOR_EXIT_POLL_S", 0.01)
    runner_mod.cancel_pending_resume()
    yield
    runner_mod.cancel_pending_resume()


class _BlockedPass:
    """A scheduler whose pass blocks until ``release`` is set; ``entered`` is set once it is inside the pass."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.entered = threading.Event()
        self.sched = BackgroundScheduler(run_once_fn=self._pass, settings_provider=lambda: _FakeSettings())
        self.sched._continuous_gap_s = 0.05
        self.sched._maint_interval_s = 1e9  # off-peak maintenance is seconds of real work: not what these tests are about
        self.sched._last_maint = time.monotonic()

    def _pass(self) -> dict:
        self.entered.set()
        self.release.wait(HANG_GUARD_S)
        return {"stored": 0}

    def close(self) -> None:
        self.release.set()
        self.sched.stop(timeout=HANG_GUARD_S)
        assert wait_until(lambda: not self.sched._active), "the pass did not end after being released"


@pytest.fixture()
def blocked(monkeypatch):
    b = _BlockedPass()
    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: b.sched)
    try:
        yield b
    finally:
        b.close()


def _staged(tmp_path):
    return SimpleNamespace(
        kind="oo-backup-3", staging_dir=tmp_path / "stage", stage_a_timings={},
        manifest=None, origin_fingerprint="x", corpus_path=tmp_path / "in.db",
    )


def _drive_to_snapshot(monkeypatch, tmp_path, on_snapshot, **kwargs):
    """Run the real ``run_restore`` until its working-copy snapshot, call ``on_snapshot`` there, and stop."""
    import src.backup.merge as merge
    import src.backup.sqlite_backup as sqlite_backup
    import src.database.connect as connect

    def fake_snapshot(*_a, **_k):
        on_snapshot()
        raise _Stop

    monkeypatch.setattr(merge, "resolve_trust_fetch_history", lambda override: bool(override))
    monkeypatch.setattr(merge, "prepare_staged_corpus", lambda *a, **k: "head")
    monkeypatch.setattr(connect, "snapshot_preserving", fake_snapshot)
    monkeypatch.setattr(sqlite_backup, "live_db_path", lambda: tmp_path / "live.db")
    with pytest.raises(_Stop):
        merge.run_restore(_staged(tmp_path), **kwargs)


# --------------------------------------------------------------------------- #
#  the defect: the copy was taken while the collector was still on the corpus
# --------------------------------------------------------------------------- #
def test_a_loop_the_bounded_stop_left_running_is_gone_before_the_copy_is_taken(monkeypatch, tmp_path, blocked):
    assert blocked.sched.start() is True
    assert blocked.entered.wait(HANG_GUARD_S)
    seen: dict = {}
    timer = threading.Timer(0.3, blocked.release.set)
    with runner_mod.exclusive_window(timeout=0.05, resume_retries=0) as was_paused:
        try:
            # Premise, the reason this test exists: the window has returned and the stop was signalled, and the
            # pass is still inside the live corpus. "Collection is paused" is not yet true.
            assert was_paused is True
            assert blocked.sched.is_running() is True
            timer.start()
            _drive_to_snapshot(
                monkeypatch, tmp_path,
                lambda: seen.update(loop_alive=blocked.sched.is_running(), pass_active=blocked.sched._active),
                commit=True,
            )
        finally:
            timer.cancel()
    assert seen == {"loop_alive": False, "pass_active": False}, (
        "the working copy was taken while a collection pass was still writing to the live corpus"
    )


def test_a_pass_run_now_started_before_the_window_is_waited_out_too(monkeypatch, tmp_path, blocked):
    """The loop is NOT running here (it was never started), so the loop's thread alone calls the collector idle."""
    assert blocked.sched.run_now() is True
    assert blocked.entered.wait(HANG_GUARD_S)
    assert blocked.sched.is_running() is False and blocked.sched._active is True  # premise
    blocked.sched.hold_exclusive()
    seen: dict = {}
    timer = threading.Timer(0.3, blocked.release.set)
    timer.start()
    try:
        _drive_to_snapshot(
            monkeypatch, tmp_path, lambda: seen.update(pass_active=blocked.sched._active), commit=True, exclusive=True
        )
    finally:
        timer.cancel()
        blocked.sched.release_exclusive()
    assert seen == {"pass_active": False}


# --------------------------------------------------------------------------- #
#  the bound, and what the restore says when it is reached
# --------------------------------------------------------------------------- #
class _Lingering:
    """A scheduler that never leaves: the loop thread reads alive for ever."""

    _state_lock = threading.Lock()
    _active = False

    def is_running(self) -> bool:
        return True


def test_the_wait_is_bounded_and_the_answer_names_what_was_still_running(monkeypatch):
    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: _Lingering())
    clock = SteppedClock()
    monkeypatch.setattr(collector_exit, "time", clock)
    got = collector_exit.wait_for_collector_exit()
    assert got["confirmed"] is False
    assert got["still"] == ["the collection loop"]
    assert got["bound_s"] == collector_exit.COLLECTOR_EXIT_WAIT_S == 600.0
    assert got["waited_s"] == 600.0, "the wait spent its whole bound and not a second more"
    assert sum(clock.slept) == pytest.approx(600.0)


def test_a_scheduler_that_cannot_be_read_is_not_reported_idle(monkeypatch):
    def boom():
        raise RuntimeError("no scheduler at /secret/place")

    monkeypatch.setattr(runner_mod, "get_scheduler", boom)
    got = collector_exit.wait_for_collector_exit()
    assert got["confirmed"] is None, "an unreadable scheduler is an unknown, never a confirmation"
    assert "RuntimeError" in got["reason"], "the reason names the class of the failure"
    assert "secret" not in got["reason"], "and never the words of the exception, which can carry a path"
    assert got["waited_s"] == 0.0


def test_nothing_running_is_confirmed_at_once(monkeypatch):
    idle = BackgroundScheduler(run_once_fn=lambda: {"stored": 0}, settings_provider=lambda: _FakeSettings())
    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: idle)
    got = collector_exit.wait_for_collector_exit()
    assert got == {"confirmed": True, "waited_s": 0.0, "bound_s": 600.0, "still": []}


def test_a_stop_ends_the_wait_and_the_restore_aborts_before_the_copy(monkeypatch, tmp_path):
    import src.backup.merge as merge

    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: _Lingering())
    clock = SteppedClock()
    monkeypatch.setattr(collector_exit, "time", clock)
    looks = {"n": 0}

    def stop_after_three_looks() -> bool:
        looks["n"] += 1
        return looks["n"] > 3

    snapshots: list[int] = []
    with pytest.raises(merge.RestoreAborted):
        _drive_to_snapshot(
            monkeypatch, tmp_path, lambda: snapshots.append(1),
            commit=True, exclusive=True, should_stop=stop_after_three_looks,
        )
    assert snapshots == [], "a Stop pressed during the wait must not be followed by the copy"
    assert sum(clock.slept) < 1.0, "the Stop was answered at the next look, not after the bound"


def test_a_restore_that_goes_on_past_the_bound_records_that_the_collector_was_still_there(monkeypatch, tmp_path):
    import src.backup.runlog as runlog

    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: _Lingering())
    monkeypatch.setattr(collector_exit, "time", SteppedClock())
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(runlog, "milestone", lambda ev, **kw: events.append((ev, kw)))
    reached: list[int] = []
    _drive_to_snapshot(monkeypatch, tmp_path, lambda: reached.append(1), commit=True, exclusive=True)
    assert reached == [1], "the pause is a courtesy: the restore goes on past the bound"
    (kw,) = [kw for ev, kw in events if ev == "collector_exit"]
    assert kw["confirmed"] is False and kw["still"] == ["the collection loop"] and kw["waited_s"] == 600.0


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"commit": True}, id="not-the-owner-of-the-machine"),
        pytest.param({"commit": False, "exclusive": True}, id="a-preview-swaps-nothing"),
    ],
)
def test_no_wait_where_the_copy_cannot_be_lost(monkeypatch, tmp_path, kwargs):
    """A restore that does not own the machine claimed nothing, and a preview never swaps: neither waits."""
    import src.backup.merge as merge

    def must_not_wait(**_k):
        raise AssertionError("the restore waited for the collector where it had no reason to")

    monkeypatch.setattr(collector_exit, "wait_for_collector_exit", must_not_wait)
    monkeypatch.setattr(merge, "resolve_trust_fetch_history", lambda override: bool(override))
    monkeypatch.setattr(merge, "prepare_staged_corpus", lambda *a, **k: "head")
    import src.backup.sqlite_backup as sqlite_backup
    import src.database.connect as connect

    monkeypatch.setattr(sqlite_backup, "live_db_path", lambda: tmp_path / "live.db")
    monkeypatch.setattr(connect, "snapshot_preserving", lambda *a, **k: (_ for _ in ()).throw(_Stop()))
    with pytest.raises(_Stop):
        merge.run_restore(_staged(tmp_path), **kwargs)


def test_a_carried_working_copy_takes_no_snapshot_and_waits_for_nothing(monkeypatch, tmp_path):
    """From the second item of a checkpoint group the copy exists already: there is no copy to protect."""
    import src.backup.merge as merge

    def must_not_wait(**_k):
        raise AssertionError("waited for a copy that is not being taken")

    monkeypatch.setattr(collector_exit, "wait_for_collector_exit", must_not_wait)
    carried = tmp_path / "working.db"
    carried.write_bytes(b"")
    monkeypatch.setattr(merge, "resolve_trust_fetch_history", lambda override: bool(override))
    monkeypatch.setattr(merge, "prepare_staged_corpus", lambda *a, **k: "head")
    import src.backup.sqlite_backup as sqlite_backup

    monkeypatch.setattr(sqlite_backup, "live_db_path", lambda: tmp_path / "live.db")

    class _Reached(Exception):
        pass

    def stop_at_merge(*_a, **_k):
        raise _Reached

    monkeypatch.setattr(merge, "merge_corpus", stop_at_merge)
    with pytest.raises(_Reached):
        merge.run_restore(_staged(tmp_path), commit=True, exclusive=True, working_copy=carried)


# --------------------------------------------------------------------------- #
#  the report carries it
# --------------------------------------------------------------------------- #
def test_the_report_carries_the_answer_next_to_the_other_run_facts():
    tree = ast.parse(_MERGE_PY.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_restore")
    created = [
        n.lineno for n in ast.walk(node)
        if isinstance(n, ast.AnnAssign) and getattr(n.target, "id", None) == "report"
    ]
    stored = [
        n.lineno for n in ast.walk(node)
        if isinstance(n, ast.Assign)
        and any(
            isinstance(t, ast.Subscript) and getattr(t.value, "id", None) == "report"
            and getattr(t.slice, "value", None) == "collector_exit"
            for t in n.targets
        )
    ]
    assert created and stored, "anti-vacuity: the report's creation and the collector_exit store were not found"
    assert min(stored) > min(created), "the answer is stored on the report, after the report exists"


# --------------------------------------------------------------------------- #
#  the import dialog stops saying collection is paused where a restore found otherwise
# --------------------------------------------------------------------------- #
def _queue(tmp_path, summaries):
    from src.backup.import_queue import ImportQueueManager

    q = ImportQueueManager(state_path=tmp_path / "queue.json")
    q._items = [
        {"id": f"{i}-corpus", "kind": "corpus", "path": f"/a/{i}", "label": f"b{i}", "state": "done",
         "started_at": 1.0, "ended_at": 2.0, "error": None, "summary": s, "force": False}
        for i, s in enumerate(summaries)
    ]
    return q


def _volume(exit_):
    """The shape the corpus path hands back: run_restore's report wrapped with the group bookkeeping."""
    return {"held": False, "report": {"committed": True, **({"collector_exit": exit_} if exit_ is not None else {})}}


_OK = {"confirmed": True, "waited_s": 0.0, "bound_s": 600.0, "still": []}
_STILL = {"confirmed": False, "waited_s": 600.0, "bound_s": 600.0, "still": ["a collection pass"]}
_UNREAD = {"confirmed": None, "waited_s": 0.0, "bound_s": 600.0, "still": [], "reason": "RuntimeError: x"}


@pytest.mark.parametrize(
    ("summaries", "unconfirmed"),
    [
        pytest.param([_volume(_OK), _volume(_OK)], False, id="every-restore-confirmed"),
        pytest.param([_volume(None), {}], False, id="no-restore-had-a-copy-to-protect-says-nothing-either-way"),
        pytest.param([_volume(_OK), _volume(_STILL)], True, id="one-restore-copied-while-a-pass-ran"),
        pytest.param([_volume(_UNREAD)], True, id="a-scheduler-that-could-not-be-read-is-not-a-confirmation"),
        pytest.param([{"committed": True, "collector_exit": _STILL}], True, id="the-legacy-path-returns-the-report-itself"),
        pytest.param([None], False, id="an-item-with-no-summary-yet"),
    ],
)
def test_the_queue_status_says_whether_any_restore_copied_the_corpus_unconfirmed(tmp_path, summaries, unconfirmed):
    q = _queue(tmp_path, summaries)
    assert q.status()["collection_exit_unconfirmed"] is unconfirmed


def test_the_dialog_does_not_claim_a_pause_that_a_restore_found_was_not_yet_true():
    """The static twin of tests/import_tail_phase_node_test.js: the claim is gated on the field."""
    js = (Path(__file__).resolve().parents[1] / "src" / "static" / "app-backup.js").read_text(encoding="utf-8")
    line = next(ln for ln in js.splitlines() if "Background collection is paused for this whole import" in ln)
    assert "!st.collection_exit_unconfirmed" in line
