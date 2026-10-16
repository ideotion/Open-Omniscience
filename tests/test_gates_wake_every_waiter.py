"""A slot or permit given back wakes EVERY waiter, so a stale entry in a Condition's waiter list cannot swallow the one wake.

``Condition.notify()`` hands its one wake to the first entry of ``_waiters``. After an interrupt lands inside ``wait()`` (a
``KeyboardInterrupt`` between the entry's creation and its removal), an entry can stay in the list with no thread behind it, and a
``notify()`` that picks it wakes nobody: the real waiter behind it sleeps on (the permit gate has no timeout, so for ever; the
pool-slot gate until its deadline, which the caller sees as a pool timeout). ``notify_all()`` wakes the real waiter too, and every
waiter re-checks its own predicate, so a woken waiter that finds the gate still full goes back to waiting.

The stale entry is planted by hand (an acquired lock appended to the list, which is what ``wait()`` leaves behind), so the tests need no
signal and no timing. They rely on CPython's private ``Condition._waiters``; if a runtime renames it the plant fails loudly (the
``getattr`` below), it does not pass silently.
"""

from __future__ import annotations

import threading
import time

from src.database.pool_reserve import _Slots
from src.scheduler.bandwidth import _AdjustableSemaphore

_PATIENCE_S = 10.0


def _plant_stale_waiter(cond: threading.Condition) -> None:
    waiters = getattr(cond, "_waiters")  # noqa: B009 - the private list IS the thing under test
    stale = threading.Lock()
    stale.acquire()  # a waiter lock nobody will ever release again: notify() "wakes" it by releasing it
    waiters.appendleft(stale)


def _wait_until(pred, what):
    deadline = time.monotonic() + _PATIENCE_S
    while time.monotonic() < deadline:
        if pred():
            return
        time.sleep(0.01)
    raise AssertionError(what)


def test_a_slot_given_back_reaches_the_real_waiter_behind_a_stale_entry():
    slots = _Slots(1)
    assert slots.acquire(1, 1.0)
    got: list[bool] = []
    t = threading.Thread(target=lambda: got.append(slots.acquire(2, _PATIENCE_S)), daemon=True)
    t.start()
    _wait_until(lambda: len(getattr(slots._cond, "_waiters")) >= 1, "the real waiter never queued")  # noqa: B009
    _plant_stale_waiter(slots._cond)  # in front of the real one
    began = time.monotonic()
    slots.release(1)
    t.join(_PATIENCE_S)
    assert got == [True], "the slot was handed back and the waiter behind the stale entry was not woken"
    assert time.monotonic() - began < _PATIENCE_S / 2, "it was woken by its deadline, not by the release"


def test_a_permit_given_back_reaches_the_real_waiter_behind_a_stale_entry():
    sem = _AdjustableSemaphore(1)
    sem.acquire()
    done = threading.Event()

    def worker():
        sem.acquire()
        done.set()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    _wait_until(lambda: len(getattr(sem._cond, "_waiters")) >= 1, "the real waiter never queued")  # noqa: B009
    _plant_stale_waiter(sem._cond)
    sem.release()
    assert done.wait(_PATIENCE_S), "the permit was handed back and the waiter behind the stale entry was never woken"
    t.join(_PATIENCE_S)


def test_a_woken_waiter_that_finds_the_gate_still_full_waits_again():
    """notify_all wakes the others too: only the waiters whose predicate holds proceed."""
    slots = _Slots(1)
    assert slots.acquire(1, 1.0)
    results: dict[int, bool] = {}

    def want(key: int) -> None:
        results[key] = slots.acquire(key, 10.0)

    threads = [threading.Thread(target=want, args=(k,), daemon=True) for k in (2, 3)]
    for t in threads:
        t.start()
    _wait_until(lambda: len(getattr(slots._cond, "_waiters")) >= 2, "both waiters never queued")  # noqa: B009
    slots.release(1)
    _wait_until(lambda: len(results) == 1, "nobody took the freed slot")
    assert slots.held == 1, "two waiters took one slot"
    winner = next(iter(results))
    slots.release(winner)
    for t in threads:
        t.join(_PATIENCE_S)
    assert sorted(results) == [2, 3] and all(results.values())
