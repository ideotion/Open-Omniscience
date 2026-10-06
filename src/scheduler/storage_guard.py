"""The storage guard: pause collection LOUDLY before a pinned WAL or a full drive.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why this exists (field diagnostics of 16 instances, 2026-09-30, ranks 1, 2 and 6). The
corpus's ``-wal`` file reached 18.7 to 42.9 GB on six of sixteen machines against a 64 MiB
resting limit, the data drive filled on three of them, and the collector kept starting passes
on a drive that could not take them (one machine logged no successful pass for 35 hours, each
pass failing on the same full disk). Nothing on main capped the WAL or stopped before the disk
filled; the 64 MiB ``journal_size_limit`` only applies when a WAL RESET happens.

WHY A STOP, AND NOT A BETTER CHECKPOINT (measured, ``tests/test_wal_pin_facts.py``). A WAL is
reset only when no reader holds a snapshot taken while it had un-backfilled frames. While one
does, ``PRAGMA wal_checkpoint(PASSIVE)`` backfills only up to that reader's mark (97 of 7,554
frames in the bench), ``TRUNCATE`` comes back busy, and the file grows by APPENDING for as long
as writers write. Nothing inside the process can evict a foreign reader. Once the reader ends,
one ``TRUNCATE`` takes the file to zero. So the only lever that bounds the FILE is to stop
appending until the reader ends, and then reset. That is this guard; it mirrors the memory
guard (``memguard.py``): it pauses, loudly, resumably, and never touches the writer gate from
a worker.

It does not change the boundary checkpoint (PASSIVE then TRUNCATE at busy timeout 0) or
``wal_autocheckpoint``: the ledger defers replacing those (MEASURE FIRST) and this adds no
checkpoint of its own beyond the DRAIN below, which is the same call the boundary makes.

WHAT IT WATCHES, every few seconds, from two readings that touch no table:

* **WAL**: the size of the corpus ``-wal`` file. Engages when it stays at or above ``wal_high``.
* **DISK**: free bytes on the drive holding the corpus. Engages when they fall below
  ``disk_reserve``, or at once when a write fails with "disk is full" (ENOSPC), or with
  SQLite's plain "disk I/O error" while the drive's own free space, read at that moment, is
  below the reserve (see :func:`is_io_error`: that message alone never latches).

WHAT EACH NUMBER PROTECTS (derived from the machine, never a constant of its own; the two
overrides exist for an operator who knows better):

* ``wal_high = min(clamp(10% of the corpus file, 512 MiB, 2 GiB), 10% of free disk)``
  (``OO_WAL_HIGH_MB`` overrides).
    - the 512 MiB floor protects NORMAL operation: SQLite's own autocheckpoint keeps a healthy
      WAL near 16 MiB, so this never fires on a machine whose WAL resets;
    - the 2 GiB ceiling protects the NEXT UNLOCK: boot recovers every frame the last session
      left, at the measured 5.0 to 39.2 s per GiB, so the ceiling costs 10 to 78 s there;
    - the 10%-of-corpus term scales a large corpus's allowance with it;
    - the 10%-of-free-disk term protects the DRIVE: a WAL is never allowed to take more than a
      tenth of what is left;
    - never below 128 MiB, so a tiny drive does not make the guard fire on a healthy WAL.
* ``disk_reserve = max(1 GiB, 2% of the drive)`` (``OO_DISK_RESERVE_MB`` overrides). ONE
  two-part reason, said the same way here, in the notice's hover, in ``state()["method"]`` and
  in the ledger: **the larger of 1 GiB (the writes still in flight while a pass winds down, plus
  the pass-tail records) and 2% of the drive (room for everything else that writes to it)** (the
  OS, a browser, a download), which is NOT a measured need of this app. It stays as decided
  (coordinator, 2026-09-30, option a): the 2% term has no upper bound, so on a very large volume
  it is the first candidate for a ceiling, and a ceiling is written only once the pass tail is
  MEASURED (the most bytes written between the guard's first refusal and the pass's end),
  never a fixed number.
* RESUME has margin so it never flaps, and each latch releases on ITS OWN reading (collection
  resumes when both are clear): the WAL latch at or below half of ``wal_high`` (a successful
  reset is zero), the disk latch at free disk at or above 1.5 x the reserve.
* ``trip_after`` = 2 consecutive samples (at least five seconds), so a single brushed reading
  cannot pause collection. A legitimate write that keeps the log above the limit for longer
  (an import or merge chunk, an index rebuild) CAN trip it: that is a stop, not a verdict,
  and it resumes by itself when the log can be reset.

HONESTY BY CONSTRUCTION. Measured readings only: an unreadable figure is ``None`` and never
trips anything (and never reads as recovery; the one exception is a latch that a failed WRITE
set, which a lapsed hold followed by an unreadable figure releases as a RETRY, because the next
failed write re-latches it at once). The state carries the numbers and the method. An engaged
guard says WHY in plain words and that it RESUMES BY ITSELF. It is not a security feature and
claims none.

WHAT "BY ITSELF" MEANS: for as long as whatever holds the log lives. A reader the app itself
holds open never ends on its own, so the exits are the operator's "Resume anyway" below, a
restart (which ends what the app itself holds open and resets the log when the database
reopens), or the holder ending. ``OO_WAL_CHECKPOINT=0`` is the operator's own switch against
the boundary checkpoint and the drain obeys it (the drain record says so); with it set the
log is reset only by a later write that SQLite itself resets on; "Resume anyway" lets collection
run past it but resets nothing.

NEVER BLOCKS. Consumers call :meth:`StorageGuard.admit` (a non-blocking read of the latch)
BEFORE taking on new work; in-flight work always finishes. The supervisor thread normally does
the sampling and the drain, so no worker does I/O on the guard's behalf. Where no supervisor
runs (a start that failed to launch it, which is logged) the places
that WAIT on the latch, the pass loop and :meth:`StorageGuard.wait_if_engaged`, take the
readings and the drain themselves (:meth:`StorageGuard.poll_and_drain_unsupervised`): a
pause must never outlive its cause. That is a fallback and not a state a running instance is
left in: starting collection (the scheduler's start, a manual run) starts the supervisor when
it is not running (``runner._ensure_storage_supervisor``), so an override is always bounded by
the sampling below while the supervisor runs (a failure to start it is logged and leaves the
fallback above), and ``OO_NO_SCHEDULER=1`` only means the supervisor is not started at boot.
The drain never runs while an exclusive operation (an import, a restore) owns the machine, and
holds a corpus lease while it runs, so a restore's file swap waits for it.

THE OPERATOR'S OVERRIDE (ruled 2026-10-01, R112, question 18 = a: "a resume button to override").
"Resume anyway" lets collection continue WHILE a limit is still exceeded; it is not a retry.
What then stops the drive from filling, in order:

* the guard keeps sampling, and the override ENDS BY ITSELF if free space falls to the
  **override floor**, ``max(128 MiB, the log's own size)``. What it protects: a checkpoint can
  need up to the log's size again to write it back into the database (worst case every frame is
  a distinct page, measured: an append-only 1 GiB log writes 1.0 GB), so while free space stays
  above the log the log can always still be written back once whatever pins it lets go; and
  128 MiB (the smallest log the guard calls large) is the room a commit and a sort still need;
* a write that FAILS for want of space ends it at once and latches the drive error hold, and
  the button is refused while that hold lasts (a drive that refuses writes cannot be forced:
  that is how one machine failed fourteen passes on one full disk);
* the button is refused when free space is already at or below the floor, or cannot be read
  (an override that cannot be bounded is not granted), and a granted one is withdrawn the same
  way when free space then stays unreadable for ``trip_after`` samples. The page does not offer
  a button that the last sample says would be refused: ``state()["override_refusal"]`` is the
  answer a click would get (from the last sample, decided by the same code as the click), and
  the page says it instead of drawing the button. One refusal is the click's own: a supervisor
  that is not running (``kind`` ``supervisor``, answered by the route) is not in that preview,
  so the button stays and a further click is refused with the same sentence;
* it covers the limits that were exceeded WHEN IT WAS GRANTED (the latch's, read under the lock
  at the click) and nothing else: a second limit that trips later (the drive's reserve while the
  log was overridden, or the other way round) ends it, the ordinary pause shows with the new
  numbers, and the button offers it again with that limit in view. A limit that tripped
  between the page's last refresh (2 to 6 s) and the click is therefore covered, and the note
  that replaces the pause names it;
* it ends when both causes are gone (the next trip pauses normally again), and it lives in
  memory only: quitting the app ends it. Start and Run now (:meth:`reset`) leave it alone while
  a covered limit is still exceeded by the last reading (or cannot be read against), and end it,
  re-arming the limit, when the last reading does not show a covered limit exceeded (for
  example when only the hysteresis holds the latch: the notes then still compare against the
  limit, and the latch holds below it until the resume level).

This is a bound, not a promise that the drive can never fill. The floor is read on every
supervisor tick, ``POLL_EVERY_S`` (5 s) apart, WHATEVER THE DRAIN IS WAITING ON: the drain runs on
its own thread, one at a time (``_supervise``, ``drain_if_due``'s in-flight flag, taken under
the guard's lock), because it checks out a pooled connection (the wait ``OO_DB_POOL_TIMEOUT``
sets: 30 s by default, and an operator may set it to minutes), then queues for the write gate that
running collectors keep busy (capped at :data:`DRAIN_GATE_TIMEOUT_S`, 30 s, whatever
``OO_CKPT_GATE_TIMEOUT_S`` says: ``0`` and a longer value leave the guard's own wait at 30 s, while
the pass-boundary checkpoint and the restore's pre-swap checkpoint keep the operator's setting),
then runs a checkpoint whose own run (TRUNCATE's busy allowance ``OO_WAL_CHECKPOINT_BUSY_MS``
included) is not bounded here; a drain that fails, a pool timeout for one, is recorded as its own
outcome (``last_drain["error"]``). The reading itself (``read_storage``: file sizes and a statvfs)
and the step that ends an override (``observe``) take no pooled connection, so no pool or gate
setting can leave the floor unread (pinned by a test that makes every connection request fail).
So the gap between two readings is 5 s plus the reading. At 1.4 MB/s of log growth, the figure the
sampling comment below uses (its original source is not in the repo; the nearest measured one is
instance 090243's 2026-09-30 diagnostics, 1.48 to 25.41 GB in five hours = 4.8 GB/h = 1.33 MB/s,
the mean of five hours that ranged 0.83 to 1.87 MB/s, kept in the project files), 5 s is about
7 MB: 5% of the smallest floor (128 MiB), and 9.4 MB, 7%, at the highest of those five hours. That
instance's own hourly series has worse ones (3.27 MB/s over 2026-09-28T23:00 to 2026-09-29T00:00,
+11.79 GB, where 5 s is 16.4 MB, 12%), so this margin is for a typical collecting hour, not a bound
on the worst; less of any larger floor. That rate is the log's growth, not everything a pass writes. What is NOT covered: a drive
that does not answer a statvfs stalls the reading itself, and the floor reserves room to write the log back and finish a
write, NOT the pass tail written after a withdrawal (a measured tail is what would size that, and
it is not a fixed number). The write error above is the last net and it does not wait for a
reading.

A drain still in flight when the app shuts down: :func:`stop` sets the supervisor's event, so a
drain that has not started never does (it checks the event first), and joins the supervisor and
the drain's thread for two seconds in all. One still waiting after that (for a pooled connection
or the write gate) is a daemon thread and is abandoned at exit: it may open one connection on a
process that is going down, which is harmless because a checkpoint is crash-safe and the next
open recovers the log, and it holds its corpus lease until it ends, so a restore that starts in
the same process still waits for it (the lease is why the drain may not run between a restore's
dispose and its replace).

The drain keeps running while the override holds, so the WAL still resets the moment its reader
lets go, and the notice says that the override is on, what bounds it, and that the next start
will spend longer recovering a large log.

``OO_STORAGE_GUARD=0`` disables it entirely (no sampling, no pause, no supervisor). The test
suite sets it for every test but the guard's own (a real sampler polling the developer's real
drive, or a supervisor thread outliving its test, has no place there).
"""

