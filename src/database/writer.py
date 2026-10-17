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
  ORM-issued DML write too, so both the unit of work and ORM-issued DML serialise.

  A TEXTUAL write (``session.execute(text("DELETE ..."))``) is gated too (the deep read of E3, 2026-10-06): ``is_insert`` and its two
  siblings are False for ``text()``, so ``_is_textual_write`` reads the statement's first word (a ``WITH`` that carries a write
  counts). A write on the session's CONNECTION (``session.connection().execute``) or on an engine connection is Core and is not seen
  by any hook; the repair does not rely on the gate for those, it compares the file's data version before it switches.

  THE ONE THING THESE TWO HOOKS CANNOT SEE, stated because this docstring used to
  claim they saw everything (found 2026-09-11, finding C8): the LEGACY BULK
  operations — ``bulk_update_mappings``, ``bulk_insert_mappings``,
  ``bulk_save_objects`` — write through ``session_transaction.connection(...)``
  directly (``sqlalchemy.orm.bulk_persistence._bulk_update`` →
  ``persistence._emit_update_statements``) and fire NEITHER ``before_flush`` NOR
  ``do_orm_execute``. They reach the file with this gate NOT held. Reproduced: two
  threads, one holding the gate and the SQLite write lock past ``busy_timeout``, the
  other issuing a ``bulk_update_mappings``, raised a raw ``sqlite3.OperationalError:
  database is locked`` every run — the exact data-loss class this module exists to
  prevent.

  SQLAlchemy emits no event for them, so the gate cannot be extended to cover them
  from inside: every such call site must take :func:`write_lock` EXPLICITLY, and
  ``tests/test_bulk_write_gate_ratchet.py`` is the source-level guard that stops the
  next one being added without it (the same shape as the socket-importer ratchet,
  and for the same reason — no runtime hook exists to catch it).

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
import re
import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager, suppress
from typing import Any

