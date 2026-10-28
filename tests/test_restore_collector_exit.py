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

import json
import os
import subprocess
import sys
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
_REPO = Path(__file__).resolve().parents[1]
_HELPER = _REPO / "tests" / "torture_helper.py"
_PASS = "a collection pass or maintenance run"


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
    assert collector_exit.wait_state() is None, "nothing was waited for, so nothing is published as waiting"
    assert collector_exit.last_answer()["confirmed"] is True, "the answer is published for the dialog the moment it exists"


def test_a_busy_pass_is_named_for_what_it_is_and_the_wait_publishes_itself_while_it_waits(monkeypatch, blocked):
    """The dialog reads the wait from here during the minutes it lasts, long before the report exists."""
    assert blocked.sched.run_now() is True
    assert blocked.entered.wait(HANG_GUARD_S)
    seen: list[dict | None] = []

    def stop_after_a_look() -> bool:
        seen.append(collector_exit.wait_state())
        return True

    got = collector_exit.wait_for_collector_exit(should_stop=stop_after_a_look)
    assert got["still"] == [_PASS], "a maintenance run sets the same flag as a pass: the label must not call it only a pass"
    (waiting,) = seen
    assert waiting is not None and waiting["still"] == [_PASS] and waiting["bound_s"] == 600.0
    assert waiting["since"] <= time.time()
    assert collector_exit.wait_state() is None, "the wait has ended: it is no longer published as waiting"
    last = collector_exit.last_answer()
    assert last["confirmed"] is False and last["stopped"] is True and last["at"] >= waiting["since"]


def test_a_stop_is_not_recorded_as_a_timeout(monkeypatch):
    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: _Lingering())
    stopped = collector_exit.wait_for_collector_exit(should_stop=lambda: True)
    assert stopped["confirmed"] is False and stopped["stopped"] is True
    monkeypatch.setattr(collector_exit, "time", SteppedClock())
    timed_out = collector_exit.wait_for_collector_exit()
    assert timed_out["confirmed"] is False and "stopped" not in timed_out, "the bound ending is a different fact from a Stop"


def test_a_wait_that_raises_does_not_stay_published_as_waiting(monkeypatch):
    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: _Lingering())

    def boom() -> bool:
        raise RuntimeError("stop check failed")

    with pytest.raises(RuntimeError):
        collector_exit.wait_for_collector_exit(should_stop=boom)
    assert collector_exit.wait_state() is None, "a dialog must never go on saying 'waiting' for a wait that is over"


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


def test_the_wait_is_a_timed_sub_stage_the_journal_names_and_not_a_phase(monkeypatch, tmp_path):
    """Up to ten minutes the phase bar stands still; the journal (and so a killed run's trace) must say what it was doing."""
    import src.backup.runlog as runlog

    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: _Lingering())
    monkeypatch.setattr(collector_exit, "time", SteppedClock())
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(runlog, "milestone", lambda ev, **kw: events.append((ev, kw)))
    phases: list[str] = []
    _drive_to_snapshot(monkeypatch, tmp_path, lambda: None, commit=True, exclusive=True, stage_progress_cb=phases.append)
    names = [(ev, kw.get("name")) for ev, kw in events if ev in ("stage_begin", "stage_end", "collector_exit")]
    sub = "snapshot_working_copy:wait_for_collector"
    assert ("stage_begin", sub) in names and ("stage_end", sub) in names
    assert names.index(("stage_begin", sub)) < names.index(("collector_exit", None)), "the begin is journalled BEFORE the wait"
    assert sub not in phases, "a sub-stage is never pinged as a phase: restore_stage_plan()'s denominator would be wrong"
    from src.backup.merge import restore_stage_plan

    assert sub not in restore_stage_plan(commit=True)


def test_a_held_first_item_waits_because_it_takes_the_groups_only_copy(monkeypatch, tmp_path):
    """The first item of a checkpoint group (held, working copy not yet there) takes the one copy every later item carries."""
    calls: list[int] = []

    def fake_wait(**_k):
        calls.append(1)
        return dict(_OK)

    monkeypatch.setattr(collector_exit, "wait_for_collector_exit", fake_wait)
    group = tmp_path / "group"
    group.mkdir()
    _drive_to_snapshot(
        monkeypatch, tmp_path, lambda: None,
        commit=True, exclusive=True, hold_after_merge=True, working_copy=group / "working.db",
    )
    assert calls == [1], "a held first item copies the corpus; a pass still writing is lost with the group's swap"


# --------------------------------------------------------------------------- #
#  the report carries it: the REAL run_restore against a real corpus, then into the dialog's status
# --------------------------------------------------------------------------- #
def _helper(data_dir: Path, *args: str) -> dict:
    env = dict(os.environ, OO_DATA_DIR=str(data_dir), OO_NO_SCHEDULER="1", OO_DB_PLAINTEXT="1")
    proc = subprocess.run(
        [sys.executable, str(_HELPER), *args],
        capture_output=True, text=True, cwd=str(_REPO), env=env, timeout=300,
    )
    assert proc.returncode == 0, f"helper failed:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture()
