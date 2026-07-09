"""The generic background-job manager (field test 2026-07-08, Item 8 P1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Deterministic: workers signal via events, so we observe running/done/cancel without sleeps
racing the assertions. Negative space: a second start while running is REFUSED (not a
second worker); a cancelled worker ends `cancelled` (its partial work is not reported as
`done`); a crashing worker never takes the app down.
"""

import threading

import pytest

from src.jobs.background import (
    BackgroundJob,
    all_job_statuses,
    get_job,
    register_job,
)


def test_start_runs_the_worker_and_reports_done():
    job = BackgroundJob("test-done", "T", lambda ctx: {"ok": 1})
    s = job.start()
    assert s["state"] == "running"
    job._thread.join(3)
    st = job.status()
    assert st["state"] == "done"
    assert st["result"] == {"ok": 1}
    assert st["error"] is None


def test_worker_progress_is_visible():
    hold = threading.Event()
    at_half = threading.Event()

    def worker(ctx):
        ctx.set_progress(done=1, total=2, detail="halfway")
        at_half.set()
        hold.wait(2)
        ctx.set_progress(done=2, detail="finishing")
        return "done"

    job = BackgroundJob("test-progress", "T", worker)
    job.start()
    assert at_half.wait(2)
    st = job.status()
    assert st["done"] == 1 and st["total"] == 2 and st["detail"] == "halfway"
    assert st["progress"]["percent"] == 50.0
    hold.set()
    job._thread.join(3)


def test_cancel_stops_a_cooperative_worker_and_reports_cancelled():
    started = threading.Event()
    calls = [0]

    def worker(ctx):
        started.set()
        while not ctx.stopping:  # cooperative
            calls[0] += 1
        return "stopped-clean"

    job = BackgroundJob("test-cancel", "T", worker, cancellable=True)
    job.start()
    assert started.wait(2)
    job.cancel()
    job._thread.join(3)
    st = job.status()
    assert st["state"] == "cancelled", "a cancelled worker must not be reported as done"
    assert st["running"] is False and st["cancellable"] is True


def test_a_noncancellable_job_never_reports_cancelled_even_if_cancel_is_called():
    """The honesty gate (skeptic D1/D2): an opaque worker that cannot check ctx.stopping
    runs to completion — a cancel() must NOT mislabel its finished, full-result run."""
    hold = threading.Event()

    def opaque(ctx):
        hold.wait(2)  # ignores ctx.stopping — cannot cooperatively stop
        return {"done": True}

    job = BackgroundJob("test-opaque", "T", opaque, cancellable=False)
    job.start()
    job.cancel()  # user clicks cancel, but this worker can't honour it
    hold.set()
    job._thread.join(3)
    st = job.status()
    assert st["state"] == "done", "an uncancellable worker that finished must be 'done', not 'cancelled'"
    assert st["cancellable"] is False and st["result"] == {"done": True}


def test_a_second_start_while_running_is_refused():
    hold = threading.Event()

    def worker(ctx):
        hold.wait(2)
        return 1

    job = BackgroundJob("test-single", "T", worker)
    job.start()
    with pytest.raises(RuntimeError):
        job.start()  # already running -> refused, never a second worker
    hold.set()
    job._thread.join(3)
    # After it finishes, a fresh start is allowed again.
    hold2 = job.start()
    assert hold2["state"] == "running"
    job._thread.join(3)


def test_worker_crash_is_captured_not_propagated():
    def boom(ctx):
        raise ValueError("kaboom")

    job = BackgroundJob("test-error", "T", boom)
    job.start()  # must not raise
    job._thread.join(3)
    st = job.status()
    assert st["state"] == "error"
    assert "kaboom" in st["error"] and st["error"].startswith("ValueError")


def test_registry_enumerates_registered_jobs():
    job = register_job(BackgroundJob("test-registry", "Reg", lambda ctx: None))
    assert get_job("test-registry") is job
    kinds = {s["kind"] for s in all_job_statuses()}
    assert "test-registry" in kinds
    assert get_job("nope-not-registered") is None
