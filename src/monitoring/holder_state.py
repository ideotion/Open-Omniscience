"""What the thread that holds the write gate was doing, as the kernel sees it, counted once a second while a hold the journal keeps lasts.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY IT EXISTS. The 16 Oct 2026 bundles show gate holds of 30 to 182 s whose holder is a collector thread, and a hold taken at a plain
``SELECT`` (a read cannot wait for the write lock in WAL mode). So the hold was either honest work done slowly or a thread that was not
making progress, and the journal could not say which: the holder's CPU time (``thread_usage``) is read at the START and END of a hold, and
a thread's counters say HOW MUCH it waited, not WHAT it waited for. This module says what, by looking at the holder's kernel state
(``/proc/self/task/<tid>/{stat,wchan,schedstat}``) once a second and counting the looks by class:

* ``run``: state ``R``, on a CPU or waiting for one. It is NOT split into running and runnable: the split was inferred from the
  scheduler's figures over the second since the previous look, and a count of looks says little about time either way (measured with the
  real look on two cores, 17 Oct: a holder on a CPU 48 per cent of the time read ``R`` in 17 per cent of its looks; a holder that waited
  for a CPU 12 per cent of the time and was on one 1 per cent read it in 33 per cent). The time spent waiting for a CPU is ``rq`` below.
* ``futex``: asleep on a futex: the GIL, a Python lock, a pooled connection's wait, a condition. ``phase_samples`` (the watchdog's own
  look at the Python frames) says which of those, when it is the pool. It is a FLOOR for waits on the GIL: every read the look makes
  gives the GIL up, and when the holder is the only thread waiting for it the look hands it over and reads the holder running; with
  several waiters (the case this exists for: fetch workers and collectors on a few cores) the holder usually still reads futex.
* ``nap``: asleep in the kernel's ``nanosleep``. SQLite's busy handler sleeps there while another connection holds the file's write lock,
  and ``time.sleep`` is the same call, so ``nap`` is a busy-handler wait only where the holder of the gate does not call ``time.sleep``:
  true of the collector's flush path, NOT of the streaming backup, which sleeps half a second between its WAL checkpoint tries while it
  holds the gate (``src/backup/stream_backup.py``, ``_drain_wal``). The method says both.
* ``disk``: uninterruptible sleep (state ``D``): the thread is waiting on the disk or on swap, or on a kernel lock a disk wait holds.
* ``other``: a wait the kernel NAMED that is none of these (a poll, a socket, a pipe: a collector doing network I/O while it holds the
  gate), or a state letter that is not one of these. Counted, never folded into a class it was not seen to be.
* ``unknown``: asleep (state ``S`` or ``I``) and the kernel named nothing: a ``wchan`` that reads ``0`` (the thread woke between the two
  reads, or the kernel does not print the symbol) or cannot be read. It is its own class because it was 22 to 34 per cent of the looks in
  three of five scenarios measured (17 Oct) and counting it in ``other`` made ``other`` unreadable as "a socket or a poll".

THE ORDER OF THE READS IS PART OF THE ANSWER. Every file the look reads gives the GIL up while the kernel answers, and a holder that is
waiting for the GIL is woken by that: read ``stat`` first and ``wchan`` second and a holder asleep at the first read is awake at the second
(measured, a pure-Python holder beside three spinners: 29 per cent of its looks read ``S`` then ``0`` and fell in ``other``). So the
``wchan`` is read FIRST: the kernel prints a symbol only for a thread blocked in the kernel at that moment, so a symbol that names a futex
or a nanosleep is the wait itself, whatever the next read finds. The state is read second and decides only what the symbol did not.

``gap`` is the longest time between two looks that could be READ. The look runs on the gate's watchdog thread, which needs the GIL: a
process that is starved as a whole (swap, too many threads for the cores) shows as a gap well over a second, and a thread that is
only the holder does not, which is exactly the difference between "everything was slow" and "this thread was stuck".

THE FIRST LOOK OF A HOLD COUNTS NOTHING. It is the point ``rq`` is measured from (below); the counts start at the second look, as they
did before the running/runnable split was dropped, so the member's reading of them did not change. They begin when the watchdog first
sees the hold (30 to 45 s in), not at its start: they are the state of the hold from the first look the journal made, said so in the
member's method.

``rq`` is the seconds the holder spent WAITING FOR A CPU from the first look whose scheduler totals could be read to the last, the
difference of the second figure of ``schedstat``: exact where a count of ``R`` looks is not (the thread changes state many times a
second), rounded to 0.1 s like ``gap``. It is ``None`` (null in the journal), never 0, when fewer than two looks could read the
totals (a kernel built without them, a file that cannot be read): the one cause, named in the member's method. The whole hold's CPU
time is ``thread_usage``'s ``cpu_ms``; ``rq`` covers the looks only.

A figure the OS cannot give is ABSENT, never 0 (a 0 would read as "the thread never waited"): off Linux the answer is ``ws`` null with
``ws_why`` ``unsupported-os``; a holder whose files are gone ``thread-gone``; files that cannot be read ``proc-unreadable``. Only
counts and seconds are kept: the kernel symbol and the thread's name are read to classify and never stored, and an error is its fixed
reason, never its text.

COST, measured on the development machine (a 2-core Intel under a Linux 6.18 kernel, 3,000 looks at a sleeping thread): 29 microseconds of
CPU per look (three small reads and the table of threads), once a second, only while a hold is past
:data:`src.database.writer.HOLD_RECORD_S` and already in the journal, on the watchdog thread and never the holder's. The counts go into
the journal at the full tick (15 s) and at the release, not at each look, so the file is not rewritten once a second.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Any

#: The classes a look is counted in, in the order of the journal's ``ws`` list.
CLASSES: tuple[str, ...] = ("run", "futex", "nap", "disk", "other", "unknown")

#: Why a hold has no counts (``ws_why``). A reason, never an error's text.
UNSUPPORTED = "unsupported-os"
GONE = "thread-gone"
UNREADABLE = "proc-unreadable"
#: Why the member shows no counts for a hold that has none to show: the hold ended before the second look, or the journal was written by a build without the field.
NOT_RECORDED = "not-recorded"

#: The directory of the process's threads. A test points it at a made-up tree; nothing else changes it.
_TASK_DIR = "/proc/self/task"
_PLATFORM = sys.platform

#: Bytes read from one ``/proc`` file: a ``stat`` line is about 300 bytes, a ``wchan`` one symbol, a ``schedstat`` three numbers.
_READ_BYTES = 2048

# A leaf lock: held for a few assignments, never across a read of a file or a call out of this module.
_LOCK = threading.Lock()


class _Look:
    """One reading of one thread: its state letter, its ``wchan`` symbol ('' when unreadable) and the scheduler's running total of the
    time it waited on a run queue, in nanoseconds (None when unreadable)."""

    __slots__ = ("state", "wait_ns", "wchan")

    def __init__(self, state: str, wchan: str, wait_ns: int | None) -> None:
        self.state = state
        self.wchan = wchan
        self.wait_ns = wait_ns


def classify(state: str, wchan: str) -> str:
    """The class of one look. A ``wchan`` that names a futex or a nanosleep is the wait, whatever ``state`` (read after it) says: the symbol
    is printed only for a thread blocked there, and the state read can be the one the look woke. A sleep (``S``, ``I``) the kernel named
    nothing for (``wchan`` ``0`` or unreadable) is ``unknown``; a named wait that is not one of these two is ``other``."""
    if "futex" in wchan:
        return "futex"
    if "nanosleep" in wchan:
        return "nap"
    if state == "R":
        return "run"
    if state == "D":
        return "disk"
    if state in ("S", "I") and wchan in ("", "0"):
        return "unknown"
    return "other"


def _state_of(stat: bytes) -> str | None:
    """The state letter of a ``stat`` line: the first field after the LAST ``)`` (the thread's name sits in parentheses and may hold any
    character, a ``)`` among them)."""
    _head, closing, tail = stat.rpartition(b")")
    rest = tail.split()
    if not closing or not rest:
        return None  # not a stat line (no closing parenthesis: a truncated or foreign read) or nothing after the name: unreadable, never a class
    letter = rest[0][:1].decode("ascii", "replace")
    return letter if letter.isalpha() else None


def _read(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read(_READ_BYTES)


def _look_at(tid: int) -> tuple[_Look | None, str | None]:
    """(the look, None) or (None, the reason there is none). Never raises."""
    base = f"{_TASK_DIR}/{tid}"
    try:  # first: the read the look disturbs least (module docstring); a kernel without the file, or a refusal, leaves a sleep as "other"
        wchan = _read(f"{base}/wchan").decode("ascii", "replace").strip()
    except Exception:  # noqa: BLE001 - counted, not guessed; the error's text is not kept
        wchan = ""
    try:
        state = _state_of(_read(f"{base}/stat"))
    except (FileNotFoundError, ProcessLookupError):
        return None, GONE
    except Exception:  # noqa: BLE001 - the reason is the answer, the error's text is not kept
        return None, UNREADABLE
    if state is None:
        return None, UNREADABLE
    wait_ns: int | None = None
    try:
        wait_ns = int(_read(f"{base}/schedstat").split()[1])
    except Exception:  # noqa: BLE001 - ``rq`` is then taken from the looks that could read it, or is null
        wait_ns = None
    return _Look(state, wchan, wait_ns), None


def native_id_of(ident: int | None) -> int | None:
    """The kernel's id of the Python thread with this ident, or None when no live thread has it."""
    if ident is None:
        return None
    for t in threading.enumerate():
        if t.ident == ident:
            return t.native_id
    return None


