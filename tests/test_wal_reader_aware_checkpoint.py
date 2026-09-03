"""
S4.1 (2026-09-02 crash analysis): a pinned WAL costs the gate milliseconds.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``checkpoint_wal`` ran TRUNCATE with a 5 s busy allowance while holding the write
gate. Against a WAL pinned by a reader, TRUNCATE calls the busy handler until the
reader finishes, so the gate was held the full allowance at every pass boundary
and the WAL did not move.

Measured on the real PRAGMAs (4.1 MB WAL, 423 frames, a reader with an
unexhausted cursor):

    TRUNCATE busy_timeout=5000 -> 5012.4 ms, busy=1, wal UNCHANGED
    PASSIVE  busy_timeout=5000 ->    0.0 ms, busy=0, 423/423 backfilled
    TRUNCATE busy_timeout=0    ->    0.0 ms, busy=1, wal UNCHANGED
    (reader closed) TRUNCATE   ->    0.8 ms, busy=0, wal 0

Two things follow, and the second REFUTES the step this slice was briefed with.
The whole hold was the busy handler, so not waiting is the fix. And gating the
TRUNCATE on ``log_frames == checkpointed_frames`` after the passive step does NOT
mean "nothing is pinned": a reader whose snapshot sits at the current end of the
WAL satisfies it exactly while still pinning the file. That predicate is asserted
here as FALSE so it is not reintroduced as an optimisation.
"""

from __future__ import annotations

import sqlite3
import time

from sqlalchemy import create_engine, text

from src.scheduler.hygiene import checkpoint_wal


def _wal_engine(tmp_path, monkeypatch, *, rows=3000):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OO_WAL_CHECKPOINT_BUSY_MS", raising=False)
    db = tmp_path / "w.db"
    eng = create_engine(f"sqlite:///{db}")
    with eng.begin() as c:
        c.execute(text("PRAGMA journal_mode=WAL"))
        c.execute(text("CREATE TABLE t(a INTEGER PRIMARY KEY, b TEXT)"))
        for _ in range(rows):
            c.execute(text("INSERT INTO t(b) VALUES (:b)"), {"b": "x" * 200})
    wal = tmp_path / "w.db-wal"
    assert wal.exists() and wal.stat().st_size > 100_000, "the fixture built no WAL"
    return eng, db, wal


def test_a_pinned_wal_costs_the_gate_milliseconds_not_seconds(tmp_path, monkeypatch):
    """The brief's acceptance. The reader keeps an unexhausted cursor, which is
    what holds the read transaction open and pins the file."""
    eng, db, wal = _wal_engine(tmp_path, monkeypatch)
    reader = sqlite3.connect(db)
    cur = reader.execute("SELECT a, b FROM t")
    cur.fetchone()  # snapshot now held
    try:
        t0 = time.monotonic()
        rec = checkpoint_wal(engine=eng, force=True)
        held_ms = (time.monotonic() - t0) * 1000.0
    finally:
        cur.fetchall()
        reader.close()

    assert rec is not None
    assert rec["busy"] == 1, "the fixture did not actually pin the WAL"
    assert held_ms < 500, (
        f"the gate was held {held_ms:.1f} ms by a pinned checkpoint (was ~5000)"
    )
    # A passive backfill DID happen, which is what bounds growth while pinned.
    assert rec["passive"]["checkpointed_frames"] > 0, (
        "nothing was backfilled, so the pinned boundary achieved nothing at all"
    )
    assert rec["passive"]["busy"] == 0, "PASSIVE reported busy — it never blocks"


def test_an_unpinned_wal_is_still_truncated_to_zero(tmp_path, monkeypatch):
    """The twin, and the one a not-waiting fix could plausibly break: with nothing
    pinning the file, the checkpoint must still do its actual job."""
    eng, db, wal = _wal_engine(tmp_path, monkeypatch)
    rec = checkpoint_wal(engine=eng, force=True)
    assert rec is not None
    assert rec["busy"] == 0
    assert rec["wal_bytes_before"] > 0
    assert rec["wal_bytes_after"] == 0, "the WAL was not reclaimed"