from __future__ import annotations

import errno
import logging
import os
import threading
import time
from collections import deque
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("scheduler.storage_guard")

MIB = 1024 * 1024
GIB = 1024 * MIB

# --- what each number protects (see the module docstring) ---------------------------
WAL_FLOOR_BYTES = 512 * MIB
WAL_CEILING_BYTES = 2 * GIB
WAL_ABSOLUTE_MIN_BYTES = 128 * MIB
WAL_CORPUS_FRACTION = 0.10
WAL_FREE_FRACTION = 0.10
WAL_RESUME_FACTOR = 0.5
DISK_RESERVE_FLOOR_BYTES = 1 * GIB
DISK_RESERVE_FRACTION = 0.02
DISK_RESUME_FACTOR = 1.5
#: After a write FAILED for want of space, hold the stop at least this long even if the free
#: figure looks healthy (quota, inode exhaustion, a figure that lags the failure): otherwise a
#: drive that says "free" but refuses writes would flap at pass cadence. The 300 s is NOT a
#: measurement: it was chosen in #1279 as a few minutes, long enough that the pass cadence cannot
#: re-try a refused write many times over (one machine failed fourteen passes on one full disk)
#: and short enough that a transient refusal costs minutes, not hours; the same hold keeps the
#: override button refused. A new failed write re-arms it.
ERROR_HOLD_S = 300.0
#: A drive reading taken for one I/O error is reused by the next one for this long. An incident
#: fails many statements in the same second, and each used to read the drive (a statvfs and the
#: WAL files' stats) on its own failing thread: cheap on a full disk, but on a hung one every
#: failing statement waited on its own read. One second is shorter than the 5 s sample the guard
#: already lives with, so a figure this old is never staler than the sample the guard acts on;
#: chosen, not measured.
IO_READING_REUSE_S = 1.0
#: How old a reading may be and still be used by a caller that finds another reading IN FLIGHT. That
#: caller does not wait (the drive may be hung), so it takes the last reading: but a figure from
#: hours before a hung read began says nothing about the drive now, and an incident is classified
#: on the drive's free space at THAT moment. Older than this it is "not classified" (the error is
#: still counted and recorded). Twelve of the guard's own 5 s samples; chosen, not measured.
IO_READING_STALE_S = 60.0
#: The in-memory history: one sample a minute for six hours. Process-scoped, never persisted
#: (the hourly ``disk_free_mib`` and ``wal_bytes`` gauges carry the long series).
HISTORY_EVERY_S = 60.0
HISTORY_KEEP = 360
#: Naming the holders is a stack capture (``sys._current_frames`` plus a traceback each): once a
#: minute at most keeps it off the hot path of a machine that is already struggling, and a
#: pinned reader is still pinned a minute later, so nothing is lost by the wait.
PIN_REPORT_EVERY_S = 60.0
#: A drain queues on the write gate for up to 30 s (:data:`DRAIN_GATE_TIMEOUT_S`) and logs its
#: record: every other sample (two sample periods) keeps a pinned WAL from keeping a permanent
#: waiter on the gate and from filling a nearly full drive's log with checkpoint records.
DRAIN_EVERY_S = 10.0
#: The longest the GUARD's own drain waits for the write gate, whatever the operator set for
#: ``OO_CKPT_GATE_TIMEOUT_S`` (``0`` there means "wait for ever" for the pass-boundary
#: checkpoint). It is not the override's bound (the floor is read on its own thread, whatever the
#: drain waits on); it keeps a drain from sitting behind a gate for ever, holding a pooled
#: connection and a corpus lease and keeping the next drain from starting.
#: Chosen as the setting's own default, not measured.
DRAIN_GATE_TIMEOUT_S = 30.0
#: Holders named per report, and frames per stack. They bound the PAYLOAD (a pin report rides
#: the diagnostics bundle and every checkpoint record rides a pass summary), not the truth:
#: eight is the small tier's collector ceiling, so a pass-end listing can name every collector
#: slot, and twelve frames reach from a worker's entry point to the statement that holds it.
PIN_HOLDERS_MAX = 8
PIN_STACK_DEPTH = 12
#: The log line names fewer than the report holds: one line per drain must stay readable in a
#: log that rotates at 60 MB on a drive that may be nearly full. The report has the rest.
PIN_LOG_HOLDERS = 4

#: The least free space an operator's override may run down to (see the module docstring): the
#: smallest log the guard calls large, which is the room a commit and a sort still need. The
#: floor is also never below the log's own size (``override_floor_bytes``).
OVERRIDE_FLOOR_MIN_BYTES = WAL_ABSOLUTE_MIN_BYTES
#: Tails kept in memory (one per engagement that caught a pass in flight). Twenty is weeks of
#: engagements on the worst field machine; the bundle carries them, nothing persists them.
TAIL_KEEP = 20

PHASE_WAL = "paused-wal-pinned"
PHASE_DISK = "paused-low-disk"

#: The plain-words sentences, as frames the page fills with the numbers in its own
#: language (the pattern of ``estimate_method_i18n``). Each is also a locale key, x12.
FRAME_WAL = (
    "Collection is paused: the database's working file (its write-ahead log) has grown to {size} "
    "(this machine's limit is {limit}) and cannot be reset while something still holds it "
    "open, such as a long read or a long write. Collection resumes by itself as soon as it "
    "can be reset."
)
#: A write failed for want of space while the drive still reports room (a quota, a lagging
#: figure): the plain disk frame would say "only X is free" about a healthy X. No sentence here
#: tells the user to do anything: the guard resumes by itself, and says what would bring that
#: sooner.
FRAME_DISK_ERROR = (
    "Collection is paused: the drive refused a write for lack of space (free space reported: "
    "{free}; this machine's reserve: {reserve}). Collection resumes by itself after a short "
    "hold, once the drive reports healthy free space; more room on the drive, or a data "
    "folder on a larger drive, brings that sooner."
)
FRAME_DISK = (
    "Collection is paused: only {free} is free on the data drive (this machine's reserve is "
    "{reserve}). Collection resumes by itself once about {resume} is free; more room on the "
    "drive, or a data folder on a larger drive, brings that sooner."
)
#: The notes shown while an operator's override holds (one per cause that is still present),
#: and what the button answers when it cannot grant one.
FRAME_OVERRIDE_WAL = (
    "Collection was resumed by you although the database's working file (its write-ahead log) "
    "is {size} (this machine's limit is {limit}). It stops again by itself if free space falls "
    "to {floor}, the room the database needs to write that file back into place and finish a "
    "write, if a write fails for lack of space, or if another limit is crossed. The next "
    "start will spend longer recovering it."
)
FRAME_OVERRIDE_DISK = (
    "Collection was resumed by you although only {free} is free on the data drive (this "
    "machine's reserve is {reserve}). It stops again by itself if free space falls to {floor}, "
    "the room the database needs to write its working file back into place and finish a "
    "write, if a write fails for lack of space, or if another limit is crossed."
)
#: A write was refused during this latch and the drive now reports room (the same test as
#: FRAME_DISK_ERROR, so the pause note and this one never disagree about it): "only X is free
#: ... reserve Y" would imply a reserve that is not exceeded. It states no time, so it stays true
#: however long ago the write failed.
FRAME_OVERRIDE_DISK_ERROR = (
    "Collection was resumed by you although the drive refused a write for lack of space and "
    "has not yet reported healthy free space (free space reported: "
    "{free}; this machine's reserve: {reserve}). It stops again by itself if free space falls "
    "to {floor}, the room the database needs to write its working file back into place and "
    "finish a write, if a write fails for lack of space, or if another limit is crossed."
)
#: Both a refusal at the click and an override that ended: the same fact either way. It does
#: not say WHEN collection resumes: that depends on which limit holds, and the pause note
#: beside it says so.
FRAME_OVERRIDE_STOPPED = (
    "Collection cannot be kept running against this limit: free space is {free}, at or below "
    "{floor}, the room the database needs to write its working file back into place and "
    "finish a write. Collection stays paused."
)
FRAME_OVERRIDE_HELD = (
    "The drive refused a write for lack of space a short while ago, so collection cannot be "
    "forced on yet. That hold ends by itself after a few minutes, and the button works again "
    "then."
)
FRAME_OVERRIDE_UNREADABLE = (
    "Free space on the data drive cannot be read, so a forced resume could not be kept within "
    "what the drive can take. Collection stays paused."
)
#: The click was answered by the route, not by :meth:`StorageGuard.override`: nothing is reading the
#: floor between passes (the supervisor could not be started), which is a different fact from free
#: space being unreadable, so it gets its own sentence.
FRAME_OVERRIDE_NO_SUPERVISOR = (
    "Collection cannot be forced on: the check that watches the drive's free space while "
    "collection is overridden could not be started, so a forced resume could not be kept within "
    "what the drive can take. Collection stays paused."
)


def _env_mb(name: str) -> int | None:
    try:
        v = int(float(os.getenv(name, "") or 0))
    except (TypeError, ValueError):
        return None
    return v * MIB if v > 0 else None


def wal_high_bytes(corpus_bytes: int | None, free_bytes: int | None) -> int:
    """The WAL size at which collection pauses, sized from THIS machine (see the docstring)."""
    override = _env_mb("OO_WAL_HIGH_MB")
    if override is not None:
        return override
    base = WAL_FLOOR_BYTES
    if corpus_bytes:
        base = int(min(max(corpus_bytes * WAL_CORPUS_FRACTION, WAL_FLOOR_BYTES), WAL_CEILING_BYTES))
    if free_bytes is not None:
        base = min(base, int(free_bytes * WAL_FREE_FRACTION))
    return max(base, WAL_ABSOLUTE_MIN_BYTES)


