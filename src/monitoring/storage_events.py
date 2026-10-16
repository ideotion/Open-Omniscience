"""The events behind the instant: long write-gate holds, storage-guard engagements, checkpoints, store opens and pool timeouts.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS (R119, the 2026-10-06 plan, WAL needs 2, 3 and 6). Every storage record the Diagnostics zip had was a point in time: the
write gate's current holder, the guard's counters, the last checkpoint, the last unlock. The kills and the stalls came with holds of
60 to 175 s, a log that grew for hours and a store that took seconds to open, and none of those was in a zip once it was over: a hold
was one log line, a checkpoint was the last row only, the second boot erased the first. This module keeps the last few of each, on
disk, so the zip of the NEXT start can say what the one before it did.

WHAT IT KEEPS (counts, seconds, thread and route names, frame names, the class of a failure; no statement, no value, no path, no
exception text, no term and no address):

- ``gate_hold``: a hold of the write gate of :data:`src.database.writer.HOLD_RECORD_S` or more: who held it, on which route, the
  innermost app frames the watchdog saw, and how long. It is written OPEN when the watchdog first sees it and updated on every sample,
  so a process that is killed in the middle of one leaves "held at least N s, never released" and not nothing.
- ``guard``: one storage-guard engagement (WAL or drive), open from the trip to the release, with the figures that tripped it, the
  peak log size while engaged and what ended it.
- ``checkpoint`` and ``checkpoint_notable``: every checkpoint of a live store with its trigger (the pass boundary, the guard's drain,
  a backup, a restore, an unlock, a snapshot), the PASSIVE and TRUNCATE rows, the seconds and the log before and after. The second
  kind keeps the last checkpoints that were busy, refused, failed or slow, because on a machine that checkpoints every five minutes the
  ten newest plain rows cover fifty minutes and the one that named the pinning reader is long gone.
- ``open``: one record per opening of the store, by an unlock or by a start with no passphrase: the synchronous total, its phases,
  the log at open and the slowest steps of ``init_db`` (the whole step record stays in ``session-forensics.json``).
- ``pool_timeout``: a checkout that waited out the pool's timeout: how long, for which route, and who held the connections then.
- ``run_export``, ``run_import`` and ``run_verify``: the last ten runs of each kind. They are the volume backup, restore and
  verification, the single-file restore of a legacy backup, the folder backup, restore and verification of the large data, and the
  folder import of newsletter files, each saying which way it came in (``via``) and how it ended (ok, refused, stopped, cancelled,
  paused, error, or never recorded as ended), the class of its failure, a FIXED sentence for a refusal, the seconds, the free bytes
  of the volume it wrote to when it began and, for a volume backup, the figures the engine measured (volumes, bytes, write-gate
  seconds, snapshot seconds and bytes, what the read-back found). A run is written OPEN when it starts, so a run that was killed in
  the middle leaves "started, never ended"; a start that was refused before any run existed (no passphrase, an unusable destination,
  a path that could not be examined, a job already running) is written closed, because the run journal opens nothing for it. The run
  journal (``run-journal.json``) names these runs differently from this journal: its ``export`` is the volume backup, its ``import``
  the volume restore and the legacy restore, its ``verify`` the folder verification (the volume-set verification has no run there),
  and it calls the folder backup ``folder-export``, the folder restore ``folder-import`` and the newsletter import
  ``newsletter-import``; match a record here to a run there by ``via``, the kind and the time. No path, no folder name, no exception text and no passphrase is a field of these: the
  hooks hand over numbers, class names and keys of the fixed tables below, and anything else is dropped here.

WHAT A NUMBER HERE PROTECTS. ``KEEP`` bounds what is KEPT, never what is COUNTED: every kind carries ``total`` (events recorded since
``since``, across restarts) and the member shows ``kept`` and ``dropped`` beside it, so a reader sees how much history the zip is NOT
showing. The caps protect the zip's 4,000,000-byte budget (R119): the slot's budget is the size measured at full retention (see
``diagnostics_slots.SLOTS``), not a guess.

HOW IT STAYS OUT OF THE WAY (the measured sites are the app's hottest paths and its worst moments):

- A recording is a dict update under one small lock and does NO disk I/O: the file is read by the background writer before its
  first write (so it extends the history and never replaces it) or by the member before it answers, never by the site that measured.
  The FILE is written by that thread, at most once a second, atomically (temp file and ``os.replace``, no fsync): a disk that hangs
  or fills (the moment the guard engages) delays only that thread, never the site that measured. A failed write is tried again,
  doubling from the delay to a minute. A process kill loses at most the last second while writes succeed; a clean stop flushes; a
  power loss can lose more (no fsync). The member says when the file was last written, how many writes failed and how many times
  the writer thread died (the next change starts a new one).
- Every public function catches everything: a journal that cannot write must never raise into the gate, the guard, a checkpoint or an
  unlock. A failure is counted (``write_failures``, with the class and errno name) and logged at DEBUG through ``log_failure`` (its scrubbed
  text; the traceback goes to the log file, never into the journal or the zip), and the in-memory record still serves the live zip.
- Every value is normalised on the way in (:func:`_clean`): strings are scrubbed of the passphrases the process holds and cut, lists
  and dicts are bounded, anything that is not JSON is its type name. The journal therefore cannot grow past ``KEEP`` times
  :data:`MAX_EVENT_BYTES` whatever a hook hands it.
- Nothing here opens the database, imports a model or touches the network.
"""

from __future__ import annotations

import atexit
import contextvars
import errno
import itertools
import json
import logging
import math
import os
import re
import shutil
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.monitoring import page_reading
from src.monitoring.secret_scrub import log_failure, scrubbed
from src.paths import data_dir

_LOG = logging.getLogger(__name__)

SCHEMA = "oo-storage-events-1"
_FILE = "storage_events.json"

#: How many events of each kind are KEPT (the rest are counted in ``total`` and named in ``dropped``). WHAT EACH PROTECTS: the member's
#: share of the 4,000,000-byte zip (R119; ``diagnostics_slots.SLOTS`` states the budget and how it was measured at these numbers).
#: Twenty holds are the stall episodes of a bad week (the 30 Sep crash read had holds of 60 to 175 s, a handful a day at worst); ten
#: of the others are the lead-up to one crash, which is what the question "was the log pinned by a reader or outrun by a writer"
#: needs. The pass boundary checkpoints every 300 s by default, so ``checkpoint`` alone covers fifty minutes and ``checkpoint_notable``
#: is what reaches back further. The three run kinds keep ten runs EACH (not ten between them): a restore queue of eight items that all
#: fail must not push the one failed backup of last week out of the journal; ten is the lead-up the other kinds keep. A client-driven
#: export writes TWO ``run_export`` records (the corpus volume backup, then the folder backup of the large data), so ten records are five
#: such exports, not ten.
KEEP: dict[str, int] = {
    "gate_hold": 20,
    "guard": 10,
    "checkpoint": 10,
    "checkpoint_notable": 10,
    "open": 10,
    "pool_timeout": 10,
    "run_export": 10,
    "run_import": 10,
    "run_verify": 10,
}

#: THE LONGEST ARE KEPT TOO, NOT ONLY THE NEWEST. For the kinds below ``KEEP`` is split: the ``n`` longest events by the named field, and
#: the rest of the cap for the newest. WHAT THIS PROTECTS: the one event a reader most needs. The 16 Oct 2026 bundles kept the newest 20
#: gate holds and the longest of the session (219.6 s) was not among them, because a stream of newer, shorter holds had pushed it out;
#: the rule "the newest N" shows the lead-up to a crash and hides the worst stall of the week. Both guarantees hold at once: the ``n``
#: longest AND the cap minus ``n`` newest are always kept (a repeat of both is counted once, and the spare room goes to the next newest),
#: so the kept list never exceeds ``KEEP`` and the slot's measured width does not change. ``picked_by`` on a kept event says why it is
#: there (``longest``, ``newest`` or ``both``). ``checkpoint`` has its own notable lane for the slow ones and the run kinds have their own
#: rule (a run still open is never pushed out), so neither is split.
LONGEST: dict[str, tuple[str, int]] = {
    "gate_hold": ("seconds", 10),
    "guard": ("seconds", 5),
    "pool_timeout": ("waited_s", 5),
    "open": ("total_ms", 5),
}


