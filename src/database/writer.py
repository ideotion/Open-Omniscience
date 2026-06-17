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
from contextlib import contextmanager

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
        self._cond = threading.Condition()
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

    def acquire(self) -> None:
        me = threading.get_ident()
        with self._cond:
            if self._owner == me:  # reentrant: same thread, nested write
                self._depth += 1
                return
            if self._owner is not None:
                # Another thread holds the write window — queue behind it.
                self._waiters += 1
                self._contended += 1
                self._peak_waiters = max(self._peak_waiters, self._waiters)
                start = time.monotonic()
                while self._owner is not None:
                    self._cond.wait()
                self._waiters -= 1
                waited = time.monotonic() - start
                self._total_wait_s += waited
                self._max_wait_s = max(self._max_wait_s, waited)
            self._owner = me
            self._depth = 1
            self._grants += 1

    def release(self) -> None:
        me = threading.get_ident()
        with self._cond:
            if self._owner != me:
                # Defensive: only the owner releases. A non-owner call is a
                # no-op (e.g. a rollback event on a session that never wrote).
                return
            self._depth -= 1
            if self._depth == 0:
                self._owner = None
                self._cond.notify()  # wake one waiter (longest-waiting first)

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
            self._cond.notify_all()

    def stats(self) -> dict:
        """A point-in-time copy of the gate's counters (honest, no estimates)."""
        with self._cond:
            return {
                "held": self._owner is not None,
                "waiters": self._waiters,
                "peak_waiters": self._peak_waiters,
                "grants": self._grants,
                "contended": self._contended,
                "total_wait_s": round(self._total_wait_s, 4),
                "max_wait_s": round(self._max_wait_s, 4),
            }


# Process-wide singleton: there is exactly one write window for the one store.
write_gate = WriterGate()


def gate_enabled() -> bool:
    """The gate is on by default; ``OO_WRITE_GATE=0`` disables it (escape hatch)."""
    return os.environ.get("OO_WRITE_GATE", "1") != "0"


@contextmanager
def write_lock() -> Iterator[None]:
    """Serialise a raw-SQL write on the live engine through the same gate.

    Use this for the few writes that do NOT go through an ORM flush (VACUUM, an
    explicit FTS rebuild). A no-op when the gate is disabled. Reentrant, so it
    composes with the session-event acquisition on the same thread.
    """
    if not gate_enabled():
        yield
        return
    write_gate.acquire()
    try:
        yield
    finally:
        write_gate.release()


def write_gate_stats() -> dict:
    """Public accessor for the gate's observability counters."""
    return write_gate.stats()


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