def disk_reserve_bytes(total_bytes: int | None) -> int:
    """The free space below which collection pauses, sized from THIS machine's drive."""
    override = _env_mb("OO_DISK_RESERVE_MB")
    if override is not None:
        return override
    if total_bytes:
        return int(max(DISK_RESERVE_FLOOR_BYTES, total_bytes * DISK_RESERVE_FRACTION))
    return DISK_RESERVE_FLOOR_BYTES


def override_floor_bytes(wal_bytes: int | None) -> int:
    """The free space at or below which an operator's override ends by itself: the log's own
    size (what a checkpoint may need to write it back), never less than 128 MiB."""
    return max(OVERRIDE_FLOOR_MIN_BYTES, int(wal_bytes or 0))


def _text_head(exc: BaseException) -> str:
    """An exception's text up to the statement SQLAlchemy appends to it. Its wrapper's ``str`` is
    ``(sqlite3.OperationalError) <driver message>`` and then ``[SQL: ...]`` and ``[parameters: ...]``:
    the driver's message is in the head, and everything after it is the statement and the values
    bound to it (a title, a URL), which a classifier must not read and a status payload must not
    keep. The Session's ``PendingRollbackError`` quotes the original the same way."""
    return str(exc).split("\n[SQL:", 1)[0]


def is_disk_full(exc: BaseException | None) -> bool:
    """Whether an exception (or anything in its chain) is the drive running out of space.

    Walks ``__cause__``/``__context__`` and SQLAlchemy's ``.orig``: the failure surfaces as
    ``OperationalError: database or disk is full`` (SQLITE_FULL), ``OSError`` errno 28 from a
    plain file write, or a quota. A message match is deliberate for the SQLite driver, which
    raises its own ``OperationalError`` without an errno; it reads only the head of the text
    (:func:`_text_head`), so a statement whose BOUND VALUE says "no space left on device" (an
    ``IntegrityError`` on a title that does) is not a full drive (the PR 1306 check, S3).
    """
    seen: set[int] = set()
    cur = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, OSError) and cur.errno in (errno.ENOSPC, getattr(errno, "EDQUOT", -1)):
            return True
        code = getattr(cur, "sqlite_errorcode", None)
        orig = getattr(cur, "orig", None)
        if _is_dbapi_error(cur) and isinstance(code, int):
            # The driver says what it was: trust that and not its words, which can echo the query
            # (``MATCH '"database or disk is full" :'`` fails with ``no such column: database or disk is
            # full``, code 1).
            if (code & 0xFF) == 13:  # SQLITE_FULL
                return True
            cur = orig or cur.__cause__ or cur.__context__
            continue
        if orig is not None and _is_dbapi_error(orig) and isinstance(getattr(orig, "sqlite_errorcode", None), int):
            cur = orig  # SQLAlchemy's wrapper repeats the driver's words in its head: read the driver's code
            continue
        msg = _text_head(cur).lower()
        if (
            "database or disk is full" in msg
            or "no space left on device" in msg
            or "disk quota exceeded" in msg
        ):
            return True
        cur = getattr(cur, "orig", None) or cur.__cause__ or cur.__context__
    return False


_DBAPI_MODULES = ("sqlite3", "sqlcipher3")


def _is_dbapi_error(exc: BaseException) -> bool:
    """Whether ``exc`` is the DRIVER's own exception (sqlite3 or sqlcipher3), not SQLAlchemy's
    wrapper around it: the wrapper's text carries the SQL statement and its bound parameters."""
    return type(exc).__module__.split(".")[0] in _DBAPI_MODULES


def _dbapi_cause(exc: BaseException | None) -> BaseException | None:
    """The driver's exception behind ``exc`` (SQLAlchemy's ``.orig``, ``__cause__`` or
    ``__context__``), or ``None``."""
    seen: set[int] = set()
    cur = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if _is_dbapi_error(cur):
            return cur
        cur = getattr(cur, "orig", None) or cur.__cause__ or cur.__context__
    return None


def is_io_error(exc: BaseException | None) -> bool:
    """Whether an exception (or anything in its chain) is SQLite's plain "disk I/O error"
    (``SQLITE_IOERR`` and its extended codes).

    This is NOT a full-drive classification, and :func:`is_disk_full` does not widen to
    include it: the same message is what a dying or unplugged drive produces (the data-drive
    watchdog's business, R86), and what a full drive produces when its filesystem reports
    ``ENOSPC`` late (at ``fsync``, on a copy-on-write or delayed-allocation filesystem) where
    SQLite then says "disk I/O error" instead of "database or disk is full". The two are
    told apart by one measurement, the drive's free space at that moment
    (:meth:`StorageGuard.note_io_error`), never by the message. A driver that carries
    ``sqlite_errorcode`` (Python 3.11 and later) is matched on it, and its message is then not read
    at all (a query can echo "disk I/O error" into an error of another code); the message is the
    fallback for a driver without a code, and only for the DRIVER's own exception: SQLAlchemy's
    wrapper text carries the statement and its bound parameters, so an ``IntegrityError`` whose
    bound title happened to say "disk I/O error" was counted as one (the deep read of #1289)."""
    seen: set[int] = set()
    cur = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        code = getattr(cur, "sqlite_errorcode", None)
        if isinstance(code, int) and (code & 0xFF) == 10:  # SQLITE_IOERR
            return True
        if _is_dbapi_error(cur) and not isinstance(code, int) and "disk i/o error" in str(cur).lower():
            return True  # no code to trust: the message, which a query can echo, is all there is
        cur = getattr(cur, "orig", None) or cur.__cause__ or cur.__context__
    return False


def _first_line_detail(exc: BaseException | None, *, quote_head: bool = False) -> str:
    """What the guard keeps of an error: the DRIVER's exception class and FIRST line of its message
    (``OperationalError: disk I/O error``), never SQLAlchemy's wrapper text, which carries the SQL and
    its bound parameters into a status payload the page polls and the bundle ships. With no driver
    exception behind it, the class alone, or (``quote_head``) the first line of the text before the
    statement: an ``OSError`` says "No space left on device" and the Session's
    ``PendingRollbackError`` quotes the original, and both are the cause the operator needs."""
    if exc is None:
        return ""
    orig = _dbapi_cause(exc)
    if orig is not None:
        shown, text = orig, str(orig)
    elif quote_head:
        # the Session's rollback error opens with a paragraph of advice and then quotes the original
        shown, text = exc, _text_head(exc).rpartition("Original exception was: ")[2]
    else:
        return type(exc).__name__
    first = (text.splitlines() or [""])[0]
    return f"{type(shown).__name__}: {first}"[:200]


def _io_error_detail(exc: BaseException | None) -> str:
    """The detail kept for an I/O error (:func:`_first_line_detail`, class only without a driver)."""
    return _first_line_detail(exc)


def _disk_full_detail(exc: BaseException | None) -> str:
    """The detail kept for a full drive (:func:`_first_line_detail`, with the quoted head)."""
    return _first_line_detail(exc, quote_head=True)


def _size_text(n: float | int | None) -> str:
    """Binary steps with the page's own unit labels ("2.0 GB"), so a log line, the bundle and
    the notice read the same figure the same way; ``?`` when unreadable."""
    if n is None:
        return "?"
    v = float(n)
    units = ("B", "KB", "MB", "GB", "TB")
    i = 0
    while v >= 1024 and i < len(units) - 1:
        v /= 1024
        i += 1
    return f"{v:.0f} {units[i]}" if i == 0 or v >= 100 else f"{v:.1f} {units[i]}"


def read_storage() -> dict[str, Any]:
    """One measured reading of the corpus WAL, the corpus file and the drive.

    Stats only (no table, no connection, no lock), so it is safe on any thread and before
    an encrypted store is unlocked. Every figure that cannot be read is ``None``.
    """
    out: dict[str, Any] = {
        "wal_bytes": None,
        "corpus_bytes": None,
        "disk_free_bytes": None,
        "disk_total_bytes": None,
        "lane_wal_bytes": {},
    }
    try:
        from src.database.session import engine

        if engine.url.get_backend_name() != "sqlite":
            return out
        db_file = engine.url.database
        if not db_file or db_file == ":memory:":
            return out
        path = Path(db_file)
        try:
            out["wal_bytes"] = Path(str(db_file) + "-wal").stat().st_size
        except FileNotFoundError:
            out["wal_bytes"] = 0  # no -wal file on a real store IS a real zero
        except OSError:
            pass
        with suppress(OSError):
            out["corpus_bytes"] = path.stat().st_size
        try:
            for side in path.parent.glob("*-wal"):
                if side.name != path.name + "-wal":
                    out["lane_wal_bytes"][side.name] = side.stat().st_size
        except OSError:
            pass
        from src.config.hardware_reading import disk_bytes

        free, total = disk_bytes(path.parent)
        out["disk_free_bytes"], out["disk_total_bytes"] = free, total
    except Exception:  # noqa: BLE001 - a reading is best-effort, never a crash
        _LOG.debug("storage guard: could not read the drive", exc_info=True)
    return out


def _default_drain() -> dict | None:
    """The same call the pass boundary makes: PASSIVE then TRUNCATE through the write gate,
    busy timeout zero. ``force`` skips only its cadence. The gate wait is the operator's
    ``OO_CKPT_GATE_TIMEOUT_S`` but never longer than :data:`DRAIN_GATE_TIMEOUT_S`, and ``0`` (for
    ever) becomes that bound here. A checkpoint that FAILED (a pooled-connection wait that timed
    out, say) comes back as ``{"error": <exception type>}``, its own outcome: ``checkpoint_wal``
    returns None for it, which reads as "disabled / not due"."""
    from src.scheduler.hygiene import _ckpt_gate_timeout_s, checkpoint_wal

    t = _ckpt_gate_timeout_s()
    errors: list[str] = []
    rec = checkpoint_wal(
        force=True,
        gate_timeout_s=min(t, DRAIN_GATE_TIMEOUT_S) if t > 0 else DRAIN_GATE_TIMEOUT_S,
        errors=errors,
    )
    if rec is None and errors:
        return {"error": errors[0]}
    return rec


def _checkpoint_enabled() -> bool:
    from src.scheduler.hygiene import wal_checkpoint_enabled

    return wal_checkpoint_enabled()