def _length(event: dict[str, Any], field: str) -> float | None:
    """The number an event is ranked by, or None (absent, or not a number: a bool is not a duration)."""
    value = event.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    return float(value)


def _select(kind: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The events of ``kind`` the journal keeps out of ``events`` (oldest first), in the same order: at most ``KEEP[kind]``. A kind in
    :data:`LONGEST` keeps its ``n`` longest (ties go to the newer) and the cap minus ``n`` newest, then fills what is left with the next
    newest; any other kind keeps the newest. Idempotent: selecting what was selected changes nothing."""
    cap = KEEP[kind]
    if len(events) <= cap:
        return list(events)
    rule = LONGEST.get(kind)
    if rule is None:
        return list(events[-cap:])
    field, n_long = rule
    n_new = cap - n_long
    keep = set(range(len(events) - n_new, len(events)))
    measured = [i for i in range(len(events)) if _length(events[i], field) is not None]
    for i in sorted(measured, key=lambda j: (-(_length(events[j], field) or 0.0), -j))[:n_long]:
        keep.add(i)
    i = len(events) - 1
    while len(keep) < cap and i >= 0:  # the room the overlap left goes to the next newest
        keep.add(i)
        i -= 1
    return [events[i] for i in sorted(keep)]


def _picked_by(kind: str, kept: list[dict[str, Any]]) -> list[str | None]:
    """Why each event of a kept list is there, from the list alone: ``longest`` (among the ``n`` longest of it), ``newest`` (among the
    cap minus ``n`` newest, or the next newest that filled the room) or ``both``. None for a kind with no rule."""
    rule = LONGEST.get(kind)
    if rule is None:
        return [None] * len(kept)
    field, n_long = rule
    n_new = KEEP[kind] - n_long
    measured = [i for i in range(len(kept)) if _length(kept[i], field) is not None]
    longest = set(sorted(measured, key=lambda j: (-(_length(kept[j], field) or 0.0), -j))[:n_long])
    out: list[str | None] = []
    for i in range(len(kept)):
        newest = i >= len(kept) - n_new
        out.append("both" if i in longest and newest else "longest" if i in longest else "newest")
    return out


#: A checkpoint that took this long is notable whatever its rows say. WHAT IT PROTECTS: the notable list's meaning. Five seconds is
#: three orders of magnitude over a healthy TRUNCATE on a drained log (milliseconds) and well under the pool's 30 s timeout.
NOTABLE_CHECKPOINT_S = 5.0

#: The most a background write is delayed after the first change. WHAT IT PROTECTS: the disk, on a path (the pass boundary, the
#: watchdog's sample) that can fire many times a minute during a stall; it bounds the writes to one a second and the loss on a kill to
#: the same second.
FLUSH_DELAY_S = 1.0

#: What :func:`_clean` allows. WHAT THEY PROTECT: the size of one event (``MAX_EVENT_BYTES``) whatever a hook hands over, so the
#: slot's measured budget cannot be eaten by one field.
STR_CHARS = 160
LIST_ITEMS = 12
DICT_KEYS = 24
DEPTH = 4
MAX_EVENT_BYTES = 3_000
#: A file larger than this is not read back (it is not one of ours, or it is damaged): the journal starts empty and the member says so.
MAX_FILE_BYTES = 1_000_000

#: The longest a failed background write waits before it is tried again (it doubles from ``FLUSH_DELAY_S``). WHAT IT PROTECTS: a full or
#: failing drive, which is exactly when the storage guard engages, from a write every second; and the last event of a quiet period,
#: which a failed write would otherwise leave in memory until the NEXT change, from being lost to a kill that comes before it.
RETRY_MAX_S = 60.0
#: A read that fails with an I/O error (a scanner or an indexer holding the file, a transient ``EIO``) is looked at again this many
#: times, this far apart, before the file is called unreadable. WHAT IT PROTECTS: the history in the file, which a journal that gave up
#: at the first look would start empty over and the next write would replace.
READ_ATTEMPTS = 3
READ_RETRY_S = 0.05
#: How many of a checkpoint's oldest reader checkouts one event keeps (``readers.n`` stays the full count). WHAT IT PROTECTS:
#: ``MAX_EVENT_BYTES``: the full list of eight with long thread names and routes alone would take an event past it, and the checkpoint is
#: the kind recorded on every pass boundary.
READER_HOLDERS = 3
#: How many closed holds' keys are remembered (see :func:`end`). WHAT IT PROTECTS: memory only; a hold's key is its start time, so a key
#: more than a few holds old cannot be offered again. WHAT EVICTION COSTS: an evicted key that was then offered to :func:`record` would
#: open an entry nothing ends. Not reachable for the gate, the one user: each tombstone is a hold of at least ``HOLD_RECORD_S`` (30 s) on
#: a gate that holds one writer at a time, so evicting a key takes 64 more such holds (over half an hour) while the watchdog sample that
#: could offer it late computes for microseconds to seconds.
ENDED_KEYS_MAX = 64

_LOCK = threading.RLock()
_COND = threading.Condition(_LOCK)
_WRITE_LOCK = threading.Lock()
_LOAD_LOCK = threading.Lock()  # one reader of the file at a time; never held while recording
_PATHS_LOCK = threading.Lock()  # guards _PATHS_USED only; a leaf, held for one set operation

#: A token for THIS process, stamped on every event, so an entry that was open when an earlier process ended is recognised as such.
_PROC = f"{os.getpid()}-{time.time_ns()}"  # nanoseconds: an exec restart keeps the pid and can come within the same second

#: The journal files this process has tried to read or write, as the path was when it did (a data directory is fixed for a process; a
#: test moves it). :func:`reset_for_tests` removes THESE and never resolves the data directory again, because resolving it is not free
#: while a marked drive is missing (it signals the volume monitor, which pauses collection for good).
_PATHS_USED: set[Path] = set()

_LOADED = False
_STATE: dict[str, dict[str, Any]] = {}  # kind -> {"total": int, "events": [event, ...]}: THIS process's events only
_EARLIER: dict[str, dict[str, Any]] = {}  # the same shape, as the file held it when it was first read (earlier processes')
_SINCE: str | None = None  # the first event of this process
_SINCE_FILE: str | None = None  # the first event ever, as the file held it
_READ_STATE = "not read yet"
_OPEN: dict[tuple[str, Any], dict[str, Any]] = {}  # (kind, key) -> the event dict still open in this process
_ENDED: dict[tuple[str, Any], None] = {}  # (kind, key) of events closed with tombstone=True, oldest first: never opened again
_VERSION = 0  # bumped on every change; a write of an older snapshot than the last written is skipped
_WRITTEN_VERSION = 0
_GENERATION = 0  # bumped by reset_for_tests: a snapshot taken before it is never written
_DIRTY = False
_THREAD: threading.Thread | None = None
_ATEXIT = False
_WRITE_FAILURES = 0
_LAST_WRITE_FAILURE: str | None = None
_LAST_WRITE_OK_AT: str | None = None
_INTERNAL_FAILURES = 0
_LAST_INTERNAL_FAILURE: str | None = None
_WRITER_DEATHS = 0
_READ_FAILURES = 0  # reads that left the file unread because of an I/O error that outlasted the looks: nothing is written over it
_LAST_READ_FAILURE: str | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _label(exc: BaseException) -> str:
    """The class of a failure and, for an ``OSError``, the NAME of its errno: never the message, which carries a path."""
    name = type(exc).__name__
    code = exc.errno if isinstance(exc, OSError) else None
    named = errno.errorcode.get(code) if isinstance(code, int) else None
    return f"{name} {named}" if named else name


def _internal_failure(what: str, exc: BaseException) -> None:
    global _INTERNAL_FAILURES, _LAST_INTERNAL_FAILURE
    _INTERNAL_FAILURES += 1
    _LAST_INTERNAL_FAILURE = f"{what}: {_label(exc)}"
    log_failure(_LOG, f"storage events: {what}", exc, level=logging.DEBUG)


# ---------------------------------------------------------------------------------------------------------------------------------
#  Normalising what a hook hands over
# ---------------------------------------------------------------------------------------------------------------------------------
def _clean(value: Any, depth: int = DEPTH) -> Any:
    """``value`` as bounded JSON: strings scrubbed of the passphrases the process holds and cut to :data:`STR_CHARS`; lists to
    :data:`LIST_ITEMS`; dicts to :data:`DICT_KEYS` keys, keys as strings cut to 48; depth to :data:`DEPTH`; a float that is not finite
    is ``None`` and the rest are rounded to three places; anything that is not JSON is its type name (never its ``repr``, which can
    carry a value)."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value, 3) if math.isfinite(value) else None
    if isinstance(value, str):
        text = scrubbed(value)
        return text if len(text) <= STR_CHARS else text[: STR_CHARS - 1] + "…"
    if depth <= 0:
        return f"({type(value).__name__})"
    if isinstance(value, (list, tuple)):
        return [_clean(v, depth - 1) for v in list(value)[:LIST_ITEMS]]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in list(value.items())[:DICT_KEYS]:
            out[scrubbed(str(k))[:48]] = _clean(v, depth - 1)
        return out
    return f"({type(value).__name__})"


#: The keys the journal writes itself (when, which process, whether still open, how it ended, and the member's own ``session``): a hook's
#: field of the same name is dropped, so a hook can neither forge an end nor leave an event open for ever.
_OWNED = frozenset({"at", "proc", "open", "ended", "ended_at", "session"})


def _size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


# ---------------------------------------------------------------------------------------------------------------------------------
#  The file
# ---------------------------------------------------------------------------------------------------------------------------------
def _path() -> Path:
    return data_dir() / _FILE


def _used_path() -> Path:
    """:func:`_path`, remembered as one this journal has touched (for :func:`reset_for_tests`)."""
    path = _path()
    with _PATHS_LOCK:
        _PATHS_USED.add(path)
    return path


def _empty_kind() -> dict[str, Any]:
    return {"total": 0, "events": []}


def _parse_kinds(data: Any) -> tuple[dict[str, dict[str, Any]], str | None]:
    """The kinds of a parsed journal file, each kept to its cap, every entry an earlier process left open closed as "not recorded".
    Raises on a file that is not ours (the caller names the class)."""
    kinds = data.get("kinds") if isinstance(data, dict) else None
    if not isinstance(kinds, dict) or data.get("schema") != SCHEMA:
        raise ValueError("not this journal")
    earlier: dict[str, dict[str, Any]] = {}
    for kind in KEEP:
        entry = kinds.get(kind)
        if not isinstance(entry, dict):
            continue
        raw = entry.get("events")
        events = [e for e in raw if isinstance(e, dict) and isinstance(e.get("at"), str)] if isinstance(raw, list) else []
        total = entry.get("total")
        total = total if isinstance(total, int) and not isinstance(total, bool) and total >= len(events) else len(events)
        for e in events:
            if e.get("open") and e.get("proc") != _PROC:
                e["open"] = False
                e["ended"] = "the process ended while this was open; its end was not recorded"
        earlier[kind] = {"total": total, "events": _select(kind, events)}
    since = data.get("since")
    return earlier, since if isinstance(since, str) else None


def _read_file() -> tuple[dict[str, dict[str, Any]], str | None, str, bool]:
    """Read the file once: ``(kinds, since, how it read, retry later)``. No lock is held (it is disk), and every entry an earlier
    process left open is closed as "not recorded". Never raises, and says why a file read as empty (the class of the failure, never its
    text). An I/O error is looked at again :data:`READ_ATTEMPTS` times; if it outlasts them, or the data directory cannot even be
    named, the file is NOT known to be empty or damaged, only unread: ``retry later`` is True and the caller must not write over it.
    A file that is missing, damaged, too large or not this journal reads as empty and is replaced by the next write."""
    last = "missing"
    for attempt in range(READ_ATTEMPTS):
        try:
            path = _used_path()
        except Exception as exc:  # noqa: BLE001 - a data volume that is not there: no file was read and none can be written
            return {}, None, f"unreadable ({_label(exc)})", True
        try:
            size = path.stat().st_size
            if size > MAX_FILE_BYTES:
                return {}, None, f"unreadable (larger than {MAX_FILE_BYTES} bytes)", False
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}, None, "missing", False
        except OSError as exc:
            last = f"unreadable ({_label(exc)})"
            if attempt + 1 < READ_ATTEMPTS:
                time.sleep(READ_RETRY_S)
            continue
        except Exception as exc:  # noqa: BLE001 - bad JSON or UTF-8 (ValueError), nesting too deep (RecursionError): damaged
            return {}, None, f"unreadable ({_label(exc)})", False
        try:
            earlier, since = _parse_kinds(data)
        except Exception as exc:  # noqa: BLE001 - a file of ours in a shape ours never wrote (skew or damage): not read back, never fatal
            how = "unreadable (not this journal)" if isinstance(exc, ValueError) else f"unreadable ({_label(exc)})"
            return {}, None, how, False
        return earlier, since, "ok", False
    return {}, None, last, True


