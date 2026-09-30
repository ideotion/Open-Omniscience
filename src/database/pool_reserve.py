"""D44 = a: the collector may not take the last ``_API_MARGIN`` pooled connections.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE DEFECT (finding F1, ruling R26, question D44). ``collect_parallelism`` ships at 50
and the floor's worker cap applies only BELOW the floor, so on the medium tier 50
collector workers share 24 pooled connections. A worker holds its connection while it
queues on the single-writer gate, so API handlers waited the 30 s ``pool_timeout`` and
answered 500. R26 raised the pool and forbade lowering the worker cap; the maintainer's
D44 answer (2026-09-30) chose the remaining way out: a RESERVATION AT CHECKOUT.

WHAT IT BOUNDS, AND WHAT IT DOES NOT. It bounds how many pooled connections threads in
the collector role may hold at once: ``pool_total - _API_MARGIN``. It does not bound
fetching -- fifty workers still fetch in parallel; only the ones about to open a DB
session queue, for the time the pool itself would have made them wait -- and it does not
touch the worker cap R26 forbids lowering. The number is derived from the machine's
pool (which the memory budget already sizes from RAM), never a constant of its own.

HOW. ``ReservingQueuePool`` is the engine's pool class. ``connect()`` is the public
entry every checkout passes through, so the slot is taken BEFORE the pool hands a
connection out (a ``checkout`` event fires after, which would already have taken it).
A thread that is not in the collector role never touches the slots: the API, the
housekeeping lane and the scheduler thread are exactly who the reservation is for. The
slot is returned on ``checkin`` or ``detach`` -- whichever happens -- and returning is
idempotent, so a connection can never release twice or leak.

A collector thread that cannot get a slot waits up to the pool's own timeout and then
raises the pool's own ``TimeoutError``, so every existing handler for "the pool was
exhausted" keeps working unchanged. A thread that already HOLDS a slot never waits for a
second (a nested session would otherwise deadlock every holder against every other), and
neither does a thread that OWNS the single-writer gate: ``before_flush`` takes the gate
before the flush checks a connection out, so a gate owner queueing for a slot while the
slot holders queue for the gate would stall the collector for the pool timeout. Those
checkouts are counted as ``collector_nested`` so the pass summary can show how often the
margin was leaned on rather than hiding it.

THE SLOT IS KEYED ON THE POOL'S CONNECTION RECORD, never on ``id(dbapi_connection)``.
SQLAlchemy clears ``record.dbapi_connection`` BEFORE it fires ``checkin`` when a connection
is invalidated (a failed rollback on return, ``invalidate()``, a disconnect -- the vanished
external drive of R86 is exactly this), so a key on the DBAPI object misses, the slot is
never returned, and a leaked ceiling's worth of them starves the collector until restart
(found by the Opus review of the first draft and reproduced against SQLAlchemy 2.1.1). The
record is the same object for the checkout's whole life and is what both ``checkin`` and
``detach`` are handed.
"""

from __future__ import annotations

import itertools
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.pool import QueuePool

_ROLE = threading.local()
_KEYS = itertools.count(1)


@contextmanager
def collector_role() -> Iterator[None]:
    """Mark the current thread as a collector worker for the duration of the block.

    Re-entrant: nesting leaves the outer marking in force. Only connections CHECKED OUT
    inside the block count against the reservation.
    """
    depth = getattr(_ROLE, "depth", 0)
    _ROLE.depth = depth + 1
    try:
        yield
    finally:
        _ROLE.depth = depth


def in_collector_role() -> bool:
    return getattr(_ROLE, "depth", 0) > 0