def _pin_report(drain: dict | None) -> dict[str, Any]:
    """Who holds the WAL, named, with a stack each: the data no bundle has had.

    ``pool_watch`` sees checkouts of the pooled engines; a read that is not a pooled
    checkout cannot be seen from here, and the report says so rather than implying it would.
    Never raises.
    """
    out: dict[str, Any] = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "drain": drain,
        "holders": [],
        "instrument": "unattached",
    }
    try:
        from src.database import pool_watch

        if pool_watch.is_registered():
            out["instrument"] = "attached"
            rows = pool_watch.checked_out()
            out["checkouts"] = len(rows)
            top = rows[:PIN_HOLDERS_MAX]
            stacks = pool_watch.stacks_for(
                [r["ident"] for r in top if r.get("ident")], depth=PIN_STACK_DEPTH
            )
            out["holders"] = [
                {
                    "thread": r["thread"],
                    "endpoint": r.get("endpoint"),
                    "pool": r.get("pool"),
                    "age_s": r["age_s"],
                    "stack": stacks.get(r["ident"], []) if r.get("ident") else [],
                }
                for r in top
            ]
    except Exception:  # noqa: BLE001
        out["instrument"] = "unreadable"
    try:
        from src.database.writer import write_gate_stats

        gate = write_gate_stats()
        out["write_gate"] = {"holder": gate.get("holder"), "held_for_s": gate.get("held_for_s")}
    except Exception:  # noqa: BLE001
        pass
    out["caveat"] = (
        "A read that is not a pooled connection checkout (a cursor another thread left open on "
        "a connection it already returned, a connection opened outside the watched engines) "
        "is invisible to this list; an empty list does not mean nobody is reading. And the "
        "other way round: a listed checkout is a candidate, not proof. On the corpus pool the "
        "driver runs its legacy transaction mode, where a plain SELECT starts no transaction, so "
        "a checkout there pins the log only while a statement or an open cursor of it is running, "
        "or after a write it has not committed; a read_snapshot checkout holds its snapshot "
        "from its first read until it ends. The pool field says which. The oldest checkout is "
        "the likeliest holder, never a measured one, and an age says how long the connection "
        "has been out, not how long a statement ran."
    )
    return out


