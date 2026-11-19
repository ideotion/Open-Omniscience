"""
Two concurrent resumes of one paused quarantine run (qualification lane, 2026-10-25).

resume() read the paused run's state under the lock, released it, and only then called start(). Two
callers (the quarantine endpoint and the task-manager jobs endpoint both reach resume) could both read
"paused" at cursor 5; if the first run finished before the second start(), the second restarted from
cursor 5 and counted the same articles again. resume() now holds the lock from its state check through
start(), so the second caller sees the run already moved on and is refused.
"""

from __future__ import annotations

import threading

import pytest

from src.analytics import quarantine_job as qj


def _work(session, **kw):
    return {"scanned": 3, "quarantined": 1, "already_quarantined": 0, "newly_written": 0,
            "by_reason": {"x": 1}, "last_id": 9, "done": True, "write": False}


class _Session:
    """A session the worker can close. The factory used to return None: the worker's ``session.close()``
    then raised AFTER the batch, the run ended in ``error`` instead of ``done``, and ``error`` is
    resumable -- so a second caller that took the lock after the worker finished was rightly let in,
    and the race test failed whenever the scheduler ordered it that way (row 176)."""

    def close(self) -> None:
        pass


def _paused_manager(tmp_path, cls=qj.QuarantineJobManager):
    mgr = cls(state_path=tmp_path / "q.json")
    mgr._state, mgr._cursor, mgr._total, mgr._done = "paused", 5, 20, 5
    mgr._tally = {"scanned": 5, "quarantined": 2, "reason:x": 2}
    mgr._work_fn = _work
    mgr._session_factory = _Session
    return mgr


def test_a_second_resume_after_the_first_run_finished_is_refused(tmp_path):
    """The concurrent test's worst ordering, made deterministic: the second caller arrives only once the
    first run has finished. It must find the run done, not resumable."""
    mgr = _paused_manager(tmp_path)
    mgr.resume()
    assert mgr._thread is not None
    mgr._thread.join(30)
    assert mgr.status()["state"] == "done", mgr.status()
    with pytest.raises(RuntimeError):
        mgr.resume()
    assert mgr.status()["tally"]["scanned"] == 8


def test_two_concurrent_resumes_count_the_remaining_work_once(tmp_path):
    barrier = threading.Barrier(2)
    turn = threading.Lock()
    a_finished = threading.Event()

    class Meet(qj.QuarantineJobManager):
        def start(self, **kw):
            # Both callers have read "paused" before either reaches start() (the old shape). Whichever
            # gets the turn runs and FINISHES before the other's start(): the interleaving that doubles.
            try:
                barrier.wait(timeout=2)
            except threading.BrokenBarrierError:
                pass  # the fixed resume() never lets two callers get here together
            if not turn.acquire(blocking=False):
                a_finished.wait(10)
                return super().start(**kw)
            out = super().start(**kw)
            worker = self._thread
            assert worker is not None
            # Joined from the side: the worker needs the manager lock, which a fixed resume() still
            # holds while it is inside start().
            threading.Thread(target=lambda: (worker.join(10), a_finished.set()), daemon=True).start()
            return out

    mgr = _paused_manager(tmp_path, Meet)

    outcomes: list[str] = []

    def call():
        try:
            mgr.resume()
            outcomes.append("resumed")
        except RuntimeError:
            outcomes.append("refused")

    threads = [threading.Thread(target=call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)

    assert sorted(outcomes) == ["refused", "resumed"], outcomes
    assert mgr._thread is not None
    mgr._thread.join(30)
    assert mgr.status()["tally"]["scanned"] == 8  # 5 before the pause + this batch once
    assert mgr.status()["tally"]["reason:x"] == 3


def test_resume_still_refuses_when_nothing_is_paused(tmp_path):
    mgr = qj.QuarantineJobManager(state_path=tmp_path / "q.json")
    with pytest.raises(RuntimeError):
        mgr.resume()
