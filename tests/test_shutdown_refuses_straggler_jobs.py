"""R689: a background job that outlives the shutdown's deadline can no longer write after the engine is disposed, and every
graceful stop path stops the jobs BEFORE the first disposal.

Before this, the lifespan's stop-all gave up after 5 s and disposed the engine while such a job still ran; ``Engine.dispose()`` only
empties the pool, so the job's next commit opened a fresh connection and landed after the disposal. And the in-app power button (and
the uninstall's stop) disposed the engine BEFORE signalling, so on the stop path people use, the stop-all came after a disposal the jobs
and the collector had already reopened.

Which stop paths wait for the jobs, stated here and pinned below:
  * WAIT (through the lifespan shutdown: scheduler stop, stop-all, write-back, disposal, in that order): the power button, the
    update's stop, the memory guard's stop (memstop) and the data-volume guard's stop (all through ``request_shutdown``), the
    uninstall's stop, Ctrl-C and SIGTERM (the launcher's stop and a service manager's).
  * DO NOT WAIT, deliberately: the panic wipe. It destroys the key and the data at once and never waits on a job; it does not stop
    the process at all.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from src.database import after_shutdown
from src.jobs import background as bg

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def registry():
    saved = dict(bg._REGISTRY)
    bg._reset_registry_for_tests()
    made: list[bg.BackgroundJob] = []
    after_shutdown.clear()
    yield made
    for job in made:
        job.cancel()
    for job in made:
        job.join(5)
    after_shutdown.clear()
    bg._reset_registry_for_tests()
    bg._REGISTRY.update(saved)


def _try_db(results: list) -> None:
    """One statement through the ORM session and one gated raw write, each recorded as ok or the exception's type name."""
    from sqlalchemy import text

    from src.database.session import session_scope
    from src.database.writer import write_lock

    try:
        with session_scope() as s:
            s.execute(text("SELECT 1"))
        results.append("orm:ok")
    except Exception as exc:  # noqa: BLE001 - the test records what happened
        results.append(f"orm:{type(exc).__name__}")
    try:
        with write_lock():
            pass
        results.append("gate:ok")
    except Exception as exc:  # noqa: BLE001
        results.append(f"gate:{type(exc).__name__}")


def _stubborn(go: threading.Event, results: list):
    def worker(ctx):
        go.wait(10)  # never looks at ctx.stopping: one long model generation
        _try_db(results)
        return "finished"

    return worker


def test_a_refused_job_thread_cannot_use_the_database_and_is_named_once(registry, monkeypatch):
    go, results = threading.Event(), []
    job = bg.register_job(
        bg.BackgroundJob("stubborn-writer", "stubborn", _stubborn(go, results), is_writer=True)
    )
    registry.append(job)
    job.start()
    assert bg.stop_all_jobs(0.2) == ["stubborn-writer"]
    threads = bg.running_job_threads()
    assert [k for _t, k in threads] == ["stubborn-writer"]
    after_shutdown.refuse_threads(threads)
    said: list[str] = []
    monkeypatch.setattr(after_shutdown._LOG, "warning", lambda msg, *a: said.append(msg % a))
    go.set()
    assert job.join(10)
    assert results == ["orm:WriteAfterShutdownRefused", "gate:WriteAfterShutdownRefused"]
    assert len(said) == 1 and "stubborn-writer" in said[0], (
        said
    )  # by kind, once, however many times it tries
    # every other thread is untouched: this one still reads and takes the gate
    mine: list = []
    _try_db(mine)
    assert mine == ["orm:ok", "gate:ok"]