class StorageGuard:
    """Two trip/resume latches (WAL, DISK) over measured readings, with hysteresis.

    Readings are pulled by the supervisor (:meth:`poll`) and pushed in tests
    (:meth:`observe`). ``readings_fn`` and ``drain_fn`` are injectable so tests drive the
    whole ladder deterministically, with a real SQLite file where the WAL matters.
    """

    def __init__(
        self,
        *,
        readings_fn=None,
        drain_fn=None,
        trip_after: int | None = None,
        resume_after: int | None = None,
        clock=time.monotonic,
    ) -> None:
        self._readings = readings_fn or read_storage
        self._drain = drain_fn or _default_drain
        self.trip_after = _env_int("OO_STORAGE_GUARD_TRIP_AFTER", 2) if trip_after is None else max(1, trip_after)
        self.resume_after = (
            _env_int("OO_STORAGE_GUARD_RESUME_AFTER", 2) if resume_after is None else max(1, resume_after)
        )
        self._clock = clock
        self._lock = threading.Lock()
        self._wal = False
        self._disk = False
        self._wal_over = self._wal_under = 0
        self._disk_over = self._disk_under = 0
        self._since: str | None = None
        self._since_mono: float | None = None
        self._engagements = 0
        self._total_engaged_s = 0.0
        self._peak_wal_while_engaged = 0
        self._disk_full_events = 0
        self._last_disk_full: dict[str, Any] | None = None
        self._io_errors = 0
        self._last_io_error: dict[str, Any] | None = None
        self._io_reading: tuple[float, dict[str, Any]] | None = None
        self._io_reading_busy = False
        self._failure_keys: dict[str, str] = {}  # per path: what failed last, see log_failure_once
        self._hold_until: float | None = None
        self._last: dict[str, Any] = {}
        self._thresholds: dict[str, Any] = {}
        self._history: deque[dict[str, Any]] = deque(maxlen=HISTORY_KEEP)
        self._last_hist_mono: float | None = None
        self._last_drain: dict[str, Any] | None = None
        self._last_drain_mono: float | None = None
        self._drain_inflight = False
        self._last_pin_report: dict[str, Any] | None = None
        self._last_pin_mono: float | None = None
        self._drains = 0
        # The operator's override: None, or {"at", "since_mono", "reason"}. Memory only.
        self._override: dict[str, Any] | None = None
        self._withdrawn: dict[str, Any] | None = None
        self._overrides = 0
        # consecutive samples with free space unreadable while overridden, or while a floor
        # withdrawal note stands (it turns into the unreadable note after trip_after of them)
        self._override_blind = 0
        # The DISK latch was set by a failed WRITE (not by a measurement): only such a latch is
        # released as a retry when its hold lapses with free space unreadable.
        self._disk_by_error = False
        self._wal_seen = 0  # the last WAL size actually read (the floor must not fall on a miss)
        # What the last pin report named (the kind and the holders), so a long pin logs ONE
        # WARNING an episode (and another when the holders change), not one a minute: the error
        # ring keeps 2,000 records and a day-long pin would replace every other warning in it.
        self._report_key: tuple | None = None
        self._episode: dict[str, Any] | None = None
        self._tails: deque[dict[str, Any]] = deque(maxlen=TAIL_KEEP)

    def _reset_for_tests(self) -> None:
        """Back to the boot state (a process-global latch must not leak across tests)."""
        with self._lock:
            self._wal = self._disk = False
            self._wal_over = self._wal_under = self._disk_over = self._disk_under = 0
            self._since = self._since_mono = None
            self._engagements = self._drains = self._disk_full_events = 0
            self._total_engaged_s = 0.0
            self._peak_wal_while_engaged = 0
            self._last_disk_full = None
            self._io_errors = 0
            self._last_io_error = None
            self._io_reading, self._io_reading_busy = None, False
            self._failure_keys.clear()
            self._hold_until = None
            self._last, self._thresholds = {}, {}
            self._history.clear()
            self._last_hist_mono = None
            self._last_drain = self._last_drain_mono = None
            self._drain_inflight = False
            self._last_pin_report = self._last_pin_mono = None
            self._override = self._withdrawn = None
            self._overrides = 0
            self._override_blind = 0
            self._disk_by_error = False
            self._wal_seen = 0
            self._report_key = None
            self._episode = None
            self._tails.clear()

    # -- switches ------------------------------------------------------------------
    @staticmethod
    def enabled() -> bool:
        return os.getenv("OO_STORAGE_GUARD", "1") != "0"

    @property
    def engaged(self) -> bool:
        with self._lock:
            return self._wal or self._disk

    def kind(self) -> str | None:
        """``"disk"`` (the more severe, wins), ``"wal"`` or None."""
        with self._lock:
            return "disk" if self._disk else ("wal" if self._wal else None)

    def admit(self) -> str | None:
        """None = start the next unit of work; else ``"disk"`` or ``"wal"``.

        A non-blocking read of the latch: it samples nothing, takes no lock a worker could
        queue on for long, and never raises. Long background writers call it at a chunk
        boundary. This is COLLECTION's gate: it is None while the operator's override holds, though
        the latch itself stays engaged (``engaged`` is the condition's truth, ``admit`` is whether
        new collection may start). A background writer that is not collection (off-peak
        maintenance, the keyword boot recompute) reads ``engaged`` or :meth:`wait_if_engaged`,
        which do NOT follow the override: forcing collection on does not force a rewrite on.
        """
        if not self.enabled():
            return None
        with self._lock:
            if self._override is not None:
                return None
            return "disk" if self._disk else ("wal" if self._wal else None)

    def phase(self) -> str | None:
        kind = self.kind()
        return PHASE_DISK if kind == "disk" else (PHASE_WAL if kind == "wal" else None)

    # -- the latches ---------------------------------------------------------------
    def observe(
        self,
        *,
        wal_bytes: int | None = None,
        corpus_bytes: int | None = None,
        disk_free_bytes: int | None = None,
        disk_total_bytes: int | None = None,
        lane_wal_bytes: dict | None = None,
    ) -> bool:
        """Feed one measured sample; returns the engaged state afterwards.

        A ``None`` figure carries no information: it advances neither the trip nor the
        resume counter (never a fabricated pressure OR a fabricated recovery).
        """
        if not self.enabled():
            return False
        high = wal_high_bytes(corpus_bytes, disk_free_bytes)
        reserve = disk_reserve_bytes(disk_total_bytes)
        wal_resume = int(high * WAL_RESUME_FACTOR)
        disk_resume = int(reserve * DISK_RESUME_FACTOR)
        now_mono = self._clock()
        tripped: list[str] = []
        released: list[str] = []
        with self._lock:
            self._last = {
                "wal_bytes": wal_bytes,
                "corpus_bytes": corpus_bytes,
                "disk_free_bytes": disk_free_bytes,
                "disk_total_bytes": disk_total_bytes,
                "lane_wal_bytes": dict(lane_wal_bytes or {}),
                "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            self._thresholds = {
                "wal_high_bytes": high,
                "wal_resume_bytes": wal_resume,
                "disk_reserve_bytes": reserve,
                "disk_resume_bytes": disk_resume,
            }
            if self._last_hist_mono is None or now_mono - self._last_hist_mono >= HISTORY_EVERY_S:
                self._last_hist_mono = now_mono
                self._history.append(
                    {"ts": self._last["ts"], "wal_bytes": wal_bytes, "disk_free_bytes": disk_free_bytes}
                )
            was = self._wal or self._disk
            if wal_bytes is not None:
                self._wal_seen = wal_bytes
                if not self._wal:
                    if wal_bytes >= high:
                        self._wal_over += 1
                        if self._wal_over >= self.trip_after:
                            self._wal, self._wal_over, self._wal_under = True, 0, 0
                            tripped.append("wal")
                    else:
                        self._wal_over = 0
                else:
                    self._peak_wal_while_engaged = max(self._peak_wal_while_engaged, wal_bytes)
                    if wal_bytes <= wal_resume:
                        self._wal_under += 1
                        if self._wal_under >= self.resume_after:
                            self._wal, self._wal_over, self._wal_under = False, 0, 0
                            released.append("wal")
                    else:
                        self._wal_under = 0
            if disk_free_bytes is not None:
                if not self._disk:
                    if disk_free_bytes < reserve:
                        self._disk_over += 1
                        if self._disk_over >= self.trip_after:
                            self._disk, self._disk_over, self._disk_under = True, 0, 0
                            tripped.append("disk")
                    else:
                        self._disk_over = 0
                else:
                    held = self._hold_until is not None and now_mono < self._hold_until
                    if disk_free_bytes < reserve:
                        # A measurement agrees the drive is short: this latch is no longer
                        # "only a failed write", so an unreadable figure later never releases it.
                        self._disk_by_error = False
                    if disk_free_bytes >= disk_resume and not held:
                        self._disk_under += 1
                        if self._disk_under >= self.resume_after:
                            self._disk, self._disk_over, self._disk_under = False, 0, 0
                            self._hold_until = None
                            self._disk_by_error = False
                            released.append("disk")
                    else:
                        self._disk_under = 0
            elif (
                self._disk
                and self._disk_by_error
                and self._hold_until is not None
                and now_mono >= self._hold_until
            ):
                # A latch ONLY a failed WRITE set (never a measurement), its hold has lapsed and
                # free space cannot be read: nothing could ever confirm recovery by measurement (a
                # PostgreSQL install reads no free space at all), so release it as a RETRY. The
                # next failed write latches it again at once, so this cannot hide a full drive.
                self._disk_under += 1
                if self._disk_under >= self.resume_after:
                    self._disk, self._disk_over, self._disk_under = False, 0, 0
                    self._hold_until = None
                    self._disk_by_error = False
                    released.append("disk-retry")
            self._account_locked(was, now_mono)
            engaged = self._wal or self._disk
            override_event = self._update_override_locked(engaged, disk_free_bytes)
        self._log_transitions(tripped, released)
        if override_event == "cleared":
            _LOG.warning("storage guard override ended: the cause is gone, the guard is armed again")
        elif override_event == "widened":
            _LOG.warning(
                "STORAGE GUARD OVERRIDE ENDED -- a limit the override was not granted for was "
                "crossed; collection pauses again, and \"Resume anyway\" offers it again with the "
                "new limit in view."
            )
        elif override_event == "unreadable":
            _LOG.warning(
                "STORAGE GUARD OVERRIDE WITHDRAWN -- free space on the data drive cannot be read, "
                "so the override can no longer be kept within what the drive can take; collection "
                "pauses again."
            )
        elif override_event is not None:
            _LOG.warning(
                "STORAGE GUARD OVERRIDE WITHDRAWN -- free space %s fell to the override floor "
                "%s (the room to write the log back into the database and finish a write); "
                "collection pauses again.",
                _size_text(disk_free_bytes),
                _size_text(override_floor_bytes(self._wal_seen)),
            )
        return engaged

    def _update_override_locked(self, engaged: bool, disk_free_bytes: int | None) -> str | None:
        """End the operator's override when its cause is gone, when a limit it was not granted
        for trips, or when it can no longer be bounded; withdraw it when free space has fallen to
        the floor. Caller holds the lock. Returns ``"cleared"``, ``"widened"``, ``"unreadable"``,
        ``"withdrawn"`` or None.

        A withdrawal note belongs to the episode that withdrew it, and to the time free space
        stays at or below the floor: it goes with the episode, and goes once free space reads
        above the floor again (the button is offered then, and would be granted). While it
        stays it says what is true NOW: each readable sample refreshes its numbers, and free
        space unreadable for ``trip_after`` samples turns it into the unreadable note."""
        floor = override_floor_bytes(self._wal_seen)
        if self._override is None:
            w = self._withdrawn
            if w is not None:
                if not engaged or (disk_free_bytes is not None and disk_free_bytes > floor):
                    self._withdrawn = None
                    self._override_blind = 0
                elif disk_free_bytes is not None:
                    self._override_blind = 0
                    self._withdrawn = {"kind": "floor", "disk_free_bytes": disk_free_bytes, "floor_bytes": floor}
                elif w.get("kind") == "floor":
                    self._override_blind += 1
                    if self._override_blind >= self.trip_after:
                        self._withdrawn = {"kind": "unreadable"}
                        self._override_blind = 0
            return None
        if not engaged:
            self._override = self._withdrawn = None
            self._override_blind = 0
            return "cleared"
        now_on = {k for k, on in (("wal", self._wal), ("disk", self._disk)) if on}
        if not now_on <= set(self._override.get("kinds", ())):
            self._override = self._withdrawn = None
            self._override_blind = 0
            return "widened"
        if disk_free_bytes is None:
            self._override_blind += 1
            if self._override_blind >= self.trip_after:
                self._override = None
                self._override_blind = 0
                self._withdrawn = {"kind": "unreadable"}
                return "unreadable"
            return None
        self._override_blind = 0
        if disk_free_bytes <= floor:
            self._override = None
            self._withdrawn = {"kind": "floor", "disk_free_bytes": disk_free_bytes, "floor_bytes": floor}
            return "withdrawn"
        return None

    def _account_locked(self, was: bool, now_mono: float) -> None:
        """Episode bookkeeping. Caller holds the lock."""
        now = self._wal or self._disk
        if now and not was:
            self._engagements += 1
            self._since = datetime.now(UTC).isoformat(timespec="seconds")
            self._since_mono = now_mono
            self._peak_wal_while_engaged = int(self._last.get("wal_bytes") or 0)
            # The figures at the FIRST refusal, kept so the pass that was in flight can be
            # measured against them when it ends (:meth:`note_pass_ended`).
            self._episode = {
                "start_mono": now_mono,
                "at": self._since,
                "kind": "disk" if self._disk else "wal",
                "free_at_trip": self._last.get("disk_free_bytes"),
                "wal_at_trip": self._last.get("wal_bytes"),
                "corpus_at_trip": self._last.get("corpus_bytes"),
                "measured": False,
            }
        elif was and not now and self._since_mono is not None:
            self._total_engaged_s += now_mono - self._since_mono
            self._since, self._since_mono = None, None
            self._report_key = None  # the next episode's first report is a WARNING again
            self._episode = None

    def _log_transitions(self, tripped: list[str], released: list[str]) -> None:
        # OUTSIDE the lock: the log handler does file I/O and workers' admit() must never
        # queue behind it (the memory guard's own rule).
        for kind in tripped:
            if kind == "wal":
                _LOG.warning(
                    "STORAGE GUARD ENGAGED (WAL) -- collection pausing: the write-ahead log is "
                    "%s against a limit of %s on this machine; it cannot be reset while a long "
                    "read or a long write holds it open. It resumes by itself when the log "
                    "resets.",
                    _size_text(self._last.get("wal_bytes")),
                    _size_text(self._thresholds.get("wal_high_bytes")),
                )
            else:
                _LOG.warning(
                    "STORAGE GUARD ENGAGED (DISK) -- collection pausing before the drive fills: "
                    "%s free against a reserve of %s. It resumes by itself once about %s is free.",
                    _size_text(self._last.get("disk_free_bytes")),
                    _size_text(self._thresholds.get("disk_reserve_bytes")),
                    _size_text(self._thresholds.get("disk_resume_bytes")),
                )
        for kind in released:
            if kind == "disk-retry":
                _LOG.warning(
                    "storage guard released (disk: the hold after a failed write has lapsed and free "
                    "space cannot be read, so this is a retry) -- collection resumes; another failed "
                    "write latches it again at once"
                )
            else:
                _LOG.warning("storage guard released (%s recovered) -- collection resumes", kind)

    def note_disk_full(self, detail: str = "a write failed: the drive is full") -> None:
        """A write FAILED for want of space: stop now, without waiting for the next sample.

        Called from the engine's error hook and from the pass's own failure path. It is a
        latch, not a sample: it holds for at least :data:`ERROR_HOLD_S` and releases only when
        free space is healthy too, so a drive that reports room but refuses writes (a quota)
        cannot flap at pass cadence. Never raises.
        """
        if not self.enabled():
            return
        try:
            now_mono = self._clock()
            with self._lock:
                was = self._wal or self._disk
                was_disk = self._disk
                self._disk_full_events += 1
                self._last_disk_full = {
                    "at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "detail": str(detail)[:200],
                    "disk_free_bytes": self._last.get("disk_free_bytes"),
                    "wal_bytes": self._last.get("wal_bytes"),
                    "corpus_bytes": self._last.get("corpus_bytes"),
                }
                if not was_disk:
                    self._disk_by_error = True  # no measurement set this latch: a write did
                self._disk = True
                self._disk_over = self._disk_under = 0
                self._hold_until = now_mono + ERROR_HOLD_S
                overridden = self._override is not None
                self._override = self._withdrawn = None  # a drive that refuses writes is not forced
                self._account_locked(was, now_mono)
                first = not was_disk
            if overridden:
                _LOG.warning(
                    "STORAGE GUARD OVERRIDE WITHDRAWN -- a write failed for want of space (%s); "
                    "collection pauses again and the button is refused while the hold lasts.",
                    str(detail)[:120],
                )
            if first:
                _LOG.warning(
                    "STORAGE GUARD ENGAGED (DISK) -- a write failed for want of space (%s); "
                    "free %s, WAL %s, corpus %s. Collection pauses until space is free again.",
                    str(detail)[:120],
                    _size_text(self._last.get("disk_free_bytes")),
                    _size_text(self._last.get("wal_bytes")),
                    _size_text(self._last.get("corpus_bytes")),
                )
        except Exception:  # noqa: BLE001 - an observer never replaces the real error
            pass

    def note_error(self, exc: BaseException | None, where: str = "") -> bool:
        """Latch DISK when ``exc`` is a full-drive failure (or an I/O error on a drive whose free
        space is below the reserve, :meth:`note_io_error`); returns whether it latched. Never raises."""
        try:
            if is_disk_full(exc):
                self.note_disk_full(f"{where + ': ' if where else ''}{_disk_full_detail(exc)}")
                return True
            return self.note_io_error(exc, where)
        except Exception:  # noqa: BLE001
            pass
        return False

    def _io_error_reading(self) -> dict[str, Any]:
        """The drive reading an I/O error is classified by: a fresh one, or the last one taken
        within :data:`IO_READING_REUSE_S`, and never two at once (a caller that finds a reading in
        flight takes the last one if it is younger than :data:`IO_READING_STALE_S`, and none
        otherwise, rather than queue behind a drive that may be hung). An unreadable drive is
        ``{}``: "not classified"."""
        now = self._clock()
        with self._lock:
            cached = self._io_reading
            if cached is not None and now - cached[0] < IO_READING_REUSE_S:
                return cached[1]
            if self._io_reading_busy:
                if cached is not None and now - cached[0] < IO_READING_STALE_S:
                    return cached[1]
                return {}
            self._io_reading_busy = True
        try:
            try:
                reading = self._readings() or {}
            except Exception:  # noqa: BLE001 - an unreadable drive is the answer "not classified"
                reading = {}
            with self._lock:
                self._io_reading = (self._clock(), reading)
            return reading
        finally:
            with self._lock:
                self._io_reading_busy = False

    def note_io_error(self, exc: BaseException | None, where: str = "") -> bool:
        """SQLite's plain "disk I/O error" (:func:`is_io_error`): latch DISK only when the drive's
        own free space, read NOW, is below the reserve (the condition the guard's samples trip
        on, brought forward to the failure). Otherwise the error is recorded (``last_io_error``
        in :meth:`state`) and left to the data-drive watchdog: a drive that reports room and
        fails with an I/O error is not "full", and pausing collection for it on the message
        alone would be a guess. A drive whose free space is unreadable is not classified either.
        Returns whether it latched. Never raises."""
        if not self.enabled():
            return False
        try:
            if not is_io_error(exc):
                return False
            reading = self._io_error_reading()
            free, total = reading.get("disk_free_bytes"), reading.get("disk_total_bytes")
            reserve = disk_reserve_bytes(total)
            full = free is not None and free < reserve
            with self._lock:
                self._io_errors += 1
                self._last_io_error = {
                    "at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "where": where or None,
                    "detail": _io_error_detail(exc),
                    "disk_free_bytes": free,
                    "disk_reserve_bytes": reserve,
                    "latched": bool(full),
                }
            if full:
                self.note_disk_full(
                    f"{where + ': ' if where else ''}disk I/O error with {_size_text(free)} free, "
                    f"below the {_size_text(reserve)} reserve"
                )
            return bool(full)
        except Exception:  # noqa: BLE001 - an observer never replaces the real error
            return False

    def reset(self, *, reason: str = "user action") -> None:
        """Explicit start or run-now: a RETRY, never an override. The latches are cleared and
        the guard re-trips after ``trip_after`` fresh over-threshold samples if the WAL is still
        pinned or the drive still full. The button that FORCES collection on is
        :meth:`override`.

        An override that is still NEEDED is left alone: while the last reading still exceeds a
        limit it covers (or cannot be read), collection already runs and there is nothing to
        retry, and clearing the latches under it would only end it and re-pause collection after
        ``trip_after`` samples, which is none of the ways R112 lets an override end (the cause
        clearing, the floor, a failed write, a second limit, free space unreadable). Where the last
        reading does not show a covered limit exceeded (for example when only the hysteresis holds
        the latch), the retry runs as usual: it ends the override and re-arms the limit, so no
        override outlives its cause for want of an exit."""
        was = False
        had_override = False
        now_mono = self._clock()
        with self._lock:
            if self._override is not None and (self._wal or self._disk) and self._override_needed_locked():
                return
            was = self._wal or self._disk
            had_override = self._override is not None
            self._wal = self._disk = False
            self._wal_over = self._wal_under = self._disk_over = self._disk_under = 0
            self._hold_until = None
            self._override = self._withdrawn = None
            self._override_blind = 0
            self._disk_by_error = False
            self._account_locked(was, now_mono)
        if was:
            _LOG.warning("storage guard released (%s) -- collection resumes", reason)
        if had_override:
            _LOG.warning(
                "STORAGE GUARD OVERRIDE ENDED (%s) -- the last reading does not show a limit it covered "
                "as exceeded, so the retry re-armed the guard.",
                reason,
            )

    def _override_needed_locked(self) -> bool:
        """Whether the last reading still exceeds (or cannot be read against) a limit the override
        covers. Caller holds the lock; an unreadable figure is not evidence that the cause cleared."""
        last, thr = self._last, self._thresholds
        kinds = set((self._override or {}).get("kinds", ()))
        wal, free = last.get("wal_bytes"), last.get("disk_free_bytes")
        wal_high, reserve = thr.get("wal_high_bytes"), thr.get("disk_reserve_bytes")
        # The WAL limit has a free-space term that is dropped when free space cannot be read, so
        # an unreadable figure may leave the stored limit too high (not with OO_WAL_HIGH_MB set,
        # where keeping the override is merely cautious: ``trip_after`` blind samples withdraw it):
        # no evidence the log is under its real limit.
        if "wal" in kinds and self._wal and (wal is None or wal_high is None or free is None or wal >= wal_high):
            return True
        return bool("disk" in kinds and self._disk and (free is None or reserve is None or free < reserve))

    def _override_refusal_locked(
        self, free: int | None, floor: int, now_mono: float
    ) -> dict[str, Any] | None:
        """What a click on "Resume anyway" would be answered with right now, or None when it
        would be granted: the ONE place the three refusals are decided, so the button that is
        offered and the click that is answered cannot disagree. Caller holds the lock."""
        if self._hold_until is not None and now_mono < self._hold_until:
            return {"kind": "held", "frame": FRAME_OVERRIDE_HELD, "vars": {}}
        if free is None:
            return {"kind": "unreadable", "frame": FRAME_OVERRIDE_UNREADABLE, "vars": {}}
        if free <= floor:
            return {"kind": "floor", "frame": FRAME_OVERRIDE_STOPPED, "vars": {"free": free, "floor": floor}}
        return None

    def override(self, *, reason: str = "operator override") -> dict[str, Any]:
        """The operator's "Resume anyway" (R112, question 18 = a): let collection continue while
        a limit is still exceeded. What bounds it is in the module docstring.

        Takes a fresh reading (file sizes and a statvfs, no lock held) and refuses, with a
        sentence frame, when a write has just failed for want of space (the hold), when free
        space cannot be read, or when it is already at or below the override floor. Returns
        ``{"engaged", "overridden", "refused"}``; never raises."""
        out: dict[str, Any] = {"engaged": False, "overridden": False, "refused": None}
        if not self.enabled():
            return out
        try:
            r = self._readings() or {}
        except Exception:  # noqa: BLE001 - an unreadable drive is a refusal, not a crash
            r = {}
        wal, free = r.get("wal_bytes"), r.get("disk_free_bytes")
        now_mono = self._clock()
        refused: dict[str, Any] | None = None
        with self._lock:
            out["engaged"] = self._wal or self._disk
            if not out["engaged"]:
                self._override = self._withdrawn = None  # nothing left to override
                return out
            floor = override_floor_bytes(wal if wal is not None else self._wal_seen)
            refused = self._override_refusal_locked(free, floor, now_mono)
            if refused is None:
                self._override = {
                    "at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "since_mono": now_mono,
                    "reason": reason,
                    # The limits that were exceeded when the operator chose: a later one is a new
                    # fact the operator has not seen (see _update_override_locked).
                    "kinds": tuple(k for k, on in (("wal", self._wal), ("disk", self._disk)) if on),
                }
                self._override_blind = 0
                self._withdrawn = None
                self._overrides += 1
                out["overridden"] = True
            else:
                out["refused"] = refused
        if refused is None:
            _LOG.warning(
                "STORAGE GUARD OVERRIDDEN (%s) -- collection continues although a limit is "
                "exceeded (WAL %s, free %s); it stops again by itself if free space falls to "
                "%s, or if a write fails for lack of space.",
                reason,
                _size_text(wal),
                _size_text(free),
                _size_text(floor),
            )
        else:
            _LOG.warning("storage guard override refused (%s): %s", refused["kind"], reason)
        return out

    def note_pass_ended(self, pass_started_mono: float) -> dict[str, Any] | None:
        """Measure the TAIL: what kept using the drive between the guard's first refusal and
        the end of the pass that was in flight when it refused.

        The disk reserve (``max(1 GiB, 2% of the drive)``) protects exactly this tail (the
        writes still in flight while a pass winds down, plus the pass-tail records), yet it is
        sized from the drive, not from anything measured. This records the measurement the
        sizing needs (2026-09-30 ruling: size the reserve from the instance's own measured
        tail plus a stated margin once it exists). Once per engagement, and only for a pass
        that STARTED before the guard first refused (a pass refused from its first source has
        no tail). Numbers only: each figure is ``None`` when it could not be read, never 0.
        The drive figure is an UPPER BOUND, since it also counts whatever else used the drive
        meanwhile. Never raises.
        """
        try:
            if not self.enabled():
                return None
            with self._lock:
                ep = self._episode
                if ep is None or ep["measured"] or not (self._wal or self._disk):
                    return None
                if ep["start_mono"] < pass_started_mono:
                    return None  # engaged before this pass began: refused from the start
                ep["measured"] = True
                snap = dict(ep)
            r = self._readings() or {}
            now_mono = self._clock()
            free_end, wal_end, corpus_end = (
                r.get("disk_free_bytes"),
                r.get("wal_bytes"),
                r.get("corpus_bytes"),
            )
            free_trip = snap["free_at_trip"]
            tail = {
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
                "engaged_at": snap["at"],
                "kind": snap["kind"],
                "seconds": round(max(0.0, now_mono - snap["start_mono"]), 1),
                "free_at_trip": free_trip,
                "free_at_end": free_end,
                # The headline: how much the drive lost in the tail (an upper bound).
                "drive_free_drop_bytes": (
                    None if free_trip is None or free_end is None else max(0, int(free_trip) - int(free_end))
                ),
                "wal_at_trip": snap["wal_at_trip"],
                "wal_at_end": wal_end,
                "corpus_at_trip": snap["corpus_at_trip"],
                "corpus_at_end": corpus_end,
            }
            with self._lock:
                self._tails.append(tail)
            _LOG.info(
                "storage guard: the pass that was in flight when the guard first refused ended "
                "%s s later; the drive lost up to %s in that tail (WAL %s -> %s)",
                tail["seconds"],
                _size_text(tail["drive_free_drop_bytes"]),
                _size_text(tail["wal_at_trip"]),
                _size_text(tail["wal_at_end"]),
            )
            return tail
        except Exception:  # noqa: BLE001 - a measurement never disturbs the pass
            _LOG.debug("storage guard: tail measurement failed", exc_info=True)
            return None

    # -- the pull side -------------------------------------------------------------
    def poll(self) -> bool:
        """Take a fresh reading NOW and return the engaged state afterwards."""
        if not self.enabled():
            return False
        r = self._readings() or {}
        return self.observe(
            wal_bytes=r.get("wal_bytes"),
            corpus_bytes=r.get("corpus_bytes"),
            disk_free_bytes=r.get("disk_free_bytes"),
            disk_total_bytes=r.get("disk_total_bytes"),
            lane_wal_bytes=r.get("lane_wal_bytes"),
        )

    def log_failure_once(self, what: str, exc: BaseException) -> None:
        """Log a failure of the guard's own work at WARNING with its traceback the FIRST time it
        happens (and when it changes), and at DEBUG while it repeats: a drain that raises on every
        tick would otherwise write a traceback every ten seconds into the 2,000-record error ring
        the diagnostics bundle carries (the pin report has the same once-per-change rule). The key
        is the exception type and its first line, kept PER PATH (``what``): two paths failing in turn
        (the drain and the unsupervised poll) would otherwise flip one shared key and each log a
        traceback again every time. It never reaches a log line."""
        try:
            first = (str(exc).splitlines() or [""])[0][:80]
        except Exception:  # noqa: BLE001 - a hostile __str__ is just a different key
            first = ""
        key = f"{what}|{type(exc).__name__}|{first}"
        with self._lock:
            changed = key != self._failure_keys.get(what)
            self._failure_keys[what] = key
        (_LOG.warning if changed else _LOG.debug)(
            "storage guard: %s failed%s", what, "" if changed else " again", exc_info=exc
        )

    def clear_failure(self, what: str) -> None:
        """A path that worked again: its next failure is news (WARNING with a traceback), not "again"."""
        with self._lock:
            self._failure_keys.pop(what, None)

    def poll_and_drain_unsupervised(self) -> None:
        """Sample and drain on the CALLER's thread when no supervisor thread is running.

        The supervisor is what releases the latch (fresh readings, the drain). A waiter that
        would otherwise wait for ever (the pass loop, :meth:`wait_if_engaged`) calls this each
        turn; it is a no-op when the supervisor runs or the guard is disabled. Never raises.
        """
        if not self.enabled() or supervisor_running():
            return
        try:
            self.poll()
            # Only a pass in which a drain RAN says the drain path works: a tick where none was due returns
            # None and proves nothing about it, so a failure only the due path raises would be news again
            # (a WARNING with a traceback) at every due tick instead of once.
            if self.drain_if_due() is not None:
                self.clear_failure("the unsupervised poll")
        except Exception as exc:  # noqa: BLE001 - a waiter must never die of the guard's own reading
            self.log_failure_once("the unsupervised poll", exc)

    def drain_if_due(self) -> dict | None:
        """While a latch is engaged, try to reset the WAL (the boundary's own call; a reset WAL
        also gives its disk back), at most every :data:`DRAIN_EVERY_S`; name the holders when
        TRUNCATE is busy.

        Returns the drain record when one ran (``{"error": <type>}`` for one that failed). Never while an exclusive operation owns the
        machine (an import, a restore's swap: the drain opens connections to the live corpus
        and must not do so between a restore's dispose and its replace), and under a corpus
        lease, so a restore that starts during a drain waits for it. At most one drain runs at a
        time (an in-flight flag taken under the guard's lock, so two callers cannot both pass the
        cadence check). A busy write gate (bounded at 30 s by the guard's own drain,
        :func:`_default_drain`) delays only the caller: the supervisor calls this on a thread of its
        own, so the floor is still read every tick.
        """
        from src.scheduler.runner import owns_the_machine

        now_mono = self._clock()
        with self._lock:
            if not self._wal and not self._disk:
                return None
            if self._drain_inflight:
                return None
            if self._last_drain_mono is not None and now_mono - self._last_drain_mono < DRAIN_EVERY_S:
                return None
            # A drive-only pause drains only when the log is big enough to give space back:
            # below the smallest log the guard itself calls large, a reset frees less than a
            # tenth of the smallest reserve and logs a record every ten seconds onto a nearly
            # full drive. An unreadable size drains (the drain is the measurement).
            wal_now = self._last.get("wal_bytes")
            if not self._wal and wal_now is not None and wal_now < WAL_ABSOLUTE_MIN_BYTES:
                return None
            self._drain_inflight = True  # claimed under the lock that made the checks
        try:
            if owns_the_machine():
                return None  # not a drain that ran: the stamp is not taken
            return self._run_drain(now_mono)
        finally:
            with self._lock:
                self._drain_inflight = False

    def _run_drain(self, now_mono: float) -> dict | None:
        """The drain a caller has claimed (:meth:`drain_if_due`): lease, checkpoint, the stamp
        when it ends, record and the pin report. ``_drain_inflight`` is the caller's to release."""
        from src.database.corpus_lease import corpus_lease

        try:
            with corpus_lease("storage-guard-drain"):
                rec = self._drain()
            self.clear_failure("the drain")  # a failure after this success is news again
        except Exception as exc:  # noqa: BLE001 - the drain's own thread must not die of it
            self.log_failure_once("the drain", exc)
            rec = {"error": type(exc).__name__}
        finally:
            # Paced from when the drain ENDED, however it ended: one that queued 30 s on the write
            # gate must not be followed five seconds later by the next (the permanent waiter this
            # cadence exists to prevent), and one that raised past the ``except`` (a
            # ``BaseException``) must not leave the cadence unstamped either.
            with self._lock:
                self._last_drain_mono = self._clock()
        # TRUNCATE came back busy: a reader holds the log. The gate was busy: a WRITER held the
        # write gate for the whole bounded wait and TRUNCATE never ran. Different facts.
        pinned = isinstance(rec, dict) and rec.get("busy") == 1
        gate_busy = isinstance(rec, dict) and "skipped" in rec
        report = None
        if (pinned or gate_busy) and (
            self._last_pin_mono is None or now_mono - self._last_pin_mono >= PIN_REPORT_EVERY_S
        ):
            report = _pin_report(rec)
        with self._lock:
            self._drains += 1
            self._last_drain = {
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
                "busy": rec.get("busy") if isinstance(rec, dict) else None,
                "skipped": rec.get("skipped") if isinstance(rec, dict) else None,
                # A checkpoint that failed (its own outcome, never "disabled / not due"): the
                # exception's type, e.g. the pool's TimeoutError after OO_DB_POOL_TIMEOUT.
                "error": rec.get("error") if isinstance(rec, dict) else None,
                "wal_bytes_before": rec.get("wal_bytes_before") if isinstance(rec, dict) else None,
                "wal_bytes_after": rec.get("wal_bytes_after") if isinstance(rec, dict) else None,
                "ran": rec is not None and not (isinstance(rec, dict) and "error" in rec),
                # OO_WAL_CHECKPOINT=0 makes the drain a no-op by the operator's own switch: the
                # latch then releases only when SQLite resets the log on a later write, or on a
                # start or run-now retry. Said here rather than left to read as a drain that failed.
                "checkpoint_disabled": bool(rec is None and not _checkpoint_enabled()),
            }
            if report is not None:
                self._last_pin_report = report
                self._last_pin_mono = now_mono
        if report is not None:
            # The oldest checkout is the likeliest candidate: the younger ones churn with the workers (and
            # more so under an override, when collection runs), so keying on all of them would
            # bring back the one-warning-a-minute flood this key exists to stop.
            holders = report.get("holders", [])
            key = ("pinned" if pinned else "gate-busy", str(holders[0].get("thread")) if holders else None)
            with self._lock:
                fresh = key != self._report_key
                self._report_key = key
            log = _LOG.warning if fresh else _LOG.info
            tops = "; ".join(
                f"{h['thread']} ({h['age_s']:.0f} s)"
                + (f" [{h['pool']} pool]" if h.get("pool") else "")
                + (f" at {h['stack'][-1]}" if h.get("stack") else "")
                for h in report.get("holders", [])[:PIN_LOG_HOLDERS]
            )
            if pinned:
                log(
                    "storage guard: the WAL cannot be reset -- TRUNCATE is busy, a reader holds "
                    "it; checkouts (candidates, not proof of a snapshot): %s",
                    tops or "none listed (the holder is not a pooled checkout)",
                )
            else:
                log(
                    "storage guard: the WAL was not reset -- the write gate stayed busy (a writer "
                    "is running), so TRUNCATE never ran; checkouts: %s",
                    tops or "none listed",
                )
        return rec

    def wait_if_engaged(
        self,
        stop: threading.Event | None = None,
        *,
        poll_s: float = 2.0,
        max_wait_s: float | None = None,
    ) -> bool:
        """Block, interruptibly, while engaged. For a long background writer at a chunk
        boundary; holds no session, gate or permit here. Returns whether it waited.

        It follows the LATCH, not the operator's override: "Resume anyway" forces COLLECTION on
        (:meth:`admit`), and a background rewrite (the keyword boot recompute) is not collection.

        Without a supervisor thread it takes the readings and the drain itself each turn
        (:meth:`poll_and_drain_unsupervised`), so the wait ends when the cause does. It ends
        when ``stop`` is set, or after ``max_wait_s`` seconds when one is given (a pause lasts
        as long as whatever holds the log lives, so a caller that cannot wait for ever says
        how long it can); with neither it waits as long as the pause lasts.
        """
        waited = False
        deadline = None if max_wait_s is None else self._clock() + max(0.0, max_wait_s)
        pause = stop if stop is not None else threading.Event()  # never set: a plain timed wait
        while True:
            self.poll_and_drain_unsupervised()
            if not (self.enabled() and self.engaged):
                break
            if stop is not None and stop.is_set():
                break
            if deadline is not None and self._clock() >= deadline:
                break
            waited = True
            pause.wait(poll_s if deadline is None else max(0.0, min(poll_s, deadline - self._clock())))
        return waited

    # -- introspection -------------------------------------------------------------
    def state(self, *, detail: bool = False) -> dict:
        """The honest, numbers-first state for status payloads and the bundle.

        ``detail`` adds the six-hour history (360 samples) and the last pin report (holders with
        stacks): they ride the bundle's storage block, never the polled status payload.
        """
        with self._lock:
            wal, disk = self._wal, self._disk
            thr = dict(self._thresholds)
            last = dict(self._last)
            notes: list[dict[str, Any]] = []
            overridden = self._override is not None and (wal or disk)
            floor_now = override_floor_bytes(self._wal_seen)
            # A write-error latch on a drive that still reports room says so, instead of
            # "only X is free" about a healthy X (the override's note included).
            free_now = last.get("disk_free_bytes")
            reserve_now = thr.get("disk_reserve_bytes")
            by_error = self._hold_until is not None and (
                free_now is None or reserve_now is None or free_now >= reserve_now
            )
            if overridden:
                if disk:
                    notes.append(
                        {
                            "kind": "override-disk",
                            "frame": FRAME_OVERRIDE_DISK_ERROR if by_error else FRAME_OVERRIDE_DISK,
                            "vars": {
                                "free": free_now,
                                "reserve": reserve_now,
                                "floor": floor_now,
                            },
                        }
                    )
                if wal:
                    notes.append(
                        {
                            "kind": "override-wal",
                            "frame": FRAME_OVERRIDE_WAL,
                            "vars": {
                                "size": last.get("wal_bytes"),
                                "limit": thr.get("wal_high_bytes"),
                                "floor": floor_now,
                            },
                        }
                    )
            elif (wal or disk) and self._withdrawn is not None:
                if self._withdrawn.get("kind") == "unreadable":
                    notes.append(
                        {"kind": "override-withdrawn", "frame": FRAME_OVERRIDE_UNREADABLE, "vars": {}}
                    )
                else:
                    notes.append(
                        {
                            "kind": "override-withdrawn",
                            "frame": FRAME_OVERRIDE_STOPPED,
                            "vars": {
                                "free": self._withdrawn["disk_free_bytes"],
                                "floor": self._withdrawn["floor_bytes"],
                            },
                        }
                    )
            if disk and not overridden:
                notes.append(
                    {
                        "kind": "disk",
                        "frame": FRAME_DISK_ERROR if by_error else FRAME_DISK,
                        "vars": {
                            "free": last.get("disk_free_bytes"),
                            "reserve": thr.get("disk_reserve_bytes"),
                            "resume": thr.get("disk_resume_bytes"),
                        },
                    }
                )
            if wal and not overridden:
                notes.append(
                    {
                        "kind": "wal",
                        "frame": FRAME_WAL,
                        "vars": {"size": last.get("wal_bytes"), "limit": thr.get("wal_high_bytes")},
                    }
                )
            reason = " ".join(_render_english(n) for n in notes) or None
            return {
                "enabled": self.enabled(),
                "engaged": wal or disk,
                "kinds": [n["kind"] for n in notes],
                "phase": None if overridden else (PHASE_DISK if disk else (PHASE_WAL if wal else None)),
                # An operator's override (R112): collection runs although the latch holds. The
                # button is offered only while it does not.
                "overridden": bool(overridden),
                # What a click on the button would be refused with right now (the same decision
                # override() makes, from the last sample), or None when it would be granted: the
                # page offers the button only then, and says the refusal otherwise (a supervisor
                # that is not running is the route's own answer and is not in this preview).
                "override_refusal": (
                    self._override_refusal_locked(free_now, floor_now, self._clock())
                    if (wal or disk) and not overridden
                    else None
                ),
                "override": (
                    {
                        "since": self._override["at"],
                        "floor_bytes": floor_now,
                        "reason": self._override["reason"],
                    }
                    if overridden and self._override is not None
                    else None
                ),
                "overrides": self._overrides,
                "since": self._since,
                "reason": reason,
                "notes": notes,
                "engagements": self._engagements,
                "total_engaged_s": round(self._total_engaged_s, 1),
                "peak_wal_bytes_while_engaged": self._peak_wal_while_engaged if (wal or disk) else None,
                "disk_full_events": self._disk_full_events,
                "last_disk_full": self._last_disk_full,
                # SQLite "disk I/O error"s seen, and the newest with the free space it was judged
                # against: ``latched`` says whether that free space was below the reserve.
                "io_errors": self._io_errors,
                "last_io_error": self._last_io_error,
                "thresholds": {
                    **thr,
                    "override_floor_bytes": floor_now,
                    "trip_after_samples": self.trip_after,
                    "resume_after_samples": self.resume_after,
                },
                "last_reading": last,
                "last_drain": self._last_drain,
                "drains": self._drains,
                # What the disk reserve protects, MEASURED (see note_pass_ended): the newest
                # tail, and with ``detail`` all of them and the largest drive loss seen.
                "last_tail": self._tails[-1] if self._tails else None,
                # The pin report carries up to eight holders with a stack each: it rides the
                # bundle (detail), not every status poll.
                **(
                    {
                        "last_pin_report": self._last_pin_report,
                        "history": list(self._history),
                        "tails": list(self._tails),
                        "max_tail_drive_free_drop_bytes": max(
                            (t["drive_free_drop_bytes"] for t in self._tails if t["drive_free_drop_bytes"] is not None),
                            default=None,
                        ),
                    }
                    if detail
                    else {"has_pin_report": self._last_pin_report is not None}
                ),
                "readings_available": (
                    any(last.get(k) is not None for k in ("wal_bytes", "disk_free_bytes")) if last else None
                ),
                "method": (
                    "Measured from file sizes and the drive's free bytes; no table is read. "
                    "WAL limit = min(clamp(10% of the corpus file, 512 MiB, 2 GiB), 10% of free "
                    "disk), never below 128 MiB: it protects normal bursts (floor), the next "
                    "unlock's recovery time (ceiling) and the drive (the free-disk term). Disk "
                    "reserve = the larger of 1 GiB (the writes still in flight while a pass winds "
                    "down) and 2% of the drive (room for everything else that writes to it). "
                    "Engages after "
                    f"{self.trip_after} consecutive samples, resumes after {self.resume_after} "
                    "healthy ones with margin, or at once on a full-disk write error. The "
                    "operator's override (\"Resume anyway\") lets collection continue while a "
                    "limit is exceeded; it ends by itself when the cause clears or another limit "
                    "is crossed, stops again if free space falls to max(128 MiB, the log's own "
                    "size) (the room to write the log back into the database and finish a write) "
                    "or cannot be read, and is refused while a write has just failed for lack of "
                    "space. "
                    "Missing readings never count. The history is one sample a minute for six "
                    "hours, in memory only; the hourly wal_bytes and disk_free_mib gauges are "
                    "recorded by idle maintenance, which yields while the guard is engaged, so "
                    "the history is what covers those hours. The tail figures measure what the disk "
                    "reserve protects: the drive's loss between the guard's first refusal and "
                    "the end of the pass in flight (an upper bound: it counts every writer)."
                ),
            }


