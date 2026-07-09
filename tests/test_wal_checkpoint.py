"""
P0.3 E4 — WAL checkpoint hygiene between passes.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Under multi-day continuous writes SQLite's -wal file can grow without bound
(a runaway -wal is a named suspect in the field's unexplained ~120 GB data
folder). The hygiene step runs ``PRAGMA wal_checkpoint(TRUNCATE)`` between
passes — through ``write_lock()`` so it can NEVER run concurrently with a
gated writer (the negative-space skeptic pinned below) — and reports the
MEASURED effect (wal bytes before/after, frames, busy) instead of assuming it.
An active reader makes TRUNCATE return an honest partial result (busy=1),
never an exception.
"""

from __future__ import annotations

import threading
import time

from sqlalchemy import create_engine

from src.scheduler import hygiene
from src.scheduler.hygiene import checkpoint_wal


def _wal_engine(tmp_path, name="ckpt.db"):
    """A REAL file-backed WAL database, isolated from the shared store."""
    db = tmp_path / name
    eng = create_engine(f"sqlite:///{db}", future=True)
    with eng.connect() as c:
        c.exec_driver_sql("PRAGMA journal_mode=WAL")
        c.exec_driver_sql("CREATE TABLE t(x)")
        for _ in range(50):
            c.exec_driver_sql("INSERT INTO t VALUES (randomblob(4096))")
        c.commit()
    return eng, db


def _fresh_cadence(monkeypatch):
    """Reset the module's min-interval memory so each test decides for itself."""
    monkeypatch.setattr(hygiene, "_LAST_CKPT_MONO", None)


def test_checkpoint_truncates_the_wal_and_reports_measured_bytes(tmp_path, monkeypatch):
    _fresh_cadence(monkeypatch)
    eng, db = _wal_engine(tmp_path)
    wal = db.with_name(db.name + "-wal")
    assert wal.stat().st_size > 0  # the writes above grew a real WAL

    rec = checkpoint_wal(engine=eng, force=True)
    assert rec is not None
    assert rec["busy"] == 0
    assert rec["wal_bytes_before"] > 0
    assert rec["wal_bytes_after"] == 0
    assert wal.stat().st_size == 0  # measured, not assumed
    assert rec["duration_ms"] >= 0
    eng.dispose()


def test_min_interval_gates_repeat_checkpoints_and_force_overrides(tmp_path, monkeypatch):
    _fresh_cadence(monkeypatch)
    monkeypatch.setenv("OO_WAL_CHECKPOINT_MIN_S", "3600")
    eng, _db = _wal_engine(tmp_path)
    assert checkpoint_wal(engine=eng) is not None  # first run: due
    assert checkpoint_wal(engine=eng) is None  # within the interval: skipped
    assert checkpoint_wal(engine=eng, force=True) is not None  # explicit force
    eng.dispose()


def test_active_reader_yields_honest_partial_result_not_an_exception(tmp_path, monkeypatch):
    _fresh_cadence(monkeypatch)
    eng, db = _wal_engine(tmp_path)
    # A reader holding a snapshot pins the WAL: TRUNCATE cannot finish.
    import sqlite3

    reader = sqlite3.connect(str(db))
    reader.execute("PRAGMA busy_timeout=50")
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM t").fetchone()
    # Grow the WAL again so there is something the checkpoint cannot flush.
    with eng.connect() as c:
        c.exec_driver_sql("INSERT INTO t VALUES (1)")
        c.commit()
    try:
        rec = checkpoint_wal(engine=eng, force=True, busy_timeout_ms=100)
        assert rec is not None
        assert rec["busy"] == 1  # the honest partial verdict, never a crash
    finally:
        reader.rollback()
        reader.close()
        eng.dispose()


def test_checkpoint_waits_for_the_write_gate_never_runs_beside_a_writer(tmp_path, monkeypatch):
    """The skeptic: 'checkpoint runs while a worker holds the gate?' — it
    can't: it takes write_lock(), so it BLOCKS until the writer releases."""
    _fresh_cadence(monkeypatch)
    from src.database.writer import write_gate

    eng, _db = _wal_engine(tmp_path)
    release = threading.Event()
    held = threading.Event()

    def _writer():
        write_gate.acquire()
        held.set()
        try:
            release.wait(5.0)
        finally:
            write_gate.release()

    t = threading.Thread(target=_writer)
    t.start()
    held.wait(5.0)
    t0 = time.monotonic()
    result: dict = {}

    def _ckpt():
        result["rec"] = checkpoint_wal(engine=eng, force=True)
        result["elapsed"] = time.monotonic() - t0

    t2 = threading.Thread(target=_ckpt)
    t2.start()
    time.sleep(0.3)
    assert "rec" not in result  # still queued behind the writer
    release.set()
    t2.join(10.0)
    t.join(5.0)
    assert result["rec"] is not None
    assert result["elapsed"] >= 0.3  # it genuinely waited for the gate
    eng.dispose()


def test_disabled_env_and_non_sqlite_return_none(tmp_path, monkeypatch):
    _fresh_cadence(monkeypatch)
    eng, _db = _wal_engine(tmp_path)
    monkeypatch.setenv("OO_WAL_CHECKPOINT", "0")
    assert checkpoint_wal(engine=eng, force=True) is None
    monkeypatch.delenv("OO_WAL_CHECKPOINT")
    # A non-SQLite engine is skipped from its URL alone — never connected
    # (an engine-shaped stub: the backend check must be the first gate).
    from types import SimpleNamespace

    from sqlalchemy.engine import make_url

    pg = SimpleNamespace(url=make_url("postgresql://nobody@nowhere/db"))
    assert checkpoint_wal(engine=pg, force=True) is None
    eng.dispose()


def test_run_pass_hygiene_carries_the_checkpoint_record(monkeypatch):
    """The composed between-pass step reports what the checkpoint measured
    (against the app's own engine — a checkpoint mutates no data)."""
    monkeypatch.setattr(hygiene, "_LAST_CKPT_MONO", None)
    out = hygiene.run_pass_hygiene()
    assert out is not None
    assert "wal_checkpoint" in out  # present (a record, or None when skipped)
