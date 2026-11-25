"""Row 383: a committing restore holds the starts of the jobs it stops for itself (the re-index drain) until it ends.

Before: the boot's last step, the Resume button or a hand-off could start the drain AFTER the restore's last writer check (R659). The drain
takes its lease batch after batch, so the swap's barrier waited its whole ``_SWAP_QUIESCE_S`` (180 s) and then refused the import with
"import again". Now ``run_restore`` with ``commit=True`` opens a hold before its first check; ``start()`` on a ``stops_for_restore`` job
inside it starts nothing and remembers the ask, and the restore makes that start on its way out (unless an import run's window is open,
or the app began shutting down since).
"""

from __future__ import annotations

import ast
import threading
import time
from pathlib import Path

import pytest

from src.jobs import background as bg

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def registry():
    """The real registry, emptied for the test and given back afterwards, with no hold open before or after."""
    with bg._REG_LOCK:
        saved = dict(bg._REGISTRY)
        bg._REGISTRY.clear()
    with bg._RESTORE_HOLD_LOCK:
        bg._RESTORE_HOLDS[0] = 0
        bg._DEFERRED_FOR_RESTORE.clear()
    yield
    with bg._RESTORE_HOLD_LOCK:
        bg._RESTORE_HOLDS[0] = 0
        bg._DEFERRED_FOR_RESTORE.clear()
    with bg._REG_LOCK:
        bg._REGISTRY.clear()
        bg._REGISTRY.update(saved)
        bg._STOPS_SEEN_AT_YIELD.clear()


def _drain(kind: str = "drain") -> tuple[bg.BackgroundJob, threading.Event]:
    """A registered stoppable writer (the drain's flags) whose worker runs until released, or until asked to stop or yield."""
    release = threading.Event()

    def worker(ctx):
        while not release.wait(0.005):
            if ctx.stopping or ctx.yielding:
                return

    job = bg.register_job(bg.BackgroundJob(kind, "Draining", worker, is_writer=True, cancellable=True, stops_for_restore=True))
    return job, release


def _no_window(monkeypatch, is_open: bool = False) -> None:
    from src.scheduler import runner

    monkeypatch.setattr(runner, "exclusive_window_open", lambda: is_open)


def test_a_start_inside_the_hold_is_held_and_made_when_the_hold_ends(registry):
    job, release = _drain()
    try:
        bg.hold_starts_for_restore()
        with pytest.raises(bg.StartHeldForRestore):
            job.start()
        assert not job._alive()
        assert job.status()["state"] == "idle", "a held start changes nothing the task manager shows"
        held = bg.release_restore_hold()
        assert held == {"drain": bg.stop_all_count()}
        assert bg.start_held_jobs(held) == ["drain"]
        assert job._alive()
    finally:
        release.set()
        job.join(5)


def test_a_held_start_is_a_runtime_error_so_every_caller_reads_it_as_not_started_now():
    assert issubclass(bg.StartHeldForRestore, RuntimeError)


def test_a_job_the_restore_does_not_stop_is_never_held(registry):
    release = threading.Event()
    job = bg.register_job(bg.BackgroundJob("w", "Writer", lambda ctx: release.wait(5), is_writer=True))
    try:
        bg.hold_starts_for_restore()
        job.start()  # it is refused by the restore's check instead, as before
        assert job._alive()
    finally:
        bg.release_restore_hold()
        release.set()
        job.join(5)


def test_the_race_no_drain_runs_between_the_restores_check_and_its_end(registry):
    """The row itself: a drain started over and over (boot, Resume, hand-off) while the restore opens its hold and runs its check is
    either running at the check, and stopped by it, or held; it never runs after the check while the restore goes on."""
    job, release = _drain()
    stop_hammer = threading.Event()

    def hammer():
        while not stop_hammer.is_set():
            try:
                job.start()
            except RuntimeError:
                pass

    try:
        for _ in range(15):
            stop_hammer.clear()
            t = threading.Thread(target=hammer, daemon=True)
            t.start()
            time.sleep(0.01)
            bg.hold_starts_for_restore()  # where run_restore opens it: before its first check
            bg.stop_jobs_for_restore(5.0)  # the check's stop (R659)
            assert bg.running_writer_jobs() == [], "the check finds nothing still writing"
            deadline = time.monotonic() + 0.1  # the rest of the restore: the hammer keeps asking
            while time.monotonic() < deadline:
                assert not job._alive(), "a drain started after the restore's check"
            stop_hammer.set()
            t.join(5)
            held = bg.release_restore_hold()
            assert "drain" in held
            with bg._REG_LOCK:
                bg._STOPS_SEEN_AT_YIELD.clear()
    finally:
        stop_hammer.set()
        release.set()
        job.join(5)