from src.monitoring import holder_state, thread_usage
from src.monitoring.secret_scrub import log_failure, scrubbed_name

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
        # The holder thread's CPU time and kernel counters at the moment it was granted the window (``thread_usage.sample``), so the release
        # of a LONG hold can say what the thread did over the whole of it: worked (CPU close to the seconds) or waited. Written and read
        # only by the owner thread, under the lock it already holds.
        self._hold_usage: thread_usage.Sample | None = None
        # WHERE THE HOLD'S SECONDS WENT (``hold_breakdown``): the seconds the holder thread spent inside INSERT statements, savepoint
        # statements, any other statement and commits, in the order of ``_SPENT_KINDS``. Written ONLY by the owner thread, by the engine and
        # session listeners below (each checks ``_owner`` first, so a statement of any other thread is never counted), without the lock: a
        # float added to a list slot by the one thread that owns it. ``_spent_for`` is the grant (``_grants``) the figures belong to, so a new
        # hold starts from zero at its first statement and a hold with none costs nothing; ``_running`` is the statement or commit in
        # progress, (kind, start), so the watchdog can count a statement that has not ended yet.
        self._spent = [0.0] * len(_SPENT_KINDS)
        self._spent_for = 0
        self._running: tuple[int, float] | None = None
        self._max_hold_s = 0.0
        self._max_hold_holder: str | None = None
        # Cumulative HELD time, so a soak can ask "what share of the run was the single
        # writer occupied?" -- a different question from ``_total_wait_s``, which is
        # thread-seconds of CONTENTION and is large both when many workers write briefly
        # and when one writes for hours. Free: the release path already computes ``held``
        # for the max, and this is one float add on that same line, inside a lock it
        # already holds (the 2026-08-06 rule about instruments on hot paths).
        self._total_held_s = 0.0
        # WHO used the window, by thread name: [holds, held_s, longest_s]. At most ``_HOLDER_NAMES_MAX`` names (a thread pool names
        # its workers, and a restart names a new set), the rest summed under ``_OTHER_HOLDERS``, so the table is bounded whatever the
        # app does; one dict lookup and three adds inside the lock the release already holds.
        self._by_holder: dict[str, list[float]] = {}
        self._timeouts = 0  # bounded acquires that gave up (S2.5)
        # WATCHED HOLDERS (2026-10-06): the holds of ONE thread, accumulated until it reads them.
        # ``_total_held_s`` is the whole process's, so no per-drain share can be taken from it:
        # another thread's holds inside the interval are in it too. A thread asks to be watched
        # (``watch``, keyed by its ident, never its name: two threads can share a name, as a
        # restart that overlaps a long drain does), and reads its own figures (``take_watched``),
        # which also removes the entry, so the table holds only the threads between a watch and a
        # take. The cost on the acquire and release paths is one dict lookup inside the lock they
        # already hold.
        self._watched: dict[int, dict[str, float]] = {}
        # S2.6 (c): FIFO handoff. Without it acquire() grants to whichever thread
        # happens to find the gate free, so a looping re-acquirer can starve a
        # waiter indefinitely -- which means max_wait_s measures STARVATION and
        # not a hold, and the 6,236 s figure cannot be read as one long write.
        # Arrival order is the LIST order, and each waiter parks on its OWN
        # condition over the shared lock, so a handoff costs exactly one wakeup.
        self._queue: list[threading.Condition] = []

    def _take(self, me: int) -> None:
        """Grant the window to ``me``. Caller holds ``self._lock``."""
        self._owner = me
        self._depth = 1
        self._running = None  # a raw connection's commit has no end event: the last hold's statement is not this hold's (read by the sampler under this lock)
        self._grants += 1
        self._holder = threading.current_thread().name
        self._held_since = time.monotonic()
        self._hold_usage = thread_usage.sample()  # under a microsecond (thread_usage's docstring has the measurement)
        watched = self._watched.get(me)
        if watched is not None:
            watched["grants"] += 1

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
        with self._lock:
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
        # (holder name, seconds, start, usage at the grant) of the hold that ended on THIS call, for the line written after the lock is dropped.
        released: tuple[str | None, float, float | None, thread_usage.Sample | None, dict[str, float] | None] | None = None
        with self._lock:
            if self._owner != me:
                # Defensive: only the owner releases. A non-owner call is a
                # no-op (e.g. a rollback event on a session that never wrote).
                return
            self._depth -= 1
            if self._depth == 0:
                held = None
                holder = self._holder
                started = self._held_since
                usage0 = self._hold_usage
                self._hold_usage = None
                breakdown: dict[str, float] | None = None
                if self._held_since is not None:
                    held = time.monotonic() - self._held_since
                    if held >= HOLD_RECORD_S:  # a hold the journal keeps: where its seconds went, while the ledger is still this hold's
                        breakdown = self._breakdown_locked(held)
                    # Outermost release only (``_depth == 0``), so a reentrant nested write
                    # is counted once rather than once per level.
                    self._total_held_s += held
                    if held > self._max_hold_s:
                        self._max_hold_s = held
                        # Retained AFTER release on purpose: the peak hold is
                        # useless without the name of what held it.
                        self._max_hold_holder = self._holder
                    self._account_holder_locked(holder, held)
                self._owner = None
                self._holder = None
                self._held_since = None
                self._wake_head()
                # AFTER the gate is free and the next waiter woken: this bookkeeping can never
                # leave the gate held, whatever it does.
                if held is not None:
                    released = (holder, held, started, usage0, breakdown)
                    watched = self._watched.get(me)
                    if watched is not None:
                        watched["held_s"] += held
                        if held > watched["longest_s"]:
                            watched["longest_s"] = held
        # OUTSIDE the lock: a log handler that blocks (a full pipe, a slow terminal) must not hold the gate's lock, and the gate is
        # already free and its next waiter woken. The cheap comparison first, so a normal hold (milliseconds) never reads the environment.
        if released is not None:
            if released[1] >= _RELEASE_LINE_FLOOR_S:
                _log_long_release(released[0], released[1])
            if released[1] >= HOLD_RECORD_S:  # a separate comparison: the journal's threshold is its own, not the log line's
                _note_hold_end(*released)

    def _account_holder_locked(self, name: str | None, held: float) -> None:
        """Add one finished hold to the per-holder table. Caller holds the lock."""
        key = name if isinstance(name, str) and name else "(unnamed)"
        row = self._by_holder.get(key)
        if row is None:
            if len(self._by_holder) >= _HOLDER_NAMES_MAX:
                key = _OTHER_HOLDERS
                row = self._by_holder.get(key)
            if row is None:
                row = self._by_holder[key] = [0.0, 0.0, 0.0]
        row[0] += 1
        row[1] += held
        if held > row[2]:
            row[2] = held

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
        with self._lock:
            return self._owner == threading.get_ident()

    def _work_begins(self, kind: int) -> None:
        """The owner thread starts a statement (``kind`` indexes ``_SPENT_KINDS``) or a commit. Called by the listeners, which have checked
        that the calling thread owns the gate. A commit still open (a raw connection's commit has no end event) is closed here, at the
        start of the next work, which makes it an upper bound; a session's commit is closed exactly by :meth:`_work_ends`."""
        now = time.monotonic()
        if self._spent_for != self._grants:
            self._spent[:] = _NO_SPENT
            self._spent_for = self._grants
        else:
            running = self._running
            if running is not None:
                self._spent[running[0]] += now - running[1]
        self._running = (kind, now)

    def _work_ends(self) -> None:
        """The statement or commit the owner thread was in has ended (after the cursor, after a failed statement, after the session's commit)."""
        running = self._running
        if running is not None and self._spent_for == self._grants:
            self._running = None
            self._spent[running[0]] += time.monotonic() - running[1]

    def _breakdown_locked(self, held: float) -> dict[str, float]:
        """The hold's ``held`` seconds split by where they went, in seconds to a tenth. Caller holds the lock. Work still running is counted up
        to now; what no measured statement or commit covers is ``between_statements``: Python work, the driver calls the listeners cannot see
        (a raw connection's), waits, and the SQLite work of the rows a SELECT hands back AFTER its first (they are stepped while the caller
        reads them, after the statement's end event)."""
        spent = list(self._spent) if self._spent_for == self._grants else [0.0] * len(_SPENT_KINDS)
        running = self._running if self._spent_for == self._grants else None
        if running is not None and self._held_since is not None:
            spent[running[0]] += max(0.0, self._held_since + held - running[1])
        return {
            **{name: round(spent[i], 1) for i, name in enumerate(_SPENT_KINDS)},
            "between_statements": round(max(0.0, held - sum(spent)), 1),
        }

    def hold_breakdown(self, started: float) -> dict[str, float] | None:
        """Where the seconds of the hold that began at ``started`` (the gate's own ``_held_since``) have gone so far, or ``None`` when that hold is
        over or another has begun. A sample for the watchdog's journal entry: a statement that ends while it is taken can be missed or counted
        twice (one statement), the figure written when the hold ends is exact."""
        with self._lock:
            if self._held_since is None or self._held_since != started:
                return None
            return self._breakdown_locked(time.monotonic() - started)

    def waiters(self) -> int:
        """Threads blocked RIGHT NOW waiting to write: the one number a long holder needs to know whether to let go.

        A snapshot under the gate's own lock; it can change the moment it returns, which is fine for the one question it answers
        ("is anyone waiting behind this batch?"). A holder that commits on a non-zero answer never starves anyone, because the
        gate is first-in-first-out and the waiter is handed the window the instant the batch's transaction ends.
        """
        with self._lock:
            return self._waiters

    def _reset_for_tests(self) -> None:
        """Test-only: forcibly clear ownership so a gate leaked by a buggy test
        cannot hang the next one. NEVER call in production — it would abandon a
        real in-flight write window. The per-test guard fixture uses this to
        recover and then fail the offending test loudly."""
        with self._lock:
            self._owner = None
            self._depth = 0
            self._holder = None
            self._held_since = None
            # Deliberately NOT resetting the counters: they are process-cumulative by
            # contract and a test that leaked the gate has not un-held it.
            # The queue too: a waiter left behind would sit at the head forever
            # and block every later acquire (FIFO). Each parks on its OWN
            # condition, so every one must be woken by name -- a notify_all on
            # the master condition would reach none of them.
            for cv in self._queue:
                cv.notify_all()
            self._queue.clear()
            self._cond.notify_all()

    def watch(self, ident: int) -> None:
        """Start (or restart, from zero) keeping the holds of the thread with this ident."""
        with self._lock:
            self._watched[ident] = {"grants": 0, "held_s": 0.0, "longest_s": 0.0}

    def take_watched(self, ident: int) -> dict[str, float] | None:
        """Read what the thread held since it was watched, and stop watching it; ``None`` if it
        was not being watched.

        A hold still in flight is not in it (it is added at release), exactly as ``stats``'s
        ``total_held_s`` says of itself."""
        with self._lock:
            return self._watched.pop(ident, None)

    def stats(self) -> dict:
        """A point-in-time copy of the gate's counters (honest, no estimates).

        The thread names in it (``holder``, ``max_hold_holder``, ``by_holder[].holder``) are copied raw under the gate's lock and
        scrubbed of the passphrases the process holds AFTER it is released: ``served_cache.change_probe`` reads these stats two or
        three times per cached read, and the scrub (a few microseconds a name) is not work to do while a writer waits on the lock."""
        with self._lock:
            held_for = (
                None if self._held_since is None else round(time.monotonic() - self._held_since, 4)
            )
            holder, max_hold_holder = self._holder, self._max_hold_holder
            # Who used the window, most seconds first: holds finished, seconds held and the longest hold, by thread name.
            # Cumulative like ``total_held_s``; a name past the table's bound is summed under "(others)". Seconds OTHERS waited
            # are not attributed to a holder: under FIFO handoff a wait spans several holders, and ``total_wait_s`` stays the
            # one honest figure for it. ROWS, not a dict keyed by name: a thread name is the one string here a caller chooses
            # (``oo-osm-{code}``), and a dict KEY is not scrubbed by the bundle's net, where a row's VALUE is, so the name is
            # scrubbed here, at the source, before it is anywhere.
            by_holder = [
                (name, int(r[0]), round(r[1], 3), round(r[2], 3))
                for name, r in sorted(self._by_holder.items(), key=lambda kv: kv[1][1], reverse=True)
            ]
            out: dict[str, Any] = {
                "held": self._owner is not None,
                "waiters": self._waiters,
                "peak_waiters": self._peak_waiters,
                "grants": self._grants,
                "contended": self._contended,
                "total_wait_s": round(self._total_wait_s, 4),
                "max_wait_s": round(self._max_wait_s, 4),
                # Accumulated on RELEASE, so a hold in flight right now is NOT in it --
                # ``held_for_s`` beside it is that hold, and adding them would be the
                # reader's decision, not a number this method may invent.
                "total_held_s": round(self._total_held_s, 4),
                # S2.6: the name, not just the number. ``holder``/``held_for_s``
                # are None when the gate is free -- absent state, never a 0 that
                # would read as "held for no time".
                "holder": None,
                "held_for_s": held_for,
                "max_hold_s": round(self._max_hold_s, 4),
                "max_hold_holder": None,
                "queued": len(self._queue),
                "timeouts": self._timeouts,
                "by_holder": [],
            }
        out["pool_wait_before_gate"] = pool_wait_stats()
        out["holder"] = _scrubbed_name(holder)
        out["max_hold_holder"] = _scrubbed_name(max_hold_holder)
        out["by_holder"] = [
            {"holder": _scrubbed_name(name), "holds": holds, "held_s": held_s, "longest_s": longest_s}
            for name, holds, held_s, longest_s in by_holder
        ]
        return out

    def _holder_snapshot(self) -> tuple[str | None, float | None, int | None]:
        """(name, held_SINCE, thread ident) under the lock -- for the watchdog.

        The monotonic START, deliberately, not an elapsed time: the watchdog
        identifies "still the same hold" by this value, and an elapsed figure
        would have to be turned back into a start against a DIFFERENT
        ``monotonic()`` reading, which drifts by the delta between the two --
        so every sample would look like a new hold and warn again.
        """
        with self._lock:
            if self._owner is None or self._held_since is None:
                return (None, None, None)
            return (self._holder, self._held_since, self._owner)


