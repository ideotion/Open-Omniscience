"""Who is holding a live-corpus session right now — the barrier the atomic swap needs.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE HOLE THIS CLOSES (maintainer, 2026-08-11: "fix the single writer gate issue that
doesn't cover the restore's raw os.replace so we can do both importing and reindexing,
whatever the sequence"). A restore commits by replacing the corpus file:

    dispose_engine(); os.replace(working, target); init_db()

``pause_for_exclusive_operation``'s own docstring already names the gap -- "that gate
does NOT cover the restore's own raw, file-level atomic swap ... this pause narrows, but
does not eliminate, that pre-existing swap-concurrency window". A thread holding a
checked-out connection across that ``os.replace`` keeps writing to the OLD, now-unlinked
inode: the bytes survive on a file nothing can open again, so the writes are silently
lost -- and a job with a durable cursor has by then advanced PAST them, which is worse
than losing them, because nothing will ever go back.

THE SINGLE-WRITER GATE CANNOT CLOSE IT, and it is worth being precise about why rather
than reaching for it and assuming. The gate is acquired on FLUSH. A re-index batch spends
most of its time in the read-and-extract phase, holding a connection and no gate at all,
and flushes at the end -- so a swap could land in that window, and the flush that follows
would go to the orphaned inode with the gate dutifully held. The gate serialises WRITERS;
the swap needs to know that nobody is holding the FILE.

THE PAIR THAT DOES CLOSE IT. Two halves, neither sufficient alone:

  * the exclusive window (already there) stops any new batch from STARTING;
  * a lease, held across each batch, proves none is IN FLIGHT.

Together: no new work can begin, and the swap waits out whatever had already begun. The
wait is bounded, and a timeout ABORTS the restore pre-swap -- where an abort is free and
complete, the live corpus byte-identical -- naming who was holding it. Waiting forever
would trade a data-loss window for a hang, and swapping anyway would be the data loss.

DELIBERATELY NOT A LOCK ANY WORKER WAITS ON. A lease is only ever *observed* by the swap;
a worker takes and drops it without ever blocking. That is what keeps a job that runs
INSIDE the import's own window (the newsletter import is a queue item) from deadlocking
against a window its own run opened -- it registers its presence, it never asks
permission.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

_LOCK = threading.Lock()
#: name -> how many holders (re-entrant per name; a worker may nest its own lease).
_HELD: dict[str, int] = {}

#: How long the swap waits for in-flight batches to finish before refusing. Generous
#: on purpose: a re-index batch is 300 articles and the alternative to waiting is
#: throwing away an import that has already done hours of work.
DEFAULT_WAIT_S = 180.0
_POLL_S = 0.25


@contextmanager
def corpus_lease(name: str) -> Iterator[None]:
    """Hold a lease for the duration of one unit of live-corpus work.

    Wrap the smallest unit that owns a session -- one batch, not one run -- so a parked
    or idle worker holds nothing and the swap is not made to wait on a job that is
    doing nothing.
    """
    with _LOCK:
        _HELD[name] = _HELD.get(name, 0) + 1
    try:
        yield
    finally:
        with _LOCK:
            n = _HELD.get(name, 0) - 1
            if n > 0:
                _HELD[name] = n
            else:
                _HELD.pop(name, None)


def active_leases() -> list[str]:
    """Names currently holding live-corpus work, sorted. Empty means quiescent."""
    with _LOCK:
        return sorted(_HELD)


def wait_for_quiescence(
    timeout: float = DEFAULT_WAIT_S,
    *,
    poll: float = _POLL_S,
    should_stop: Callable[[], bool] | None = None,
) -> list[str]:
    """Block until nothing holds a lease. Returns the names STILL held on timeout.

    An empty list is the caller's go-ahead. A non-empty one is not an error here -- the
    caller decides what to do with it, and for the swap that decision is to abort while
    aborting is still free.

    ``should_stop`` RETURNS EARLY, IT DOES NOT DECIDE. A wait this long sits on the far
    side of the restore's last abort point, so without it a Stop pressed here would be
    ignored for the whole timeout and the swap would commit anyway -- an inert Stop
    button on the one control the operator is watching. Returning early is all this owes:
    it hands the decision back to the caller, whose own abort point then reports a stop AS
    a stop rather than as "another job is writing", which would name the wrong cause.
    """
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        held = active_leases()
        if not held:
            return []
        if should_stop is not None and should_stop():
            return held
        if time.monotonic() >= deadline:
            return held
        time.sleep(poll)
