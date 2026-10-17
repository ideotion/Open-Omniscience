"""A long hold names the phase its thread is in, what the thread did over it, and the memory it ended in.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 16 Oct 2026 bundles: holds of 60 to 220 s, a ``SAVEPOINT`` averaging 36.5 s, and ``gate_hold`` events that carried no phase, so
"waiting for a connection" could not be told from "inside the driver" or "in Python". The watchdog's sample now classifies the holder's
innermost frame; the release of a long hold reads the holder thread's CPU time and kernel counters over the whole of it and the
machine's available memory and swap.
"""

from __future__ import annotations

import threading
import time

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import QueuePool

from src.database import writer
from src.monitoring import storage_events as se
from src.monitoring import thread_usage


@pytest.fixture
def journal(tmp_path, monkeypatch):
    path = tmp_path / "storage_events.json"
    monkeypatch.setattr(se, "_path", lambda: path)
    monkeypatch.setattr(se, "FLUSH_DELAY_S", 0.02)
    monkeypatch.setattr(writer, "_JOURNALED_HOLD", None)
    monkeypatch.setattr(writer, "HOLD_RECORD_S", 0.05)
    monkeypatch.setenv("OO_WRITE_GATE_WATCHDOG", "0")
    # The env var only stops a watchdog from STARTING. The process's own one (armed by the first hold of the whole run, a tick every 15 s) shares
    # the module's gate, and a tick of its that lands in a hold these tests count adds a sample: the 17 Oct battery read {"execute": 3} for two
    # ticks, about 8 per cent of runs (1.2 s of 15), and a 0.5 s interval makes it fail every time. So only THIS thread ticks here.
    me = threading.get_ident()
    real_tick, real_look = writer.watchdog_tick, writer.sample_holder_state
    monkeypatch.setattr(writer, "watchdog_tick", lambda g, w: real_tick(g, w) if threading.get_ident() == me else w)
    monkeypatch.setattr(writer, "sample_holder_state", lambda g, now=None: real_look(g, now) if threading.get_ident() == me else False)
    writer._PHASE_SAMPLES.clear()
    se.reset_for_tests()
    yield path
    se.reset_for_tests()


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'phase.db'}", poolclass=QueuePool, pool_size=1, max_overflow=0, pool_timeout=20)

    @event.listens_for(eng, "connect")
    def _functions(dbapi, _record):
        dbapi.create_function("pause", 1, lambda s: time.sleep(s) or 1)

    yield eng
    eng.dispose()


class _Holder:
    """A thread that takes the write gate, runs ``body`` while holding it, and gives it back when told."""

    def __init__(self, body):
        self.started = threading.Event()
        self.finish = threading.Event()
        self.thread = threading.Thread(target=self._run, args=(body,), name="oo-phase-holder")

    def _run(self, body):
        with writer.write_lock():
            self.started.set()
            body(self.finish)

    def __enter__(self):
        self.thread.start()
        assert self.started.wait(5)
        time.sleep(0.25)  # into the body's wait
        return self

    def __exit__(self, *exc):
        self.finish.set()
        self.thread.join(15)
        assert not self.thread.is_alive()


def test_a_holder_waiting_for_a_pooled_connection_is_in_the_pool_wait_phase(engine):
    hog = engine.connect()  # the pool's only connection is out

    def body(finish):
        c = engine.connect()  # blocks inside the pool
        c.close()

    holder = _Holder(body)
    try:
        with holder:
            assert writer.thread_phase(holder.thread.ident) == "pool-wait"
            hog.close()  # frees the pool, the holder's connect() returns
    finally:
        hog.close()


def test_a_holder_inside_a_statement_is_in_the_execute_phase(engine):
    def body(finish):
        with engine.connect() as c:
            c.exec_driver_sql("SELECT pause(0.8)").fetchall()

    with _Holder(body) as holder:
        assert writer.thread_phase(holder.thread.ident) == "execute"


def test_a_holder_working_in_python_is_in_the_python_phase():
    def body(finish):
        finish.wait(5)  # no SQLAlchemy frame on its stack

    with _Holder(body) as holder:
        assert writer.thread_phase(holder.thread.ident) == "python"