# Process-wide singleton: there is exactly one write window for the one store.
#: What a hold's statements are sorted into, in the order of the gate's ``_spent`` list: ``insert`` (any INSERT, an executemany is one statement),
#: ``savepoint`` (SAVEPOINT, RELEASE and ROLLBACK TO), ``other_statement`` (every other statement: reads, UPDATE, DELETE, PRAGMA) and ``commit``
#: (the engine's commit event to the session's after-commit, or to the next work or the release for a raw connection's). The journal's
#: ``seconds_by`` carries these and ``between_statements`` (what no measured statement covers: Python, waits, a raw connection's driver calls and the SQLite work of a
#: SELECT's rows after its first, which runs as the caller reads them, so a read's seconds land THERE and not in ``other_statement``). WHAT THE FIVE ANSWER: the 16 Oct bundles' holds were INSERT INTO articles 58.6 %,
#: SAVEPOINT 11.5 % and a read of mention rows inside the hold about 16 %, from the slow-query ring; this puts the split on the hold itself.
_SPENT_KINDS = ("insert", "savepoint", "other_statement", "commit")
_INSERT, _SAVEPOINT, _OTHER, _COMMIT = range(4)
_NO_SPENT = (0.0,) * len(_SPENT_KINDS)

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


def write_gate_waiters() -> int:
    """How many threads are blocked waiting for the write window right now (see ``WriterGate.waiters``)."""
    return write_gate.waiters()