def _stores(tmp_path):
    """A live corpus ``A`` and a backup ``art`` of a different corpus to merge into it."""
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir(), b.mkdir()
    art = tmp_path / "corpusB.oobak.ooenc"
    assert _helper(b, "build", "B", "--artifact", str(art), "--passphrase", "pw-x").get("artifact")
    _helper(a, "build", "A")
    return a, art


def _merge(a: Path, art: Path, *flags: str) -> dict:
    return _helper(a, "merge", str(art), "--passphrase", "pw-x", *flags)["report"]


_E2E = pytest.mark.skipif(sys.platform == "win32", reason="subprocess round-trip mirrors the POSIX torture harness")


@_E2E
def test_a_real_restore_that_owns_the_machine_reports_what_the_wait_found(_stores):
    a, art = _stores
    report = _merge(a, art, "--commit", "--exclusive")
    assert report["committed"] is True
    assert report["collector_exit"]["confirmed"] is True and report["collector_exit"]["still"] == []


@_E2E
def test_a_real_restore_that_found_a_pass_still_there_says_so_and_the_dialog_stops_claiming_a_pause(_stores, tmp_path):
    """The three ways the fix can lie while its wait is right: a report that always says confirmed, a report that is
    never given the answer, and a status that does not read the report. All three pass a test of the wait alone."""
    a, art = _stores
    report = _merge(a, art, "--commit", "--exclusive", "--collector-busy")
    got = report["collector_exit"]
    assert got["confirmed"] is False and got["still"] == [_PASS]
    assert got["waited_s"] >= got["bound_s"] - 0.1, "the wait spent its bound before it went on"
    assert report["committed"] is True, "the restore goes on past the bound: the pause is a courtesy"
    # The corpus path's wrapper and the legacy path's bare report, as the queue holds them.
    assert _queue(tmp_path, [{"held": False, "report": report}]).status()["collection_exit_unconfirmed"] is True
    assert _queue(tmp_path, [report]).status()["collection_exit_unconfirmed"] is True


@_E2E
def test_the_first_held_item_waits_and_a_carried_one_does_not_in_a_real_group(_stores, tmp_path):
    a, art = _stores
    working = tmp_path / "group" / "working.db"
    working.parent.mkdir()
    held = _merge(a, art, "--commit", "--exclusive", "--collector-busy", "--hold", "--working-copy", str(working))
    assert held["held"] is True and held["collector_exit"]["confirmed"] is False
    carried = _merge(a, art, "--commit", "--exclusive", "--collector-busy", "--working-copy", str(working))
    assert "collector_exit" not in carried, "a carried copy was taken by the group's first item: this item protects no copy"


@_E2E
def test_a_real_restore_that_does_not_own_the_machine_claims_nothing(_stores):
    a, art = _stores
    report = _merge(a, art, "--commit", "--collector-busy")
    assert report["committed"] is True and "collector_exit" not in report


# --------------------------------------------------------------------------- #
#  the import dialog stops saying collection is paused where a restore found otherwise
# --------------------------------------------------------------------------- #
def _queue(tmp_path, summaries, states=None):
    from src.backup.import_queue import ImportQueueManager

    q = ImportQueueManager(state_path=tmp_path / "queue.json")
    states = states or ["done"] * len(summaries)
    q._items = [
        {"id": f"{i}-corpus", "kind": "corpus", "path": f"/a/{i}", "label": f"b{i}", "state": st,
         "started_at": 1.0, "ended_at": 2.0, "error": None, "summary": s, "force": False}
        for i, (s, st) in enumerate(zip(summaries, states, strict=True))
    ]
    return q


def _volume(exit_):
    """The shape the corpus path hands back: run_restore's report wrapped with the group bookkeeping."""
    return {"held": False, "report": {"committed": True, **({"collector_exit": exit_} if exit_ is not None else {})}}


_OK = {"confirmed": True, "waited_s": 0.0, "bound_s": 600.0, "still": []}
_STILL = {"confirmed": False, "waited_s": 600.0, "bound_s": 600.0, "still": [_PASS]}
_UNREAD = {"confirmed": None, "waited_s": 0.0, "bound_s": 600.0, "still": [], "reason": "the scheduler could not be read (RuntimeError)"}


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