class _Hold:
    """The looks taken at ONE hold. Written by the watchdog thread (under :data:`_LOCK`), read by the thread that releases the gate."""

    __slots__ = ("counts", "gap", "ident", "last_ok", "started", "tid", "wait_first", "wait_last", "wait_looks", "why", "why_seen")

    def __init__(self, started: float, ident: int | None) -> None:
        self.started = started
        self.ident = ident
        self.tid: int | None = None
        self.counts = [0] * len(CLASSES)
        self.last_ok: float | None = None
        self.wait_first: int | None = None  # the run-queue wait total (ns) at the first look that could read it, and at the latest
        self.wait_last: int | None = None
        self.wait_looks = 0  # how many looks read it: ``rq`` needs two
        self.gap = 0.0
        self.why: str | None = None  # why the LAST look could not be taken; None after one that could
        self.why_seen = False  # a reason was given at some look, so a later journal update must clear it

    def rq(self) -> float | None:
        """Seconds waited for a CPU from the first look that read the scheduler's total to the last, to 0.1 s; None (never 0) when fewer than two did."""
        if self.wait_looks < 2 or self.wait_first is None or self.wait_last is None:
            return None
        return round(max(0, self.wait_last - self.wait_first) / 1e9, 1)

    def fields(self) -> dict[str, Any]:
        """What the journal records for this hold now: the counts, the gap and ``rq``, or null and the reason, or nothing yet."""
        if sum(self.counts):
            out: dict[str, Any] = {"ws": list(self.counts), "gap": round(self.gap, 1), "rq": self.rq()}
            if self.why_seen:
                out["ws_why"] = None  # the journal merges: a reason given while the file was unreadable must not outlive the counts
            return out
        if self.why is not None:
            return {"ws": None, "ws_why": self.why}
        if self.why_seen:
            return {"ws": None, "ws_why": NOT_RECORDED}  # a reason went to the journal and the looks since have only set a new baseline: it must not outlive its cause
        return {}


