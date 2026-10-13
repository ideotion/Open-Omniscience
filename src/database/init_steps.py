"""The wall-clock time of each step of ``init_db`` (STORE-02, audit 16 finding 9).

WHY THIS EXISTS. The unlock record kept ONE number for the whole call (``init_db (schema self-heal +
migrations + WAL recovery)``), and the field read 4.1 and 4.2 s of it on two machines and 0.7 s on a
third. Nothing in any bundle could say which of the 37 steps was the time, so the audit's reading ("about
30 self-heal probes on a cold cache") stayed a hypothesis. This module times every step by name and
keeps the record, so the next zip says which one.

WHAT IT IS NOT. It changes nothing ``init_db`` does: the same statements, in the same order, on the same
connections. It opens no connection, takes no lock of the store's and none that ``init_db`` waits on (only
its own, around two assignments) and decides nothing (a step is moved off the synchronous path only when a
field record names it; ``docs/ledger/OPEN_QUEUE.md``).

HOW A STEP IS TIMED. ``init_db`` calls :func:`step` with a name BEFORE each thing it does. A step runs
from its call to the next call (or to the end of ``init_db``), so the time between two calls belongs to
the earlier name; an ``import`` inside ``init_db`` therefore gets its own name (``import:...``) rather
than being charged to whatever ran before it, which on a cold process is the question. A step that
raises is recorded with its exception CLASS and nothing else, and the exception goes on unchanged:
engine text can carry a path or a passphrase, and a name plus a number never can.

THE RECORD (one per ``init_db`` call)::

    {"steps": [{"step": "create_all", "ms": 192.0}, ...],
     "total_ms": 1535.6,        # the call's wall time, import and step bookkeeping included
     "process_call": 1,         # how many calls this process had made, this one included, even those that raised
     "earlier_complete_calls": 0,  # 0 = no earlier call got through: THIS is the cold call that opened the store
     "complete": True,          # False when a step raised (that step carries "raised": ClassName)
     "machine_uptime_s": 8123.4 | None, "machine_uptime_unavailable": "ClassName" (only when None),
     "at": "<UTC ISO time the call ended>"}

``machine_uptime_s`` is there because the audit's hypothesis is a cold page cache after a reboot, and the
kit never recorded how long the machine had been up. Nothing here measures the page cache; the uptime is
the honest nearby fact, and it is absent, with the reason, where it cannot be read.

Standard library only: ``session.py`` imports this, and ``session.py`` is imported by everything.
"""

from __future__ import annotations

import functools
import math
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

#: The clock every step is timed with: the platform's highest-resolution monotonic clock, because a step that
#: takes a millisecond is the usual case.
_clock: Callable[[], float] = time.perf_counter

#: What a reader of a stored record needs to read it correctly; the consumers (the P0.4 verdict) print it
#: beside the steps instead of every record carrying its own copy.
METHOD = (
    "Wall-clock per step of init_db, taken with the high-resolution monotonic clock. A step runs from the "
    "moment it is named to the moment the next one is (an import inside init_db is a step of its own). The "
    "first step of a process to use the ORM also pays SQLAlchemy's one-time mapper configuration "
    "(about 95 to 250 ms on the development machine, taken as heal_bulk_build's first call minus its "
    "second), so on the call that opens the store that cost sits in whichever step reaches the ORM first, "
    "not in a step that is slow of its own accord. process_call counts every call this process made, "
    "including one that raised (a start that tries init_db before the store is unlocked has that attempt "
    "as call 1); earlier_complete_calls is how many earlier calls got through, and 0 means this is the "
    "cold call that opened the store. machine_uptime_s is how long the machine had been up; it is not a "
    "reading of the page cache, which nothing here measures."
)

_LOCK = threading.Lock()
_CALLS = 0
_COMPLETE = 0  # calls that returned without raising
_FIRST: dict[str, Any] | None = None
_LAST: dict[str, Any] | None = None
_LOCAL = threading.local()


def _machine_uptime() -> dict[str, Any]:
    """How long the machine had been up, from the OS's own boot time, or the reason it cannot be read.

    Read BEFORE the call's clock starts: importing ``psutil`` on a cold process is not ``init_db``'s cost.
    """
    try:
        import psutil

        return {"machine_uptime_s": round(max(0.0, time.time() - psutil.boot_time()), 1)}
    except Exception as exc:  # noqa: BLE001 - a reading that is not there is a reason, never a failure
        return {"machine_uptime_s": None, "machine_uptime_unavailable": type(exc).__name__}


