"""R689: a background job that outlives the shutdown's deadline can no longer write after the engine is disposed, and every
graceful stop path stops the jobs BEFORE the first disposal.

Before this, the lifespan's stop-all gave up after 5 s and disposed the engine while such a job still ran; ``Engine.dispose()`` only
empties the pool, so the job's next commit opened a fresh connection and landed after the disposal. And the in-app power button (and
the uninstall's stop) disposed the engine BEFORE signalling, so on the stop path people use, the stop-all came after a disposal the jobs
and the collector had already reopened.

Which stop paths wait for the jobs, stated here and pinned below where a test can reach them:
  * WAIT (through the lifespan shutdown: scheduler stop, stop-all, the database closed to jobs, write-back, disposal, in that
    order): the power button, the update's stop, the memory guard's stop (memstop) and the data-volume guard's stop
    (``_shut_down``), all through ``request_shutdown``; the uninstall's stop; Ctrl-C and SIGTERM (the launcher's stop, a service
    manager's), and on Windows the in-app stop's SIGINT.
  * DO NOT WAIT:
    - the panic wipe, deliberately: it destroys the key and the data at once, whatever is running, and does not stop the process;
    - the data-volume guard's restart after the drive comes back (``_restart_after_reconnect``: ``os.execve``): no lifespan, no
      stop-all and no disposal, so the ordering holds only because nothing is disposed; work in progress ends mid-unit, rolled back;
    - a SECOND Ctrl-C during uvicorn's connection drain, which makes it skip the lifespan shutdown: the exit hook then closes the
      database to jobs and disposes (``arm_exit_disposal``), without waiting;
    - Windows ending a console session, which ends the process after about 5 s, before the stop-all deadline;
    - the data-volume guard's exits while it waits at boot for the drive (``os._exit`` and ``execve``), before the app has an engine
      or a job.
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
    assert not after_shutdown._REFUSED, dict(
        after_shutdown._REFUSED
    )  # nobody refused by name: it had stopped


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
        main.index("close_for_jobs(running_job_threads())"),
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


def _flushed_but_uncommitted(go: threading.Event, results: list, savepoint: bool):
    def worker(ctx):
        from sqlalchemy import text

        from src.database.session import session_scope
        from src.database.writer import write_gate

        go.wait(10)
        try:
            with session_scope() as s:
                if savepoint:
                    s.begin_nested()
                s.execute(text("INSERT INTO app_state (key, value, updated_at) VALUES ('r689-row', '1', 'x')"))
                results.append("insert:ok")  # flushed: the INSERT reached the driver, inside the open transaction
        except Exception as exc:  # noqa: BLE001 - the test records what happened
            results.append(f"write:{type(exc).__name__}")
        results.append(f"gate-owner:{write_gate._owner}")

    return worker


@pytest.mark.parametrize("savepoint", [False, True])
def test_nothing_a_refused_job_flushed_lands_and_the_gate_is_left_free(registry, monkeypatch, savepoint):
    """The refusal lands AFTER the job's INSERT reached the driver. Without a savepoint the commit is what is refused. With one, the
    session's commit first sends ``RELEASE SAVEPOINT``, and pysqlite's legacy mode (no BEGIN) makes that the real COMMIT: refusing
    only the commit event would let the row land, so the RELEASE is refused as the statement it is (every statement is)."""
    from sqlalchemy import event, text
    from sqlalchemy.engine import Engine

    from src.config import kv_store
    from src.database.session import session_scope

    kv_store.kv_set_json("r689-warm", {"x": 1})  # the table exists
    job_sql: list[str] = []  # the job's statements that reached the driver (this listener runs after the refusal's own)

    def note(conn, cursor, statement, *a):
        if threading.current_thread().name.startswith("bgjob-"):
            job_sql.append(str(statement).split()[0].upper())

    event.listen(Engine, "before_cursor_execute", note)
    refused: list[str] = []
    real_check = after_shutdown.check

    def only_the_commit(what: str) -> None:
        # Let every statement through but the one after the job's INSERT: with a savepoint, the session's commit sends
        # SAVEPOINT, INSERT, then RELEASE (traced), and that RELEASE is what has to be refused.
        on_job = threading.current_thread().name.startswith("bgjob-")
        if on_job and (what == "a commit" or (what == "a statement" and job_sql[-1:] == ["INSERT"])):
            refused.append(what)
            real_check(what)

    monkeypatch.setattr(after_shutdown, "check", only_the_commit)
    monkeypatch.setattr(after_shutdown._LOG, "warning", lambda *a: None)
    go, results = threading.Event(), []
    job = bg.register_job(bg.BackgroundJob("half-writer", "half", _flushed_but_uncommitted(go, results, savepoint), is_writer=True))
    registry.append(job)
    try:
        job.start()
        after_shutdown.close_for_jobs(bg.running_job_threads())
        go.set()
        assert job.join(10)
    finally:
        event.remove(Engine, "before_cursor_execute", note)
    assert results == ["insert:ok", "write:WriteAfterShutdownRefused", "gate-owner:None"], results
    assert job_sql == (["SAVEPOINT", "INSERT"] if savepoint else ["INSERT"]), job_sql
    assert refused == (["a statement"] if savepoint else ["a commit"]), refused
    with session_scope() as s:
        n = s.execute(text("SELECT COUNT(*) FROM app_state WHERE key = 'r689-row'")).scalar()
    assert n == 0


def test_the_manual_collection_pass_and_its_workers_are_refused(monkeypatch):
    """The manual pass stores on its ``oo-collect`` pool; the workers inherit the pass thread's refusal."""
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr(after_shutdown._LOG, "warning", lambda *a: None)
    go, seen = threading.Event(), {}

    def manual_pass():
        go.wait(10)
        mine: list = []
        _try_db(mine)
        seen["pass"] = mine

        def worker(_source, _source_id):
            r: list = []
            _try_db(r)
            return r

        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="oo-collect") as pool:
            run = after_shutdown.inherit(worker)
            seen["workers"] = [f.result() for f in [pool.submit(run, None, i) for i in (1, 2)]]

    t = threading.Thread(target=manual_pass, name="oo-scrape-now")
    t.start()
    after_shutdown.close_for_jobs([])
    go.set()
    t.join(10)
    refused = ["orm:WriteAfterShutdownRefused", "gate:WriteAfterShutdownRefused"]
    assert seen == {"pass": refused, "workers": [refused, refused]}, seen
    # the collector wraps its workers so (source-level: a real pass needs the network)
    runner = (ROOT / "src/scheduler/runner.py").read_text(encoding="utf-8")
    assert "pool.submit(run_worker, s, s.id)" in runner and "run_worker = _inherit_refusal(_worker)" in runner