class _Slots:
    """A counting gate with a live, readable count and an idempotent release by key."""

    def __init__(self, limit: int) -> None:
        self.limit = max(1, int(limit))
        self._cond = threading.Condition()
        self._held: dict[int, threading.Thread] = {}  # slot key -> the thread that took it
        self.waits = 0  # checkouts that had to queue, ever (a reading, not a control)
        self.nested = 0  # checkouts by a thread that already held a slot (see holds())

    def acquire(self, key: int, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with self._cond:
            queued = False
            while len(self._held) >= self.limit:
                if not queued:
                    queued = True
                    self.waits += 1
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._cond.wait(left)
            self._held[key] = threading.current_thread()
            return True

    def note_nested(self) -> None:
        with self._cond:
            self.nested += 1

    def holds(self, thread: threading.Thread) -> bool:
        """Whether this thread already holds a slot.

        A holder that asks for a SECOND connection (a nested session) must not wait for a
        slot: with every slot held by a thread that is itself waiting for another, nobody
        could ever release one -- the pool's own exhaustion deadlock, moved up a level.
        Such a checkout goes through unreserved and is counted in ``nested``.
        """
        with self._cond:
            # Compared by OBJECT, not ident: a finished thread's ident is reused by the next one.
            return any(t is thread for t in self._held.values())

    def release(self, key: int) -> None:
        with self._cond:
            if key in self._held:
                del self._held[key]
                self._cond.notify()

    @property
    def held(self) -> int:
        with self._cond:
            return len(self._held)


def _owns_write_gate() -> bool:
    """Whether this thread holds the single-writer gate (imported lazily: no cycle)."""
    from src.database.writer import write_gate

    return write_gate.held_by_current_thread()


def collector_ceiling(pool_total: int, api_margin: int) -> int:
    """How many pooled connections the collector may hold: all but the API's margin.

    At least one, so that a pool no larger than the margin still lets the collector run
    (its verdict then reports honestly that the margin cannot be kept).
    """
    return max(1, int(pool_total) - int(api_margin))


class ReservingQueuePool(QueuePool):
    """``QueuePool`` whose collector-role checkouts leave ``api_margin`` connections free."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # The margin is the memory budget's, read here rather than passed through
        # ``create_engine`` (which would forward an unknown keyword to the pool).
        from src.config.memory_budget import _API_MARGIN

        self._api_margin = int(_API_MARGIN)
        self._reserve = _Slots(
            collector_ceiling(self.size() + self._max_overflow, self._api_margin)
        )
        self._slot_key: dict[int, int] = {}  # id(connection record) -> slot key
        self._slot_lock = threading.Lock()
        event.listen(self, "checkin", self._on_return)
        event.listen(self, "detach", self._on_return)

    # -- the public checkout entry -------------------------------------------------
    def connect(self):  # type: ignore[override]
        if not in_collector_role():
            return super().connect()
        if self._reserve.holds(threading.current_thread()) or _owns_write_gate():
            self._reserve.note_nested()
            return super().connect()
        key = next(_KEYS)
        if not self._reserve.acquire(key, float(self._timeout)):
            raise PoolTimeoutError(
                "QueuePool limit reached for the collector: it may not take the last "
                f"{self._api_margin} connections, which stay free for the app "
                f"(collector ceiling {self._reserve.limit}); "
                f"connection timed out, timeout {self._timeout:.2f}"
            )
        try:
            fairy = super().connect()
        except BaseException:
            self._reserve.release(key)
            raise
        record = getattr(fairy, "_connection_record", None)
        if record is None:
            # Cannot be tracked, so it cannot be returned by the events: give the slot
            # back NOW. An unreserved connection is a smaller failure than a leaked slot.
            self._reserve.release(key)
            return fairy
        with self._slot_lock:
            self._slot_key[id(record)] = key
        return fairy

    def _on_return(self, _dbapi_connection, record=None) -> None:
        if record is None:
            return
        with self._slot_lock:
            key = self._slot_key.pop(id(record), None)
        if key is not None:
            self._reserve.release(key)

    # -- readings ------------------------------------------------------------------
    def reservation(self) -> dict[str, int]:
        """A point-in-time reading for the pass summary and the diagnostics bundle."""
        return {
            "collector_ceiling": self._reserve.limit,
            "collector_held": self._reserve.held,
            "collector_waits": self._reserve.waits,
            "collector_nested": self._reserve.nested,
            "api_margin": self._api_margin,
        }