class _Recorder:
    """The steps of ONE ``init_db`` call. Used from the calling thread only."""

    def __init__(self, call: int, earlier_complete: int) -> None:
        self.call = call
        self.earlier_complete = earlier_complete
        self.steps: list[dict[str, Any]] = []
        self._open: str | None = None
        self._since = 0.0
        self.uptime = _machine_uptime()
        self.t0 = _clock()

    def begin(self, name: str) -> None:
        now = _clock()
        self._close(now)
        self._open = name
        self._since = now

    def _close(self, now: float, raised: str | None = None) -> None:
        if self._open is None:
            return
        entry: dict[str, Any] = {"step": self._open, "ms": round((now - self._since) * 1000, 1)}
        if raised is not None:
            entry["raised"] = raised
        self.steps.append(entry)
        self._open = None

    def finish(self, raised: str | None) -> dict[str, Any]:
        now = _clock()
        self._close(now, raised)
        return {
            "steps": self.steps,
            "total_ms": round((now - self.t0) * 1000, 1),
            "process_call": self.call,
            "earlier_complete_calls": self.earlier_complete,
            "complete": raised is None,
            **self.uptime,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
        }


def step(name: str) -> None:
    """Close the step that was running and start ``name``. Does nothing outside a recorded call."""
    rec = getattr(_LOCAL, "recorder", None)
    if rec is not None:
        rec.begin(name)


def recorded(fn: Callable[[], None]) -> Callable[[], None]:
    """Decorate ``init_db``: record the steps it names, publish the record, change nothing else.

    The record is published whether the call returns or raises; the exception, if any, is re-raised as it
    was (its class is kept in the record, its text is not).
    """

    @functools.wraps(fn)
    def wrapper() -> None:
        global _CALLS
        with _LOCK:
            _CALLS += 1
            call = _CALLS
            earlier_complete = _COMPLETE
        previous = getattr(_LOCAL, "recorder", None)
        rec = _Recorder(call, earlier_complete)
        _LOCAL.recorder = rec
        raised: str | None = None
        try:
            fn()
        except BaseException as exc:
            raised = type(exc).__name__
            raise
        finally:
            _LOCAL.recorder = previous
            _publish(rec.finish(raised))

    return wrapper


def _publish(record: dict[str, Any]) -> None:
    global _COMPLETE, _FIRST, _LAST
    with _LOCK:
        if record["complete"]:
            _COMPLETE += 1
            if _FIRST is None:
                _FIRST = record
        _LAST = record
    _LOCAL.last = record


def _copy(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if record is None:
        return None
    return {**record, "steps": [dict(s) for s in record["steps"]]}


def this_thread_record() -> dict[str, Any] | None:
    """The record of the last ``init_db`` call THIS thread made, or None. What the unlock path reads: a
    restore or a repair calling ``init_db`` on another thread must not be mistaken for its own."""
    return _copy(getattr(_LOCAL, "last", None))


def first_record() -> dict[str, Any] | None:
    """The first ``init_db`` call of this process to COMPLETE (the cold call that opened the store), or None
    while none has. A call that raised is not it: a start that tries ``init_db`` against a still-locked store
    raises at ``create_all`` and says nothing of what opening the store costs; that call is ``last_record``."""
    with _LOCK:
        return _copy(_FIRST)


def last_record() -> dict[str, Any] | None:
    """The most recent ``init_db`` call of this process, on any thread, or None before any."""
    with _LOCK:
        return _copy(_LAST)


def slowest_step(record: Any) -> dict[str, Any] | None:
    """The slowest step of a record, or None when the record has no usable step (an old record, a damaged
    one). Reads a stored record, so it trusts nothing about its shape."""
    steps = record.get("steps") if isinstance(record, dict) else None
    best: dict[str, Any] | None = None
    for s in steps if isinstance(steps, list) else []:
        ms = s.get("ms") if isinstance(s, dict) else None
        name = s.get("step") if isinstance(s, dict) else None
        if isinstance(ms, bool) or not isinstance(ms, (int, float)) or not isinstance(name, str):
            continue
        try:
            finite = math.isfinite(ms)  # json.loads reads NaN and Infinity: a damaged record must not win
        except OverflowError:  # an integer too large for a float
            finite = False
        if not finite:
            continue
        if best is None or ms > best["ms"]:
            best = {"step": name, "ms": ms}
    return best
