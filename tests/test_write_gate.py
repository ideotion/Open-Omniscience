"""The single-writer gate: writers serialise, two never collide on the lock.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Covers src/database/writer.py (keystone #1). Proves the primitive's contract
(reentrancy, cross-thread mutual exclusion, honest stats, safe non-owner
release) and — the headline — that many threads writing a REAL file-backed
SQLite store through the gate-wired session events never raise "database is
locked" and are observably serialised, while read-only transactions never take
the gate.
"""

from __future__ import annotations

import threading
import time

from sqlalchemy import Integer, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from src.database.writer import (
    WriterGate,
    _on_after_transaction_end,
    _on_before_flush,
    _on_orm_execute,
    write_gate,
)

# --------------------------------------------------------------------------- #
# WriterGate primitive
# --------------------------------------------------------------------------- #


def test_reentrant_same_thread():
    g = WriterGate()
    g.acquire()
    assert g.held_by_current_thread()
    g.acquire()  # nested, same thread — must not deadlock
    assert g.held_by_current_thread()
    g.release()
    assert g.held_by_current_thread()  # still held: depth was 2
    g.release()
    assert not g.held_by_current_thread()
    assert g.stats()["held"] is False


def test_release_by_non_owner_is_noop():
    g = WriterGate()
    g.acquire()  # owned by this (main) thread

    def _other_releases():
        g.release()  # different thread — must be a no-op, never steal/raise

    t = threading.Thread(target=_other_releases)
    t.start()
    t.join()
    assert g.held_by_current_thread()  # still ours
    g.release()
    assert not g.stats()["held"]


def test_cross_thread_mutual_exclusion_and_stats():
    """Two threads in the write window are impossible; the second waits."""
    g = WriterGate()
    order: list[str] = []
    b_may_try = threading.Event()
    a_inside = threading.Event()

    def a():
        g.acquire()
        a_inside.set()
        order.append("a-enter")
        b_may_try.wait(2)
        time.sleep(0.05)  # hold the window while B is blocked
        order.append("a-exit")
        g.release()

    def b():
        a_inside.wait(2)
        b_may_try.set()
        g.acquire()  # must block until A releases
        order.append("b-enter")
        g.release()

    ta, tb = threading.Thread(target=a), threading.Thread(target=b)
    ta.start()
    tb.start()
    ta.join(3)
    tb.join(3)

    # B never entered before A left — serialisation held.
    assert order == ["a-enter", "a-exit", "b-enter"]
    st = g.stats()
    assert st["grants"] == 2
    assert st["contended"] == 1  # B had to wait exactly once
    assert st["max_wait_s"] >= 0.0
    assert st["held"] is False


# --------------------------------------------------------------------------- #
# Wired to real SQLite + real threads (the headline proof)
# --------------------------------------------------------------------------- #


class _Base(DeclarativeBase):
    pass


class _Row(_Base):
    __tablename__ = "gate_test_row"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    writer: Mapped[int] = mapped_column(Integer)


def _wired_sessionmaker(tmp_path):
    """A file-backed SQLite sessionmaker with the REAL gate handlers attached.

    File-backed (not :memory:) + check_same_thread=False so genuine cross-thread
    write contention is possible; a short busy_timeout means that WITHOUT the
    gate concurrent commits would risk 'database is locked' — the gate is what
    makes them safe. We attach the same handlers the app wires on SessionLocal.
    """
    db = tmp_path / "gate.db"
    engine = create_engine(
        f"sqlite:///{db}", future=True, connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _rec):  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=200")  # short: contention would bite fast
        cur.close()

    _Base.metadata.create_all(engine)
    Maker = sessionmaker(bind=engine, autoflush=False, future=True)
    event.listen(Maker, "before_flush", _on_before_flush)
    event.listen(Maker, "do_orm_execute", _on_orm_execute)
    event.listen(Maker, "after_transaction_end", _on_after_transaction_end)
    return engine, Maker


def test_concurrent_writers_never_locked_and_are_serialised(tmp_path):
    engine, Maker = _wired_sessionmaker(tmp_path)
    n_threads, per_thread = 6, 40
    errors: list[Exception] = []
    before = write_gate.stats()

    def worker(wid: int):
        try:
            for _ in range(per_thread):
                s = Maker()
                try:
                    s.add(_Row(writer=wid))
                    s.commit()
                finally:
                    s.close()
        except Exception as exc:  # noqa: BLE001 - capture for the assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)

    assert errors == [], f"a concurrent writer failed (expected none): {errors!r}"
    with Maker() as s:
        assert s.query(_Row).count() == n_threads * per_thread  # nothing lost

    after = write_gate.stats()
    # Every commit took the gate exactly once -> grants grew by the total.
    assert after["grants"] - before["grants"] >= n_threads * per_thread
    assert not after["held"]  # the gate is free again
    # (That writers actually QUEUE under contention is proven deterministically
    # by test_cross_thread_mutual_exclusion_and_stats; asserting contended>0 here
    # is overwhelmingly likely but scheduler-dependent, so we don't gate on it.)
    engine.dispose()


