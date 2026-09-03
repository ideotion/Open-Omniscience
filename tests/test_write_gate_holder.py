"""
S2.5 + S2.6 (2026-09-02 crash analysis): bound the gate, and name what holds it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The field's 6,236-second gate wait and its three-hour WAL growth both arrived
with no name attached, and the pass tail could wait on the gate forever -- so
``record_run``, which sits BELOW the checkpoint, was never reached and a stalled
pass left no record of itself at all.

Every test here drives the REAL ``WriterGate``/``write_lock``/``checkpoint_wal``
rather than a lookalike, and every guard has its negative twin: an instrument
that names an innocent thread, or a bound that gives up on a gate it could have
had, is worse than the gap it closes.
"""

from __future__ import annotations

import threading
import time

import pytest
from sqlalchemy import create_engine, event, text

from src.database.writer import (
    WriteGateBusy,
    WriterGate,
    watchdog_tick,
    write_lock,
)


def _wait_until(pred, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.005)
    return pred()


class _Holder:
    """Holds a gate from a NAMED thread until told to let go."""

    def __init__(self, gate: WriterGate, name: str = "field-writer") -> None:
        self.gate = gate
        self.taken = threading.Event()
        self.let_go = threading.Event()
        self.thread = threading.Thread(target=self._run, name=name, daemon=True)

    def _run(self) -> None:
        self.gate.acquire()
        self.taken.set()
        self.let_go.wait(10)
        self.gate.release()

    def __enter__(self) -> _Holder:
        self.thread.start()
        assert self.taken.wait(3), "the holder thread never took the gate"
        return self

    def __exit__(self, *_exc) -> None:
        self.let_go.set()
        self.thread.join(5)
        assert not self.thread.is_alive(), "the holder thread never released"


# --- S2.5: the bound ------------------------------------------------------- #


def test_a_bounded_acquire_gives_up_and_says_so():
    gate = WriterGate()
    with _Holder(gate):
        t0 = time.monotonic()
        assert gate.acquire(timeout=0.15) is False
        assert time.monotonic() - t0 < 2.0, "the bound did not bound"
    assert gate.stats()["timeouts"] == 1


def test_an_unbounded_acquire_still_waits_for_its_turn():
    """The negative twin. A bound that made every acquire give up early would
    turn a correct wait into a skipped write -- the data-loss direction."""
    gate = WriterGate()
    holder = _Holder(gate)
    holder.__enter__()
    got: list[bool] = []

    def waiter() -> None:
        got.append(gate.acquire())  # no timeout: must wait, not give up
        gate.release()

    t = threading.Thread(target=waiter, name="patient", daemon=True)
    t.start()
    assert _wait_until(lambda: gate.stats()["queued"] == 1)
    time.sleep(0.2)
    assert got == [], "an unbounded acquire returned while the gate was held"
    holder.__exit__()
    t.join(5)
    assert got == [True]
    assert gate.stats()["timeouts"] == 0


def test_write_lock_raises_write_gate_busy_rather_than_writing_ungated():
    from src.database.writer import write_gate

    with _Holder(write_gate):
        with pytest.raises(WriteGateBusy) as exc:
            with write_lock(timeout=0.1):
                pytest.fail("write_lock entered a gate it never got")
    # The refusal names WHO, or it is just another anonymous timeout.
    assert "field-writer" in str(exc.value)