@pytest.mark.parametrize(
    ("state", "unconfirmed"),
    [
        pytest.param("done", True, id="swapped-in"),
        pytest.param("staged", True, id="carried-toward-the-groups-swap"),
        pytest.param("error", False, id="refused-by-verification-the-live-corpus-was-untouched"),
        pytest.param("discarded", False, id="its-group-was-thrown-away"),
        pytest.param("stopped", False, id="stopped"),
        pytest.param("skipped", False, id="skipped"),
    ],
)
def test_only_a_restore_whose_copy_reaches_the_corpus_makes_the_dialog_withdraw_its_pause(tmp_path, state, unconfirmed):
    """A restore that found a pass still running and was then REFUSED (or discarded) changed nothing in the live file."""
    q = _queue(tmp_path, [_volume(_STILL)], states=[state])
    assert q.status()["collection_exit_unconfirmed"] is unconfirmed


def _running_queue(tmp_path, started_at=100.0):
    q = _queue(tmp_path, [None], states=["running"])
    q._items[0]["started_at"] = started_at
    q._state = "running"
    return q


def _answered(monkeypatch, answer: dict, at: float) -> None:
    """The wait's published answer, as it stands ``at`` seconds on the wall clock (set directly: no process-wide clock patch)."""
    monkeypatch.setattr(collector_exit, "_LAST", dict(answer, at=at))


def test_the_dialog_withdraws_its_pause_while_the_item_that_found_otherwise_is_still_running(tmp_path, monkeypatch):
    """THE POINT OF F1. The item's summary exists only after the swap, hours later on a large import; the loss happens
    in between. The answer is read from the wait's own publication."""
    monkeypatch.setattr(collector_exit, "_LAST", None)
    q = _running_queue(tmp_path)
    assert q.status()["collection_exit_unconfirmed"] is False, "nothing has been answered yet"
    _answered(monkeypatch, _STILL, at=150.0)
    st = q.status()
    assert st["collection_exit_unconfirmed"] is True and st["items"][0]["summary"] is None
    _answered(monkeypatch, _OK, at=150.0)
    assert q.status()["collection_exit_unconfirmed"] is False


def test_an_answer_from_before_the_running_item_began_is_not_this_items(tmp_path, monkeypatch):
    _answered(monkeypatch, _STILL, at=50.0)
    assert _running_queue(tmp_path, started_at=100.0).status()["collection_exit_unconfirmed"] is False


def test_the_answer_of_a_run_that_is_over_is_read_from_the_summaries_only(tmp_path, monkeypatch):
    _answered(monkeypatch, _STILL, at=150.0)
    q = _running_queue(tmp_path)
    q._state = "done"
    q._items[0]["state"] = "done"
    assert q.status()["collection_exit_unconfirmed"] is False, "a later, unrelated run's published answer is nobody's"


def test_the_status_carries_the_wait_while_it_waits_and_not_otherwise(tmp_path, monkeypatch):
    q = _running_queue(tmp_path)
    assert q.status()["collection_exit_wait"] is None
    monkeypatch.setattr(collector_exit, "_WAITING", {"since": time.time() - 12.0, "still": [_PASS], "bound_s": 600.0})
    wait = q.status()["collection_exit_wait"]
    assert wait["still"] == [_PASS] and wait["bound_s"] == 600.0 and 11.0 <= wait["elapsed_s"] <= 60.0
    q._state = "done"
    assert q.status()["collection_exit_wait"] is None, "a finished run is not waiting for anything"


def test_a_window_that_could_not_open_is_said_and_collection_is_not_called_paused(tmp_path, monkeypatch):
    import contextlib

    import src.backup.volume_job as volume_job

    q = _queue(tmp_path, [None], states=["queued"])
    seen: dict = {}

    @contextlib.contextmanager
    def window_that_fails():
        raise RuntimeError("scheduler would not stop")
        yield  # pragma: no cover

    monkeypatch.setattr(runner_mod, "exclusive_window", window_that_fails)
    monkeypatch.setattr(volume_job, "start_reindex_drain", lambda: (False, "test"))
    monkeypatch.setattr(q, "_drive", lambda: seen.update(q.status()))
    q._state = "running"
    q._run()
    assert seen["collection_window_failed"] is True and seen["collection_paused"] is False, (
        "the import goes on without a pause, and the dialog says that instead of staying silent"
    )


def test_a_window_that_opened_is_not_reported_failed(tmp_path, monkeypatch):
    import contextlib

    import src.backup.volume_job as volume_job

    q = _queue(tmp_path, [None], states=["queued"])
    seen: dict = {}

    @contextlib.contextmanager
    def window_that_opens():
        yield True

    monkeypatch.setattr(runner_mod, "exclusive_window", window_that_opens)
    monkeypatch.setattr(volume_job, "start_reindex_drain", lambda: (False, "test"))
    monkeypatch.setattr(q, "_drive", lambda: seen.update(q.status()))
    q._state = "running"
    q._run()
    assert seen["collection_window_failed"] is False and seen["collection_paused"] is True