def _ensure_loaded(generation: int | None = None) -> None:
    """Read the file the first time a writer or a reader NEEDS what it holds (the background writer before its first write, so it
    never replaces the history with this process's events alone; the member before it answers). A recording never calls this: it does
    no disk I/O, so the measured site, which can hold the gate's lock or the guard's, cannot wait on a disk through it.
    ``generation`` is the one the caller saw: a reset since then makes the call a no-op (a stale writer neither reads the file of
    the state that replaced its own nor applies what it read). A file that could not be READ (an I/O error that outlasted the looks)
    leaves the journal not loaded: the failure is counted and shown, the history is not assumed empty, and the next caller reads it
    again, so no write replaces a history that is only unreadable for now."""
    global _LOADED, _EARLIER, _SINCE_FILE, _READ_STATE, _READ_FAILURES, _LAST_READ_FAILURE
    if _LOADED:
        return
    with _LOAD_LOCK:
        if _LOADED:
            return
        seen = _GENERATION if generation is None else generation
        if seen != _GENERATION:
            return
        earlier, since, how, retry_later = _read_file()  # disk, no journal lock held
        with _LOCK:
            if seen != _GENERATION:
                return  # reset while the file was being read: the next caller reads it again
            _READ_STATE = how
            if retry_later:
                _READ_FAILURES += 1
                _LAST_READ_FAILURE = how
                return
            _EARLIER, _SINCE_FILE, _LOADED = earlier, since, True


def _combined_locked() -> tuple[dict[str, dict[str, Any]], str | None]:
    """What the journal holds: the file's events then this process's, the newest ``KEEP`` of each kind, and the running totals of both.
    Caller holds the lock."""
    kinds: dict[str, dict[str, Any]] = {}
    for kind in KEEP:
        old = _EARLIER.get(kind) or _empty_kind()
        new = _STATE.get(kind) or _empty_kind()
        kinds[kind] = {"total": old["total"] + new["total"], "events": _select(kind, [*old["events"], *new["events"]])}
    return kinds, _SINCE_FILE or _SINCE


