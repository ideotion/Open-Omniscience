"""A background job whose worker ends in a ``BaseException`` (``SystemExit``, ``KeyboardInterrupt``) is not left "running".

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``BackgroundJob._run`` caught ``Exception`` only, so a worker that ended in ``SystemExit`` (a library calling ``sys.exit``) skipped the
handler: the ``finally`` stamped ``_ended_at`` and the state stayed "running" for the life of the process. The task manager showed an
active job that was gone, a writer job held ``db_writers_busy``, and a second ``start()`` ran beside nothing. It now ends "error" and
names the exception's CLASS only: a ``SystemExit`` carries the caller's own words, and a job's kwargs can carry a passphrase.
"""

from __future__ import annotations

import logging

import pytest

from src.database import connect
from src.jobs.background import BackgroundJob

# The worker thread re-raises (that is the behaviour under test), so pytest's thread-exception hook reports it; that report is expected here.
pytestmark = pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")

HELD = "kQ7!vLm-the-held-key"


def _run(exc: BaseException, *, is_writer: bool = False) -> tuple[BackgroundJob, dict]:
    def worker(ctx):
        raise exc

    job = BackgroundJob("test-base-exc", "T", worker, is_writer=is_writer)
    job.start()
    job._thread.join(5)
    return job, job.status()


@pytest.mark.parametrize("exc", [SystemExit(HELD), KeyboardInterrupt(HELD)], ids=["SystemExit", "KeyboardInterrupt"])
def test_a_worker_that_ends_in_a_base_exception_is_an_error_not_a_running_job(exc, monkeypatch):
    monkeypatch.setattr(connect, "_passphrase", HELD)
    job, st = _run(exc)
    assert st["state"] == "error", st
    assert st["error"] == f"{type(exc).__name__}: its text is withheld", st
    assert HELD not in str(st), "the exception's words reached the status"
    assert st["ended_at"] is not None


def test_the_job_can_be_started_again_after_it(monkeypatch):
    job, _ = _run(SystemExit(1))
    ran: list[int] = []
    job._worker = lambda ctx: ran.append(1)
    job.start()
    job._thread.join(5)
    assert ran == [1] and job.status()["state"] == "done"


def test_an_ordinary_exception_and_a_clean_run_are_unchanged():
    _, st = _run(RuntimeError("boom"))
    assert st["state"] == "error" and st["error"].startswith("RuntimeError: boom")
    job = BackgroundJob("test-base-exc-ok", "T", lambda ctx: 7)
    job.start()
    job._thread.join(5)
    assert job.status()["state"] == "done"


def test_it_is_logged_once_by_class_and_the_words_stay_out_of_the_log(monkeypatch, caplog):
    monkeypatch.setattr(connect, "_passphrase", HELD)
    caplog.set_level(logging.DEBUG, logger="jobs.background")
    _run(SystemExit(HELD))
    records = [r for r in caplog.records if r.name == "jobs.background"]
    assert [r.getMessage() for r in records] == ["background job test-base-exc ended by SystemExit"], records
    assert records[0].levelno == logging.WARNING and records[0].exc_info is None
    assert HELD not in caplog.text


def test_the_exit_goes_on_up_after_the_state_is_set():
    """The handler records the end and re-raises: swallowing a ``SystemExit`` would change what the thread (and its hook) sees."""
    from src.jobs.background import JobContext

    def worker(ctx):
        raise SystemExit(3)

    job = BackgroundJob("test-base-exc-up", "T", worker)
    with pytest.raises(SystemExit):
        job._run(JobContext(job), {})
    assert job.status()["state"] == "error"