def test_run_restore_holds_only_when_it_commits(registry, monkeypatch):
    from src.backup import merge

    _no_window(monkeypatch)
    job, release = _drain()
    seen: list[str] = []

    @merge._holding_drain_starts
    def fake_restore(*, commit: bool):
        try:
            job.start()
            seen.append("started")
        except bg.StartHeldForRestore:
            seen.append("held")
        return "report"

    try:
        assert fake_restore(commit=True) == "report"
        assert seen == ["held"]
        assert job._alive(), "the held start is made as the restore ends"
        job.cancel()
        job.join(5)
        assert fake_restore(commit=False) == "report"
        assert seen == ["held", "started"], "a preview holds nothing"
    finally:
        release.set()
        job.join(5)


def test_a_restore_that_fails_still_makes_the_held_start(registry, monkeypatch):
    from src.backup import merge

    _no_window(monkeypatch)
    job, release = _drain()

    @merge._holding_drain_starts
    def failing_restore(*, commit: bool):
        with pytest.raises(bg.StartHeldForRestore):
            job.start()
        raise merge.RestoreRefused("refused")

    try:
        with pytest.raises(merge.RestoreRefused):
            failing_restore(commit=True)
        assert job._alive()
        with bg._RESTORE_HOLD_LOCK:
            assert bg._RESTORE_HOLDS[0] == 0, "the hold is closed on every way out"
    finally:
        release.set()
        job.join(5)


def test_inside_an_import_runs_window_the_held_start_is_left_to_the_run(registry, monkeypatch):
    from src.backup import merge

    _no_window(monkeypatch, is_open=True)
    job, release = _drain()

    @merge._holding_drain_starts
    def fake_restore(*, commit: bool):
        with pytest.raises(bg.StartHeldForRestore):
            job.start()

    try:
        fake_restore(commit=True)
        assert not job._alive(), "the run starts the drain once, when it ends"
        with bg._RESTORE_HOLD_LOCK:
            assert bg._DEFERRED_FOR_RESTORE == {}
    finally:
        release.set()
        job.join(5)


def test_a_shutdown_since_the_ask_drops_the_held_start(registry, monkeypatch):
    job, release = _drain()
    try:
        bg.hold_starts_for_restore()
        with pytest.raises(bg.StartHeldForRestore):
            job.start()
        held = bg.release_restore_hold()
        monkeypatch.setattr(bg, "_STOP_ALL_SEQ", bg._STOP_ALL_SEQ + 1)
        assert bg.start_held_jobs(held) == []
        assert not job._alive()
    finally:
        release.set()
        job.join(5)


def test_a_held_ask_is_fresh_so_an_earlier_cancel_does_not_drop_it(registry):
    job, release = _drain()
    try:
        job.start()
        job.cancel()
        job.join(5)
        assert job.status()["state"] == "cancelled"
        bg.hold_starts_for_restore()
        with pytest.raises(bg.StartHeldForRestore):
            job.start()  # the operator pressed Resume during the import
        assert bg.start_held_jobs(bg.release_restore_hold()) == ["drain"]
    finally:
        release.set()
        job.join(5)


def test_nested_holds_release_only_at_the_last(registry):
    job, release = _drain()
    try:
        bg.hold_starts_for_restore()
        bg.hold_starts_for_restore()
        with pytest.raises(bg.StartHeldForRestore):
            job.start()
        assert bg.release_restore_hold() == {}
        with pytest.raises(bg.StartHeldForRestore):
            job.start()
        assert list(bg.release_restore_hold()) == ["drain"]
    finally:
        release.set()
        job.join(5)


def test_the_resume_button_says_it_was_held(registry):
    from src.api import backup_v2

    bg.hold_starts_for_restore()
    try:
        st = backup_v2.reindex_backlog_resume()
    finally:
        bg.release_restore_hold()  # dropped, not made: nothing real is started by this test
    assert st["started"] is False
    assert st["held_for_import"] is True
    assert not backup_v2._REINDEX_RESUME_JOB._alive()


def test_run_restore_is_wrapped_by_the_hold():
    tree = ast.parse((ROOT / "src/backup/merge.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_restore")
    names = [d.id for d in fn.decorator_list if isinstance(d, ast.Name)]
    assert "_holding_drain_starts" in names
