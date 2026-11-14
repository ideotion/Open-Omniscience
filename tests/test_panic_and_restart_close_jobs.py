"""The two stops that skip the lifespan close the database to background jobs too (R689 follow-ups (1) and (4)).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

* The panic wipe holds collection and refuses every job BEFORE the erase, disposes the pool after it, and waits on nothing: a wipe races
  a seizure. A step that fails never stops the wipe.
* The data-drive restart runs the graceful stop's job steps (ask, wait against ONE 5 s deadline, refuse, dispose) before its
  execve, so a job is no longer cut mid-unit. A failed execve is loud and ends in a shutdown, never a half-alive app.
* The shared helper closes the database to jobs whatever the wait found, even when the wait itself fails.
"""

from __future__ import annotations

import threading

import pytest

from src.database import after_shutdown
from src.safety import data_volume


def test_the_helper_closes_the_database_whatever_the_wait_found(monkeypatch):
    import src.jobs.background as bg

    seen = {}
    def stop_all_jobs(timeout):
        seen["timeout"] = timeout
        return ["llm-bulk"]

    monkeypatch.setattr(bg, "stop_all_jobs", stop_all_jobs)
    monkeypatch.setattr(bg, "running_job_threads", lambda: [])
    assert after_shutdown.stop_jobs_and_close(0.0) == ["llm-bulk"]
    assert seen["timeout"] == 0.0
    assert after_shutdown.is_closed()


def test_the_helper_closes_the_database_even_when_the_wait_fails(monkeypatch):
    import src.jobs.background as bg

    def boom(_timeout):
        raise RuntimeError("registry broken")

    monkeypatch.setattr(bg, "stop_all_jobs", boom)
    monkeypatch.setattr(bg, "running_job_threads", boom)
    assert after_shutdown.stop_jobs_and_close(5.0) == []
    assert after_shutdown.is_closed(), "a failed wait still closes the database to jobs"


def test_a_job_thread_is_refused_after_the_helper_ran(monkeypatch):
    import src.jobs.background as bg

    monkeypatch.setattr(bg, "stop_all_jobs", lambda timeout: [])
    monkeypatch.setattr(bg, "running_job_threads", lambda: [])
    after_shutdown.stop_jobs_and_close(0.0)
    out = {}

    def job():
        try:
            after_shutdown.check("a commit")
            out["refused"] = False
        except after_shutdown.WriteAfterShutdownRefused:
            out["refused"] = True

    t = threading.Thread(target=job, name="bgjob-insights-backlog")
    t.start()
    t.join(5)
    assert out == {"refused": True}


@pytest.fixture
def panic_steps(monkeypatch):
    import src.database.session as session
    import src.ingest as ingest
    import src.safety.crypto_erase as crypto_erase
    import src.scheduler.runner as runner

    calls: list[tuple] = []
    monkeypatch.setattr(runner, "pause_for_exclusive_operation", lambda timeout=10.0, **_k: calls.append(("pause", timeout)))
    monkeypatch.setattr(after_shutdown, "stop_jobs_and_close", lambda timeout: calls.append(("jobs", timeout)) or [])
    monkeypatch.setattr(session, "dispose_engine", lambda: calls.append(("dispose",)) or {})
    monkeypatch.setattr(crypto_erase, "quick_crypto_erase", lambda **_k: calls.append(("erase",)) or {"files_wiped": 0})
    monkeypatch.setattr(ingest, "activate_kill_switch", lambda *a, **k: None)
    return calls


def test_the_panic_wipe_closes_the_database_first_and_waits_on_nothing(panic_steps):
    from src.safety import panic_wipe

    panic_wipe(confirm=True)
    assert panic_steps == [("pause", 0.0), ("jobs", 0.0), ("erase",), ("dispose",)], "the pool is closed only once the key is gone"


def test_a_failing_close_step_never_stops_the_wipe(panic_steps, monkeypatch):
    import src.database.session as session
    import src.scheduler.runner as runner
    from src.safety import panic_wipe

    def boom(*_a, **_k):
        raise RuntimeError("step failed")

    monkeypatch.setattr(runner, "pause_for_exclusive_operation", boom)
    monkeypatch.setattr(after_shutdown, "stop_jobs_and_close", boom)
    monkeypatch.setattr(session, "dispose_engine", boom)
    assert panic_wipe(confirm=True) == {"files_wiped": 0}
    assert panic_steps == [("erase",)]


def test_the_wipe_refuses_the_collectors_own_threads(panic_steps):
    from src.safety import panic_wipe

    go, out = threading.Event(), {}

    def collector():
        go.wait(10)
        try:
            after_shutdown.check("a commit")
            out["refused"] = False
        except after_shutdown.WriteAfterShutdownRefused:
            out["refused"] = True

    t = threading.Thread(target=collector, name="oo-collect_0")
    t.start()
    try:
        panic_wipe(confirm=True)
    finally:
        go.set()
        t.join(10)
    assert out == {"refused": True}


def test_an_unconfirmed_wipe_closes_nothing(panic_steps):
    from src.safety import panic_wipe

    with pytest.raises(PermissionError):
        panic_wipe(confirm=False)
    assert panic_steps == []


@pytest.fixture
def restart_steps(monkeypatch):
    import src.database.session as session

    calls: list[tuple] = []
    monkeypatch.setattr(data_volume.time, "sleep", lambda _s: None)
    monkeypatch.setattr(after_shutdown, "stop_jobs_and_close", lambda timeout: calls.append(("jobs", timeout)) or [])
    monkeypatch.setattr(session, "dispose_engine", lambda: calls.append(("dispose",)) or {})
    monkeypatch.setattr(data_volume, "_reap", lambda: calls.append(("reap",)))
    monkeypatch.setattr(data_volume, "_restart_process", lambda: calls.append(("execve",)))
    return calls