def test_checkpoint_wal_records_an_honest_skip_when_the_gate_is_busy(monkeypatch, tmp_path):
    """The pass tail must return, with the skip visible, so record_run is reached."""
    from src.database.writer import write_gate
    from src.scheduler import hygiene

    monkeypatch.setenv("OO_CKPT_GATE_TIMEOUT_S", "0.1")
    monkeypatch.setattr(hygiene, "_LAST_CKPT_MONO", None, raising=False)
    db = tmp_path / "ckpt.db"
    eng = create_engine(f"sqlite:///{db}")
    with eng.connect() as con:
        con.execute(text("PRAGMA journal_mode=WAL"))
        con.execute(text("CREATE TABLE t (a INTEGER)"))
        con.commit()

    with _Holder(write_gate):
        t0 = time.monotonic()
        out = hygiene.checkpoint_wal(engine=eng, force=True)
        elapsed = time.monotonic() - t0

    assert out is not None, "a busy gate must not read as 'not due' (None)"
    assert out["skipped"] == "gate busy"
    assert out["waited_s"] == pytest.approx(0.1)
    assert "field-writer" in out["detail"]
    assert elapsed < 3.0
    eng.dispose()


def test_checkpoint_wal_still_checkpoints_when_the_gate_is_free(monkeypatch, tmp_path):
    """The negative twin: a skip that fired unconditionally would silently stop
    every checkpoint, and the WAL growth this exists to bound would be worse."""
    from src.scheduler import hygiene

    monkeypatch.setenv("OO_CKPT_GATE_TIMEOUT_S", "5")
    monkeypatch.setattr(hygiene, "_LAST_CKPT_MONO", None, raising=False)
    db = tmp_path / "free.db"
    eng = create_engine(f"sqlite:///{db}")
    with eng.connect() as con:
        con.execute(text("PRAGMA journal_mode=WAL"))
        con.execute(text("CREATE TABLE t (a INTEGER)"))
        con.commit()

    out = hygiene.checkpoint_wal(engine=eng, force=True)
    assert out is not None
    assert "skipped" not in out, out
    assert "checkpointed_frames" in out
    eng.dispose()


# --- S2.6 (c): FIFO handoff ------------------------------------------------ #


def test_a_free_gate_is_not_granted_while_someone_is_queued():
    """The load-bearing half of FIFO: the fast path must REFUSE a free gate when
    a ticket is already queued. Without it a looping re-acquirer takes the gate
    the instant it releases its own, while the queued waiter is still being
    woken -- which is how ``max_wait_s`` comes to measure starvation instead of
    a hold, and why the field's 6,236 s figure could not be read as one write."""
    gate = WriterGate()
    with gate._cond:
        # Park a waiter the way acquire() does -- its OWN condition over the
        # gate's lock. Any hand-built stand-in risks manufacturing a state the
        # code cannot produce, which reads exactly like the guard being absent
        # (an earlier draft appended a bare 0 that collided with the fresh
        # gate's own first ticket, so the acquirer read ITSELF as the head).
        gate._queue.append(threading.Condition(gate._lock))
    try:
        assert gate.acquire(timeout=0.15) is False
    finally:
        with gate._cond:
            gate._queue.clear()


def test_waiters_are_served_in_arrival_order():
    gate = WriterGate()
    order: list[str] = []
    order_lock = threading.Lock()

    def waiter(tag: str) -> None:
        gate.acquire()
        with order_lock:
            order.append(tag)
        gate.release()

    holder = _Holder(gate)
    holder.__enter__()
    threads = []
    for tag in ("first", "second", "third"):
        t = threading.Thread(target=waiter, args=(tag,), name=tag, daemon=True)
        t.start()
        threads.append(t)
        assert _wait_until(lambda n=len(threads): gate.stats()["queued"] == n), (
            f"{tag} never queued"
        )
    holder.__exit__()
    for t in threads:
        t.join(5)
    assert order == ["first", "second", "third"]


# --- S2.6 (a): the holder has a name --------------------------------------- #


def test_stats_names_the_current_holder_and_its_age():
    gate = WriterGate()
    free = gate.stats()
    assert free["holder"] is None
    assert free["held_for_s"] is None, "a free gate must report absence, never 0"
    with _Holder(gate, name="oo-import"):
        time.sleep(0.05)
        s = gate.stats()
        assert s["held"] is True
        assert s["holder"] == "oo-import"
        assert s["held_for_s"] is not None and s["held_for_s"] > 0.0