def _snapshot_locked() -> tuple[str, int, int]:
    kinds, since = _combined_locked()
    text = json.dumps({"schema": SCHEMA, "since": since, "kinds": kinds}, ensure_ascii=False, separators=(",", ":"))
    return text, _VERSION, _GENERATION


def _write(text: str, version: int, generation: int) -> bool:
    """Write one snapshot atomically (temp file and replace; no fsync: a journal, not a ledger, so a power loss can leave the old file
    or an empty one, which the next read reports as unreadable). Never raises. False when the write FAILED (the caller tries again);
    True when it was written or was not due (a newer snapshot was written first, or the state was reset since this one was taken)."""
    global _WRITTEN_VERSION, _WRITE_FAILURES, _LAST_WRITE_FAILURE, _LAST_WRITE_OK_AT
    with _WRITE_LOCK:
        if generation != _GENERATION or version <= _WRITTEN_VERSION:
            return True
        tmp = None
        try:
            path = _used_path()
            tmp = path.with_name(path.name + ".tmp")
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
        except Exception as exc:  # noqa: BLE001 - a full or hung disk is when this matters; it must not reach the measured site
            _WRITE_FAILURES += 1
            _LAST_WRITE_FAILURE = _label(exc)
            log_failure(_LOG, "storage events: could not write the journal", exc, level=logging.DEBUG)
            if tmp is not None:
                with suppress(OSError):
                    tmp.unlink(missing_ok=True)
            return False
        _WRITTEN_VERSION = version
        _LAST_WRITE_OK_AT = _now()
        return True


def _wait_out(generation: int, seconds: float) -> None:
    """Wait ``seconds`` on the condition, to the deadline whatever wakes it (every change does), or until a reset."""
    deadline = time.monotonic() + seconds
    with _COND:
        while generation == _GENERATION and (left := deadline - time.monotonic()) > 0:
            _COND.wait(left)


def _flusher_loop() -> None:
    failures = 0  # consecutive failed writes: the retry waits longer each time, to RETRY_MAX_S
    while True:
        try:
            with _COND:
                while not _DIRTY:
                    _COND.wait()
                generation = _GENERATION
            # Let a burst of changes become one write: every change wakes the wait, so it runs to the deadline, not to the next wake.
            # A reset ends the wait too (it wakes it): what was waiting to be written is gone.
            _wait_out(generation, FLUSH_DELAY_S)
            if generation != _GENERATION:
                continue
            _ensure_loaded(generation)  # the file's history first, so the write below extends it and never replaces it
            snap = None
            with _LOCK:
                if generation != _GENERATION:
                    continue  # reset while this waited: what was waiting to be written is gone
                if _LOADED:
                    if not _DIRTY:
                        continue  # written by a flush() while this waited: nothing is left to write
                    snap = _snapshot_locked()  # a copy: the lock is dropped before any disk is touched
                    _clear_dirty_locked()
            # Either the file could not be read (counted in _ensure_loaded: the history is not known, so nothing is written over
            # it) or the write failed (counted in _write): the change is still not in the file, so it is wanted again, later.
            if snap is not None and _write(*snap):
                failures = 0
                continue
            failures += 1
            with _LOCK:
                if generation == _GENERATION:
                    _mark_wanted_locked()
            _wait_out(generation, min(RETRY_MAX_S, FLUSH_DELAY_S * 2 ** min(failures, 10)))
        except Exception as exc:  # noqa: BLE001 - the thread must outlive anything
            _internal_failure("flusher", exc)
            time.sleep(FLUSH_DELAY_S)  # a failure that repeats must not spin


def _flusher() -> None:
    """The writer thread. If it ends anyway (an exception that is not an ``Exception``), that is counted once and kept by class, and
    the next change starts a new one: a journal's writer never takes the app down, and an uncaught error in a thread is not printed
    (the interpreter would print its text, which can hold a path or a passphrase)."""
    global _WRITER_DEATHS
    try:
        _flusher_loop()
    except BaseException as exc:  # noqa: BLE001
        _WRITER_DEATHS += 1
        _internal_failure("the writer thread ended", exc)


def _clear_dirty_locked() -> None:
    global _DIRTY
    _DIRTY = False


def _mark_wanted_locked() -> None:
    """The snapshot just taken was not written: ask for another, without a new version (nothing changed). Caller holds the lock."""
    global _DIRTY
    _DIRTY = True


def _mark_dirty_locked() -> None:
    """A change was made. Caller holds the lock. Starts the writer thread on first use (never at import) and wakes it."""
    global _VERSION, _DIRTY, _THREAD, _ATEXIT
    _VERSION += 1
    _DIRTY = True
    if _THREAD is None or not _THREAD.is_alive():
        _THREAD = threading.Thread(target=_flusher, name="oo-storage-events", daemon=True)
        _THREAD.start()
    if not _ATEXIT:
        _ATEXIT = True
        atexit.register(flush)
    _COND.notify_all()


def flush() -> None:
    """Write the journal now, on this thread (the clean stop, ``atexit``, and the tests). Never raises. It is the only caller that
    waits for the disk, and the only one that is not a measured site: the writer thread's own write is not waited for by anyone. A
    hard kill never gets here; the entries still OPEN in the file are what that case leaves (they are closed as "not recorded" at
    the next read)."""
    try:
        with _LOCK:
            if _VERSION <= _WRITTEN_VERSION:
                return  # nothing was recorded, or everything recorded is in the file already: it stays as it is
            generation = _GENERATION
        _ensure_loaded(generation)
        with _LOCK:
            if generation != _GENERATION or not _LOADED:
                return  # reset while the file was being read
            snap = _snapshot_locked()  # a copy: the lock is dropped before the disk is touched
            _clear_dirty_locked()
        _write(*snap)  # a snapshot the writer thread already wrote (same version) is skipped inside
    except Exception as exc:  # noqa: BLE001
        _internal_failure("flush", exc)


# ---------------------------------------------------------------------------------------------------------------------------------
#  Recording
# ---------------------------------------------------------------------------------------------------------------------------------
def _build(fields: dict[str, Any]) -> dict[str, Any]:
    event: dict[str, Any] = {"at": _now(), "proc": _PROC}
    cleaned = _clean(fields)
    if isinstance(cleaned, dict):
        for k, v in cleaned.items():
            if k not in _OWNED:
                event[k] = v
    total = _size(event)
    if total > MAX_EVENT_BYTES:
        # The largest field goes first, until the event fits: what is left (the trigger, the outcome, the rows, the seconds) still says
        # what happened, and the names of what went are kept. Dropping every field would turn the most informative events into stubs.
        gone: list[str] = []
        event["oversize_bytes"] = total
        while _size(event) > MAX_EVENT_BYTES:
            candidates = [k for k in event if k not in ("at", "proc", "oversize_bytes", "fields_dropped")]
            if not candidates:
                break
            biggest = max(candidates, key=lambda k: _size(event[k]))
            gone.append(biggest)
            del event[biggest]
            event["fields_dropped"] = gone
    return event


