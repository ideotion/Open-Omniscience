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
  or fills (the moment the guard engages) delays only that thread, never the site that measured. A kill loses at most the last
  second, and the member says when the file was last written and how many writes failed.
- Every public function catches everything: a journal that cannot write must never raise into the gate, the guard, a checkpoint or an
  unlock. A failure is counted (``write_failures``) and logged at DEBUG by class, and the in-memory record still serves the live zip.
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
from contextlib import contextmanager
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

_LOCK = threading.RLock()
_COND = threading.Condition(_LOCK)
_WRITE_LOCK = threading.Lock()
_LOAD_LOCK = threading.Lock()  # one reader of the file at a time; never held while recording

#: A token for THIS process, stamped on every event, so an entry that was open when an earlier process ended is recognised as such.
_PROC = f"{os.getpid()}-{int(time.time())}"

_LOADED = False
_STATE: dict[str, dict[str, Any]] = {}  # kind -> {"total": int, "events": [event, ...]}: THIS process's events only
_EARLIER: dict[str, dict[str, Any]] = {}  # the same shape, as the file held it when it was first read (earlier processes')
_SINCE: str | None = None  # the first event of this process
_SINCE_FILE: str | None = None  # the first event ever, as the file held it
_READ_STATE = "not read yet"
_OPEN: dict[tuple[str, Any], dict[str, Any]] = {}  # (kind, key) -> the event dict still open in this process
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


def _read_file() -> tuple[dict[str, dict[str, Any]], str | None, str]:
    """Read the file once: ``(kinds, since, how it read)``. No lock is held (it is disk), and every entry an earlier process left open
    is closed as "not recorded". Never raises: an unreadable file reads as empty and says why."""
    earlier: dict[str, dict[str, Any]] = {}
    path = _path()
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return earlier, None, "missing"
    except OSError as exc:
        return earlier, None, f"unreadable ({_label(exc)})"
    if size > MAX_FILE_BYTES:
        return earlier, None, f"unreadable (larger than {MAX_FILE_BYTES} bytes)"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # a UnicodeDecodeError is a ValueError: the class only is kept
        return earlier, None, f"unreadable ({_label(exc)})"
    kinds = data.get("kinds") if isinstance(data, dict) else None
    if not isinstance(kinds, dict) or data.get("schema") != SCHEMA:
        return earlier, None, "unreadable (not this journal)"
    since = data.get("since")
    for kind, cap in KEEP.items():
        entry = kinds.get(kind)
        if not isinstance(entry, dict):
            continue
        events = [e for e in (entry.get("events") or []) if isinstance(e, dict) and isinstance(e.get("at"), str)]
        total = entry.get("total")
        total = total if isinstance(total, int) and not isinstance(total, bool) and total >= len(events) else len(events)
        for e in events:
            if e.get("open") and e.get("proc") != _PROC:
                e["open"] = False
                e["ended"] = "the process ended while this was open; its end was not recorded"
        earlier[kind] = {"total": total, "events": events[-cap:]}
    return earlier, since if isinstance(since, str) else None, "ok"


def _ensure_loaded(generation: int | None = None) -> None:
    """Read the file the first time a writer or a reader NEEDS what it holds (the background writer before its first write, so it
    never replaces the history with this process's events alone; the member before it answers). A recording never calls this: it does
    no disk I/O, so the measured site, which can hold the gate's lock or the guard's, cannot wait on a disk through it.
    ``generation`` is the one the caller saw: a reset since then makes the call a no-op (a stale writer neither reads the file of
    the state that replaced its own nor applies what it read)."""
    global _LOADED, _EARLIER, _SINCE_FILE, _READ_STATE
    if _LOADED:
        return
    with _LOAD_LOCK:
        if _LOADED:
            return
        seen = _GENERATION if generation is None else generation
        if seen != _GENERATION:
            return
        earlier, since, how = _read_file()  # disk, no journal lock held
        with _LOCK:
            if seen != _GENERATION:
                return  # reset while the file was being read: the next caller reads it again
            _EARLIER, _SINCE_FILE, _READ_STATE, _LOADED = earlier, since, how, True


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


