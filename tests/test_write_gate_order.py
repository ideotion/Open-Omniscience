"""A writer waits for its pooled connection BEFORE it asks for the write gate, never while it holds it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``before_flush`` and ``do_orm_execute`` fire before SQLAlchemy checks a connection out for the statement, so a session whose FIRST
statement was its write took the gate and then waited for the pool. With 23 of 24 connections out (the 16 Oct 2026 bundles) that
wait is the pool's 30 s timeout, spent holding the one window every other writer needs. ``connection_first`` checks the connection
out first. These tests use a real pool of one whose only connection is out, a real session factory wired with the writer's own hooks,
and read the gate from a third thread while the writer is waiting.
"""

from __future__ import annotations

import threading
import time

import pytest
from sqlalchemy import Column, Integer, String, create_engine, event, update
from sqlalchemy.exc import OperationalError, UnboundExecutionError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.pool import QueuePool

from src.database import writer

Base = declarative_base()


class Row(Base):
    __tablename__ = "gate_order_rows"
    id = Column(Integer, primary_key=True)
    v = Column(String)


@pytest.fixture
def pool_of_one(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_WRITE_GATE_WATCHDOG", "0")
    eng = create_engine(
        f"sqlite:///{tmp_path / 'order.db'}", poolclass=QueuePool, pool_size=1, max_overflow=0, pool_timeout=3
    )
    Base.metadata.create_all(eng)
    factory = sessionmaker(bind=eng, autoflush=False)
    event.listen(factory, "before_flush", writer._on_before_flush)
    event.listen(factory, "do_orm_execute", writer._on_orm_execute)
    event.listen(factory, "after_transaction_end", writer._on_after_transaction_end)
    yield eng, factory
    eng.dispose()


def _waiting_writer(factory, write):
    """Run ``write(session)`` on a thread named ``oo-waiter`` and return the thread and the outcome dict."""
    outcome: dict[str, object] = {}

    def run():
        s = factory()
        try:
            write(s)
            s.commit()
            outcome["ok"] = True
        except Exception as exc:  # noqa: BLE001 - the test reads the class
            outcome["error"] = type(exc)
        finally:
            s.close()

    t = threading.Thread(target=run, name="oo-waiter")
    t.start()
    return t, outcome


def _before_waiting(factory, write, *, settle=0.4):
    """The gate as a THIRD thread sees it while ``write`` waits for the pool's only connection, and the outcome after it is released."""
    eng = factory.kw["bind"]
    hog = eng.connect()
    t, outcome = _waiting_writer(factory, write)
    time.sleep(settle)
    seen = writer.write_gate.stats()
    hog.close()
    t.join(10)
    assert not t.is_alive()
    return seen, outcome


def test_a_flush_that_is_the_sessions_first_statement_waits_for_the_pool_without_the_gate(pool_of_one):
    _eng, factory = pool_of_one
    before = writer.pool_wait_stats()
    seen, outcome = _before_waiting(factory, lambda s: s.add(Row(v="x")))
    assert seen["held"] is False and seen["holder"] is None, f"the waiter held the gate while it waited for a connection: {seen}"
    assert outcome == {"ok": True}, "released, the write goes through"
    after = writer.pool_wait_stats()
    assert after["n"] == before["n"] + 1
    assert after["max_s"] >= 0.35, "it really waited (the check above was not made before the writer reached the pool)"
    assert writer.write_gate.stats()["pool_wait_before_gate"]["max_s"] == after["max_s"], "the gate's own stats carry the figure"


def test_a_bulk_update_that_is_the_sessions_first_statement_waits_for_the_pool_without_the_gate(pool_of_one):
    _eng, factory = pool_of_one
    seen, outcome = _before_waiting(factory, lambda s: s.execute(update(Row).values(v="y")))
    assert seen["held"] is False and seen["holder"] is None, seen
    assert outcome == {"ok": True}


def test_the_gate_is_held_for_the_write_itself_as_before(pool_of_one):
    """The change moves the wait out of the window; it does not move the window: the flush still runs under the gate."""
    _eng, factory = pool_of_one
    s = factory()
    s.add(Row(v="z"))
    s.flush()
    assert writer.write_gate.held_by_current_thread()
    s.commit()
    assert not writer.write_gate.held_by_current_thread()
    s.close()


def test_a_pool_timeout_reaches_the_caller_unchanged_with_nothing_held_and_is_counted_as_a_stall(pool_of_one, monkeypatch):
    eng, factory = pool_of_one
    eng.pool._timeout = 1.2  # a wait past POOL_WAIT_STALL_S
    before = writer.pool_wait_stats()
    hog = eng.connect()
    t, outcome = _waiting_writer(factory, lambda s: s.add(Row(v="x")))
    t.join(10)
    hog.close()
    assert outcome == {"error": PoolTimeoutError}, "the pool's own error, not wrapped and not swallowed"
    assert writer.write_gate.stats()["held"] is False, "a timed-out writer left nothing held"
    after = writer.pool_wait_stats()
    assert after["stalls"] == before["stalls"] + 1 and after["max_s"] >= 1.1


def test_a_second_flush_in_the_same_transaction_is_not_timed_again(pool_of_one):
    _eng, factory = pool_of_one
    s = factory()
    before = writer.pool_wait_stats()["n"]
    s.add(Row(v="a"))
    s.flush()
    s.add(Row(v="b"))
    s.flush()
    s.commit()
    s.close()
    assert writer.pool_wait_stats()["n"] == before + 1


def test_a_session_with_no_bind_keeps_its_old_order_and_its_old_error():
    """More than one bind and no default raises ``UnboundExecutionError`` from ``session.connection()``: the flush chooses the bind per
    mapper, so this case falls through to the gate-then-connection order and the flush raises what it always raised."""
    factory = sessionmaker(autoflush=False)
    event.listen(factory, "before_flush", writer._on_before_flush)
    event.listen(factory, "after_transaction_end", writer._on_after_transaction_end)
    s = factory()
    s.add(Row(v="x"))
    with pytest.raises(UnboundExecutionError):
        s.flush()
    s.close()
    assert writer.write_gate.stats()["held"] is False


class _Failing(Session):
    def __init__(self, error):
        super().__init__()
        self._error = error

    def connection(self, *a, **k):
        raise self._error


def test_a_connection_failure_other_than_an_unbound_session_propagates_and_is_not_hidden():
    boom = OperationalError("connect", {}, Exception("unable to open database file"))
    with pytest.raises(OperationalError):
        writer.connection_first(_Failing(boom))
    unbound = UnboundExecutionError("no bind")
    assert writer.connection_first(_Failing(unbound)) is None