def record(kind: str, fields: dict[str, Any], *, key: Any = None) -> None:
    """Record one event of ``kind``. With a ``key`` it stays addressable as an OPEN event: :func:`update` and :func:`end` find it by
    that key for as long as this process runs, and an earlier process's open event is closed as "not recorded" when the file is read.
    Never raises, never blocks on the disk."""
    global _SINCE
    try:
        if kind not in KEEP:
            return
        event = _build(fields)
        if key is not None:
            event["open"] = True
        with _LOCK:
            if key is not None and (kind, key) in _ENDED:
                return  # its closer ran first (see end): the entry that closer wrote is the record of this event
            if _SINCE is None:
                _SINCE = event["at"]
            entry = _STATE.setdefault(kind, _empty_kind())
            entry["total"] += 1
            entry["events"].append(event)
            if key is not None:
                _OPEN[(kind, key)] = event
            if kind in LONGEST and len(entry["events"]) > KEEP[kind]:
                # The longest are kept beside the newest (see LONGEST); an event that is not kept is forgotten, open or not (an open hold
                # is the newest, so it is always kept).
                kept = _select(kind, entry["events"])
                kept_ids = {id(e) for e in kept}
                for gone in [e for e in entry["events"] if id(e) not in kept_ids]:
                    for k in [k for k, v in _OPEN.items() if v is gone]:
                        _OPEN.pop(k, None)
                entry["events"] = kept
            while len(entry["events"]) > KEEP[kind]:
                # A RUN still open in this process is not pushed out by the records written after it: ten refused starts during one
                # long backup would otherwise evict its open record, and its end would be lost. The oldest event that is not live
                # goes first; only when every event is live does the oldest go. The other kinds keep the plain rule (the oldest goes).
                live = {id(v) for v in _OPEN.values()} if kind in _RUN_JOURNAL_KINDS else set()
                gone = entry["events"].pop(next((i for i, e in enumerate(entry["events"]) if id(e) not in live), 0))
                for k in [k for k, v in _OPEN.items() if v is gone]:
                    _OPEN.pop(k, None)
            _mark_dirty_locked()
    except Exception as exc:  # noqa: BLE001
        _internal_failure("record", exc)


def update(kind: str, key: Any, fields: dict[str, Any]) -> bool:
    """Merge ``fields`` into the open event ``(kind, key)``. False when there is none (it was never opened, was already ended, or was
    pushed out by newer events). Never raises."""
    try:
        with _LOCK:
            event = _OPEN.get((kind, key))
            if event is None:
                return False
            cleaned = _clean(fields)
            if isinstance(cleaned, dict):
                merged = {**event, **{k: v for k, v in cleaned.items() if k not in _OWNED}}
                if _size(merged) <= MAX_EVENT_BYTES:
                    event.update(merged)
                    _mark_dirty_locked()  # a merge refused for size changed nothing: no write for it
            return True
    except Exception as exc:  # noqa: BLE001
        _internal_failure("update", exc)
        return False


def end(kind: str, key: Any, fields: dict[str, Any] | None = None, *, tombstone: bool = False) -> bool:
    """Merge ``fields`` into the open event ``(kind, key)`` and close it. Returns False when there is none to close. Never raises.

    ``tombstone=True`` also remembers the key as closed, found or not: a later :func:`record` with that key is then refused. That is
    for an event whose opener can run AFTER its closer (the write gate's watchdog computes a sample for seconds, and the holder's
    release can come in between): without it the late opener would add a second entry for the same hold, open for ever, which reads
    exactly like a kill in the middle of a hold. :data:`ENDED_KEYS_MAX` bounds the memory."""
    try:
        with _LOCK:
            if tombstone:
                _ENDED[(kind, key)] = None
                while len(_ENDED) > ENDED_KEYS_MAX:
                    _ENDED.pop(next(iter(_ENDED)), None)
            event = _OPEN.get((kind, key))
            if event is None:
                return False
            if fields:
                cleaned = _clean(fields)
                if isinstance(cleaned, dict):
                    merged = {**event, **{k: v for k, v in cleaned.items() if k not in _OWNED}}
                    if _size(merged) <= MAX_EVENT_BYTES:
                        event.update(merged)
            event["open"] = False
            event["ended_at"] = _now()
            _OPEN.pop((kind, key), None)
            _mark_dirty_locked()
            return True
    except Exception as exc:  # noqa: BLE001
        _internal_failure("end", exc)
        return False


# ---------------------------------------------------------------------------------------------------------------------------------
#  The builders the hook sites call: one line at the site, the shape of the event in one place
# ---------------------------------------------------------------------------------------------------------------------------------
_TRIGGER: contextvars.ContextVar[str] = contextvars.ContextVar("oo_checkpoint_trigger", default="boundary")


@contextmanager
def checkpoint_trigger(name: str) -> Iterator[None]:
    """Say who is asking for the checkpoint made inside this block (``guard``), for the journal: a context rather than
    a parameter of ``checkpoint_wal``, so that function and every test double of it keep their signature."""
    token = _TRIGGER.set(name)
    try:
        yield
    finally:
        _TRIGGER.reset(token)


def current_trigger() -> str:
    """Who is asking for the checkpoint being made on this thread: ``boundary`` (the scheduler's pass boundary) unless a caller said otherwise."""
    return _TRIGGER.get()


def _row(row: Any) -> list[int | None] | None:
    """A ``PRAGMA wal_checkpoint`` result as ``[busy, log frames, checkpointed frames]``, or None when the call gave none."""
    try:
        if row is None:
            return None
        busy, log, done = row
        return [int(busy), int(log), int(done)]
    except (TypeError, ValueError):
        return None


def _compact_readers(readers: Any) -> Any:
    """A checkpoint's reader snapshot with at most :data:`READER_HOLDERS` of its holders (``n`` is the full count of checkouts)."""
    if isinstance(readers, dict) and isinstance(readers.get("holders"), list):
        return {**readers, "holders": readers["holders"][:READER_HOLDERS]}
    return readers


