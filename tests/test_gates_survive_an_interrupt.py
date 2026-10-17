"""An exception that lands inside a gate's own code leaves the gate usable and the exception intact.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Two ways a KeyboardInterrupt (or any exception delivered between two bytecodes) broke a gate, both found by the read of the lock work and
both closed here:

* THE ACQUIRE -> TRY GAP. ``if not gate.acquire(): ...`` then ``try: ... finally: release``: an exception after the gate was TAKEN and before the
  ``try`` opened left it held for ever (``write_lock``, the session events, the collector's pool slot). The tests below make the gate's own
  ``acquire`` take the gate and then raise, which is the same state seen from the caller.
* THE INTERRUPTED WAIT. ``Condition.wait`` re-takes the plain lock in a ``finally``; an interrupt while it is blocked there leaves the thread
  without the lock, so the ``with`` fails on exit with ``RuntimeError: cannot release un-acquired lock`` in place of the interrupt, and the gate's
  own ``finally`` edits its queue and counters unlocked. ``FlakyRLock`` re-creates that: its ``_acquire_restore`` raises KeyboardInterrupt once
  WITHOUT having taken the lock (what a blocked C ``acquire`` does when it is interrupted).
"""

from __future__ import annotations

import threading
import time

import pytest

from src.database import writer
from src.scheduler.bandwidth import _AdjustableSemaphore


class FlakyRLock:
    """A reentrant lock whose first ``_acquire_restore`` (the re-take at the end of ``Condition.wait``) raises KeyboardInterrupt."""

    def __init__(self) -> None:
        self._real = threading.RLock()
        self.interrupts_left = 1
        self.raised = 0

    def acquire(self, *a, **k):
        return self._real.acquire(*a, **k)

    def release(self):
        return self._real.release()

    __enter__ = acquire

    def __exit__(self, *exc):
        return self._real.release()

    def _is_owned(self):
        return self._real._is_owned()

    def _release_save(self):
        return self._real._release_save()

    def _acquire_restore(self, state):
        if self.interrupts_left:
            self.interrupts_left -= 1
            self.raised += 1
            raise KeyboardInterrupt  # the lock was NOT taken
        return self._real._acquire_restore(state)