def test_the_peak_hold_keeps_its_holder_after_release():
    """A peak with no name cannot be acted on -- that is the whole finding."""
    gate = WriterGate()
    with _Holder(gate, name="oo-slow-merge"):
        time.sleep(0.12)
    s = gate.stats()
    assert s["holder"] is None, "a released gate must not keep naming a thread"
    assert s["held_for_s"] is None
    assert s["max_hold_s"] >= 0.1
    assert s["max_hold_holder"] == "oo-slow-merge"


def test_the_gate_stats_ride_the_collect_perf_sample():
    """S2.6 asks for the holder fields 'in every collect_perf sample'. They are,
    by construction -- collect_perf already samples write_gate_stats()."""
    from src.monitoring.collect_perf import _writer_stats

    assert set(_writer_stats()) >= {"holder", "held_for_s", "max_hold_s", "max_hold_holder"}


# --- S2.6 (a): the watchdog ------------------------------------------------ #


def test_the_watchdog_warns_once_per_hold_and_names_the_holder(monkeypatch, caplog):
    monkeypatch.setenv("OO_WRITE_GATE_WARN_S", "0.05")
    gate = WriterGate()
    with _Holder(gate, name="oo-wal-pinner"):
        time.sleep(0.1)
        with caplog.at_level("WARNING", logger="database.writer"):
            first = watchdog_tick(gate, None)
            again = watchdog_tick(gate, first)
    warnings = [r for r in caplog.records if "write gate held" in r.getMessage()]
    assert len(warnings) == 1, "a watchdog that warns per SAMPLE is a log storm"
    assert "oo-wal-pinner" in warnings[0].getMessage()
    assert again == first, "the second tick started a new hold that never happened"


def test_the_watchdog_is_silent_below_the_threshold_and_on_a_free_gate(monkeypatch, caplog):
    """The negative twin: a watchdog that warned about every hold would name
    every ordinary write and teach the operator to ignore it."""
    monkeypatch.setenv("OO_WRITE_GATE_WARN_S", "30")
    gate = WriterGate()
    with caplog.at_level("WARNING", logger="database.writer"):
        assert watchdog_tick(gate, None) is None  # free
        with _Holder(gate, name="oo-quick"):
            assert watchdog_tick(gate, None) is None  # held, but not long
    assert [r for r in caplog.records if "write gate held" in r.getMessage()] == []


def test_the_watchdog_is_armed_by_the_production_write_path(tmp_path):
    """A real ORM write arms it -- the property, not the mechanism.

    RE-ANCHORED (2026-09-03). This used to assert ``_WATCHDOG_STARTED is True``
    straight after importing the session module, on the premise that
    register_write_gate() started the thread. That premise was a DEFECT (an
    import must not spawn a monitoring thread; see the placement pair below),
    and the assertion was passing vacuously anyway -- an earlier test in this
    file had already taken the gate and armed it, so it held whatever the
    wiring did.

    What actually matters is that the watchdog exists by the time a hold could
    become long, so this drives the session-event path end to end: no thread on
    import, a thread once a write has taken the gate. Subprocess, because
    "armed yet?" is process-global.
    """
    import subprocess
    import sys

    code = (
        "import os, threading\n"
        f"os.environ['OO_DATA_DIR'] = {str(tmp_path)!r}\n"
        "os.environ['OO_DB_PLAINTEXT'] = '1'\n"
        "def live():\n"
        "    return sorted(t.name for t in threading.enumerate() if 'write-gate-watchdog' in t.name)\n"
        "import src.database.session as S\n"
        "print('ON_IMPORT', live())\n"
        "S.init_db()\n"
        "from src.database.models import Source\n"
        "s = S.SessionLocal()\n"
        "s.add(Source(name='w', domain='watchdog.example', country='us'))\n"
        "s.commit(); s.close()\n"
        "print('AFTER_WRITE', live())\n"
    )
    r = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=180
    )
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "ON_IMPORT []" in r.stdout, r.stdout
    assert "AFTER_WRITE ['oo-write-gate-watchdog']" in r.stdout, (
        "a real ORM write did not arm the watchdog: a long hold would go unnamed\n"
        + r.stdout
    )