def _render_english(note: dict[str, Any]) -> str:
    v = note["vars"]
    return note["frame"].format(**{k: _size_text(x) for k, x in v.items()})


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, "") or default))
    except (TypeError, ValueError):
        return default


# Process-wide singleton (no thread, no I/O at import). Call sites use it as
# ``storage_guard.storage_guard`` (a module attribute) so tests can swap in a fake.
storage_guard = StorageGuard()


def on_engine_error(context) -> None:
    """The SQLAlchemy ``handle_error`` listener for an engine that WRITES to the data drive.

    A write that failed for want of space stops collection now (:meth:`StorageGuard.note_disk_full`);
    SQLite's plain "disk I/O error" does so only when the drive's free space is below the reserve
    (:meth:`StorageGuard.note_io_error`). Registered on the corpus engine (``database.session``)
    and on every lane engine (``versioned.store``): a 100 GB lane fills the same drive. Observes
    only: the error still propagates unchanged, and nothing here raises."""
    try:
        exc = getattr(context, "original_exception", None)
        if is_disk_full(exc):
            storage_guard.note_disk_full(_disk_full_detail(exc))
        else:
            storage_guard.note_io_error(exc)
    except Exception:  # noqa: BLE001 - an observer never replaces the real error
        pass


# --- the supervisor -----------------------------------------------------------------