def _write(text: str, version: int, generation: int) -> None:
    """Write one snapshot atomically (temp file and replace; no fsync: a journal, not a ledger). Never raises."""
    global _WRITTEN_VERSION, _WRITE_FAILURES, _LAST_WRITE_FAILURE, _LAST_WRITE_OK_AT
    with _WRITE_LOCK:
        if generation != _GENERATION or version <= _WRITTEN_VERSION:
            return  # a newer snapshot was written first, or the state was reset since this one was taken
        path = _path()
        tmp = path.with_name(path.name + ".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
        except Exception as exc:  # noqa: BLE001 - a full or hung disk is when this matters; it must not reach the measured site
            _WRITE_FAILURES += 1
            _LAST_WRITE_FAILURE = _label(exc)
            log_failure(_LOG, "storage events: could not write the journal", exc, level=logging.DEBUG)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return
        _WRITTEN_VERSION = version
        _LAST_WRITE_OK_AT = _now()


def _flusher_loop() -> None:
    while True:
        try:
            with _COND:
                while not _DIRTY:
                    _COND.wait()
                generation = _GENERATION
                # Let a burst of changes become one write: every change wakes this wait, so it runs to the deadline, not to the next wake.
                # A reset ends the wait too (it wakes it): what was waiting to be written is gone.
                deadline = time.monotonic() + FLUSH_DELAY_S
                while generation == _GENERATION and (left := deadline - time.monotonic()) > 0:
                    _COND.wait(left)
                if generation != _GENERATION:
                    continue
            _ensure_loaded(generation)  # the file's history first, so the write below extends it and never replaces it
            with _LOCK:
                if generation != _GENERATION or not _LOADED or not _DIRTY:
                    continue  # reset, or written by a flush(), while this waited: nothing is left to write
                snap = _snapshot_locked()  # a copy: the lock is dropped before any disk is touched
                _clear_dirty_locked()
            _write(*snap)
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
    if _size(event) > MAX_EVENT_BYTES:
        event = {"at": event["at"], "proc": _PROC, "oversize_bytes": _size(event), "fields_kept": False}
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
            _mark_dirty_locked()
            return True
    except Exception as exc:  # noqa: BLE001
        _internal_failure("update", exc)
        return False


def end(kind: str, key: Any, fields: dict[str, Any] | None = None) -> bool:
    """Merge ``fields`` into the open event ``(kind, key)`` and close it. Returns False when there is none to close. Never raises."""
    try:
        with _LOCK:
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
            "readers": readers,
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
    "holds (the newest, the cap is 'keep'); 'dropped' is total minus kept. An event 'open' was still going when this member was "
    "built; one whose process ended first says so ('ended')."
)
_CAVEAT = (
    "A kill loses the last second of events. An event is a count, a duration or a name; a hold is attributed to the thread that held "
    "the gate, not to the code that was running (the frames are the watchdog's sample and are absent for a hold it never saw "
    "while it lasted). The file is read once at the first use after a start: events of earlier processes are marked 'earlier'."
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
    with _LOCK:
        _LOADED = False
        _STATE = {}
        _EARLIER = {}
        _SINCE = None
        _SINCE_FILE = None
        _READ_STATE = "not read yet"
        _OPEN = {}
        _DIRTY = False
        _VERSION = 0
        _GENERATION += 1
        _INTERNAL_FAILURES = 0
        _LAST_INTERNAL_FAILURE = None
        _WRITER_DEATHS = 0
        _COND.notify_all()  # a writer waiting out its delay for what was just forgotten goes back to waiting for a change
    with _WRITE_LOCK:
        _WRITTEN_VERSION = 0
        _WRITE_FAILURES = 0
        _LAST_WRITE_FAILURE = _LAST_WRITE_OK_AT = None
        if not keep_file:
            for path in (_path(), _path().with_name(_path().name + ".tmp")):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