def test_a_reused_pool_thread_carries_no_refusal_into_later_work(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr(after_shutdown._LOG, "warning", lambda *a: None)
    gate = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        holder: dict = {}

        def linked():
            gate.wait(10)
            r: list = []
            _try_db(r)
            return r

        def parent():
            holder["run"] = after_shutdown.inherit(linked)
            holder["while_linked"] = pool.submit(holder["run"]).result()

        p = threading.Thread(target=parent, name="parent-under-test")
        p.start()
        after_shutdown.refuse_threads([(p, "parent-under-test")])
        gate.set()
        p.join(10)
        assert holder["while_linked"] == ["orm:WriteAfterShutdownRefused", "gate:WriteAfterShutdownRefused"]

        def later():
            r: list = []
            _try_db(r)
            return r

        assert pool.submit(later).result() == ["orm:ok", "gate:ok"]


def test_the_helpers_of_a_refused_job_and_a_job_started_after_the_wait_are_refused(
    registry, monkeypatch
):
    from src.llm.concurrency import run_concurrent

    monkeypatch.setattr(after_shutdown._LOG, "warning", lambda *a: None)
    go, members = threading.Event(), []

    def coordinator(ctx):
        go.wait(10)  # one coordinator turn; its members commit on the pool's threads

        def member(_i):
            r: list = []
            _try_db(r)
            return r

        members.extend(x.value for x in run_concurrent([1, 2], member, max_workers=2))

    job = bg.register_job(bg.BackgroundJob("coord", "coord", coordinator, is_writer=True))
    registry.append(job)
    job.start()
    after_shutdown.close_for_jobs(bg.running_job_threads())
    go.set()
    assert job.join(10)
    assert members == [["orm:WriteAfterShutdownRefused", "gate:WriteAfterShutdownRefused"]] * 2
    # a job started AFTER the database closed (a request still being served) is refused by its thread's name
    late_go, results = threading.Event(), []
    late = bg.register_job(
        bg.BackgroundJob("late-start", "late", _stubborn(late_go, results), is_writer=True)
    )
    registry.append(late)
    late.start()
    late_go.set()
    assert late.join(10)
    assert results == ["orm:WriteAfterShutdownRefused", "gate:WriteAfterShutdownRefused"]


def test_the_helper_pool_inherits_the_refusal(monkeypatch):
    from src.llm.concurrency import run_concurrent

    monkeypatch.setattr(after_shutdown._LOG, "warning", lambda *a: None)
    seen: list = []
    gate = threading.Event()

    def parent_job():
        def member(_i):
            gate.wait(10)
            r: list = []
            _try_db(r)
            return r

        seen.extend(x.value for x in run_concurrent([1, 2], member, max_workers=2))

    t = threading.Thread(target=parent_job, name="parent-under-test")
    t.start()
    after_shutdown.refuse_threads([(t, "parent-under-test")])
    gate.set()
    t.join(10)
    assert seen == [["orm:WriteAfterShutdownRefused", "gate:WriteAfterShutdownRefused"]] * 2


def test_the_exit_hook_disposes_only_when_the_lifespan_did_not(monkeypatch):
    disposed: list = []
    monkeypatch.setattr("src.database.session.dispose_engine", lambda: disposed.append(1))
    after_shutdown.note_lifespan_disposed()
    after_shutdown._dispose_at_exit()
    assert disposed == []
    monkeypatch.setattr(after_shutdown, "_LIFESPAN_DISPOSED", False)
    after_shutdown._dispose_at_exit()
    assert disposed == [1] and after_shutdown.is_closed()


def test_a_write_queued_for_the_gate_is_refused_once_granted(registry, monkeypatch):
    """The gate is checked on entry AND once granted: a job queued behind another writer when the database closed takes nothing."""
    from src.database.writer import write_gate, write_lock

    monkeypatch.setattr(after_shutdown._LOG, "warning", lambda *a: None)
    go, results = threading.Event(), []

    def worker(ctx):
        go.wait(10)
        try:
            with write_lock():
                results.append("wrote")
        except Exception as exc:  # noqa: BLE001 - the test records what happened
            results.append(type(exc).__name__)

    assert write_gate.acquire()
    try:
        job = bg.register_job(bg.BackgroundJob("queued-writer", "queued", worker, is_writer=True))
        registry.append(job)
        job.start()
        go.set()
        deadline = time.monotonic() + 10
        while not write_gate._queue and time.monotonic() < deadline:
            time.sleep(0.005)
        assert write_gate._queue, "the job never queued"
        after_shutdown.close_for_jobs(bg.running_job_threads())
    finally:
        write_gate.release()
    assert job.join(10)
    assert results == ["WriteAfterShutdownRefused"], results
    assert write_gate._owner is None


def test_a_rollback_statement_is_let_through_on_a_refused_thread(monkeypatch):
    monkeypatch.setattr(after_shutdown._LOG, "warning", lambda *a: None)
    seen: dict = {}
    go = threading.Event()

    def refused():
        go.wait(10)
        seen["rollback"] = after_shutdown._on_statement(None, None, "  rollback to savepoint sa_savepoint_1", None, None, False)
        try:
            after_shutdown._on_statement(None, None, "RELEASE SAVEPOINT sa_savepoint_1", None, None, False)
            seen["release"] = "ok"
        except after_shutdown.WriteAfterShutdownRefused:
            seen["release"] = "refused"

    t = threading.Thread(target=refused, name="bgjob-unwinding")
    t.start()
    after_shutdown.close_for_jobs([])
    go.set()
    t.join(10)
    assert seen == {"rollback": None, "release": "refused"}


def test_the_repair_stops_before_its_swap_once_the_database_closed(monkeypatch, tmp_path):
    """Its copy and swap are raw work no event sees: on a job thread once the database closed, ``_swap`` stops as a stop of the app
    (``SalvageStopped``, recorded as stopped), before it disposes or switches anything."""
    from src.database import repair, salvage

    disposed: list = []
    monkeypatch.setattr("src.database.session.dispose_engine", lambda: disposed.append(1))
    monkeypatch.setattr(repair, "_quiet", lambda *_a: disposed.append("quiet"))
    monkeypatch.setattr(after_shutdown._LOG, "warning", lambda *a: None)
    seen: dict = {}
    go = threading.Event()

    def job():
        go.wait(10)
        try:
            repair._swap(tmp_path / "copy.partial", tmp_path / "live.db", "stamp", {})
        except salvage.SalvageStopped:
            seen["outcome"] = "stopped"
        except Exception as exc:  # noqa: BLE001 - the test records what happened
            seen["outcome"] = type(exc).__name__

    t = threading.Thread(target=job, name="bgjob-database-repair")
    t.start()
    after_shutdown.close_for_jobs([])
    go.set()
    t.join(10)
    assert seen == {"outcome": "stopped"} and disposed == [], (seen, disposed)


def test_the_repair_is_stopped_by_its_own_flag_before_the_stop_all_and_waited_for_by_it(registry, monkeypatch):
    """R689 follow-up (2): the repair is a registry job the stop-all cannot cancel (``cancellable=False``: its switch is never cut
    halfway), so it is stopped by its own flag. The lifespan raises that flag (``_stop_database_check``) BEFORE the stop-all, and the
    stop-all then waits for the repair within its one deadline, like any job."""
    from src.database import repair

    assert repair.REPAIR_JOB.cancellable is False
    main = (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    assert "repair.stop()" in main[main.index("def _stop_database_check"):main.index("def _ends_the_check_wait")]
    assert main.index("    _stop_database_check()") < main.index("jobs_left = stop_all_jobs(")

    # A writer that cannot be cancelled and ends only on the repair's own flag, as the copy does at its next batch.
    monkeypatch.setattr(repair, "_CANCEL", threading.Event())
    monkeypatch.setattr(repair, "_ARMED", False)
    started = threading.Event()

    def worker(ctx):
        started.set()
        while not repair._CANCEL.wait(0.02):
            pass
        return {"outcome": "stopped"}

    job = bg.register_job(bg.BackgroundJob("repair-like", "repair-like", worker, is_writer=True, cancellable=False))
    registry.append(job)
    job.start()
    assert started.wait(5)
    assert bg.stop_all_jobs(0.3) == ["repair-like"], "without its own flag, nothing ends it"
    repair.stop()
    assert bg.stop_all_jobs(5.0) == []
