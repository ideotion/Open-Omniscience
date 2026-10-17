"""``Condition.wait`` for a caller that holds the plain lock under it once, and keeps its own exception when the wait is interrupted.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``Condition.wait`` gives the lock up, sleeps, and takes it back in a ``finally``. A KeyboardInterrupt that lands while it is blocked
re-taking the lock leaves the thread WITHOUT the lock (a blocked C ``acquire`` that is interrupted raises without having taken it). The
caller's ``with lock:`` then fails on the way out with ``RuntimeError: cannot release un-acquired lock``, which replaces the interrupt, and
any ``finally`` between the wait and the end of the ``with`` runs on shared state with nobody holding the lock. Measured with real SIGALRM
interrupts (``scripts/signal_leak_probe.py``): 174 of 65,632 interrupted waits (0.27 %) surfaced as that RuntimeError; nothing was left
held. :func:`wait` takes the lock back itself in that one case and lets the original exception go on, so the code around it runs under
the lock it believes it holds and ``with lock:`` releases it once.

It assumes the lock is held exactly ONCE by the caller (every use here is one ``with self._lock:`` around the wait), which is the only
level at which taking it back as a single ``acquire()`` restores what the ``with`` expects.
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
            lock.acquire()
        raise