def test_bulk_dml_delete_takes_the_gate(tmp_path):
    """Regression (field log 2026-06-17): a bulk ``Query.delete()`` does NOT fire
    before_flush — it executes immediately. WITHOUT the do_orm_execute hook it
    would grab the SQLite write lock OUTSIDE the gate (this is what produced the
    149+ 'database is locked' failures in index_article's idempotent re-index).
    Here we prove the bulk delete takes the gate (unlike a read)."""
    engine, Maker = _wired_sessionmaker(tmp_path)
    with Maker() as seed:
        seed.add(_Row(writer=7))
        seed.commit()

    s = Maker()
    try:
        s.query(_Row).filter_by(writer=7).delete()  # bulk DML — no before_flush
        assert s.info.get("_oo_write_gate_held"), "bulk delete must take the gate"
        assert write_gate.held_by_current_thread()
        s.commit()  # ends the transaction -> releases
        assert not write_gate.held_by_current_thread()
        assert not s.info.get("_oo_write_gate_held")
    finally:
        s.close()
    engine.dispose()


def test_bulk_dml_never_locked_against_a_long_held_writer(tmp_path):
    """The headline field scenario: a writer holds the window long past the
    busy_timeout (the 213s gate-holder in the log) while another thread issues a
    bulk ``Query.delete()``. WITHOUT the do_orm_execute gate the delete hits
    SQLite directly and fails 'database is locked'; WITH it the delete queues on
    the gate and succeeds."""
    engine, Maker = _wired_sessionmaker(tmp_path)  # busy_timeout=200ms
    with Maker() as seed:
        seed.add_all([_Row(writer=1), _Row(writer=2)])
        seed.commit()

    errors: list[Exception] = []
    holder_in = threading.Event()
    deleter_done = threading.Event()

    def holder():
        s = Maker()
        try:
            s.add(_Row(writer=3))
            s.flush()  # takes the gate AND the SQLite write lock
            holder_in.set()
            # Hold well past busy_timeout (200ms) so an UNGATED delete would fail.
            deleter_done.wait(2)
            s.commit()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            s.close()

    def deleter():
        holder_in.wait(2)
        s = Maker()
        try:
            s.query(_Row).filter_by(writer=1).delete()
            s.commit()
        except Exception as exc:  # noqa: BLE001 - the bug would land here
            errors.append(exc)
        finally:
            s.close()
            deleter_done.set()

    th, td = threading.Thread(target=holder), threading.Thread(target=deleter)
    th.start()
    td.start()
    th.join(5)
    td.join(5)

    assert errors == [], f"a gated bulk delete must never lock: {errors!r}"
    with Maker() as s:
        assert s.query(_Row).filter_by(writer=1).count() == 0  # the delete landed
    engine.dispose()


def test_read_only_transaction_does_not_take_the_gate(tmp_path):
    engine, Maker = _wired_sessionmaker(tmp_path)
    before = write_gate.stats()
    s = Maker()
    try:
        s.query(_Row).count()  # pure read; no pending changes
        s.commit()  # commit with nothing to flush -> no before_flush -> no gate
        assert not s.info.get("_oo_write_gate_held")
    finally:
        s.close()
    assert write_gate.stats()["grants"] == before["grants"]  # no write grant
    engine.dispose()


def test_gate_released_when_session_closed_without_commit(tmp_path):
    """Regression for the gate-leak hang: a session that flushes then is CLOSED
    WITHOUT committing (the common test/abandon pattern) must release the gate.
    close() does NOT reliably emit after_rollback in SQLAlchemy 2.0, so the
    release rides on after_transaction_end (the outermost transaction ending) —
    proven here with NO safety-net help."""
    engine, Maker = _wired_sessionmaker(tmp_path)
    s = Maker()
    s.add(_Row(writer=99))
    s.flush()  # takes the gate
    assert s.info.get("_oo_write_gate_held")
    assert write_gate.held_by_current_thread()
    s.close()  # the ONLY release path exercised here (no commit, no safety net)
    assert not write_gate.held_by_current_thread(), "close() must release the gate"
    assert not write_gate.stats()["held"]
    assert not s.info.get("_oo_write_gate_held")  # flag cleared for reuse
    engine.dispose()