def test_after_the_reader_closes_the_next_call_reclaims_the_file(tmp_path, monkeypatch):
    eng, db, wal = _wal_engine(tmp_path, monkeypatch)
    reader = sqlite3.connect(db)
    cur = reader.execute("SELECT a, b FROM t")
    cur.fetchone()
    first = checkpoint_wal(engine=eng, force=True)
    assert first is not None and first["busy"] == 1
    cur.fetchall()
    reader.close()
    second = checkpoint_wal(engine=eng, force=True)
    assert second is not None
    assert second["busy"] == 0
    assert second["wal_bytes_after"] == 0


def test_the_briefs_pinned_predicate_is_false_and_must_not_be_used(tmp_path, monkeypatch):
    """REFUTATION, pinned so it is not reintroduced. `log_frames ==
    checkpointed_frames` after the passive step reads as "nothing is pinned" and
    is not: a reader at the current end of the WAL satisfies it while pinning."""
    eng, db, wal = _wal_engine(tmp_path, monkeypatch)
    reader = sqlite3.connect(db)
    cur = reader.execute("SELECT a, b FROM t")
    cur.fetchone()
    try:
        rec = checkpoint_wal(engine=eng, force=True)
    finally:
        cur.fetchall()
        reader.close()

    assert rec is not None
    p = rec["passive"]
    assert p["log_frames"] == p["checkpointed_frames"], (
        "the fixture no longer reproduces the refuted case"
    )
    assert rec["busy"] == 1, (
        "the WAL was pinned while the predicate said it was not — which is exactly "
        "why the TRUNCATE must not be gated on it"
    )


def test_the_default_busy_allowance_is_zero(tmp_path, monkeypatch):
    """The mechanism. A non-zero default is the 5 s hold, measured."""
    monkeypatch.delenv("OO_WAL_CHECKPOINT_BUSY_MS", raising=False)
    from src.scheduler.hygiene import _ckpt_busy_timeout_ms

    assert _ckpt_busy_timeout_ms() == 0
    monkeypatch.setenv("OO_WAL_CHECKPOINT_BUSY_MS", "750")
    assert _ckpt_busy_timeout_ms() == 750, "the operator's allowance is not honoured"
    monkeypatch.setenv("OO_WAL_CHECKPOINT_BUSY_MS", "not-a-number")
    assert _ckpt_busy_timeout_ms() == 0, "a malformed override must fall back to 0"


def test_a_busy_checkpoint_names_its_candidate_pinner(tmp_path, monkeypatch):
    from src.database import pool_watch

    monkeypatch.setattr(pool_watch, "is_registered", lambda: True)
    monkeypatch.setattr(
        pool_watch, "checked_out", lambda: [{"thread": "insights-3", "age_s": 900.1}]
    )
    eng, db, wal = _wal_engine(tmp_path, monkeypatch, rows=500)
    rec = checkpoint_wal(engine=eng, force=True)
    assert rec is not None
    assert rec["readers"]["oldest_thread"] == "insights-3"
    assert rec["readers"]["oldest_age_s"] == 900.1


def test_an_unattached_pool_watch_is_not_reported_as_no_readers(tmp_path, monkeypatch):
    """The same opposite-facts rule as the collector sample: an instrument that is
    not running must not publish a clean bill of health."""
    from src.database import pool_watch

    monkeypatch.setattr(pool_watch, "is_registered", lambda: False)
    eng, db, wal = _wal_engine(tmp_path, monkeypatch, rows=500)
    rec = checkpoint_wal(engine=eng, force=True)
    assert rec is not None
    assert rec["readers"] == {"instrument": "unattached"}
    assert "n" not in rec["readers"]
