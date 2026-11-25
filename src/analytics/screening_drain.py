"""The background junk screening of imported articles (R827 R10, R830; row 408 PR 3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A restore used to screen the articles it added inside its own window, after the swap: one more stage the operator waited
for on every item of an import run. It now queues them instead (``screening_pending``, written in the working copy before
the swap, see ``_merge_articles``), and this worker judges them once the run has let go of the machine, with the very same
rules (``default_quarantine_candidates_batch``): the junk is stamped, its mentions leave the keyword counters, and every
judged article leaves the queue, all in one commit per chunk.

WHAT IT GUARANTEES, and how:

* An article is "not screened yet" exactly while its row is in the queue: the row goes in the same commit as the verdict.
  Until then every aggregate leaves it out (``not_counted`` in ``src/analytics/quarantine_scope.py``) and says so.
* Nothing is lost to a stop, a crash or a swap. The queue IS the cursor: the worker never remembers a position of its
  own, so whatever was not committed is simply still queued, and the next start (or the next kick) drains it.
* It never works inside an import's window. It waits while an import owns the machine, and holds a corpus lease across
  each chunk, so a swap waits out a chunk in flight instead of orphaning its writes (``src/database/corpus_lease.py``).
* One worker per process. ``kick()`` is idempotent and cheap: it starts the thread only when none is running.
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
from typing import Any

from src.database.corpus_lease import corpus_lease
from src.monitoring.secret_scrub import log_failure
from src.shared import import_owns_the_machine as _import_owns_the_machine

_LOG = logging.getLogger(__name__)

#: Articles judged per commit: the stamp writes chunk themselves under SQLite's bound-variable cap, and a chunk this size
#: holds the write gate for a fraction of a second (the bench's 26,000 junk-heavy articles took 2.9 s in all).
CHUNK = 2000

#: How often a worker parked behind an import re-checks the machine.
_POLL_S = 2.0


def _default_session():
    from src.database.session import SessionLocal

    return SessionLocal()


def pending_ids(session: Any, limit: int) -> list[int]:
    """The oldest ``limit`` queued article ids (by id, which is insertion order for a restore's articles)."""
    from sqlalchemy import select

    from src.database.models import ScreeningPending

    return [
        int(i)
        for (i,) in session.execute(
            select(ScreeningPending.article_id).order_by(ScreeningPending.article_id).limit(limit)
        )
    ]


#: A chunk that raised (a lock held too long, a store that went away) is tried again this many times, after a pause that doubles
#: from _RETRY_FIRST_S, before the worker stops and says why. The queue keeps every article either way.
_RETRIES = 4
_RETRY_FIRST_S = 5.0

#: The epoch bumps the worker owes (see ``defer_epoch_bump``) are paid at the end of a drain, and at most this often during a
#: long one, so the rollups catch up while it runs without rebuilding once per chunk.
_BUMP_EVERY_S = 60.0

#: ``_one_chunk``'s answer when an import owned the machine once the lease was held: nothing was judged, wait and ask again.
_YIELDED = -1


class ScreeningDrain:
    """The one worker that empties ``screening_pending``. Status is in memory only: the queue itself is the durable state."""

    def __init__(self, *, session_factory=None) -> None:
        self._session_factory = session_factory
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False  # set by kick(), cleared by the thread itself under the lock as its very last act
        self._again = False  # a kick that came while the thread was running: it looks at the queue once more before it ends
        self._stop = threading.Event()
        self._tally = {"screened": 0, "quarantined": 0, "chunks": 0}
        self._state = "idle"
        self._error: str | None = None
        self._bump_owed = False
        self._last_bump = 0.0

    def kick(self) -> bool:
        """Start the worker if it is not running. Returns whether this call started it. A kick while it runs makes it read
        the queue once more before it ends, so rows queued just as it found the queue empty are never left waiting."""
        with self._lock:
            if self._running:
                self._again = True
                return False
            self._running = True
            self._again = False
            self._stop.clear()
            self._error = None
            self._state = "running"
            self._thread = threading.Thread(target=self._run, name="oo-screening-drain", daemon=True)
            self._thread.start()
            return True

    def stop(self, timeout: float | None = None) -> None:
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout)

    def status(self) -> dict:
        with self._lock:
            out: dict[str, Any] = {"state": self._state, **self._tally}
            if self._error:
                out["error"] = self._error
            return out

    def _one_chunk(self) -> int:
        """Judge the next chunk; how many articles left the queue (0 when it is empty, ``_YIELDED`` when an import took the
        machine). The import check runs AFTER the lease is taken (``storage_guard``'s order): an import that opens its window
        first finds the lease and waits for this chunk, and one that already holds the machine makes this chunk step back."""
        from src.analytics.quarantine_job import default_quarantine_candidates_batch

        session = (self._session_factory or _default_session)()
        try:
            with corpus_lease("screening"):
                if _import_owns_the_machine():
                    return _YIELDED
                ids = pending_ids(session, CHUNK)
                if not ids:
                    return 0
                r = default_quarantine_candidates_batch(
                    session, article_ids=ids, write=True, release_pending=True, defer_epoch_bump=True
                )
        finally:
            try:
                session.close()
            except Exception as exc:  # noqa: BLE001 - the chunk is committed or rolled back already; only the close failed
                log_failure(_LOG, "the screening worker's session did not close", exc, level=logging.WARNING)
        with self._lock:
            self._tally["screened"] += int(r.get("scanned", 0))
            self._tally["quarantined"] += int(r.get("newly_written", 0))
            self._tally["chunks"] += 1
        if r.get("epoch_bump_owed"):
            self._bump_owed = True
        # A chunk whose rows could not leave the queue (a store without the table, say) would come back forever: stop.
        return int(r.get("released", 0))

    def _pay_bump(self, *, force: bool) -> None:
        """Bump the corpus epoch once for the chunks that left it owed (best effort: a missed bump only leaves a rollup one
        mutation behind, as ``bump_corpus_epoch`` says)."""
        import time

        if not self._bump_owed or (not force and time.monotonic() - self._last_bump < _BUMP_EVERY_S):
            return
        from src.analytics.corpus_epoch import bump_corpus_epoch

        session = (self._session_factory or _default_session)()
        try:
            bump_corpus_epoch(session, reason="screening")
            self._bump_owed = False
            self._last_bump = time.monotonic()
        finally:
            with contextlib.suppress(Exception):
                session.close()

    def _chunk_with_retries(self) -> int:
        delay = _RETRY_FIRST_S
        for attempt in range(_RETRIES + 1):
            try:
                return self._one_chunk()
            except Exception as exc:  # noqa: BLE001 - the chunk rolled back whole; the queue keeps its rows
                if attempt == _RETRIES or self._stop.is_set():
                    raise
                log_failure(_LOG, "a screening chunk failed; trying it again", exc, level=logging.WARNING)
                if self._stop.wait(delay):
                    raise
                delay *= 2
        return 0  # not reached

    def _run(self) -> None:
        import time

        self._last_bump = time.monotonic()
        try:
            while not self._stop.is_set():
                if _import_owns_the_machine():
                    self._stop.wait(_POLL_S)
                    continue
                n = self._chunk_with_retries()
                if n == _YIELDED:
                    self._stop.wait(_POLL_S)
                    continue
                self._pay_bump(force=False)
                if n == 0:
                    with self._lock:
                        if not self._again:
                            break
                        self._again = False
            self._pay_bump(force=True)
            with self._lock:
                self._state = "stopped" if self._stop.is_set() else "idle"
        except Exception as exc:  # noqa: BLE001 - surface the failure, never crash the thread; the queue keeps every article
            from src.monitoring.engine_text import engine_text

            log_failure(_LOG, "the background screening of imported articles stopped", exc, level=logging.WARNING)
            with contextlib.suppress(Exception):
                self._pay_bump(force=True)
            with self._lock:
                self._state = "error"
                self._error = engine_text(exc)
        finally:
            with self._lock:
                self._running = False