def test_the_watchdog_can_be_turned_off(monkeypatch):
    from src.database import writer

    monkeypatch.setenv("OO_WRITE_GATE_WATCHDOG", "0")
    monkeypatch.setattr(writer, "_WATCHDOG_STARTED", False)
    assert writer.start_write_gate_watchdog() is False
    assert writer._WATCHDOG_STARTED is False


# --- S2.6 (b): the pooled-connection register ------------------------------ #


def test_a_checked_out_connection_is_listed_with_its_age(tmp_path):
    from src.database import pool_watch

    eng = create_engine(f"sqlite:///{tmp_path / 'pool.db'}")
    event.listen(eng, "checkout", pool_watch._on_checkout)
    event.listen(eng, "checkin", pool_watch._on_checkin)
    pool_watch._reset_for_tests()
    try:
        with eng.connect() as con:
            con.execute(text("SELECT 1"))
            rows = pool_watch.checked_out()
            assert len(rows) == 1, rows
            assert rows[0]["thread"] == threading.current_thread().name
            assert rows[0]["age_s"] >= 0.0
    finally:
        pool_watch._reset_for_tests()
        eng.dispose()


def test_a_returned_connection_is_not_listed(tmp_path):
    """The negative twin, and the reason this instrument is trustworthy: an
    over-eager register would keep naming whichever thread ran last, so every
    reading would accuse an innocent one."""
    from src.database import pool_watch

    eng = create_engine(f"sqlite:///{tmp_path / 'pool2.db'}")
    event.listen(eng, "checkout", pool_watch._on_checkout)
    event.listen(eng, "checkin", pool_watch._on_checkin)
    pool_watch._reset_for_tests()
    try:
        with eng.connect() as con:
            con.execute(text("SELECT 1"))
        assert pool_watch.checked_out() == []
    finally:
        pool_watch._reset_for_tests()
        eng.dispose()


def test_the_pool_listeners_are_attached_to_the_app_engine():
    """Wiring guard: without it the two tests above pass against listeners they
    attach themselves, while production records nothing at all."""
    from src.database import pool_watch
    from src.database.session import engine

    assert event.contains(engine, "checkout", pool_watch._on_checkout)
    assert event.contains(engine, "checkin", pool_watch._on_checkin)


def test_the_write_gate_report_names_both_pins():
    from src.api.diagnostics import write_gate_report

    out = write_gate_report()
    assert set(out) >= {"gate", "pool", "method", "caveat"}
    assert "holder" in out["gate"]
    assert isinstance(out["pool"], list)


def test_a_refused_checkpoint_is_not_reported_as_the_last_real_one(monkeypatch):
    """A gate-busy skip is a dict too, so the storage diagnostic would have read
    it as 'the most recent REAL checkpoint measurement' -- with no busy flag and
    no wal_bytes_after to contradict it. The two are opposite findings: a WAL
    nobody could reclaim because a WRITER held the gate, versus one a READER
    pinned (busy=1); a reader who cannot tell them apart looks in the wrong
    subsystem."""
    from src.monitoring import storage
    from src.scheduler import runlog

    runs = [
        {"started_at": "2026-09-03T10:00:00",
         "hygiene": {"wal_checkpoint": {"skipped": "gate busy", "waited_s": 30.0}}},
        {"started_at": "2026-09-03T09:00:00",
         "hygiene": {"wal_checkpoint": {"busy": 0, "checkpointed_frames": 12}}},
    ]
    monkeypatch.setattr(runlog, "recent_runs", lambda limit=50: runs)

    real = storage._last_wal_checkpoint()
    assert real is not None and real["busy"] == 0, real
    assert "skipped" not in real

    skip = storage._last_wal_checkpoint_skip()
    assert skip is not None and skip["skipped"] == "gate busy"
    assert skip["run_at"] == "2026-09-03T10:00:00"


