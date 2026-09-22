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
    # The worker BLOCKS on `release` so the just-started state is deterministically
    # "running" (a trivial worker could finish before start() returns its status, racing
    # the assertion — especially under full-suite load).
    release = threading.Event()

    def worker(ctx):
        release.wait(2)
        return {"ok": 1}

    job = BackgroundJob("test-done", "T", worker)
    s = job.start()
    assert s["state"] == "running"
    release.set()
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
    # After it finishes, a fresh start is ALLOWED again (no RuntimeError). The state may be
    # running or already done (hold is now set, so this worker no longer blocks) — either is
    # a valid post-start state; the point is that start() succeeded.
    hold2 = job.start()
    assert hold2["state"] in ("running", "done")
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


# --------------------------------------------------------------------------- #
# Live metrics (2026-09-21, audit docs/audit/15 finding F3)                    #
# --------------------------------------------------------------------------- #


def test_metrics_default_to_none_and_are_published_live():
    """``done``/``total``/``detail`` say HOW FAR; metrics say what the time is going
    ON. The backlog drain runs for days, so a split that only lands in the final
    ``result`` arrives long after the operator needed it."""
    seen: list = []

    def worker(ctx):
        seen.append(job.status()["metrics"])  # before anything is published
        ctx.set_metrics({"apply_s": 1.5})
        seen.append(job.status()["metrics"])
        ctx.set_metrics({"apply_s": 3.0})
        return "ok"

    job = BackgroundJob("test-metrics", "M", worker)
    job.start()
    job._thread.join(3)
    assert seen == [None, {"apply_s": 1.5}]
    assert job.status()["metrics"] == {"apply_s": 3.0}


def test_metrics_are_copied_so_a_worker_cannot_publish_a_half_updated_read():
    """A worker that keeps mutating its own accumulator must not be able to change
    what a poll already read."""
    acc = {"articles": 1}

    def worker(ctx):
        ctx.set_metrics(acc)
        acc["articles"] = 999  # the worker keeps accumulating after publishing

    job = BackgroundJob("test-metrics-copy", "M", worker)
    job.start()
    job._thread.join(3)
    assert job.status()["metrics"] == {"articles": 1}
    # ...and the read is a copy too: mutating it cannot reach back into the job.
    st = job.status()
    st["metrics"]["articles"] = -1
    assert job.status()["metrics"] == {"articles": 1}


def test_metrics_are_cleared_by_the_next_start():
    def worker(ctx):
        ctx.set_metrics({"articles": 7})

    job = BackgroundJob("test-metrics-reset", "M", worker)
    job.start()
    job._thread.join(3)
    assert job.status()["metrics"] == {"articles": 7}

    seen: list = []
    job._worker = lambda ctx: seen.append(job.status()["metrics"])
    job.start()
    job._thread.join(3)
    assert seen == [None], "a new run must not show the previous run's measurements"


def test_set_metrics_none_clears_them():
    def worker(ctx):
        ctx.set_metrics({"articles": 2})
        ctx.set_metrics(None)

    job = BackgroundJob("test-metrics-clear", "M", worker)
    job.start()
    job._thread.join(3)
    assert job.status()["metrics"] is None
