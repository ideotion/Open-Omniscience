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
import json
import logging
import math
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
#: is what reaches back further.
KEEP: dict[str, int] = {
    "gate_hold": 20,
    "guard": 10,
    "checkpoint": 10,
    "checkpoint_notable": 10,
    "open": 10,
    "pool_timeout": 10,
}

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
#: more than a few holds old cannot be offered again.
ENDED_KEYS_MAX = 64

_LOCK = threading.RLock()
_COND = threading.Condition(_LOCK)
_WRITE_LOCK = threading.Lock()
_LOAD_LOCK = threading.Lock()  # one reader of the file at a time; never held while recording

#: A token for THIS process, stamped on every event, so an entry that was open when an earlier process ended is recognised as such.
_PROC = f"{os.getpid()}-{time.time_ns()}"  # nanoseconds: an exec restart keeps the pid and can come within the same second

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


def _empty_kind() -> dict[str, Any]:
    return {"total": 0, "events": []}


def _parse_kinds(data: Any) -> tuple[dict[str, dict[str, Any]], str | None]:
    """The kinds of a parsed journal file, each kept to its cap, every entry an earlier process left open closed as "not recorded".
    Raises on a file that is not ours (the caller names the class)."""
    kinds = data.get("kinds") if isinstance(data, dict) else None
    if not isinstance(kinds, dict) or data.get("schema") != SCHEMA:
        raise ValueError("not this journal")
    earlier: dict[str, dict[str, Any]] = {}
    for kind, cap in KEEP.items():
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
        earlier[kind] = {"total": total, "events": events[-cap:]}
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
            path = _path()
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
    for kind, cap in KEEP.items():
        old = _EARLIER.get(kind) or _empty_kind()
        new = _STATE.get(kind) or _empty_kind()
        kinds[kind] = {"total": old["total"] + new["total"], "events": [*old["events"], *new["events"]][-cap:]}
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
            path = _path()
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
            while len(entry["events"]) > KEEP[kind]:
                gone = entry["events"].pop(0)
                for k in [k for k, v in _OPEN.items() if v is gone]:
                    _OPEN.pop(k, None)
            if key is not None:
                _OPEN[(kind, key)] = event
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
) -> None:
    """The store was opened: ``via`` is ``unlock`` (a passphrase was entered; ``phases`` are the synchronous phases the unlock
    timed) or ``boot`` (a start with no passphrase, where only ``init_db`` is timed)."""
    try:
        event = {
            "via": via,
            "total_ms": total_ms,
            "phases": [[p.get("phase"), p.get("ms")] for p in phases if isinstance(p, dict)] if isinstance(phases, list) else None,
            "wal_bytes_before_open": wal_bytes_before,
            "init_db": _compact_init_db(init_db),
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
#  The Diagnostics member (the slot contract: ``(max_bytes) -> dict``, never raises, counts and names the cut)
# ---------------------------------------------------------------------------------------------------------------------------------
_METHOD = (
    "Events recorded at the sites that already measure them (the write gate's release and its 15-second watchdog, the storage "
    "guard's transitions, the checkpoint sites, the unlock and the boot, the pool's timeout) and kept in a small file written by a "
    "background thread at most once a second. 'total' counts every event since 'since', across restarts; 'kept' is what the file "
    "holds (the newest, the cap is 'keep'); 'dropped' is the events the cap removed (total minus the file's events). If the zip's "
    "budget cut the member further, 'dropped_to_fit' names how many events of each kind it removed after that, and 'kept' is what is "
    "shown. An event 'open' was still going when this member was built; one whose process ended first says so ('ended'). A field "
    "named in 'fields_dropped' was too large for one event and was left out; 'oversize_bytes' is the size it would have been."
)
_CAVEAT = (
    "A process kill loses the last second of events when writes succeed (a failed write is tried again, doubling to a minute), and a "
    "power loss can lose more or leave an unreadable file (no fsync). An event is a count, a duration or a name; a hold is attributed to the thread that held "
    "the gate, not to the code that was running (the frames are the watchdog's sample and are absent for a hold it never saw "
    "while it lasted). The file is read once at the first use after a start: events of earlier processes are marked 'earlier'. A file "
    "that cannot be READ (an I/O error that outlasts three looks) is not written over: 'history_loaded' is false, 'read_failures' counts "
    "the tries, and the events shown are this process's only."
)


def _for_member(event: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in event.items() if k != "proc"}
    out["session"] = "this" if event.get("proc") == _PROC else "earlier"
    return out


def diagnostics_member(max_bytes: int) -> dict[str, Any]:
    """The journal as one Diagnostics member. Over ``max_bytes`` the OLDEST events of the largest kind go first and the member
    says how many (``dropped_to_fit``); ``total`` and ``dropped`` never change by that cut."""
    try:
        budget = max(1024, int(max_bytes))
        _ensure_loaded()
        with _LOCK:
            combined, since = _combined_locked()
            kinds: dict[str, Any] = {}
            for kind, cap in KEEP.items():
                entry = combined[kind]
                events = [_for_member(e) for e in entry["events"]]
                kinds[kind] = {
                    "keep": cap,
                    "total": entry["total"],
                    "kept": len(events),
                    "dropped": entry["total"] - len(events),
                    "events": events,
                }
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
            kinds[biggest]["events"].pop(0)
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
            with suppress(Exception):  # a test that broke the path must still be able to reset
                path = _path()
                for victim in (path, path.with_name(path.name + ".tmp")):
                    with suppress(OSError):
                        victim.unlink(missing_ok=True)