def _in_thread(fn):
    """Run ``fn`` on its own thread; return ``(result_or_exception, thread)`` once it has finished (bounded)."""
    box: dict = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - the point is what comes out
            box["exc"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(5)
    assert not t.is_alive(), "the thread did not finish: a gate was left held"
    return box


def test_the_rlock_private_the_helper_relies_on_exists():
    assert hasattr(threading.RLock(), "_is_owned"), "src.utils.interrupts asks the lock whether it is owned"


# --- the interrupted wait ----------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("timeout", [None, 3], ids=["unbounded wait", "bounded wait"])
def test_an_interrupted_wait_on_the_write_gate_stays_the_interrupt_and_leaves_the_gate_working(timeout):
    gate = writer.WriterGate()
    flaky = FlakyRLock()
    gate._lock = flaky
    gate._cond = threading.Condition(flaky)
    assert gate.acquire()  # the main thread holds it, so the next acquire queues and waits
    started = threading.Event()

    def waiter():
        started.set()
        return gate.acquire(timeout=timeout)

    box_holder: dict = {}

    def run():
        try:
            box_holder["value"] = waiter()
        except BaseException as exc:  # noqa: BLE001
            box_holder["exc"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    started.wait(2)
    for _ in range(200):  # until it is queued
        if gate.waiters():
            break
        time.sleep(0.01)
    assert gate.waiters() == 1
    gate.release()  # wakes the head: its wait re-takes the lock and is interrupted there
    t.join(5)
    assert not t.is_alive()
    assert flaky.raised == 1
    assert isinstance(box_holder.get("exc"), KeyboardInterrupt), f"the interrupt must come out as itself, got {box_holder!r}"
    assert gate.waiters() == 0 and not gate._queue, "the interrupted waiter must leave the queue and the count"
    # and the gate still works, for the same thread and another
    assert gate.acquire(timeout=1)
    gate.release()
    other = _in_thread(lambda: (gate.acquire(timeout=1), gate.release()))
    assert other.get("value") == (True, None), other


def test_an_interrupted_wait_in_the_pool_slots_and_the_governor_stays_the_interrupt():
    from src.database.pool_reserve import _Slots

    slots = _Slots(1)
    flaky = FlakyRLock()
    slots._lock = flaky
    slots._cond = threading.Condition(flaky)
    assert slots.acquire(1, 1.0)
    box = {}

    def run():
        try:
            box["value"] = slots.acquire(2, 3.0)
        except BaseException as exc:  # noqa: BLE001
            box["exc"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    for _ in range(200):
        if slots.waits:
            break
        time.sleep(0.01)
    slots.release(1)
    t.join(5)
    assert not t.is_alive() and flaky.raised == 1
    assert isinstance(box.get("exc"), KeyboardInterrupt), box
    assert slots.held == 0 and slots.acquire(3, 1.0), "the slot table must be intact"

    sem = _AdjustableSemaphore(1)
    flaky2 = FlakyRLock()
    sem._lock = flaky2
    sem._cond = threading.Condition(flaky2)
    sem.acquire()
    box2 = {}

    def run2():
        try:
            sem.acquire()
        except BaseException as exc:  # noqa: BLE001
            box2["exc"] = exc

    t2 = threading.Thread(target=run2, daemon=True)
    t2.start()
    time.sleep(0.2)
    sem.release()
    t2.join(5)
    assert not t2.is_alive() and flaky2.raised == 1
    assert isinstance(box2.get("exc"), KeyboardInterrupt), box2
    sem.acquire()  # not stuck


def test_an_interrupted_wait_in_the_settings_hold_stays_the_interrupt(monkeypatch):
    from src.config import kv_store

    flaky = FlakyRLock()
    monkeypatch.setattr(kv_store, "_hold_lock", flaky)
    monkeypatch.setattr(kv_store, "_hold", threading.Condition(flaky))
    token = object()
    with kv_store._hold_lock:
        kv_store._inflight.add(token)  # a write in flight: the hold has to wait for it
    box = {}

    def run():
        try:
            with kv_store.hold_writes(3.0):
                box["held"] = True
        except BaseException as exc:  # noqa: BLE001
            box["exc"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    time.sleep(0.3)
    kv_store._inflight.discard(token)
    with kv_store._hold_lock:
        kv_store._hold.notify_all()
    t.join(5)
    assert not t.is_alive() and flaky.raised == 1
    assert isinstance(box.get("exc"), KeyboardInterrupt), box
    assert kv_store._hold_by is None, "an interrupted hold must not stay set"


# --- the acquire -> try gap ---------------------------------------------------------------------------------------------------------------


@pytest.fixture
def interrupting_acquire(monkeypatch):
    """The gate's ``acquire`` takes the window and THEN raises: the state a caller is left in by an interrupt after the take."""
    real = writer.write_gate.acquire

    def acquire_then_raise(timeout=None):
        real(timeout=timeout)
        raise KeyboardInterrupt

    monkeypatch.setattr(writer.write_gate, "acquire", acquire_then_raise)
    monkeypatch.setattr(writer, "gate_enabled", lambda: True)
    return acquire_then_raise


def test_write_lock_gives_the_window_back_when_the_acquire_raises_after_taking_it(interrupting_acquire):
    with pytest.raises(KeyboardInterrupt), writer.write_lock():
        pytest.fail("the body must not run")
    assert not writer.write_gate.held_by_current_thread(), "the window was left held"


def test_write_lock_nested_gives_back_only_its_own_level(monkeypatch):
    monkeypatch.setattr(writer, "gate_enabled", lambda: True)
    real = writer.write_gate.acquire
    with writer.write_lock():  # the outer level
        assert writer.write_gate.depth_of_current_thread() == 1

        def acquire_then_raise(timeout=None):
            real(timeout=timeout)
            raise KeyboardInterrupt

        monkeypatch.setattr(writer.write_gate, "acquire", acquire_then_raise)
        with pytest.raises(KeyboardInterrupt), writer.write_lock():
            pass
        monkeypatch.setattr(writer.write_gate, "acquire", real)
        assert writer.write_gate.depth_of_current_thread() == 1, "the outer level must still be held, exactly once"
    assert not writer.write_gate.held_by_current_thread()


def test_write_lock_nested_does_not_give_back_the_outer_level_when_the_acquire_raises_before_taking(monkeypatch):
    monkeypatch.setattr(writer, "gate_enabled", lambda: True)
    with writer.write_lock():
        real = writer.write_gate.acquire

        def raise_before_taking(timeout=None):
            raise KeyboardInterrupt

        monkeypatch.setattr(writer.write_gate, "acquire", raise_before_taking)
        with pytest.raises(KeyboardInterrupt), writer.write_lock():
            pass
        monkeypatch.setattr(writer.write_gate, "acquire", real)
        assert writer.write_gate.depth_of_current_thread() == 1, "the outer level was given back by a call that never took one"
    assert not writer.write_gate.held_by_current_thread()


def test_a_session_interrupted_just_after_it_was_marked_is_unmarked_and_holds_nothing():
    class _MarkThenRaise(dict):
        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            raise KeyboardInterrupt

    class _Session:
        pass

    session = _Session()
    session.info = _MarkThenRaise()
    with pytest.raises(KeyboardInterrupt):
        writer._take_for_session(session)
    assert not writer.write_gate.held_by_current_thread()
    assert writer._SESSION_FLAG not in session.info, "a flag with no window behind it makes a later release_if_held drop someone else's level"


def test_a_session_that_is_interrupted_after_the_window_was_taken_holds_nothing(interrupting_acquire):
    class _Session:
        info: dict = {}

    session = _Session()
    session.info = {}
    with pytest.raises(KeyboardInterrupt):
        writer._take_for_session(session)
    assert not writer.write_gate.held_by_current_thread()
    assert writer._SESSION_FLAG not in session.info


def test_a_session_takes_the_window_once_and_marks_itself(monkeypatch):
    class _Session:
        pass

    session = _Session()
    session.info = {}
    try:
        writer._take_for_session(session)
        assert session.info[writer._SESSION_FLAG] is True
        assert writer.write_gate.depth_of_current_thread() == 1
    finally:
        writer.release_if_held(session)
    assert not writer.write_gate.held_by_current_thread()


def test_the_collector_slot_is_given_back_when_the_reservation_raises_after_taking_it():
    import sqlite3

    from sqlalchemy import create_engine

    from src.database.pool_reserve import ReservingQueuePool, collector_role

    engine = create_engine(
        "sqlite://",
        creator=lambda: sqlite3.connect(":memory:", check_same_thread=False),
        poolclass=ReservingQueuePool,
        pool_size=2,
        max_overflow=4,
        pool_timeout=0.3,
    )
    pool = engine.pool
    real = pool._reserve.acquire

    def take_then_raise(key, timeout):
        real(key, timeout)
        raise KeyboardInterrupt

    pool._reserve.acquire = take_then_raise
    with collector_role(), pytest.raises(KeyboardInterrupt):
        engine.connect()
    assert pool._reserve.held == 0, "the slot was leaked"