def _run_restart_thread():
    before = set(threading.enumerate())
    data_volume._restart_after_reconnect()
    for t in set(threading.enumerate()) - before:
        if t.name == "oo-data-volume-restart":
            t.join(10)


def test_the_drive_restart_stops_the_jobs_with_the_graceful_deadline_before_its_execve(restart_steps):
    _run_restart_thread()
    assert restart_steps == [("jobs", 5.0), ("dispose",), ("reap",), ("execve",)]
    assert data_volume._JOBS_STOP_DEADLINE_S == 5.0


def test_a_failed_execve_is_loud_and_shuts_down(restart_steps, monkeypatch, caplog):
    def boom():
        raise OSError("exec format error")

    incidents = []
    closed = []
    monkeypatch.setattr(data_volume, "_restart_process", boom)
    monkeypatch.setattr(data_volume, "record_incident", lambda event, **f: incidents.append(event))
    monkeypatch.setattr(data_volume.MONITOR, "_exit", lambda: closed.append(True))
    monkeypatch.setattr(data_volume.MONITOR, "phase", "restarting")
    with caplog.at_level("ERROR", logger=data_volume._LOG.name):
        _run_restart_thread()
    assert "restart_failed" in incidents
    assert closed == [True] and data_volume.MONITOR.phase == "closing"
    assert any("the restart failed" in r.getMessage() for r in caplog.records)


def test_the_wipe_rewrites_the_kept_files_after_the_dispose_and_once_more_later(panic_steps, monkeypatch):
    import src.safety.crypto_erase as crypto_erase
    from src.safety import panic, panic_wipe

    done = threading.Event()

    def rescrub(*, close, generation=None):
        panic_steps.append(("rescrub", close))
        if close:
            done.set()
        return 1

    monkeypatch.setattr(crypto_erase, "rescrub_held", rescrub)
    monkeypatch.setattr(crypto_erase, "held_count", lambda *_a: 1)
    monkeypatch.setattr(panic, "_LATE_RESCRUB_S", 0.01)
    panic_wipe(confirm=True)
    assert done.wait(10)
    assert panic_steps[-3:] == [("dispose",), ("rescrub", False), ("rescrub", True)]


def test_the_late_pass_runs_even_when_the_first_rewrote_nothing(panic_steps, monkeypatch):
    """The late pass is also the one that lets the descriptors go: a first pass whose every rewrite failed must not leave
    them (one pins the unlinked corpus inode) held for the life of the process."""
    import src.safety.crypto_erase as crypto_erase
    from src.safety import panic, panic_wipe

    done = threading.Event()

    def rescrub(*, close, generation=None):
        panic_steps.append(("rescrub", close))
        if close:
            done.set()
        return 0

    monkeypatch.setattr(crypto_erase, "rescrub_held", rescrub)
    monkeypatch.setattr(crypto_erase, "held_count", lambda *_a: 2)
    monkeypatch.setattr(panic, "_LATE_RESCRUB_S", 0.01)
    panic_wipe(confirm=True)
    assert done.wait(10)


def test_a_failing_step_after_a_completed_erase_still_returns_the_report(panic_steps, monkeypatch):
    """Row 35: the erase succeeded, so the wipe answers with its report and names the step that failed, never a 500."""
    from src.api import served_cache
    from src.safety import panic_wipe

    real = served_cache.invalidate
    calls = []

    def boom(*a, **k):
        if not calls:  # the wipe's call fails; a later one (the suite's own isolation) goes through
            calls.append(True)
            raise RuntimeError("cache broken")
        return real(*a, **k)

    monkeypatch.setattr(served_cache, "invalidate", boom)
    report = panic_wipe(confirm=True)
    assert report["after_erase_failures"] == ["served_counts"]
    assert panic_steps[-1] == ("dispose",), "the pool is still closed after the failed step"


def test_the_kill_switch_failing_is_named_and_the_rest_still_runs(panic_steps, monkeypatch):
    import src.ingest as ingest
    from src.database import connect
    from src.safety import panic_wipe

    cleared = []
    monkeypatch.setattr(ingest, "activate_kill_switch", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no switch")))
    monkeypatch.setattr(connect, "invalidate_header_cache", lambda: cleared.append(True))
    report = panic_wipe(confirm=True)
    assert report["after_erase_failures"] == ["kill_switch"]
    assert cleared == [True]


def test_a_failed_erase_still_raises_after_the_tidying(panic_steps, monkeypatch):
    import src.safety.crypto_erase as crypto_erase
    from src.safety import panic_wipe

    def broken(**_k):
        raise OSError("erase failed")

    monkeypatch.setattr(crypto_erase, "quick_crypto_erase", broken)
    with pytest.raises(OSError):
        panic_wipe(confirm=True)
    assert panic_steps[-1] == ("dispose",)


def test_a_failed_execve_shuts_down_even_when_recording_it_fails(restart_steps, monkeypatch):
    def boom():
        raise OSError("exec format error")

    calls = []

    def broken(event, **_k):
        calls.append(event)
        if event == "restart_failed":
            raise RuntimeError("incident log broken")

    closed = []
    monkeypatch.setattr(data_volume, "_restart_process", boom)
    monkeypatch.setattr(data_volume, "record_incident", broken)
    monkeypatch.setattr(data_volume.MONITOR, "_exit", lambda: closed.append(True))
    monkeypatch.setattr(data_volume.MONITOR, "phase", "restarting")
    _run_restart_thread()
    assert closed == [True] and data_volume.MONITOR.phase == "closing"
    assert calls == ["restart_failed", "shutdown"]
