"""``Condition.wait`` for a caller that holds the plain lock under it once, and keeps its own exception when the wait is interrupted.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``Condition.wait`` is Python code: it gives the lock up (``_release_save``), and only then opens the ``try`` whose ``finally`` takes it back. An
exception that lands between the two, or inside that ``finally`` before the lock is back, leaves the thread WITHOUT the lock (and the waiter in
the Condition's list). The caller's ``with lock:`` then fails on the way out with ``RuntimeError: cannot release un-acquired lock``, which
replaces the exception, and any ``finally`` between the wait and the end of the ``with`` runs on shared state with nobody holding the lock.
Measured with real SIGALRM interrupts on CPython 3.13 (``scripts/signal_leak_probe.py`` and a re-run by the reader of this change): 68 of
66,131 interrupted plain waits surfaced as that RuntimeError (the earlier figure, 174 of 65,632, is the same event). Where it lands was
measured too: NOT in the lock's own re-take (a blocked ``RLock._acquire_restore`` is not interruptible on 3.13; the interrupt arrived after the
lock was back) but in the Python code between ``_release_save`` and the ``try``. Either way the state is the same, and :func:`wait` fixes
it: it takes the lock back itself in that one case, with the same uninterruptible restore the Condition uses, and lets the original exception
go on. When the lock IS owned at the exception (the common case: the interrupt landed after the re-take) it does nothing.

THE LOOP FORM IS PART OF THE GUARANTEE. Every caller waits in a loop under ``with lock:``. On CPython 3.13 the back-edge (``JUMP_BACKWARD``) of
``while <wanted>:`` is compiled OUTSIDE the ``with``'s exception-table entry, and outside the ``try``/``finally`` around it, so an interrupt
delivered at that instruction skips the release and every cleanup: measured with ``scripts/signal_leak_probe.py gate_*``, 0.3 to 0.9 % of
interrupts left the pool slots', the governor's, the library lock's and the settings hold's lock owned (and the hold set, refusing every later save)
for ever. ``while True: if not <wanted>: break`` keeps the jump inside the entry (checked with ``dis``; pinned by
``tests/test_gates_survive_an_interrupt.py``). Write every wait loop that way.

It assumes the lock is held exactly ONCE by the caller (every use here is one ``with self._lock:`` around the wait), which is the only
level at which restoring ``(1, this thread)`` gives back what the ``with`` expects.
"""

from __future__ import annotations

import threading


def wait(cond: threading.Condition, lock: threading.RLock, timeout: float | None = None) -> bool:
    """``cond.wait(timeout)`` where ``cond`` was built over ``lock`` and the caller holds ``lock`` once; same return value."""
    try:
        return cond.wait(timeout)
    except BaseException:
        # `_is_owned` is the question Condition itself asks of its lock (it needs the lock owned to wait at all)
        if not lock._is_owned():  # type: ignore[attr-defined]
            # `_acquire_restore` is what Condition.wait itself uses to take the lock back: on the C RLock it is not interruptible, where a
            # plain `acquire()` blocked on a contended lock is (a second interrupt would escape without the lock again)
            lock._acquire_restore((1, threading.get_ident()))  # type: ignore[attr-defined]
        raise