def watch_holder(ident: int) -> None:
    """Ask the gate to keep the holds of the thread with this ident (see ``take_watched_holder``)."""
    write_gate.watch(ident)


def take_watched_holder(ident: int) -> dict[str, float] | None:
    """What the watched thread held since ``watch_holder`` (grants, held_s, longest_s), once."""
    return write_gate.take_watched(ident)


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


#: A hold of this many seconds is kept in the storage-events journal (``monitoring/storage_events.py``, the Diagnostics zip's
#: ``storage-events.json``): opened by the watchdog when it first samples the hold at or past it, updated on every sample, closed at the
#: release. WHAT IT PROTECTS: the journal's twenty places and the zip's byte budget. A hold under thirty seconds is a slow batch (the
#: re-index's write window is bounded by ``OO_REINDEX_HOLD_TARGET_S``, 10 s), a hold past it is the shape of the stalls the 30 Sep crash
#: read found (60 to 175 s), and the watchdog's own 15-second sample means a hold is first seen between 30 and 45 s.
HOLD_RECORD_S = 30.0

#: The per-holder table's bound: thread names past it are summed under ``(others)``. WHAT IT PROTECTS: the gate's memory and the size
#: of ``write-gate``'s ``by_holder`` in the zip (a worker pool and every restart name new threads).
_HOLDER_NAMES_MAX = 16
_OTHER_HOLDERS = "(others)"

#: Holds shorter than this never reach the release line's threshold check (which reads the environment): the line is for holds of
#: the watchdog threshold, 60 s by default, and a hold of milliseconds is the normal case on a path every writer takes.
_RELEASE_LINE_FLOOR_S = 1.0


def _log_long_release(holder: str | None, held: float) -> None:
    """Say how long a hold that reached the watchdog threshold actually lasted, once, when it ends.

    THE WATCHDOG CANNOT SAY IT. It warns once per hold, at the first sample at or past the threshold, so its "held 66.0s" is when the
    hold was noticed (the threshold plus up to one tick): a hold of 40 minutes logs the same line as one of 61 seconds, and the logs of
    the 30 Sep crash read "60.3 to 73.3 s" for holds nobody could size. The gate keeps only the longest hold of the process
    (``max_hold_s``), so every other length was lost. This line is the length of every hold at or past the threshold (and at least
    ``_RELEASE_LINE_FLOOR_S``, so a threshold set under one second does not make every millisecond hold speak).

    Only the holder's thread name (with the passphrases the process holds taken out of it: a name can be chosen by a request) and the
    seconds are written: no exception, no statement, no engine text, so a hold that ended in an error says no more than one that did not.
    Never raises."""
    with suppress(Exception):
        if held >= _watchdog_threshold_s():
            _LOG.warning("write gate released after %.1fs by %r", held, _scrubbed_name(holder))


def _scrubbed_name(name: str | None) -> str | None:
    """A thread name as the diagnostics may show it: the passphrases the process holds taken out. A name is a code constant or a
    catalogue/request key, so none is expected to carry one; this keeps it true if one ever does. Never raises."""
    try:
        return scrubbed_name(name)  # the one helper (secret_scrub); None stays None
    except Exception:  # noqa: BLE001 - a name that cannot be checked is not shown
        return "(name withheld)"


#: The start (monotonic) of the hold the journal was last opened for, so a sample updates the open entry and never opens a second one.
_JOURNALED_HOLD: float | None = None


#: The most characters one frame of a hold's ``frames`` is written with. WHAT IT PROTECTS: the storage-events slot's byte budget, which counts
#: three frames on each of the twenty kept holds at this width instead of the journal's 160-character string cut. IT IS A MEASURED MAXIMUM, not a
#: choice, with NO slack: the longest ``module:function:line`` any function under ``src/`` can produce is 79 characters (``src.ai_layer.
#: perception_extract_job:_perception_extract_sleep_interruptible`` and a three-digit line), and ``tests/test_holder_state.py`` walks every
#: module's names and fails BOTH ways: on a function whose frame would be wider than this (the fix is to raise it and re-measure the slot) and
#: when this is wider than any frame can be (lower it: the bytes are the budget's). So a frame is never cut in practice and the budget cannot be
#: wrong by a long name. A frame that WERE longer (a function made by ``exec``, say) ends in an ellipsis, as the journal's own cut does, so a cut
#: is never mistaken for a whole name. (It was 90 in the first cut of this record: eleven characters nothing had measured, a margin, which is
#: what a measured maximum is not.)
FRAME_CHARS = 79