#: How often the supervisor samples the drive. File sizes and a statvfs: cheap enough that
#: five seconds is not a cost, and short enough that a WAL growing at 1.4 MB/s moves under 10 MB
#: between samples (the figure's original source is not in the repo; the nearest measured one is
#: instance 090243's 2026-09-30 diagnostics: 4.8 GB an hour (the mean of five), 1.33 MB/s, 1.87 MB/s
#: in the highest of those five hours; the same instance's series has a worse hour at 3.27 MB/s,
#: where five seconds is 16 MB; kept in the project files). The drain never delays a sample: it runs
#: on its own thread (``_supervise``).
POLL_EVERY_S = 5.0

#: How long ``stop()`` waits, in all, for the supervisor and its drain thread to end. It protects shutdown
#: from two opposite harms: hanging on a drain that is waiting for a pooled connection or the write gate
#: (up to ``OO_DB_POOL_TIMEOUT`` plus ``DRAIN_GATE_TIMEOUT_S``, or minutes for an operator's setting), and
#: disposing the engine under a checkpoint that would have finished in milliseconds. A checkpoint of a
#: small log ends well inside it; a big one is abandoned (crash-safe: the next open recovers the log).
#: Two seconds is chosen, not measured.
STOP_JOIN_S = 2.0

_THREAD: threading.Thread | None = None
_DRAIN_THREAD: threading.Thread | None = None
_STOP = threading.Event()
_SUP_LOCK = threading.Lock()


