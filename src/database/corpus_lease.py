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

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from src.safety import process_owner

_LOG = logging.getLogger(__name__)

_LOCK = threading.Lock()
#: name -> how many holders (re-entrant per name; a worker may nest its own lease).
_HELD: dict[str, int] = {}

#: How long the swap waits for in-flight batches to finish before refusing. Generous
#: on purpose: a re-index batch is 300 articles and the alternative to waiting is
#: throwing away an import that has already done hours of work.
DEFAULT_WAIT_S = 180.0
_POLL_S = 0.25

#: SEVERAL SERVERS ON ONE DATA FOLDER (R176, R183). The dict above is this process's; a swap in server A could not see server B's batch in flight and would swap the file
#: under it. So the FIRST holder of a name in a process also writes ``<data>/leases/<name>.<process>.lease`` (the owner record: pid, start time, host, machine tag) and the
#: LAST one removes it. A reader counts another process's file as held when its owner is ALIVE, or UNKNOWN (another host or machine on a shared drive, an unreadable record: a
#: swap that cannot tell refuses and names it, it does not swap under someone). A file whose owner is DEAD is a leftover: it is ignored and swept (the takeover). Workers still
#: never wait on any of this. A file that cannot be written logs once and the in-process lease stands (a missing record is not evidence).
_PROCESS = uuid.uuid4().hex
_FILE_LOCK = threading.Lock()
_FILE_WARNED = False
_OWNER: dict | None = None
_SUFFIX = ".lease"


def _dir() -> Path:
    from src.paths import data_dir

    return data_dir() / "leases"


def _own_file(name: str) -> Path:
    return _dir() / f"{name}.{_PROCESS}{_SUFFIX}"


def _warn_once(exc: Exception) -> None:
    global _FILE_WARNED
    if not _FILE_WARNED:
        _FILE_WARNED = True
        _LOG.warning("corpus lease: could not update a lease file (%s); other servers cannot see this process's lease", type(exc).__name__)


def _write_file(name: str) -> None:
    """Write this process's lease file for ``name`` (the caller holds ``_FILE_LOCK``). Best effort: the in-process lease stands, a record that cannot be written is not evidence of anything."""
    global _OWNER
    try:
        from src.safety.file_lock import atomic_replace

        path = _own_file(name)
        if _OWNER is None:
            _OWNER = process_owner.owner_record()
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_replace(path, json.dumps({**_OWNER, "name": name, "process": _PROCESS}), fsync=False)
    except Exception as exc:  # noqa: BLE001
        _warn_once(exc)


def _remove_file(name: str) -> None:
    try:
        _own_file(name).unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        _warn_once(exc)


def _foreign_leases() -> list[str]:
    """Names held by OTHER processes (alive or unknown owner); sweeps the files of dead owners."""
    held: set[str] = set()
    try:
        files = sorted(_dir().glob(f"*{_SUFFIX}"))
    except OSError:
        return []
    for f in files:
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
            name = str(rec["name"])
            if rec.get("process") == _PROCESS:
                continue
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            name = f.name.split(".", 1)[0] or f.name  # unreadable: judged "unknown", so held, under the name its file carries
            rec = None
        if rec is not None and process_owner.record_state(rec, machine=process_owner.machine_tag()) == "dead":
            f.unlink(missing_ok=True)  # the takeover: a dead owner's lease is a leftover
            continue
        held.add(name)
    return sorted(held)


@contextmanager
def corpus_lease(name: str) -> Iterator[None]:
    """Hold a lease for the duration of one unit of live-corpus work.

    Wrap the smallest unit that owns a session -- one batch, not one run -- so a parked
    or idle worker holds nothing and the swap is not made to wait on a job that is
    doing nothing.

    The FILE is written BEFORE the count is raised (a swap in another server that looks between the two sees the lease, never a gap) and removed AFTER it is lowered (it
    lingers a moment, never early). An interrupt between lowering and removing leaves a file that other servers count as held until this process ends; they then sweep it.
    """
    took = False
    try:
        with _FILE_LOCK:
            with _LOCK:
                first = _HELD.get(name, 0) == 0
            if first:
                _write_file(name)
            with _LOCK:
                _HELD[name] = _HELD.get(name, 0) + 1
                took = True  # no call between the store and this line: an interrupt later (even in the lock's own exit) finds the lease taken and gives it back
        yield
    finally:
        if took:
            with _FILE_LOCK:
                with _LOCK:
                    _HELD[name] -= 1  # one statement with no call in it; a name at zero stays in the dict and is not listed (active_leases)
                    last = _HELD[name] == 0
                if last:
                    _remove_file(name)


def active_leases() -> list[str]:
    """Names currently holding live-corpus work, in this process or in another server on the same data folder, sorted. Empty means quiescent."""
    with _FILE_LOCK, _LOCK:  # a release is complete (count lowered AND file removed) before it reads as released
        own = {name for name, n in _HELD.items() if n > 0}
    return sorted(own | set(_foreign_leases()))


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