def note_checkpoint(
    trigger: str,
    *,
    passive: Any = None,
    truncate: Any = None,
    seconds: float | None = None,
    wal_before: int | None = None,
    wal_after: int | None = None,
    readers: Any = None,
    outcome: str = "done",
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """One checkpoint of the live store. ``trigger`` names who asked (``boundary``, ``guard``, ``forced`` for the restore's checkpoint
    before the swap, ``backup``, ``unlock``, ``snapshot``); ``passive`` and ``truncate`` are the rows the PRAGMAs answered; ``readers`` is the pool's oldest-checkout snapshot
    when the site has it (hygiene does); ``outcome`` is ``done``, ``skipped`` (the gate was busy), or ``failed`` with ``error`` the
    exception CLASS. A busy TRUNCATE, a refusal, a failure or a slow one is also kept in ``checkpoint_notable``."""
    try:
        p, t = _row(passive), _row(truncate)
        event = {
            "trigger": trigger,
            "outcome": outcome,
            "passive": p,
            "truncate": t,
            "seconds": seconds,
            "wal_bytes_before": wal_before,
            "wal_bytes_after": wal_after,
            "readers": _compact_readers(readers),
            "error": error,
            **(extra or {}),
        }
        event = {k: v for k, v in event.items() if v is not None}
        record("checkpoint", event)
        busy = (t is not None and t[0] != 0) or (t is None and p is not None and p[0] != 0)
        slow = isinstance(seconds, (int, float)) and seconds >= NOTABLE_CHECKPOINT_S
        if outcome != "done" or busy or slow:
            record("checkpoint_notable", {**event, "why": "refused or failed" if outcome != "done" else "a reader pinned the log" if busy else "slow"})
    except Exception as exc:  # noqa: BLE001
        _internal_failure("note_checkpoint", exc)


def _compact_init_db(record_: Any) -> dict[str, Any] | None:
    """The part of an ``init_db`` step record worth keeping per opening: the total, which call it was and the three slowest steps.
    The whole record (every step) stays in ``session-forensics.json``, once."""
    if not isinstance(record_, dict):
        return None
    steps = [s for s in (record_.get("steps") or []) if isinstance(s, dict) and isinstance(s.get("ms"), (int, float))]
    slowest = sorted(steps, key=lambda s: s["ms"], reverse=True)[:3]
    return {
        "total_ms": record_.get("total_ms"),
        "process_call": record_.get("process_call"),
        "earlier_complete_calls": record_.get("earlier_complete_calls"),
        "complete": record_.get("complete"),
        "slowest": [[s.get("step"), s.get("ms")] for s in slowest],
    }


def note_open(
    via: str,
    *,
    total_ms: float | None = None,
    phases: Any = None,
    wal_bytes_before: int | None = None,
    init_db: Any = None,
    pages: Any = None,
) -> None:
    """The store was opened: ``via`` is ``unlock`` (a passphrase was entered; ``phases`` are the synchronous phases the unlock
    timed) or ``boot`` (a start with no passphrase, where only ``init_db`` is timed). ``pages`` is the reading of the file's size in
    pages against the size it counts (``src.monitoring.page_reading``): taken from the file's bytes before any connection existed (a
    boot) or off the unlock's verify connection before it wrote or checkpointed (an unlock), a fact with the source that produced it,
    never a verdict."""
    try:
        event = {
            "via": via,
            "total_ms": total_ms,
            "phases": [[p.get("phase"), p.get("ms")] for p in phases if isinstance(p, dict)] if isinstance(phases, list) else None,
            "wal_bytes_before_open": wal_bytes_before,
            "init_db": _compact_init_db(init_db),
            "pages": page_reading.compact(pages),
        }
        record("open", {k: v for k, v in event.items() if v is not None})
    except Exception as exc:  # noqa: BLE001
        _internal_failure("note_open", exc)


def note_pool_timeout(
    *,
    waited_s: float | None = None,
    thread: str | None = None,
    route: str | None = None,
    collector: bool | None = None,
    pool_size: int | None = None,
    overflow: int | None = None,
    timeout_s: float | None = None,
    checked_out: int | None = None,
    holders: Any = None,
) -> None:
    """A checkout that waited out the pool's timeout: how long, the thread and route that waited, the pool as configured, and the oldest
    checkouts at that moment (``holders``: thread, route, age). The pool's own error is raised after this returns, unchanged."""
    try:
        event = {
            "waited_s": waited_s,
            "thread": thread,
            "route": route,
            "collector": collector,
            "pool_size": pool_size,
            "overflow": overflow,
            "timeout_s": timeout_s,
            "checked_out": checked_out,
            "holders": holders,
        }
        record("pool_timeout", {k: v for k, v in event.items() if v is not None})
    except Exception as exc:  # noqa: BLE001
        _internal_failure("note_pool_timeout", exc)


# ---------------------------------------------------------------------------------------------------------------------------------
#  Runs: the volume backup, restore and verification
# ---------------------------------------------------------------------------------------------------------------------------------
#: The journal kind of each run, by the name a run has HERE (``export`` is the volume backup and the folder backup, ``import`` every
#: restore and the newsletter import, ``verify`` both verifications). The run journal names the folder and newsletter runs differently
#: (see the module docstring), so a record here and a run in ``run-journal.json`` are matched by ``via`` and time, never by name alone.
RUN_KINDS: dict[str, str] = {"export": "run_export", "import": "run_import", "verify": "run_verify"}
_RUN_JOURNAL_KINDS = frozenset(RUN_KINDS.values())  # the kinds whose open events the trimming in :func:`record` keeps

#: How a run can end, as the run journal names it, with these differences: a backup the newsletter filter refused is "error" in
#: ``run-journal.json`` (which records its class) and "refused" here, because nothing ran; and for the legacy single-file restore the
#: hook here sees a failure before the run journal does, so a merge check's refusal (``MergeError``) is "refused" here and "error"
#: there, and the operator's own Stop (``RestoreAborted``) is "stopped-by-operator" here and "error" there. The same cause can end
#: differently by way in (a ``MergeError`` of a volume restore is "error" here), which is why every run carries ``via``. Anything else a
#: hook hands over is recorded as ``(unnamed outcome)``.
RUN_OUTCOMES = frozenset(
    {"ok", "skipped-already-merged", "refused", "stopped-by-operator", "cancelled", "paused", "error", "ended-without-a-recorded-outcome"}
)

#: Why a run was refused, as a FIXED sentence: a refusal's own text names a folder, a holder or a path, so the journal keeps the key
#: the hook chose and writes the sentence itself. A key that is not here records no sentence.
RUN_REFUSALS: dict[str, str] = {
    "no-passphrase": "the volume backup is always encrypted and no passphrase was given",
    "destination-unusable": "the destination folder could not be used (empty, not a folder, not writable or not creatable)",
    "not-a-folder": "the path given is not a folder",
    "already-running": "another volume backup, restore or verification was already running",
    "barrier": "another job still held the corpus when the restore reached the swap",
    "not-a-file": "the path given is not a file",
    "memory": "this machine could not hold the merge of an encrypted corpus, asked before anything was staged",
    "import-running": "another folder import was already running",
    "folder-running": "another folder backup, restore or verification was already running",
    "no-space": "the destination did not have the free space the backup needs",
    "free-space-unreadable": "the free space of the destination could not be read, so the backup was not started",
    "path-unreadable": "a path the request named could not be examined (the operating system refused to look at it)",
}

#: What a run came through, as a FIXED key, on every run: the volume backup, restore and verification (``volume-set``), the single-file
#: restore of a legacy backup (``single-file``), the folder import of newsletter files (``newsletter-eml``) and the large-data folder
#: backup, restore and verification (``folder``). Several ways in record as the same kind (every restore is an ``import``),
#: so a reader tells them apart by this key and by nothing else. A value outside the table is not recorded (it is never a path or a
#: folder name).
RUN_VIA: frozenset[str] = frozenset({"volume-set", "single-file", "newsletter-eml", "folder"})

#: The measurements a run may carry, by name; a value is kept only if it is a number. The free bytes are the volume the run WRITES to,
#: read when it began: the destination for a backup, the data folder (where the restore stages) for a restore. An unreadable figure is
#: absent, never ``0``.
_RUN_NUMBERS = frozenset(
    {"dest_free_bytes", "data_free_bytes", "volumes", "bytes", "gate_held_s", "snapshot_s", "snapshot_bytes", "engine_wall_s",
     "articles_merged", "reindexed", "files", "files_done", "resumed_from", "copied", "skipped", "restored", "checked",
     "mismatches"}
)
#: What the backup's read-back of the written set found (``VolumeBackupManager._verify_after_write``), the five outcomes it keeps apart.
_RUN_VERIFY_STATES = frozenset({"verified", "failed", "off", "stopped", "unavailable"})
#: A fact that is a yes or a no (a verification's own verdict on the set it read).
_RUN_FLAGS = frozenset({"set_ok"})
#: A fact that is the CLASS of a failure at a step that is not the run's end (the backup's summary file could not be written).
_RUN_CLASSES = frozenset({"summary_error"})
_CLASS_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*")
_CLASS_NAME_MAX = 80
_RUN_SEQ = itertools.count(1)


def _class_name(value: Any) -> str | None:
    """``value`` if it is shaped like the name of a class (letters, digits, underscores, dots; at most 80), else a fixed marker: the
    journal accepts a class and never a message, so a hook that hands it a sentence by mistake leaves the marker, not the sentence."""
    if value is None:
        return None
    if isinstance(value, str) and len(value) <= _CLASS_NAME_MAX and _CLASS_NAME.fullmatch(value):
        return value
    return "(not a class name)"


def _run_fields(facts: dict[str, Any]) -> dict[str, Any]:
    """The facts a run may carry, from what a hook handed over: numbers and flags by name, class names, one of five read-back states.
    Every other key, and a value of the wrong kind, is dropped (a text field cannot be added by accident, whatever the site holds)."""
    out: dict[str, Any] = {}
    for key, value in facts.items():
        if key in _RUN_NUMBERS:
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                out[key] = value
        elif key in _RUN_FLAGS:
            if isinstance(value, bool):
                out[key] = value
        elif key in _RUN_CLASSES:
            if value is not None:
                out[key] = _class_name(value)
        elif isinstance(value, str) and (
            (key == "verify" and value in _RUN_VERIFY_STATES) or (key == "via" and value in RUN_VIA)
        ):
            out[key] = value  # one of five read-back states, or the way in: a key of a fixed table, never the text
    return out


class RunNote:
    """A run opened in the journal: which kind, the key it is addressable by while this process runs, and when it began (monotonic)."""

    __slots__ = ("kind", "key", "started")

    def __init__(self, kind: str, key: Any, started: float) -> None:
        self.kind = kind
        self.key = key
        self.started = started


def run_started(what: str, **facts: Any) -> RunNote | None:
    """Open a run of ``what`` (``export``, ``import`` or ``verify``): written OPEN, so a process killed in the middle of it leaves
    "started, never ended". Returns the note the later calls take, or None (an unknown ``what``, or the journal could not record it:
    every later call then does nothing). Never raises, never touches the disk."""
    try:
        kind = RUN_KINDS.get(what)
        if kind is None:
            return None
        key = ("run", next(_RUN_SEQ))
        record(kind, _run_fields(facts), key=key)
        return RunNote(kind, key, time.monotonic())
    except Exception as exc:  # noqa: BLE001
        _internal_failure("run_started", exc)
        return None


def run_facts(note: RunNote | None, **facts: Any) -> None:
    """Add facts to the run still open under ``note`` (see :func:`_run_fields` for what is kept). Never raises."""
    if note is None:
        return
    try:
        fields = _run_fields(facts)
        if fields:
            update(note.kind, note.key, fields)
    except Exception as exc:  # noqa: BLE001
        _internal_failure("run_facts", exc)


def free_bytes_of(path: str | os.PathLike[str] | None = None) -> int | None:
    """Free bytes on the volume holding ``path`` (the data folder when ``path`` is None), or None when it cannot be read: an unreadable
    figure is not ``0``, which would read as a full drive, and it is not another volume's figure either (the path is stat-ed as given,
    never its parent). Never raises. A stat of the volume, so it is for a worker thread, never for a site that holds the write gate; it
    is a helper of the run records and not a recording, which stay dict updates. A volume that cannot be read (gone, a permission, a
    mount that gave up) is an absent field and nothing more: it is not a fault of the journal and is neither counted nor logged."""
    try:
        return int(shutil.disk_usage(Path(path) if path is not None else data_dir()).free)
    except OSError:
        return None
    except Exception as exc:  # noqa: BLE001 - a path that is not a path: the journal's fault, counted
        _internal_failure("free_bytes_of", exc)
        return None


def run_free_space(note: RunNote | None, name: str, path: str | os.PathLike[str] | None = None) -> None:
    """Read the free bytes of the volume the run writes to and add them to it as ``name`` (``dest_free_bytes`` or ``data_free_bytes``).
    Called AFTER :func:`run_started`, so a stat that hangs on a dead mount leaves the run open, which is what a reader needs to see."""
    if note is None or name not in ("dest_free_bytes", "data_free_bytes"):
        return
    free = free_bytes_of(path)
    if free is not None:
        run_facts(note, **{name: free})


def run_ended(note: RunNote | None, outcome: str, *, failure: str | None = None, reason: str | None = None, **facts: Any) -> None:
    """Close the run under ``note``: how it ended (one of :data:`RUN_OUTCOMES`), the CLASS NAME of its failure (``failure=type(exc).__name__``,
    never a message; recorded as ``error``), a key of :data:`RUN_REFUSALS` when it was refused, the seconds since it began and the facts. A no-op for a run that
    already ended (the ``finally`` net calls it unconditionally). Never raises."""
    if note is None:
        return
    try:
        fields: dict[str, Any] = {
            "outcome": outcome if outcome in RUN_OUTCOMES else "(unnamed outcome)",
            "seconds": round(time.monotonic() - note.started, 3),
        }
        cls = _class_name(failure)
        if cls is not None:
            fields["error"] = cls
        sentence = RUN_REFUSALS.get(reason) if isinstance(reason, str) else None
        if sentence is not None:
            fields["reason"] = sentence
        fields.update(_run_fields(facts))
        end(note.kind, note.key, fields)
    except Exception as exc:  # noqa: BLE001
        _internal_failure("run_ended", exc)


def run_refused(what: str, reason: str, *, failure: str | None = None, via: str | None = None) -> None:
    """Record a start that was refused before any run existed (the run journal opens nothing for it), closed in one write: the outcome,
    ``ran`` False, the fixed sentence of ``reason`` (a key of :data:`RUN_REFUSALS`), the way in (``via``, a key of :data:`RUN_VIA`) and,
    if given, the class name. Never raises."""
    try:
        kind = RUN_KINDS.get(what)
        if kind is None:
            return
        fields: dict[str, Any] = {"outcome": "refused", "ran": False}
        sentence = RUN_REFUSALS.get(reason) if isinstance(reason, str) else None
        if sentence is not None:
            fields["reason"] = sentence
        cls = _class_name(failure)
        if cls is not None:
            fields["error"] = cls
        fields.update(_run_fields({"via": via}))
        record(kind, fields)
    except Exception as exc:  # noqa: BLE001
        _internal_failure("run_refused", exc)


@contextmanager
def run_path_checked(what: str, *, via: str | None = None) -> Iterator[None]:
    """Around a request's first look at the paths it names (a stat, a listing): an ``OSError`` the operating system raises there ends the
    start in a refusal record (the ``path-unreadable`` sentence, the class name, the way in) and is raised on unchanged, so a start that
    could not even examine its path leaves a record like every other refused start. Nothing else is caught, and the record never raises."""
    try:
        yield
    except OSError as exc:
        run_refused(what, "path-unreadable", failure=type(exc).__name__, via=via)
        raise


@contextmanager
def run_refused_if_raised(
    what: str, reason: str, exc_type: type[BaseException] | tuple[type[BaseException], ...], *, via: str | None = None
) -> Iterator[None]:
    """Around the ONE statement that refuses a start by raising ``exc_type`` (the ``if not path.is_dir(): raise ...`` of a start): the
    refusal is recorded (``reason``, a key of :data:`RUN_REFUSALS`, and the way in) and the exception goes on unchanged. The checking
    statement stays as it was written, byte for byte, which is why this is a wrapper and not a call inside its branch: code scanning
    fingerprints a path check by its own text and the text that follows it, so a line added there makes an old finding a new one."""
    try:
        yield
    except exc_type:
        run_refused(what, reason, via=via)
        raise


@contextmanager
def run_ended_if_raised(
    note: RunNote | None, outcome: str, exc_type: type[BaseException] | tuple[type[BaseException], ...], *, reason: str | None = None
) -> Iterator[None]:
    """Around the ONE statement whose ``exc_type`` failure ends the run under ``note`` (the read of the file being restored): the run is
    closed with ``outcome``, the CLASS NAME of the failure (never its message) and, if given, a key of :data:`RUN_REFUSALS`, and the
    exception goes on unchanged for the caller's own handler. A wrapper for the same reason as :func:`run_refused_if_raised`."""
    try:
        yield
    except exc_type as exc:
        run_ended(note, outcome, failure=type(exc).__name__, reason=reason)
        raise


# ---------------------------------------------------------------------------------------------------------------------------------
#  The Diagnostics member (the slot contract: ``(max_bytes) -> dict``, never raises, counts and names the cut)
# ---------------------------------------------------------------------------------------------------------------------------------
_METHOD = (
    "Events recorded at the sites that already measure them (the write gate's release and its 15-second watchdog, the storage "
    "guard's transitions, the checkpoint sites, the unlock and the boot, the pool's timeout) and kept in a small file written by a "
    "background thread at most once a second. 'total' counts every event since 'since', across restarts; 'kept' is what the file "
    "holds (the newest, the cap is 'keep'; for 'gate_hold', 'guard', 'pool_timeout' and 'open' the cap is split by 'keep_rule': the "
    "longest by the named field AND the newest, each event saying why it is there in 'picked_by': 'longest', 'newest' or 'both', so a "
    "long hold is not pushed out by a stream of shorter, newer ones); 'dropped' is the events the cap removed (total minus the file's events). If the zip's "
    "budget cut the member further, 'dropped_to_fit' names how many events of each kind it removed after that, and 'kept' is what is "
    "shown. An event 'open' was still going when this member was built; one whose process ended first says so ('ended'). A field "
    "named in 'fields_dropped' was too large for one event and was left out; 'oversize_bytes' is the size it would have been. "
    "'run_export' (the volume backup and the folder backup of the large data), 'run_import' (the volume restore, the single-file "
    "restore of a legacy backup, the folder restore of the large data and the folder import of newsletter files) and 'run_verify' (the "
    "volume-set and the folder verification) keep the last ten runs of each, every run saying which way it came in ('via': "
    "'volume-set', 'single-file', 'newsletter-eml' or 'folder'): how each ended, the class of its failure, a fixed sentence for a "
    "refusal, its seconds, the free bytes of the volume it wrote to when it began ('dest_free_bytes' for a backup, 'data_free_bytes' "
    "for a restore, where it stages; absent when unreadable, and for a folder restore, which writes to several volumes) and the "
    "figures the engine measured. A run 'open' with no end was going when this member was built, or its process was killed (an "
    "earlier process's says so in 'ended'); a refusal with 'ran' false is a start that never became a run. The run journal names "
    "the same runs differently ('export', 'import' and 'verify' for the volume backup, the volume and legacy restores and the folder "
    "verification; 'folder-export', 'folder-import' and 'newsletter-import' for the rest): match by 'via' and time. Outcomes agree "
    "except 'refused' here for a backup the newsletter filter refused or a legacy restore refused by a merge check, and "
    "'stopped-by-operator' here for the operator's stop of a legacy restore ('error' there for all three). A folder "
    "verification's 'mismatches' counts what its verdict counts, a bad signature among them. Refused starts share the ten "
    "kept with the runs ('total' counts them all); a run still open is the last to be pushed out."
)
_CAVEAT = (
    "A process kill loses the last second of events when writes succeed (a failed write is tried again, doubling to a minute), and a "
    "power loss can lose more or leave an unreadable file (no fsync). An event is a count, a duration or a name; a hold is attributed to the thread that held "
    "the gate, not to the code that was running (the frames are the watchdog's sample and are absent for a hold it never saw "
    "while it lasted). The file is read once at the first use after a start: events of earlier processes are marked 'earlier'. A file "
    "that cannot be READ (an I/O error that outlasts three looks) is not written over: 'history_loaded' is false, 'read_failures' counts "
    "the tries, and the events shown are this process's only."
)


def _for_member(event: dict[str, Any], picked_by: str | None = None) -> dict[str, Any]:
    out = {k: v for k, v in event.items() if k != "proc"}
    out["session"] = "this" if event.get("proc") == _PROC else "earlier"
    if picked_by is not None:
        out["picked_by"] = picked_by
    return out


def diagnostics_member(max_bytes: int) -> dict[str, Any]:
    """The journal as one Diagnostics member. Over ``max_bytes`` the OLDEST events of the largest kind go first (an event kept as one of
    the longest goes last) and the member says how many (``dropped_to_fit``); ``total`` and ``dropped`` never change by that cut."""
    try:
        budget = max(1024, int(max_bytes))
        _ensure_loaded()
        with _LOCK:
            combined, since = _combined_locked()
            kinds: dict[str, Any] = {}
            for kind, cap in KEEP.items():
                entry = combined[kind]
                tags = _picked_by(kind, entry["events"])
                events = [_for_member(e, tag) for e, tag in zip(entry["events"], tags, strict=True)]
                kinds[kind] = {
                    "keep": cap,
                    "total": entry["total"],
                    "kept": len(events),
                    "dropped": entry["total"] - len(events),
                    "events": events,
                }
                if kind in LONGEST:
                    field, n_long = LONGEST[kind]
                    kinds[kind]["keep_rule"] = {"longest": n_long, "by": field, "newest": cap - n_long}
            file_state = {
                "read_at_first_use": _READ_STATE,
                "history_loaded": _LOADED,
                "read_failures": _READ_FAILURES,
                "last_read_failure": _LAST_READ_FAILURE,
                "last_write_ok_at": _LAST_WRITE_OK_AT,
                "write_failures": _WRITE_FAILURES,
                "last_write_failure": _LAST_WRITE_FAILURE,
                "internal_failures": _INTERNAL_FAILURES,
                "last_internal_failure": _LAST_INTERNAL_FAILURE,
                "writer_deaths": _WRITER_DEATHS,
                "flush_delay_s": FLUSH_DELAY_S,
            }
        out: dict[str, Any] = {
            "schema": SCHEMA,
            "since": since,
            "method": _METHOD,
            "caveat": _CAVEAT,
            "file": file_state,
            "kinds": kinds,
            "dropped_to_fit": {},
        }
        while _size(out) > budget:
            biggest = max(kinds, key=lambda k: _size(kinds[k]["events"]))
            if not kinds[biggest]["events"]:
                return {"omitted": "max_bytes is below the member's fixed part", "needs_at_least_bytes": _size(out)}
            # The oldest goes first, but a "longest" one is the last to go: it is the event the zip is kept for (see LONGEST).
            events = kinds[biggest]["events"]
            events.pop(next((i for i, e in enumerate(events) if e.get("picked_by") not in ("longest", "both")), 0))
            kinds[biggest]["kept"] -= 1
            out["dropped_to_fit"][biggest] = out["dropped_to_fit"].get(biggest, 0) + 1
        return out
    except Exception as exc:  # noqa: BLE001 - a bundle member must never raise
        return {"error": _label(exc)}


def reset_for_tests(*, keep_file: bool = False) -> None:
    """Forget everything in memory and make a write that was already taken a no-op. The journal file in the current data directory is
    removed too, so the next test does not read this one's events as an earlier process's; ``keep_file`` leaves it (a test that
    simulates a restart: memory gone, file kept)."""
    global _LOADED, _STATE, _EARLIER, _SINCE, _SINCE_FILE, _READ_STATE, _OPEN, _VERSION, _WRITTEN_VERSION, _GENERATION, _DIRTY
    global _WRITE_FAILURES, _LAST_WRITE_FAILURE, _LAST_WRITE_OK_AT, _INTERNAL_FAILURES, _LAST_INTERNAL_FAILURE, _WRITER_DEATHS
    global _READ_FAILURES, _LAST_READ_FAILURE
    with _LOCK:
        _LOADED = False
        _STATE = {}
        _EARLIER = {}
        _SINCE = None
        _SINCE_FILE = None
        _READ_STATE = "not read yet"
        _OPEN = {}
        _ENDED.clear()
        _DIRTY = False
        _VERSION = 0
        _GENERATION += 1
        _INTERNAL_FAILURES = 0
        _LAST_INTERNAL_FAILURE = None
        _WRITER_DEATHS = 0
        _READ_FAILURES = 0
        _LAST_READ_FAILURE = None
        _COND.notify_all()  # a writer waiting out its delay for what was just forgotten goes back to waiting for a change
    with _WRITE_LOCK:
        _WRITTEN_VERSION = 0
        _WRITE_FAILURES = 0
        _LAST_WRITE_FAILURE = _LAST_WRITE_OK_AT = None
        if not keep_file:
            # The files this journal tried to read or write, not the data directory as it resolves now: resolving it after a test
            # made a marked folder disappear signalled the volume monitor, which paused collection for the rest of the process. A file
            # it could not READ is among them (the attempt names it), so a test's unreadable file does not outlive the test.
            with _PATHS_LOCK:
                paths = list(_PATHS_USED)
                _PATHS_USED.clear()
            for path in paths:
                with suppress(Exception):  # a test that broke the path must still be able to reset
                    for victim in (path, path.with_name(path.name + ".tmp")):
                        with suppress(OSError):
                            victim.unlink(missing_ok=True)