def test_a_thread_that_is_gone_or_unknown_has_no_phase():
    assert writer.thread_phase(None) is None
    assert writer.thread_phase(2**62) is None


def test_every_name_the_phase_table_relies_on_still_exists_in_the_libraries_installed():
    """A library that renames one of these makes the phase 'python' rather than a wrong one; this makes the rename a failing test."""
    import importlib

    from src.database import pool_reserve

    for (module, function), phase in writer._PHASE_AT.items():
        mod = importlib.import_module(module)
        found = [
            obj
            for owner in [mod, *[v for v in vars(mod).values() if isinstance(v, type)]]
            for name, obj in vars(owner).items()
            if name == function and callable(obj) and getattr(obj, "__module__", None) == module
        ]
        assert found, f"{module}.{function} ({phase}) no longer exists: the phase table is stale"
    assert pool_reserve._Slots.acquire.__code__.co_name == "acquire"


def _gate_hold_events():
    return se.diagnostics_member(10_000_000)["kinds"]["gate_hold"]["events"]


def test_the_watchdog_sample_records_the_phase_and_counts_the_samples_of_one_hold(journal, engine):
    def body(finish):
        with engine.connect() as c:
            c.exec_driver_sql("SELECT pause(1.2)").fetchall()

    gate = writer.write_gate
    warned = None
    with _Holder(body):
        warned = writer.watchdog_tick(gate, warned)
        warned = writer.watchdog_tick(gate, warned)
    ev = _gate_hold_events()
    assert len(ev) == 1
    assert ev[0]["phase"] == "execute" and ev[0]["phase_samples"] == {"execute": 2}, ev[0]
    assert ev[0]["holder"] == "oo-phase-holder"


def test_a_new_hold_starts_its_samples_from_none(journal):
    gate = writer.write_gate
    for _ in range(2):
        with _Holder(lambda finish: finish.wait(5)):
            writer.watchdog_tick(gate, None)
            samples = dict(writer._PHASE_SAMPLES)
        assert samples == {"python": 1}, samples


def test_the_end_of_a_long_hold_carries_the_holders_cpu_and_the_memory(journal, monkeypatch):
    """A hold that sleeps has little CPU against its seconds; one that burns has about as much CPU as seconds. Both are read on the holder."""
    monkeypatch.setattr(writer, "_memory_numbers", lambda: {"mem_available_mb": 4321, "swap_used_mb": 987})

    def sleeper(finish):
        time.sleep(0.4)

    def burner(finish):
        t0 = time.thread_time()
        while time.thread_time() - t0 < 0.4:
            pass

    for body in (sleeper, burner):
        h = _Holder(body)
        h.thread.start()
        assert h.started.wait(5)
        h.thread.join(10)
    slept, burned = sorted(_gate_hold_events(), key=lambda e: e.get("cpu_ms", 0))
    assert slept["mem_available_mb"] == 4321 and slept["swap_used_mb"] == 987
    assert slept["cpu_ms"] < 150 and slept["seconds"] >= 0.4, slept
    assert burned["cpu_ms"] >= 380 and burned["seconds"] >= 0.4, burned
    if thread_usage.RUSAGE_THREAD is not None:
        assert slept["nvcsw"] >= 1


def test_a_figure_that_cannot_be_read_is_absent_from_the_hold_record_never_zero(journal, monkeypatch):
    import src.database.writer as w

    monkeypatch.setattr(w.thread_usage, "RUSAGE_THREAD", None)
    monkeypatch.setattr(w, "_memory_numbers", lambda: {})
    h = _Holder(lambda finish: time.sleep(0.2))
    h.thread.start()
    assert h.started.wait(5)
    h.thread.join(10)
    (ev,) = _gate_hold_events()
    assert "cpu_ms" in ev and not ({"nvcsw", "nivcsw", "majflt", "inblock", "mem_available_mb", "swap_used_mb"} & set(ev)), ev


def test_the_memory_reader_gives_whole_megabytes_or_nothing():
    out = writer._memory_numbers()
    assert set(out) <= {"mem_available_mb", "swap_used_mb"}
    assert all(isinstance(v, int) and v >= 0 for v in out.values())