def _drain_in_background(g: StorageGuard, stop: threading.Event) -> None:
    if stop.is_set():
        return  # shutting down: a drain that has not started must not reach the engine now
    try:
        if g.drain_if_due() is not None:  # None: none was due, which says nothing about the drain path
            g.clear_failure("the background drain")
    except Exception as exc:  # noqa: BLE001 - the drain must never kill anything but itself
        g.log_failure_once("the background drain", exc)


def _supervise(stop: threading.Event) -> None:
    """The supervisor loop: read the floor every tick; run the drain beside it, never in it."""
    global _DRAIN_THREAD
    drain: threading.Thread | None = None
    while not stop.is_set():
        try:
            g = storage_guard
            if g.enabled():
                g.poll()
                # The drain runs on its OWN thread, at most one at a time, so the floor is read
                # every ``POLL_EVERY_S`` whatever the drain is waiting on: it checks out a pooled
                # connection before the write gate (a wait ``OO_DB_POOL_TIMEOUT`` sets, which an
                # operator may raise to minutes), then queues on the gate, then runs a checkpoint.
                # Run inline, any of the three would leave the override's floor unread.
                if g.engaged and (drain is None or not drain.is_alive()):
                    # The stop check and the publishing of the thread are one step under the lock
                    # ``stop()`` reads the threads under: a drain thread is either published before
                    # it reads (and joined) or never started, never in between.
                    with _SUP_LOCK:
                        if not stop.is_set():
                            drain = threading.Thread(
                                target=_drain_in_background,
                                args=(g, stop),
                                name="oo-storage-guard-drain",
                                daemon=True,
                            )
                            _DRAIN_THREAD = drain  # so stop() can join it
                            drain.start()
        except Exception:  # noqa: BLE001 - a guard that dies silently is worse than none
            _LOG.warning("storage guard supervisor tick failed", exc_info=True)
        stop.wait(POLL_EVERY_S)


def start() -> bool:
    """Start the supervisor (idempotent across unlocks; False when disabled or running).

    Zero network, no database connection of its own at start: the first tick reads file
    sizes, and only an engaged latch ever runs a checkpoint. Each thread owns the event it
    stops on, so a ``stop()`` followed at once by a ``start()`` leaves exactly one live
    supervisor: the old thread exits on its own event, it is never revived by the clear.
    """
    global _THREAD, _STOP
    if not storage_guard.enabled():
        return False
    with _SUP_LOCK:
        if _THREAD is not None and _THREAD.is_alive() and not _STOP.is_set():
            return False
        _STOP = threading.Event()
        _THREAD = threading.Thread(target=_supervise, args=(_STOP,), name="oo-storage-guard", daemon=True)
        _THREAD.start()
        return True


def stop() -> None:
    """Ask the supervisor to exit (it finishes its current tick) and wait up to
    :data:`STOP_JOIN_S` in all for it and for its drain thread. A drain that has not started
    never does; one still waiting after that is abandoned (see the module docstring). Safe to call
    twice, and after a ``start()`` that failed to launch its thread."""
    with _SUP_LOCK:
        _STOP.set()
        threads = (_THREAD, _DRAIN_THREAD)
    deadline = time.monotonic() + STOP_JOIN_S
    for t in threads:
        # ``ident`` is None for a thread that was created but never started (a failed start()).
        if t is not None and t is not threading.current_thread() and t.ident is not None:
            t.join(timeout=max(0.0, deadline - time.monotonic()))


def supervisor_running() -> bool:
    """Whether the supervisor thread is alive. The pass loop asks, because the supervisor is
    what releases the latch: without it (it failed to start, or the guard is driven directly) a
    loop waiting on the latch would wait for ever, so the loop then takes the readings and the
    drain itself. Starting collection starts the supervisor (``runner._ensure_storage_supervisor``)."""
    with _SUP_LOCK:
        t, ev = _THREAD, _STOP
    return t is not None and t.is_alive() and not ev.is_set()