def _app_frames(ident: int | None, limit: int = 3) -> list[str]:
    """The innermost ``limit`` frames of app code (``src.*``, this module excluded) of the thread with this ident, as
    ``module:function:line``: names and numbers, no argument and no source text, each at most :data:`FRAME_CHARS` characters.
    Best-effort, [] when the thread is gone."""
    out: list[str] = []
    try:
        import sys

        frame = sys._current_frames().get(ident) if ident is not None else None
        while frame is not None and len(out) < limit:
            module = str(frame.f_globals.get("__name__", ""))
            if module.startswith("src.") and module != __name__:
                text = f"{module}:{frame.f_code.co_name}:{frame.f_lineno}"
                out.append(text if len(text) <= FRAME_CHARS else text[: FRAME_CHARS - 1] + "…")
            frame = frame.f_back
    except Exception:  # noqa: BLE001 - a diagnostic must never raise
        return out
    return out


#: Where a held window's thread is, read from its INNERMOST matching frame: ``(module, function) -> phase``. Sampling only (the watchdog's tick,
#: once a hold is past :data:`HOLD_RECORD_S`), so it costs nothing on the acquire path. WHAT IT ANSWERS: whether a long hold was spent
#: waiting for a pooled connection, inside the driver's execute or commit, or in Python. It names the library's own functions, so a
#: library that renames one makes the phase "python" rather than a wrong one; ``tests/test_write_gate_phase.py`` pins that every name
#: here still exists in the installed SQLAlchemy and in ``pool_reserve``, so a version bump that moves one fails a test instead of
#: quietly misreporting.
_PHASE_AT: dict[tuple[str, str], str] = {
    ("sqlalchemy.pool.impl", "_do_get"): "pool-wait",
    ("sqlalchemy.util.queue", "get"): "pool-wait",
    ("src.database.pool_reserve", "acquire"): "pool-wait",
    ("sqlalchemy.engine.default", "do_execute"): "execute",
    ("sqlalchemy.engine.default", "do_executemany"): "execute",
    ("sqlalchemy.engine.default", "do_execute_no_params"): "execute",
    ("sqlalchemy.engine.default", "do_commit"): "commit",
    ("sqlalchemy.engine.default", "do_rollback"): "commit",
}
#: The most frames one classification walks. WHAT IT PROTECTS: the watchdog's tick from a pathological stack; a stack this deep is "python".
_PHASE_FRAMES = 400

#: How many watchdog samples of the CURRENT long hold fell in each phase (cleared when a new hold is first sampled); written by the watchdog thread only.
_PHASE_SAMPLES: dict[str, int] = {}


def _phase_of(frame: Any) -> str:
    """The phase of one thread's innermost-matching frame (``python`` when none of the table's functions is on its stack)."""
    walked = 0
    while frame is not None and walked < _PHASE_FRAMES:
        hit = _PHASE_AT.get((str(frame.f_globals.get("__name__", "")), frame.f_code.co_name))
        if hit is not None:
            return hit
        frame = frame.f_back
        walked += 1
    return "python"


def thread_phases(idents: Iterable[int | None]) -> dict[int, str | None]:
    """:func:`thread_phase` for several threads from ONE snapshot of the interpreter's frames (the pin report asks for up to a handful
    at once, and a snapshot per thread would read the stacks at different instants). A thread that is gone, or an ident that is
    ``None``, maps to ``None``. Best-effort, never raises: when the snapshot itself fails every ident maps to ``None``."""
    wanted = [i for i in idents if i is not None]
    out: dict[int, str | None] = dict.fromkeys(wanted)
    frames: dict[int, Any] | None = None
    frame: Any = None
    try:
        import sys

        frames = sys._current_frames()
        for ident in wanted:
            frame = frames.get(ident)
            out[ident] = _phase_of(frame) if frame is not None else None
    except Exception:  # noqa: BLE001 - a diagnostic must never raise
        return dict.fromkeys(wanted)
    finally:
        # The snapshot holds THIS function's own frame (the calling thread's innermost), and this frame holds the snapshot: a reference
        # cycle that keeps every frame in the chain, and every local in them, alive until the next collection. The watchdog asks every
        # 15 s of a long hold, so the names are dropped as the function ends.
        del frames, frame
    return out


def thread_phase(ident: int | None) -> str | None:
    """``pool-wait``, ``execute``, ``commit`` or ``python`` for the thread with this ident, from its innermost matching frame; ``None`` when
    the thread is gone. Best-effort, never raises. Public because the storage guard's pin report reads it for the threads that hold a
    checkout, and the gate-hold journal for the thread that holds the gate: one classifier, so the two records agree."""
    if ident is None:
        return None
    return thread_phases([ident]).get(ident)