_DRAIN: ScreeningDrain | None = None
_DRAIN_LOCK = threading.Lock()


def get_screening_drain() -> ScreeningDrain:
    global _DRAIN
    with _DRAIN_LOCK:
        if _DRAIN is None:
            _DRAIN = ScreeningDrain()
        return _DRAIN


def autostart_allowed() -> bool:
    """``OO_SCREENING_AUTOSTART=0`` keeps the worker from starting on its own (the test suite sets it, so a test that drives a
    restore acquires no thread writing behind its back); the queue then waits for an explicit ``kick()``."""
    return os.getenv("OO_SCREENING_AUTOSTART", "1").strip() != "0"


def kick_if_allowed() -> bool:
    """``kick()`` unless autostart is declined. Never raises."""
    if not autostart_allowed():
        return False
    try:
        return get_screening_drain().kick()
    except Exception as exc:  # noqa: BLE001 - the queue stays; the next start tries again
        log_failure(_LOG, "could not start the background screening of imported articles", exc, level=logging.WARNING)
        return False


def kick_if_pending() -> bool:
    """Start the worker when anything is queued (the boot path). Never raises."""
    if not autostart_allowed():
        return False
    try:
        from src.analytics.quarantine_scope import any_pending
        from src.database.session import session_scope

        with session_scope() as s:
            if not any_pending(s):
                return False
        return get_screening_drain().kick()
    except Exception as exc:  # noqa: BLE001 - the queue stays; the next start tries again
        log_failure(_LOG, "could not start the background screening of imported articles", exc, level=logging.WARNING)
        return False
