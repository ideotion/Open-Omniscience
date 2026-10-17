"""R163: the retry loop of ``resume_after_exclusive_operation`` stays inside the ``try`` whose ``finally`` hands the scheduler's exclusive window back.

Kept apart from tests/test_gates_survive_an_interrupt.py, whose dis helper it uses, because that file and this change ship in different bundles."""

from __future__ import annotations

from tests.test_gates_survive_an_interrupt import _uncovered_back_edges


def test_the_resume_retry_loop_keeps_its_back_edge_inside_the_finally_that_releases_the_window():
    """R163: ``resume_after_exclusive_operation`` is reached on the main thread by ``scripts/run_scale_bench.py``. Its ``finally`` hands the
    scheduler's exclusive window back, so the retry loop is a function of its own, called from inside the ``try``."""
    from src.scheduler import runner

    assert not _uncovered_back_edges(runner.resume_after_exclusive_operation)
    assert not _uncovered_back_edges(runner._start_or_stand_down)


def test_the_resume_still_retries_stands_down_for_the_kill_switch_and_always_releases_the_window(monkeypatch):
    import src.ingest as ingest
    from src.scheduler import runner

    class Sched:
        def __init__(self, starts):
            self.starts, self.calls, self.released = list(starts), 0, 0

        def start(self):
            self.calls += 1
            return self.starts.pop(0)

        def release_exclusive(self):
            self.released += 1

    monkeypatch.setattr(runner, "exclusive_window_open", lambda: False)
    monkeypatch.setattr(runner.time, "sleep", lambda _s: None)
    watched = []
    monkeypatch.setattr(runner, "_watch_for_resume", lambda sched: watched.append(sched))

    # starts on the third try: two refusals, no watcher
    sched = Sched([False, False, True])
    monkeypatch.setattr(runner, "get_scheduler", lambda: sched)
    monkeypatch.setattr(ingest, "kill_switch_active", lambda: False)
    runner.resume_after_exclusive_operation(True, retries=5, retry_delay=0)
    assert (sched.calls, sched.released, watched) == (3, 1, [])

    # the kill switch wins: nothing is started, the window is still given back
    sched = Sched([True])
    monkeypatch.setattr(runner, "get_scheduler", lambda: sched)
    monkeypatch.setattr(ingest, "kill_switch_active", lambda: True)
    runner.resume_after_exclusive_operation(True, retries=5, retry_delay=0)
    assert (sched.calls, sched.released, watched) == (0, 1, [])

    # the retries run out: one attempt per retry plus the first, then the watcher, then the window is given back
    sched = Sched([False] * 4)
    monkeypatch.setattr(runner, "get_scheduler", lambda: sched)
    monkeypatch.setattr(ingest, "kill_switch_active", lambda: False)
    runner.resume_after_exclusive_operation(True, retries=3, retry_delay=0)
    assert (sched.calls, sched.released, watched) == (4, 1, [sched])