def test_a_run_log_with_only_refusals_reports_no_real_checkpoint(monkeypatch):
    """The negative twin: absence stated, never a fabricated 'a checkpoint ran'."""
    from src.monitoring import storage
    from src.scheduler import runlog

    monkeypatch.setattr(
        runlog,
        "recent_runs",
        lambda limit=50: [{"hygiene": {"wal_checkpoint": {"skipped": "gate busy"}}}],
    )
    assert storage._last_wal_checkpoint() is None
    assert storage._last_wal_checkpoint_skip() is not None


# ---------------------------------------------------------------------------
# The watchdog arms on the first ACQUIRE, never at import.
#
# Caught by tests/test_database_session.py::test_import_has_no_side_effects, and
# worth its own named pair here: the first cut started the thread from
# register_write_gate(), whose docstring said "rather than at import" -- while
# session.py CALLS that function at module level, so importing the models
# spawned a monitoring thread. The docstring asserted the property; the code did
# not have it.
#
# Both directions, because either one alone passes against a broken build: a
# watchdog deleted outright satisfies "import starts no thread", and a watchdog
# started at import satisfies "it is running after an acquire".
#
# Subprocesses, because "has it started yet" is process-global: any earlier test
# in the session may already have taken the gate and armed it.
# ---------------------------------------------------------------------------


def _watchdog_probe(body: str, tmp_path) -> str:
    """Run BODY in a fresh interpreter; return its stdout."""
    import subprocess
    import sys

    code = (
        "import os, threading\n"
        f"os.environ['OO_DATA_DIR'] = {str(tmp_path)!r}\n"
        "def live():\n"
        "    return sorted(t.name for t in threading.enumerate() if 'write-gate-watchdog' in t.name)\n"
        f"{body}\n"
    )
    r = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert r.returncode == 0, f"probe failed:\n{r.stdout}\n{r.stderr}"
    return r.stdout


def test_importing_the_models_starts_no_watchdog_thread(tmp_path):
    """Importing must be inert: no thread, however the gate is wired."""
    out = _watchdog_probe(
        "import src.database.models  # noqa: F401\n"
        "print('THREADS', live())",
        tmp_path,
    )
    assert "THREADS []" in out, out


def test_the_watchdog_arms_on_the_first_acquire(tmp_path):
    """The twin: it must still exist by the time a hold could be long."""
    out = _watchdog_probe(
        "from src.database.writer import write_gate\n"
        "print('BEFORE', live())\n"
        "write_gate.acquire()\n"
        "write_gate.release()\n"
        "print('AFTER', live())",
        tmp_path,
    )
    assert "BEFORE []" in out, out
    assert "AFTER ['oo-write-gate-watchdog']" in out, out


def test_the_environment_is_consulted_once_not_per_write(tmp_path):
    """Disabled stays disabled without paying an env read on every acquire.

    _WATCHDOG_STARTED remains False forever when the watchdog is off, so keying
    the hot path on it would re-read the environment and re-take a lock for
    every single write. The separate 'considered' flag is what makes the
    disabled case one-shot too.
    """
    out = _watchdog_probe(
        "os.environ['OO_WRITE_GATE_WATCHDOG'] = '0'\n"
        "import src.database.writer as w\n"
        "reads = []\n"
        "real = os.environ.get\n"
        "os.environ.get = lambda k, d=None: (reads.append(k) if k == 'OO_WRITE_GATE_WATCHDOG' else None) or real(k, d)\n"
        "for _ in range(50):\n"
        "    w.write_gate.acquire(); w.write_gate.release()\n"
        "os.environ.get = real\n"
        "print('ENV_READS', len(reads))\n"
        "print('THREADS', live())",
        tmp_path,
    )
    assert "ENV_READS 1" in out, out
    assert "THREADS []" in out, out