def test_the_lifespan_shutdown_refuses_the_job_it_stopped_waiting_for(registry, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app

    real = bg.stop_all_jobs
    monkeypatch.setattr(bg, "stop_all_jobs", lambda _t: real(0.2))  # the deadline, made short
    go, results = threading.Event(), []
    job = bg.register_job(
        bg.BackgroundJob("late-writer", "late", _stubborn(go, results), is_writer=True)
    )
    registry.append(job)
    with TestClient(app):
        job.start()
    said: list[str] = []
    # The app's start reconfigures logging, so the line is caught at the logger itself rather than through caplog.
    monkeypatch.setattr(after_shutdown._LOG, "warning", lambda msg, *a: said.append(msg % a))
    go.set()  # the job wakes after the disposal and tries to write
    assert job.join(10)
    assert results == ["orm:WriteAfterShutdownRefused", "gate:WriteAfterShutdownRefused"]
    assert len(said) == 1 and "late-writer" in said[0], said
    # and a new start forgets it
    with TestClient(app):
        assert after_shutdown.refused_kind() is None


def test_a_job_that_stopped_in_time_is_never_refused(registry, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app

    def cooperative(ctx):
        while not ctx.stopping:
            time.sleep(0.01)

    job = bg.register_job(
        bg.BackgroundJob("polite", "polite", cooperative, is_writer=True, cancellable=True)
    )
    registry.append(job)
    with TestClient(app):
        job.start()
    assert not after_shutdown._REFUSED, dict(after_shutdown._REFUSED)


def test_the_power_button_does_not_dispose_before_the_lifespan_stops_the_jobs(monkeypatch):
    from src.safety import shutdown as S

    disposed, signalled = [], threading.Event()
    monkeypatch.setattr("src.database.session.dispose_engine", lambda: disposed.append(1))
    monkeypatch.setattr(S, "_reap_worker_processes", lambda: None)
    monkeypatch.setattr(S, "stop_self", signalled.set)
    S._default_arm(0.0)
    assert signalled.wait(10)
    assert disposed == [], "the stop thread disposed before the lifespan's stop-all"


def test_no_graceful_stop_path_disposes_on_its_own():
    """Every graceful stop goes through the lifespan's one order. A disposal added back to a stop thread fails here."""
    for rel in ("src/safety/shutdown.py", "src/safety/uninstall.py"):
        assert "dispose_engine" not in (ROOT / rel).read_text(encoding="utf-8"), rel
    for rel in ("src/scheduler/memstop.py", "src/safety/data_volume.py", "src/api/system.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "request_shutdown(" in src and "dispose_engine" not in src, rel
    main = (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    i_stop, i_refuse, i_dispose = (
        main.index("jobs_left = stop_all_jobs("),
        main.index("refuse_threads(running_job_threads())"),
        main.index("disposed = dispose_engine()"),
    )
    assert i_stop < i_refuse < i_dispose


def test_the_panic_wipe_never_waits_on_a_job(monkeypatch, tmp_path):
    """Deliberate: an emergency erase destroys the key at once, whatever is running."""
    calls = []
    monkeypatch.setattr(bg, "stop_all_jobs", lambda *a, **k: calls.append(a) or [])
    from src.safety import crypto_erase
    from src.safety.panic import panic_wipe

    monkeypatch.setattr(
        crypto_erase, "quick_crypto_erase", lambda **k: {"files_seen": 0, "files_wiped": 0}
    )
    panic_wipe(tmp_path, confirm=True)
    assert calls == []
    src = (ROOT / "src/safety/panic.py").read_text(encoding="utf-8")
    assert "stop_all_jobs" not in src and "request_shutdown" not in src


def test_a_refused_job_cannot_write_or_delete_settings_even_with_the_gate_off(
    registry, monkeypatch
):
    """The app-state store writes through its own raw connection; the bulk queue keeps its state there."""
    from src.config import kv_store

    monkeypatch.setenv("OO_WRITE_GATE", "0")
    go, results = threading.Event(), []

    def worker(ctx):
        go.wait(10)
        for name, call in (
            ("set", lambda: kv_store.kv_set_json("r689-probe", {"x": 1})),
            ("delete", lambda: kv_store.kv_delete("r689-probe")),
        ):
            try:
                call()
                results.append(f"{name}:ok")
            except Exception as exc:  # noqa: BLE001 - the test records what happened
                results.append(f"{name}:{type(exc).__name__}")

    job = bg.register_job(bg.BackgroundJob("kv-writer", "kv", worker, is_writer=True))
    registry.append(job)
    job.start()
    after_shutdown.refuse_threads(bg.running_job_threads())
    monkeypatch.setattr(after_shutdown._LOG, "warning", lambda *a: None)
    go.set()
    assert job.join(10)
    assert results == ["set:WriteAfterShutdownRefused", "delete:WriteAfterShutdownRefused"]