_ROOT = Path(__file__).resolve().parents[1]
_LOCALES = ("ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh")
_PAUSED = "Background collection is paused for this whole import and resumes when it finishes."
_OTHER = "Other background work is not paused: what it, or you, saves to your corpus while the import runs can be lost."
_UNCONFIRMED = (
    "It could not be confirmed that background collection had stopped when the import copied your corpus, "
    "so what collection saved after that copy is not kept."
)
_NOT_PAUSED_AT_ALL = (
    "Background collection could not be paused for this import, and other background work is not paused either: "
    "what they, or you, save to your corpus while the import runs can be lost."
)
_WAITING = "Waiting for background collection to finish what it is writing before your corpus is copied (up to 10 minutes)."


def _js() -> str:
    return (_ROOT / "src" / "static" / "app-backup.js").read_text(encoding="utf-8")


def _table(lang: str) -> dict:
    return json.loads((_ROOT / "src" / "static" / "locales" / f"{lang}.json").read_text(encoding="utf-8"))


def _hover_key() -> str:
    keys = [k for k in _table("en") if k.startswith("Paused: the collection loop")]
    assert len(keys) == 1, keys
    return keys[0]


def test_the_dialog_does_not_claim_a_pause_that_a_restore_found_was_not_yet_true():
    """The static twin of tests/import_tail_phase_node_test.js: the claim is the ELSE of the unconfirmed test."""
    import re

    js = _js()
    unconfirmed = re.search(r"if \(st\.collection_exit_unconfirmed\) \{\s*collLines\.push\(t\(\"It could not be confirmed", js)
    failed = re.search(r"\} else if \(running && st\.collection_window_failed\) \{\s*collLines\.push\(t\(\"Background collection could not be paused", js)
    paused = re.search(r"\} else if \(running && st\.collection_paused\) \{\s*collLines\.push\(t\(\"Background collection is paused", js)
    assert unconfirmed and failed and paused and unconfirmed.start() < failed.start() < paused.start()


def test_every_line_the_dialog_says_about_the_pause_is_a_translated_key_in_every_language():
    """x12: every string is a key of every locale, carried by the JS literally, and translated (not the English copied)."""
    js = _js()
    hover = _hover_key()
    for text in (_PAUSED, _OTHER, _UNCONFIRMED, _NOT_PAUSED_AT_ALL, _WAITING, hover):
        assert f't("{text}")' in js, f"the dialog must look this up by its exact key: {text[:60]}"
    for lang in _LOCALES:
        table = _table(lang)
        for text in (_OTHER, _UNCONFIRMED, _NOT_PAUSED_AT_ALL, _WAITING, hover):
            assert text in table, f"{lang}: missing"
            if lang != "en":
                assert table[text] != text and len(table[text]) > 20, f"{lang}: left in English"


def test_the_ten_minutes_the_hover_promises_are_the_bound_the_wait_has():
    """The hover is a statement about the code: 'up to N minutes' must be COLLECTOR_EXIT_WAIT_S, in every language's digits."""
    import re

    assert "up to 10 minutes" in _hover_key() and "up to 10 minutes" in _WAITING
    assert collector_exit.COLLECTOR_EXIT_WAIT_S == 10 * 60
    # the other languages state the same number (ASCII digits, or Bengali digits for bn)
    for lang in _LOCALES:
        table = _table(lang)
        for key in (_hover_key(), _WAITING):
            assert re.search(r"(?<![0-9\u09e6-\u09ef])10(?![0-9])|\u09e7\u09e6", table[key]), f"{lang}: the bound is not stated in {key[:40]}"


def test_the_hover_names_every_writer_class_the_window_does_not_stop():
    hover = _hover_key()
    for named in (
        "the background tasks (markets, calendars, law, hazards, crawling and backfill)",
        "Wikipedia updates",
        "AI sweeps",
        "start-up upkeep",
        "anything you change in the app",
    ):
        assert named in hover
    assert "settings, agenda and interface choices" in hover, "what the swap carries over is stated beside what it discards"
    # F7: jobs that park at a batch boundary are not "not paused" outright; F5: Start / the network toggle restart the loop.
    assert "stop at their next batch" in hover and "a batch that is already running can still save" in hover
    assert "Starting collection again yourself while the import runs" in hover and "is not blocked" in hover


def test_the_queue_note_and_the_restores_own_text_no_longer_claim_that_nothing_else_writes():
    q = _queue(Path("."), [])  # the note is a constant of the status, whatever the run
    note = q.status()["collection_note"]
    assert "paused" in note.lower() and "not paused" in note.lower()
    merge_src = _MERGE_PY.read_text(encoding="utf-8")
    assert "nothing else is expected to write" not in merge_src, "the unqualified claim about the exclusive window is gone"
    assert "WHAT IT IS NOT: a lock on the corpus" in merge_src
