"""
The single-writer gate: every database write serialises through ONE in-process
queue, so two writers never collide on the SQLite write lock.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why this exists (keystone #1, SCRAPING_AUTOMATION_PLAN Step 2):
  The store is single-writer by design (one SQLite/SQLCipher file). WAL lets
  readers pass a writer, but two *writers* still serialise at the SQLite layer,
  and a long collection pass can hold the writer past ``PRAGMA busy_timeout``.
  When that happens SQLite raises ``OperationalError: database is locked`` and
  the loser historically **discarded data it had already fetched over the
  network** (field log 2026-06-13: copper/aluminum/nickel/zinc fetched OK then
  failed to store). ``run_write_with_retry`` (src/database/write.py) was the
  surgical safety net; THIS is the proper fix that removes the contention
  entirely: writers queue in *Python* (waiting, not erroring) so only one is
  ever inside a write transaction at a time. SQLite therefore never sees two
  concurrent writers, so the lock is never contended and the timeout never
  fires.

What it is, stated honestly:
  An application-level **reentrant write mutex** with FIFO-ish wake order
  (``Condition.notify`` wakes the longest-waiter on CPython). Threads queue on
  it; it is not a worker pool that owns the connection. This is the standard,
  correct way to serialise writers against one SQLite file, and it is exactly
  the "all writes enqueue; import + scrape never collide" the maintainer ruled.
  It also unblocks safe **parallel collection** (Group B): many threads may
  FETCH concurrently while their writes drain through this one gate.

How it is wired (zero call-site churn for ORM writes):
  Every contending write in the app goes through a SQLAlchemy ORM session and
  ends in ``flush``/``commit`` (verified: ingest, markets, wiki, law, the API
  write endpoints). :func:`register_write_gate` attaches session events so the
  gate is acquired on the session's first ``flush`` (= the moment a write is
  about to hit the file) and released on ``commit``/``rollback``. The handful
  of *raw*-SQL writes on the live engine (VACUUM, an explicit FTS rebuild) take
  the gate explicitly via :func:`write_lock`.

  CRUCIAL: ``before_flush`` only fires for the ORM unit-of-work (``add`` +
  flush). **Bulk DML** — ``Query.delete()`` / ``Query.update()`` and
  ``session.execute(insert()/update()/delete())`` — executes immediately and
  does NOT fire ``before_flush``, so it would grab the SQLite write lock OUTSIDE
  the gate (field log 2026-06-17: the idempotent ``KeywordMention``/
  ``ArticleMentionedPlace``/``ArticleEntity`` ``.delete()`` in ``index_article``
  collided with a long-held writer under the parallel collector → 149+
  ``database is locked`` failures, dropping keyword/link/who indexing). The
  ``do_orm_execute`` listener closes that hole: it acquires the gate for any
  ORM-issued DML write too, so EVERY write — flush or bulk — serialises.

Scope & guards:
  * SQLite only — a server PostgreSQL backend has MVCC + row locks and must not
    be throttled through one mutex (registration is skipped for non-SQLite).
  * ``OO_WRITE_GATE=0`` disables the gate (an escape hatch for diagnosing a
    suspected deadlock in the field; the busy_timeout + retry net still apply).
  * The gate is acquired only around the *write* window, never across network
    I/O — the hot paths fetch first, then write, so the held window is the
    flush→commit of synchronous DB work (verified, no flush-then-fetch).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress

_LOG = logging.getLogger("database.writer")

# Per-session marker (stored in SQLAlchemy's ``Session.info``) recording that
# THIS session has taken the gate, so it is released exactly once on commit or
# rollback — and never by a session/event that did not take it.
_SESSION_FLAG = "_oo_write_gate_held"


class WriterGate:
    """A reentrant, observable serialisation gate for database writers.

    Reentrant *per thread*: a thread already holding the gate (e.g. it has an
    open write transaction on session A) may take it again for a nested write
    (session B on the same thread) without deadlocking — acquire/release are
    balanced by depth. Across *different* threads it is a strict mutex: the
    second thread blocks until the first releases, which is the serialisation.

    Acquire and release for one transaction always happen on the same thread
    (sessions are never shared across threads — the app's rule), so the
    same-thread release contract holds.
    """

    def __init__(self) -> None:
        # ONE lock, shared by the master condition and by every waiter's own
        # condition (see _queue): that is what lets release wake EXACTLY the
        # queue head instead of everyone.
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._owner: int | None = None  # thread ident holding the write window
        self._depth = 0  # reentrant depth for the owner thread
        self._waiters = 0  # threads currently blocked waiting to write
        # Observability (feeds the task-manager System view later; proves
        # serialisation in tests). Plain counters under the condition lock.
        self._grants = 0  # total acquisitions granted
        self._contended = 0  # acquisitions that had to wait for another thread
        self._total_wait_s = 0.0
        self._max_wait_s = 0.0
        self._peak_waiters = 0
        # S2.6 (a): WHO holds it, and for how long. The field's 6,236 s wait had
        # no name attached, so it could not be attributed to a subsystem. Thread
        # NAME only -- a stack on every acquire would be instrumentation on a hot
        # path (the 2026-08-06 lesson); the watchdog captures one on demand.
        self._holder: str | None = None
        self._held_since: float | None = None
        self._max_hold_s = 0.0
        self._max_hold_holder: str | None = None
        self._timeouts = 0  # bounded acquires that gave up (S2.5)
        # S2.6 (c): FIFO handoff. Without it acquire() grants to whichever thread
        # happens to find the gate free, so a looping re-acquirer can starve a
        # waiter indefinitely -- which means max_wait_s measures STARVATION and
        # not a hold, and the 6,236 s figure cannot be read as one long write.
        # Arrival order is the LIST order, and each waiter parks on its OWN
        # condition over the shared lock, so a handoff costs exactly one wakeup.
        self._queue: list[threading.Condition] = []

    def _take(self, me: int) -> None:
        """Grant the window to ``me``. Caller holds ``self._cond``."""
        self._owner = me
        self._depth = 1
        self._grants += 1
        self._holder = threading.current_thread().name
        self._held_since = time.monotonic()

    def acquire(self, timeout: float | None = None) -> bool:
        """Take the write window. Returns True when granted.

        ``timeout`` (S2.5) bounds the wait: ``False`` means the caller did NOT
        get the gate and must not write. The default stays unbounded, so every
        existing call site is byte-identical in behaviour -- a write that waits
        is correct; a write that silently proceeds without the gate is not.
        """
        # Outside the lock: never spawn a thread while holding the write window.
        _maybe_start_watchdog()
        me = threading.get_ident()
        with self._cond:
            if self._owner == me:  # reentrant: same thread, nested write
                self._depth += 1
                return True
            # FIFO (S2.6 c): a free gate may be taken immediately ONLY when no
            # one is already queued. Otherwise this thread would jump the queue,
            # which is exactly how a looping re-acquirer starves a waiter.
            if self._owner is None and not self._queue:
                self._take(me)
                return True
            # Our own condition over the shared lock. MEASURED, not assumed:
            # the obvious FIFO (one shared condition + notify_all) was 5.3x
            # SLOWER end to end at 50 workers x 200 us holds (2543 ms vs the old
            # 482 ms) because every release woke all 49 waiters for one of them
            # to proceed -- a thundering herd on the collector's hot path, which
            # is the very throughput the field report complains about. Waking
            # one costs what the pre-FIFO notify() cost.
            #
            # WHAT FAIRNESS DOES COST, measured on the same bench so the trade is
            # stated rather than implied: fully contended, 50 workers x 200 us,
            # 473 ms -> 550 ms wall (+16%) while the WORST wait falls 458 ms ->
            # 14.6 ms (31x). That is the classic fair-vs-barging trade -- a
            # barging mutex is faster precisely because a running thread re-takes
            # it without a context switch -- and it is the trade S2.6 asks for,
            # since a max_wait_s that measures starvation cannot be read at all.
            # Uncontended (50 us holds) the two are within noise, 113 vs 115 ms,
            # and the real collector is network-bound BETWEEN writes, so the
            # fully-contended figure is the worst case and not the typical one.
            cv = threading.Condition(self._lock)
            self._queue.append(cv)
            self._waiters += 1
            self._contended += 1
            self._peak_waiters = max(self._peak_waiters, self._waiters)
            start = time.monotonic()
            deadline = None if timeout is None else start + timeout
            granted = False
            try:
                while True:
                    if self._owner is None and self._queue and self._queue[0] is cv:
                        granted = True
                        break
                    if deadline is None:
                        cv.wait()
                    else:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        cv.wait(remaining)
            finally:
                self._waiters -= 1
                waited = time.monotonic() - start
                self._total_wait_s += waited
                self._max_wait_s = max(self._max_wait_s, waited)
                with suppress(ValueError):
                    self._queue.remove(cv)
                if granted:
                    self._take(me)
                else:
                    self._timeouts += 1
                    # We may have BEEN the head; whoever is now must be woken, or
                    # nothing ever will (a lost wakeup this branch owns).
                    self._wake_head()
        return granted

    def release(self) -> None:
        me = threading.get_ident()
        with self._cond:
            if self._owner != me:
                # Defensive: only the owner releases. A non-owner call is a
                # no-op (e.g. a rollback event on a session that never wrote).
                return
            self._depth -= 1
            if self._depth == 0:
                if self._held_since is not None:
                    held = time.monotonic() - self._held_since
                    if held > self._max_hold_s:
                        self._max_hold_s = held
                        # Retained AFTER release on purpose: the peak hold is
                        # useless without the name of what held it.
                        self._max_hold_holder = self._holder
                self._owner = None
                self._holder = None
                self._held_since = None
                self._wake_head()

    def _wake_head(self) -> None:
        """Wake EXACTLY the queue head. Caller holds the lock.

        The head is the only thread FIFO permits to take a free gate, so waking
        anyone else is pure cost -- and at 50 workers that cost was measured at
        5.3x the total wall time (see acquire). One wakeup per handoff is what
        the pre-FIFO ``notify()`` cost, so fairness here is not paid for out of
        throughput.
        """
        if self._queue:
            self._queue[0].notify()

    def held_by_current_thread(self) -> bool:
        with self._cond:
            return self._owner == threading.get_ident()

    def _reset_for_tests(self) -> None:
        """Test-only: forcibly clear ownership so a gate leaked by a buggy test
        cannot hang the next one. NEVER call in production — it would abandon a
        real in-flight write window. The per-test guard fixture uses this to
        recover and then fail the offending test loudly."""
        with self._cond:
            self._owner = None
            self._depth = 0
            self._holder = None
            self._held_since = None
            # The queue too: a waiter left behind would sit at the head forever
            # and block every later acquire (FIFO). Each parks on its OWN
            # condition, so every one must be woken by name -- a notify_all on
            # the master condition would reach none of them.
            for cv in self._queue:
                cv.notify_all()
            self._queue.clear()
            self._cond.notify_all()

    def stats(self) -> dict:
        """A point-in-time copy of the gate's counters (honest, no estimates)."""
        with self._cond:
            held_for = (
                None if self._held_since is None else round(time.monotonic() - self._held_since, 4)
            )
            return {
                "held": self._owner is not None,
                "waiters": self._waiters,
                "peak_waiters": self._peak_waiters,
                "grants": self._grants,
                "contended": self._contended,
                "total_wait_s": round(self._total_wait_s, 4),
                "max_wait_s": round(self._max_wait_s, 4),
                # S2.6: the name, not just the number. ``holder``/``held_for_s``
                # are None when the gate is free -- absent state, never a 0 that
                # would read as "held for no time".
                "holder": self._holder,
                "held_for_s": held_for,
                "max_hold_s": round(self._max_hold_s, 4),
                "max_hold_holder": self._max_hold_holder,
                "queued": len(self._queue),
                "timeouts": self._timeouts,
            }

    def _holder_snapshot(self) -> tuple[str | None, float | None, int | None]:
        """(name, held_SINCE, thread ident) under the lock -- for the watchdog.

        The monotonic START, deliberately, not an elapsed time: the watchdog
        identifies "still the same hold" by this value, and an elapsed figure
        would have to be turned back into a start against a DIFFERENT
        ``monotonic()`` reading, which drifts by the delta between the two --
        so every sample would look like a new hold and warn again.
        """
        with self._cond:
            if self._owner is None or self._held_since is None:
                return (None, None, None)
            return (self._holder, self._held_since, self._owner)


# Process-wide singleton: there is exactly one write window for the one store.
write_gate = WriterGate()


def gate_enabled() -> bool:
    """The gate is on by default; ``OO_WRITE_GATE=0`` disables it (escape hatch)."""
    return os.environ.get("OO_WRITE_GATE", "1") != "0"


class WriteGateBusy(RuntimeError):
    """A bounded :func:`write_lock` gave up: the caller did NOT get the gate.

    Raised only when the caller asked for a timeout, so it can never surprise an
    existing unbounded call site. Catching it means "someone else is writing" --
    it is a schedulable condition, not a failure of the write.
    """


@contextmanager
def write_lock(timeout: float | None = None) -> Iterator[None]:
    """Serialise a raw-SQL write on the live engine through the same gate.

    Use this for the few writes that do NOT go through an ORM flush (VACUUM, an
    explicit FTS rebuild). A no-op when the gate is disabled. Reentrant, so it
    composes with the session-event acquisition on the same thread.

    ``timeout`` (S2.5) bounds the wait and raises :class:`WriteGateBusy` rather
    than proceeding: a caller that must not block forever gets to record an
    honest skip and move on. The default is UNBOUNDED -- a real write waits, and
    a write that ran without the gate would be the data-loss bug this exists to
    prevent.
    """
    if not gate_enabled():
        yield
        return
    if not write_gate.acquire(timeout=timeout):
        s = write_gate.stats()
        raise WriteGateBusy(
            f"write gate busy after {timeout}s "
            f"(holder={s.get('holder')!r}, held_for_s={s.get('held_for_s')}, "
            f"queued={s.get('queued')})"
        )
    try:
        yield
    finally:
        write_gate.release()


def write_gate_stats() -> dict:
    """Public accessor for the gate's observability counters."""
    return write_gate.stats()


# --- S2.6: the watchdog that gives a long hold a name ---------------------- #
#
# Sampling, NOT instrumentation on the acquire path: capturing a stack on every
# acquire would put a traceback build inside the write window (the 2026-08-06
# lesson -- an instrument on a hot path is a load source). This thread wakes on
# a slow cadence, reads the holder under the lock, and only when a hold has
# ALREADY exceeded the threshold does it pay for a stack, ONCE per hold.

_WATCHDOG_STARTED = False
_WATCHDOG_LOCK = threading.Lock()
_WATCHDOG_CONSIDERED = False


def _maybe_start_watchdog() -> None:
    """Arm the watchdog on the FIRST gate acquisition, never at import.

    Placement is the whole point, and a test (test_database_session.py::
    test_import_has_no_side_effects) caught it being wrong: the watchdog used to
    start from register_write_gate(), whose own docstring said "rather than at
    import" -- but that function is CALLED at import from session.py, so simply
    importing src.database.models spawned a monitoring thread. A comment
    asserting a property is not the property.

    First-acquire is the honest trigger because watchdog_tick reads the GATE's
    holder and nothing else: a hold cannot exist before an acquire, so arming
    here loses no coverage while a process that never writes (a migration, a
    CLI, an import in a test) pays for no thread at all.

    One global read on the steady-state hot path. The env is consulted exactly
    once per process -- including when the watchdog is DISABLED, which is why
    this flag is separate from _WATCHDOG_STARTED (that one stays False forever
    in the disabled case, so keying on it would re-read the environment and
    re-take a lock on every single write).
    """
    global _WATCHDOG_CONSIDERED
    if _WATCHDOG_CONSIDERED:
        return
    _WATCHDOG_CONSIDERED = True
    # A race here just calls a function that is already idempotent under its
    # own lock; it can never start two threads.
    start_write_gate_watchdog()


def _watchdog_threshold_s() -> float:
    try:
        return max(0.0, float(os.getenv("OO_WRITE_GATE_WARN_S", "") or 60.0))
    except (TypeError, ValueError):
        return 60.0


def _watchdog_interval_s() -> float:
    try:
        return max(0.5, float(os.getenv("OO_WRITE_GATE_WATCH_INTERVAL_S", "") or 15.0))
    except (TypeError, ValueError):
        return 15.0


def _holder_stack(ident: int | None) -> str:
    """A stack for the holding thread, captured ON DEMAND. Best-effort."""
    if ident is None:
        return ""
    try:
        import sys
        import traceback

        frame = sys._current_frames().get(ident)
        if frame is None:
            return ""
        return "".join(traceback.format_stack(frame)[-12:])
    except Exception:  # noqa: BLE001 - a diagnostic must never raise
        return ""


def watchdog_tick(gate: WriterGate, warned_since: float | None) -> float | None:
    """One watchdog sample. Returns the new ``warned_since`` for the next tick.

    Split out of the loop so the property that matters -- ONE warning per hold,
    not one per sample -- is testable without a thread and a real clock.
    ``warned_since`` is the hold's own start time, which is what distinguishes
    "still the same long hold" from "a new one that is also long".
    """
    holder, started, ident = gate._holder_snapshot()
    if started is None or holder is None:
        return None  # gate free: the next long hold warns again
    held_for = time.monotonic() - started
    if held_for < _watchdog_threshold_s() or warned_since == started:
        return warned_since
    s = gate.stats()
    _LOG.warning(
        "write gate held %.1fs by %r (waiters=%s, queued=%s) -- stack:\n%s",
        held_for,
        holder,
        s.get("waiters"),
        s.get("queued"),
        _holder_stack(ident),
    )
    return started


def _watchdog_loop(stop: threading.Event) -> None:
    interval = _watchdog_interval_s()
    warned_since: float | None = None
    while not stop.wait(interval):
        try:
            warned_since = watchdog_tick(write_gate, warned_since)
        except Exception:  # noqa: BLE001 - the watchdog must never take the app down
            _LOG.debug("write gate watchdog tick failed", exc_info=True)


def start_write_gate_watchdog() -> bool:
    """Start the long-hold watchdog once. ``OO_WRITE_GATE_WATCHDOG=0`` disables.

    Idempotent and daemon. Armed lazily by :func:`_maybe_start_watchdog` on the
    first gate acquisition, never at import: ``register_write_gate`` is itself
    called at import time, so starting from there spawned a thread merely by
    importing the models.
    """
    global _WATCHDOG_STARTED
    if os.environ.get("OO_WRITE_GATE_WATCHDOG", "1") == "0":
        return False
    with _WATCHDOG_LOCK:
        if _WATCHDOG_STARTED:
            return False
        stop = threading.Event()
        t = threading.Thread(
            target=_watchdog_loop, args=(stop,), daemon=True, name="oo-write-gate-watchdog"
        )
        t.start()
        _WATCHDOG_STARTED = True
    return True


def release_if_held(session) -> None:
    """Belt-and-braces release for a session that may still hold the gate.

    The session events release on commit/rollback in the common path; this is
    the safety net called from the scoped helpers' ``finally`` AFTER the session
    is closed (so any open write transaction is already resolved). Idempotent:
    a no-op if an event already released (the per-session flag is gone).
    """
    if session.info.pop(_SESSION_FLAG, False):
        write_gate.release()


_REGISTERED = False


def register_write_gate(session_factory) -> None:
    """Attach the gate to a SQLAlchemy ``sessionmaker`` (or ``Session`` class).

    Idempotent (a module flag) so re-importing the session module cannot stack
    duplicate listeners. Skipped entirely when the gate is disabled.
    """
    global _REGISTERED
    if _REGISTERED:
        return
    if not gate_enabled():
        _LOG.info("write gate disabled (OO_WRITE_GATE=0); writers rely on busy_timeout + retry")
        _REGISTERED = True
        return

    from sqlalchemy import event

    event.listen(session_factory, "before_flush", _on_before_flush)
    # Bulk DML (Query.delete()/update(), session.execute(insert/update/delete))
    # does NOT fire before_flush — it executes immediately. Acquire the gate for
    # those writes too, or they grab the SQLite write lock outside the gate and
    # collide with a gated writer (the 2026-06-17 "database is locked" storm).
    event.listen(session_factory, "do_orm_execute", _on_orm_execute)
    # Release on transaction END (commit, rollback, OR close) rather than on
    # commit/rollback alone: a session that flushes then is CLOSED without
    # committing (a common test/abandon pattern) does NOT reliably emit
    # after_rollback in SQLAlchemy 2.0, but its outermost transaction ending on
    # close DOES emit after_transaction_end — so this is the leak-proof hook.
    event.listen(session_factory, "after_transaction_end", _on_after_transaction_end)
    # S2.6: a long hold names itself in the log. The watchdog is NOT started
    # here -- this function runs at import (session.py calls it at module level),
    # and importing must not spawn a monitoring thread. It arms on the first
    # acquire() instead; see _maybe_start_watchdog.
    _REGISTERED = True


def _on_before_flush(session, _flush_context, _instances) -> None:
    # First write of this session's transaction is about to hit the file —
    # take the write window. Idempotent within the transaction via the flag.
    if not session.info.get(_SESSION_FLAG):
        write_gate.acquire()
        session.info[_SESSION_FLAG] = True


def _on_orm_execute(orm_execute_state) -> None:
    # Fires for EVERY ORM-issued statement (reads included). Take the write
    # window only for DML writes — a read must never gate (WAL lets readers pass
    # a writer). Idempotent within the transaction via the per-session flag, so a
    # flush that already acquired (before_flush) is not re-counted, and a bulk
    # delete followed by an INSERT flush holds ONE continuous window.
    if not (
        orm_execute_state.is_insert
        or orm_execute_state.is_update
        or orm_execute_state.is_delete
    ):
        return
    session = orm_execute_state.session
    if not session.info.get(_SESSION_FLAG):
        write_gate.acquire()
        session.info[_SESSION_FLAG] = True


def _on_after_transaction_end(session, transaction) -> None:
    # Only the OUTERMOST transaction's end releases the gate (savepoints/nested
    # transactions have a parent and must not release the outer window). Clearing
    # the flag here lets the next transaction on a reused session re-acquire.
    if transaction.parent is None and session.info.pop(_SESSION_FLAG, False):
        write_gate.release()