_CURRENT: _Hold | None = None


def look(started: float, ident: int | None, now: float) -> bool:
    """Take one look at the holder of the hold that began at ``started``. True while the looks should go on at their one-second pace.

    ``now`` is a monotonic time. The reads happen outside the lock; the counts are applied inside it. Called by the watchdog thread only."""
    global _CURRENT
    with _LOCK:
        hold = _CURRENT
        if hold is None or hold.started != started:
            hold = _CURRENT = _Hold(started, ident)
        tid = hold.tid
    if not (_PLATFORM.startswith("linux") and _dir_exists()):
        _apply(hold, None, UNSUPPORTED, now, tid)
        return False
    if tid is None:
        tid = native_id_of(ident)
    if tid is None:
        return _apply(hold, None, GONE, now, None)  # not in the interpreter's table (yet): the next look asks again
    seen, reason = _look_at(tid)
    return _apply(hold, seen, reason, now, tid)


def _dir_exists() -> bool:
    return os.path.isdir(_TASK_DIR)


def _apply(hold: _Hold, seen: _Look | None, reason: str | None, now: float, tid: int | None) -> bool:
    with _LOCK:
        if _CURRENT is not hold:
            return False  # a newer hold replaced this one while the files were being read
        hold.tid = tid
        if seen is None:
            hold.why = reason
            hold.why_seen = True
            return reason in (GONE, UNREADABLE)  # transient: try again at the pace; the OS cannot do it: do not
        hold.why = None
        if seen.wait_ns is not None:
            if hold.wait_first is None:
                hold.wait_first = seen.wait_ns
            hold.wait_last = seen.wait_ns
            hold.wait_looks += 1
        last = hold.last_ok
        hold.last_ok = now
        if last is None:
            return True  # the first look: where ``rq`` starts, counted as nothing (see the module docstring)
        hold.gap = max(hold.gap, now - last)
        hold.counts[CLASSES.index(classify(seen.state, seen.wchan))] += 1
        return True


def fields_for(started: float | None) -> dict[str, Any]:
    """The journal fields for the hold that began at ``started`` ({} when no look was taken at that hold). Any thread."""
    if started is None:
        return {}
    with _LOCK:
        hold = _CURRENT
        if hold is None or hold.started != started:
            return {}
        return hold.fields()


def forget(started: float | None = None) -> None:
    """Drop the looks of the hold that began at ``started`` (the thread that released the gate calls this after it has read them), or, with
    no argument, whatever hold is kept. Never called by the watchdog: it sees a free gate before the releasing thread has read the counts,
    and a hold it dropped would end with the last 15-second sample's counts, or none (the 17 Oct read)."""
    global _CURRENT
    with _LOCK:
        if started is None or (_CURRENT is not None and _CURRENT.started == started):
            _CURRENT = None