def _memory_numbers() -> dict[str, int]:
    """``mem_available_mb`` and ``swap_used_mb`` now, whole megabytes; a figure that cannot be read is absent, never 0. Read when a LONG hold
    ends (a few hundred microseconds, on a path that runs at most a few times an hour), so a slow hold can be read against memory pressure."""
    out: dict[str, int] = {}
    try:
        import psutil

        out["mem_available_mb"] = int(psutil.virtual_memory().available // (1024 * 1024))
        out["swap_used_mb"] = int(psutil.swap_memory().used // (1024 * 1024))
    except Exception:  # noqa: BLE001 - a diagnostic must never raise; what was read stays
        return out
    return out


def _route_of_thread(ident: int | None) -> str | None:
    """The route the thread with this ident was serving when it took its connection (the pool watch's checkout record), else None."""
    try:
        from src.database import pool_watch

        for row in pool_watch.checked_out():
            if row.get("ident") == ident:
                return row.get("endpoint")
    except Exception:  # noqa: BLE001
        return None
    return None


def _note_long_hold(gate: WriterGate, holder: str | None, started: float, ident: int | None, held_for: float) -> None:
    """The watchdog's sample of a hold at or past :data:`HOLD_RECORD_S`: open the journal entry on the first sample, update it on
    the rest. Never raises; the journal itself never blocks (it updates a dict and a background thread writes the file)."""
    global _JOURNALED_HOLD
    try:
        from src.monitoring import storage_events

        s = gate.stats()
        fields = {
            "holder": holder,
            "seconds": round(held_for, 1),
            "waiters": s.get("waiters"),
            "queued": s.get("queued"),
        }
        spent = gate.hold_breakdown(started)
        if spent is not None:  # None: the hold ended while this sample was being taken, and its end writes the exact figures
            fields["seconds_by"] = spent
        phase = thread_phase(ident)
        if started != _JOURNALED_HOLD:
            _PHASE_SAMPLES.clear()  # a new hold: its samples start from none
        if phase is not None:
            _PHASE_SAMPLES[phase] = _PHASE_SAMPLES.get(phase, 0) + 1
            fields["phase"] = phase
            fields["phase_samples"] = dict(_PHASE_SAMPLES)
        fields.update(holder_state.fields_for(started))  # the holder's kernel state, counted once a second since the last sample (module docstring)
        if started == _JOURNALED_HOLD and storage_events.update("gate_hold", ("hold", started), fields):
            return
        storage_events.record(
            "gate_hold",
            {**fields, "route": _route_of_thread(ident), "frames": _app_frames(ident)},
            key=("hold", started),
        )
        _JOURNALED_HOLD = started
    except Exception as exc:  # noqa: BLE001
        log_failure(_LOG, "write gate hold could not be journaled", exc, level=logging.DEBUG)


def _note_hold_end(
    holder: str | None,
    held: float,
    started: float | None,
    usage0: thread_usage.Sample | None = None,
    breakdown: dict[str, float] | None = None,
) -> None:
    """A hold of :data:`HOLD_RECORD_S` or more ended, on the holder's own thread: close its journal entry with the final length and
    the route (read from the request's context, which this thread still has), or write it whole when the watchdog never sampled it
    while it lasted. Never raises."""
    try:
        from src.database import pool_watch
        from src.monitoring import storage_events

        fields: dict[str, object] = {"holder": holder, "seconds": round(held, 1)}
        if usage0 is not None:
            # What the holder's own thread did over the whole hold, taken here on that thread: ``cpu_ms`` close to ``seconds`` is work, far
            # below it is waiting (``thread_usage`` says what each counter means and what it cannot tell apart).
            fields.update(thread_usage.since(usage0))
        fields.update(_memory_numbers())
        fields.update(holder_state.fields_for(started))  # the looks up to the release, not the last 15-second sample's
        if breakdown is not None:
            fields["seconds_by"] = breakdown  # exact: taken by the gate at the release, over the whole hold
        route = pool_watch.endpoint_template()
        if route is not None:  # no template found: the label the watchdog sampled stays, it is not overwritten with nothing
            fields["route"] = route
        # ``tombstone``: a watchdog sample that was already computing when this hold ended must not open a SECOND entry for it
        # (it would stay open for ever, which reads as a kill in the middle of a hold).
        if not storage_events.end("gate_hold", ("hold", started), fields, tombstone=True):
            storage_events.record("gate_hold", {**fields, "sampled_while_held": False})
    except Exception as exc:  # noqa: BLE001
        log_failure(_LOG, "write gate hold could not be journaled", exc, level=logging.DEBUG)
    finally:
        if started is not None:
            holder_state.forget(started)  # read above, on this thread; the watchdog never drops a hold's looks (holder_state.forget)


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
    if held_for >= HOLD_RECORD_S:
        _note_long_hold(gate, holder, started, ident, held_for)
    if held_for < _watchdog_threshold_s() or warned_since == started:
        return warned_since
    s = gate.stats()
    _LOG.warning(
        "write gate held %.1fs by %r (waiters=%s, queued=%s) -- stack:\n%s",
        held_for,
        _scrubbed_name(holder),
        s.get("waiters"),
        s.get("queued"),
        _holder_stack(ident),
    )
    return started


#: How often the holder of a hold the journal keeps is looked at (``holder_state``), in seconds. WHAT IT PROTECTS: the resolution of the counts
#: (a hold of 30 s has thirty looks) against the cost of three small ``/proc`` reads on the watchdog thread; the full tick stays at its own
#: 15 s. The looks run only while a hold is past :data:`HOLD_RECORD_S` AND already in the journal, so an idle gate costs nothing.
HOLD_LOOK_S = 1.0


def sample_holder_state(gate: WriterGate, now: float | None = None) -> bool:
    """One look at the holder of a long hold the journal already has (see :mod:`src.monitoring.holder_state`). True while the looks should
    go on at :data:`HOLD_LOOK_S`. Called by the watchdog thread after its full tick; never raises, never touches the gate's lock beyond the
    snapshot every tick takes."""
    try:
        holder, started, ident = gate._holder_snapshot()
        if started is None or holder is None:
            return False  # the gate is free: the looks stop; the thread that released it reads and forgets them (_note_hold_end)
        if started != _JOURNALED_HOLD:
            return False  # not a hold the journal keeps (yet): the full tick opens the entry first, at HOLD_RECORD_S or more
        return holder_state.look(started, ident, time.monotonic() if now is None else now)
    except Exception as exc:  # noqa: BLE001 - a diagnostic must never raise
        log_failure(_LOG, "write gate holder state could not be sampled", exc, level=logging.DEBUG)
        return False


def _next_wait_s(interval: float, due: float, now: float, looking: bool) -> float:
    """How long the watchdog sleeps next: until the full tick is due, or until the next look at a long hold's holder when that comes first."""
    until_full = max(0.0, due - now)
    return min(until_full, HOLD_LOOK_S) if looking else until_full


def _watchdog_loop(stop: threading.Event) -> None:
    interval = _watchdog_interval_s()
    warned_since: float | None = None
    due = time.monotonic() + interval  # the next full tick; the looks at a long hold's holder run between them
    wait = interval
    while not stop.wait(wait):
        looking = False
        try:
            now = time.monotonic()
            if now >= due:
                due = now + interval  # set BEFORE the tick: a tick that raises still waits its interval, it does not spin
                warned_since = watchdog_tick(write_gate, warned_since)
                due = time.monotonic() + interval
        except Exception as exc:  # noqa: BLE001 - the watchdog must never take the app down
            log_failure(_LOG, "write gate watchdog tick failed", exc, level=logging.DEBUG)
        try:
            looking = sample_holder_state(write_gate)  # its own try: a failing tick does not stop the looks
        except Exception as exc:  # noqa: BLE001 - sample_holder_state does not raise; the loop does not rely on it
            log_failure(_LOG, "write gate holder state could not be sampled", exc, level=logging.DEBUG)
        wait = _next_wait_s(interval, due, time.monotonic(), looking)


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


def hold_write_window(session) -> bool:
    """Take the write window for this session's transaction NOW, before a read the write depends on.

    The session events take the window at the first write, which is right for a write that does not
    depend on what it read first. A write that DOES (the re-index's diff of an article's mention rows
    against the rows it read) must not read before the window is held: a plain SELECT opens no
    transaction on the SQLite driver's default mode, so another writer's commit between the read and
    the first write leaves the diff working from rows that no longer exist. Taking the window first
    makes the read and the write one serialised step. The window is released by the session's
    outermost transaction end, exactly as when a write took it, and the flag keeps it idempotent.

    Returns True when this session's transaction now holds the window. It does nothing (False) when
    the gate is disabled, or when the session was not made from the gated factory: nothing would
    release a window taken for such a session, and a leaked window would stop every other writer.
    """
    if not gate_enabled() or _on_after_transaction_end not in session.dispatch.after_transaction_end:
        return False
    if not session.info.get(_SESSION_FLAG):
        if session.get_transaction() is None:
            # Only a transaction's END releases the window, so there must be one to end: begin it
            # (the read that follows would have).
            session.connection()
        write_gate.acquire()
        session.info[_SESSION_FLAG] = True
    return True


_REGISTERED = False


def _statement_kind(statement: object) -> int:
    """Which of the gate's buckets a statement's seconds go to: INSERT, a savepoint statement, or any other (``_SPENT_KINDS``). The first
    word only, so a ``WITH ... INSERT`` counts as other; never raises."""
    head = statement[:24].lstrip().upper() if isinstance(statement, str) else ""
    if head.startswith("INSERT"):
        return _INSERT
    if head.startswith(("SAVEPOINT", "RELEASE", "ROLLBACK TO")):
        return _SAVEPOINT
    return _OTHER


def _on_statement_start(conn, cursor, statement, parameters, context, executemany) -> None:  # pragma: no cover - event, exercised through the engine
    """``before_cursor_execute`` on every engine: the gate's holder starts a statement. Any other thread, and the holder outside a hold,
    return at once (one attribute read and one comparison). Never raises: it runs on every statement of the process."""
    if write_gate._owner != threading.get_ident():
        return
    with suppress(Exception):
        write_gate._work_begins(_statement_kind(statement))


def _on_statement_end(conn, cursor, statement, parameters, context, executemany) -> None:  # pragma: no cover - event
    if write_gate._owner != threading.get_ident():
        return
    with suppress(Exception):
        write_gate._work_ends()


def _on_statement_error(exception_context) -> None:  # pragma: no cover - event
    """A statement that raised has no ``after_cursor_execute``; its seconds end here. Returns None so no exception is replaced."""
    if write_gate._owner != threading.get_ident():
        return
    with suppress(Exception):
        write_gate._work_ends()


def _on_commit_start(conn) -> None:  # pragma: no cover - event
    """The engine's ``commit`` event, before the driver commits: the holder's commit begins."""
    if write_gate._owner != threading.get_ident():
        return
    with suppress(Exception):
        write_gate._work_begins(_COMMIT)


def _on_session_commit(session) -> None:  # pragma: no cover - event
    """The session's ``after_commit``: the commit that began at the engine's event has ended."""
    if write_gate._owner != threading.get_ident():
        return
    with suppress(Exception):
        write_gate._work_ends()


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
    # Where a hold's seconds go (``hold_breakdown``): the holder thread's statements and commits, on every engine. The class, not one engine,
    # so a second engine (a test's, the keyed copy a restore opens) is measured the same way; a statement of any thread that does not own
    # the gate costs one comparison.
    from sqlalchemy.engine import Engine

    event.listen(Engine, "before_cursor_execute", _on_statement_start)
    event.listen(Engine, "after_cursor_execute", _on_statement_end)
    event.listen(Engine, "handle_error", _on_statement_error)
    event.listen(Engine, "commit", _on_commit_start)
    event.listen(session_factory, "after_commit", _on_session_commit)
    # S2.6: a long hold names itself in the log. The watchdog is NOT started
    # here -- this function runs at import (session.py calls it at module level),
    # and importing must not spawn a monitoring thread. It arms on the first
    # acquire() instead; see _maybe_start_watchdog.
    _REGISTERED = True


#: A wait for the pooled connection of this many seconds or more, before the gate was asked for, is counted apart (``stalls``). WHAT IT
#: PROTECTS: the meaning of the count: a checkout is microseconds and an opened encrypted connection is about 0.17 s, so a second is a
#: wait for a connection to come back, which is the pool's 30 s timeout starting.
POOL_WAIT_STALL_S = 1.0

_POOL_WAIT_LOCK = threading.Lock()
_POOL_WAIT: dict[str, float] = {"n": 0, "total_s": 0.0, "max_s": 0.0, "stalls": 0}


def _note_pool_wait(waited: float) -> None:
    with _POOL_WAIT_LOCK:
        _POOL_WAIT["n"] += 1
        _POOL_WAIT["total_s"] += waited
        if waited > _POOL_WAIT["max_s"]:
            _POOL_WAIT["max_s"] = waited
        if waited >= POOL_WAIT_STALL_S:
            _POOL_WAIT["stalls"] += 1


def pool_wait_stats() -> dict[str, float]:
    """How long writers waited for their pooled connection BEFORE asking for the gate: ``n`` writes timed, ``total_s``, ``max_s`` and ``stalls``
    (waits of :data:`POOL_WAIT_STALL_S` or more). Process-cumulative, like the rest of the gate's counters."""
    with _POOL_WAIT_LOCK:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in _POOL_WAIT.items()}


def connection_first(session) -> None:
    """Check the session's pooled connection out BEFORE the write window is asked for.

    THE ORDER WAS WRONG. ``before_flush`` and ``do_orm_execute`` fire BEFORE SQLAlchemy checks a connection out for the statement, so a
    session whose first statement is its write (a ``release_idle_connection`` gives the connection back between statements, so every
    collector write after one is exactly that) took the gate and THEN waited for the pool. With 23 of 24 connections out (the 16 Oct 2026
    bundles) the wait is the pool's 30 s timeout, and the whole write queue stood behind a writer that was not writing. Reproduced: a
    pool of one with its connection out, a session adding a row, the gate held by the waiter. :func:`hold_write_window` already did it
    in this order (``session.connection()`` first); the two hooks now do too.

    THE RULE IS ONE ORDER EVERYWHERE: the pooled connection, then the gate. A writer that holds a connection while it queues for the gate is
    safe only if every other taker of both asks for the connection first, or the queued writers hold the pool and the gate holder waits
    for the pool's timeout. This function is for a session whose work follows under ``write_lock()``; a raw connection is taken as
    ``with engine.connect() as conn, write_lock():``. ``tests/test_gate_connection_order.py`` scans ``src/`` for the other order.

    A session with more than one bind and no default raises ``UnboundExecutionError`` here; the flush chooses the bind per mapper, so that
    case keeps its old order (the gate, then the connection). Any other error, a pool timeout included, is raised from here exactly as
    the flush would have raised it, with the gate NOT taken, so there is nothing to release. The wait is recorded in
    :func:`pool_wait_stats`. Never swallows a failure to get a connection."""
    from sqlalchemy.exc import UnboundExecutionError

    started = time.monotonic()
    try:
        session.connection()
    except UnboundExecutionError:
        return
    finally:
        _note_pool_wait(time.monotonic() - started)


def _on_before_flush(session, _flush_context, _instances) -> None:
    # First write of this session's transaction is about to hit the file —
    # take the write window. Idempotent within the transaction via the flag.
    if not session.info.get(_SESSION_FLAG):
        connection_first(session)
        write_gate.acquire()
        session.info[_SESSION_FLAG] = True


_SQL_LEADING = re.compile(r"(?:\s+|--[^\n]*(?:\n|$)|/\*.*?\*/)*", re.DOTALL)
_SQL_FIRST_WORD = re.compile(r"[A-Za-z]+")
_SQL_WRITES = frozenset({"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER"})
_SQL_WRITE_ANYWHERE = re.compile(r"\b(?:INSERT|UPDATE|DELETE|REPLACE)\b", re.IGNORECASE)


def _is_textual_write(statement) -> bool:  # noqa: ANN001 - any SQLAlchemy statement
    """A ``text("...")`` statement that changes the file: its first word, after whitespace and comments, is a write (``INSERT``,
    ``UPDATE``, ``DELETE``, ``REPLACE``, or a ``CREATE``/``DROP``/``ALTER``, which write the file too), or it is a ``WITH`` that
    carries one. ``is_insert`` and its two siblings are False for ``text()``, so a textual write ran outside the gate (found by the
    deep read of E3, 2026-10-06: a repair holds the gate for the whole copy and a text ``DELETE`` committed into the old file anyway).
    A read this takes for a write (a ``WITH`` that merely names ``update`` in a string) is gated and slowed, never lost."""
    from sqlalchemy.sql.elements import TextClause

    if not isinstance(statement, TextClause):
        return False
    sql = str(statement.text)
    head = _SQL_LEADING.match(sql)
    word = _SQL_FIRST_WORD.match(sql, head.end() if head else 0)
    first = word.group(0).upper() if word else ""
    if first in _SQL_WRITES:
        return True
    return first == "WITH" and _SQL_WRITE_ANYWHERE.search(sql) is not None


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
        or _is_textual_write(orm_execute_state.statement)
    ):
        return
    session = orm_execute_state.session
    if not session.info.get(_SESSION_FLAG):
        connection_first(session)
        write_gate.acquire()
        session.info[_SESSION_FLAG] = True


def _on_after_transaction_end(session, transaction) -> None:
    # Only the OUTERMOST transaction's end releases the gate (savepoints/nested
    # transactions have a parent and must not release the outer window). Clearing
    # the flag here lets the next transaction on a reused session re-acquire.
    if transaction.parent is None and session.info.pop(_SESSION_FLAG, False):
        write_gate.release()
