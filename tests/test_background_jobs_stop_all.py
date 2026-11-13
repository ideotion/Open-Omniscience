"""Audit A-029: the shutdown asks every registered background job to stop, and waits for them, before the engine is disposed.

Before this the lifespan stopped the scheduler, the offline maintenance and the storage guard, then wrote the log back and disposed the
pool, while a registered ``BackgroundJob`` (a backfill, an enrichment, an import) could still be writing: its checked-out connection kept
the log from being folded, and the process exit ended the unit it was writing. ``stop_all_jobs`` asks each running job to stop and waits
for all of them against ONE deadline; the lifespan calls it before the write-back and logs the kinds still running.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import pytest

from src.jobs import background as bg
from tests.js_source_helper import python_function_source

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def registry():
    saved = dict(bg._REGISTRY)
    bg._reset_registry_for_tests()
    made: list[bg.BackgroundJob] = []
    yield made
    for job in made:  # never leave a worker thread behind
        job.cancel()
    release.set()
    for job in made:
        job.join(5)
    bg._reset_registry_for_tests()
    bg._REGISTRY.update(saved)


release = threading.Event()


def _cooperative(ctx):
    while not ctx.stopping:
        time.sleep(0.01)
    return "stopped"


def _ignores_stop(ctx):
    release.wait(10)
    return "finished"


def _job(registry, kind, worker, cancellable):
    job = bg.register_job(bg.BackgroundJob(kind, kind, worker, is_writer=True, cancellable=cancellable))
    registry.append(job)
    return job


def test_a_cooperative_job_is_asked_to_stop_and_joined(registry):
    release.clear()
    job = _job(registry, "coop", _cooperative, cancellable=True)
    job.start()
    assert bg.stop_all_jobs(5.0) == []
    assert job.status()["state"] == "cancelled"
    assert not job._alive()


def test_a_job_that_does_not_stop_is_named_and_the_wait_is_one_shared_deadline(registry):
    release.clear()
    a = _job(registry, "stubborn-a", _ignores_stop, cancellable=False)
    b = _job(registry, "stubborn-b", _ignores_stop, cancellable=True)  # cancellable, but its worker never looks
    a.start()
    b.start()
    began = time.monotonic()
    left = bg.stop_all_jobs(0.3)
    took = time.monotonic() - began
    assert left == ["stubborn-a", "stubborn-b"]
    assert took < 0.3 + 0.5, f"two jobs must share ONE deadline, not one each ({took:.2f} s)"
    # an opaque job is not flagged: a late finish must read 'done', never 'cancelled'
    assert not a._stop.is_set()
    release.set()
    assert a.join(5) and b.join(5)
    assert a.status()["state"] == "done"


def test_an_idle_registry_answers_at_once_and_never_raises(registry):
    _job(registry, "idle", _cooperative, cancellable=True)  # registered, never started
    began = time.monotonic()
    assert bg.stop_all_jobs(5.0) == []
    assert time.monotonic() - began < 0.5


def test_the_lifespan_stops_the_jobs_before_the_write_back_and_the_disposal():
    """Anchored to the lifespan's own source (never the app singleton): the stop comes after the storage guard's and before both the
    write-back and ``dispose_engine``, and the kinds it reports are logged."""
    src = python_function_source((ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8"), "lifespan")
    teardown = src.index("    yield\n")  # the teardown starts at the lifespan's own yield
    at = {name: src.find(needle, teardown) for name, needle in {
        "guard": "_stop_storage_guard()",
        "jobs": "stop_all_jobs(",
        "write_back": "checkpoint_before_dispose()",
        "dispose": "disposed = dispose_engine()",
    }.items()}
    assert all(v >= 0 for v in at.values()), at
    assert at["guard"] < at["jobs"] < at["write_back"] < at["dispose"], at
    # the kinds left are logged, and only the kinds (the job's arguments can hold a passphrase)
    assert re.compile(r"logger\.warning\(\s*\"background jobs still running[^\"]*\",\s*\", \"\.join\(jobs_left\)\)").search(src, teardown)

