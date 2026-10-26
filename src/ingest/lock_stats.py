"""
What the extraction lock cost: how long extractions waited for it, and how long each held it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``src/ingest/extract.py`` runs one extraction at a time in the whole process (``_LXML_LOCK``), and
nothing times a long page out: a 10 MiB nav-heavy page measured 85 s, during which every other
extraction waits. On a real install that would read as a stalled collector. This module keeps the
numbers that tell the two apart, for the window between :func:`reset` and :func:`snapshot`; the
collection monitor opens the window when a pass starts and writes the snapshot into the pass's
summary line in ``collect_perf.jsonl`` (``extraction_lock``), and the scheduler copies it into the
pass's result, which is the run report in ``scheduler_runs.jsonl`` and so the ``scheduler`` member of
the debug bundle (its last 30 runs, in the slim copy as well).

What is recorded, and what is not:

* the COUNT of ``holds`` that finished in the window (every extraction that took the lock, whether it
  returned an article, ``None`` or raised), the longest and the total WAIT (seconds between asking for
  the lock and getting it), the longest and the total HOLD (seconds between getting it and giving it
  up), and for the longest hold the UTF-8 length of the text handed to ``extract_article`` -- not the
  bytes the server sent, which this function is never told;
* NOT the URL, the title, the text or any exception text: the record is numbers only, so it carries
  nothing the host allowlist or the passphrase rule would have to be applied to;
* a hold counts when it ENDS, so one that began before :func:`reset` and ended after it is in the new
  window, with its full length: it did occupy the lock there. Extractions from any thread are counted
  (the collector's pool, the housekeeping lane's crawl, a manual add), because the lock is
  process-wide. A hold that ends while NO pass is running (a manual add, a lane step between two
  passes) is in no pass's window and is dropped by the next :func:`reset`: nothing in a pass waited
  on it. A pass without a monitor (the sequential path, used only on a caller's own session) never
  opens a window and writes no block.

Best-effort by construction: arithmetic under a private lock, no I/O. The pass window above is taken
AFTER the extraction lock is given up (:func:`record`), so it adds nothing to a hold. :func:`record`
swallows its own ``Exception``, so a fault in the statistic cannot replace an extraction's result. It is
not free: a hold that may be the longest costs its caller one pass over the page (:func:`_utf8_size`, a
few milliseconds for a 10 MiB page, no copy of it).

THE LIVE GAUGE (below the window, never reset by it) answers what the window cannot: a hold counts in the
window only when it ENDS, so a pass that never ends (a crash, a hang) leaves nothing, and a hold still
open (the 85 s page) is invisible while every other extraction waits behind it. The gauge keeps two
cumulative totals, the seconds the lock was held and the thread-seconds spent waiting for it, and
:func:`live_reading` adds the part of a hold or a wait that is still open at the instant of the reading.
Both totals only grow, so the DIFFERENCE between two readings is exact for the interval between them
(open holds and open waits included), whatever else happened in it. Its marks are NOT all outside the
hold: :func:`asking` runs before the lock is asked for and :func:`gave_up` (called by :func:`record`, after the lock is
given up, and idempotent) when the thread is no longer waiting, but :func:`holding` and :func:`released` run INSIDE the
hold, each one clock read and a few additions under a private leaf lock. The cost was measured, not assumed: the four
marks of one extraction take about 2 to 3 microseconds together (medians 2.1 to 3.0 over nine runs on two shared-vCPU
machines, 2.5 on the last three), the two inside the hold about 1.1 to 1.7 (medians 1.1, 1.1, 1.7, 1.2, 1.2, 1.2, then
1.36, 1.34 and 1.35 on the head that merges), against a mean hold of 35 to 40 ms (8 KB pages) or 285 to 320 ms (64 KB);
a 14-collector run of the real collector, base tree against gauge tree, five alternating runs per cell, is in the shipped
row. Those micro figures are warm and uncontended. In the loaded run the gap between the window's ``got`` stamp and the
gauge's start of a hold is 2 to 6 microseconds per hold: that is what the part of :func:`holding` BEFORE its clock read
costs in situ, so it is a floor for the whole of :func:`holding` there, and the cost inside a hold in a loaded run is
more than the warm micro figure (0.005 to 0.015 percent of a 40 ms hold for that part alone).
``tests/test_lock_live_reading.py`` pins that the marks do no
I/O and take no other lock, and that a step body has no interrupt point of its own (no call, no backward jump, no ``with``),
so one mark is applied whole or not at all when an interrupt arrives (:func:`_mark` says what an interrupt can still do);
a step also computes every new total BEFORE it stores any, so a step that fails (``MemoryError`` while allocating a float)
leaves the totals and the open intervals exactly as they were. The gauge reads the clock under its own lock, so a
mark and a reading are totally ordered and a reading can never see more held time than elapsed.

The gauge assumes the extraction lock is EXCLUSIVE (it is an ``RLock``): with a no-op lock (the lock-off cells of the
bench harness) two threads are inside at once and its totals mean nothing.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

#: A leaf lock: nothing is called while it is held except :func:`_utf8_size` in the rare case below,
#: and it is never taken inside the extraction lock.
_STATS_LOCK = threading.Lock()

_EMPTY: dict = {
    "holds": 0,
    "wait_max_s": 0.0,
    "wait_total_s": 0.0,
    "hold_max_s": 0.0,
    "hold_total_s": 0.0,
    "hold_max_html_utf8_bytes": None,
}
_state: dict = dict(_EMPTY)

#: The live gauge's private lock: a leaf. Unlike :data:`_STATS_LOCK` it IS taken inside the extraction lock
#: (:func:`holding`, :func:`released`), so nothing is called while it is held except the clock, and the
#: extraction lock is never asked for under it.
_LIVE_LOCK = threading.Lock()
#: Threads between asking for the extraction lock and getting it: ``thread ident -> the clock when it asked``.
#: A dict and not a running sum: ``(a + b) - b != a`` in floating point, so a sum of timestamps would drift.
_waiters: dict[int, float] = {}
#: ``depth`` = how many nested calls hold the (re-entrant) lock; ``since`` / ``holder`` = the clock when the OUTERMOST
#: one took it and its thread; ``occupied_s`` / ``waited_s`` = completed holds / completed waits, in seconds, for the life
#: of the process.
_live: dict = {"depth": 0, "since": None, "holder": None, "occupied_s": 0.0, "waited_s": 0.0}

#: Characters encoded at a time when a page is not pure ASCII: the sum of the pieces is the length of the
#: whole (a lone surrogate is one ``?`` wherever the cut falls), and no copy of a 10 MiB page is made.
_CHUNK = 1 << 16

#: Stands for "the size was not measured yet" (``None`` is a measured failure).
_UNMEASURED = object()

#: What the numbers mean, carried in every snapshot that has any (the repo's rule: a signal says its
#: method with it).
METHOD = (
    "seconds on a monotonic clock; wait = from asking for the extraction lock to getting it, hold = from "
    "getting it to giving it up; holds = every extraction that took the lock and finished in this pass's "
    "window, whatever it returned; hold_max_html_utf8_bytes = UTF-8 length of the text handed to "
    "extract_article for the longest hold"
)

#: What the ``extraction_lock`` block of a collect_perf TICK means. NOT written into the log: on the pass summary it measured
#: +220 to +275 B per slim diagnostics copy once deflated (a copy taken after a pass holds the summary, and the sentence is
#: unique text), more than the block and the trims net, and the rule is that new diagnostics bytes are net-zero
#: (``docs/ledger/shipped.d``, the row for the tick block, has the measurement). The tick's field names say what they hold;
#: these are the words, for the code, the tests and that row.
LIVE_METHOD = (
    "extraction_lock in a collect tick: held_frac = share of the tick's wall time some thread held the extraction lock "
    "(outermost holds only, 0 to 1); wait_rate = thread-seconds spent waiting for it per wall second (a mean queue length, "
    "can exceed 1); holder_age_s = seconds the current holder had held it at the tick's instant, absent when nobody held it; "
    "both rates are differences of two readings of one monotonic clock, open holds and open waits included, over the "
    "interval between this row's ts and the previous row's (the first tick's: about one tick, from the baseline taken when "
    "the monitor starts); extractions only, the lock and not the CPU, and not which page"
)


def now() -> float:
    """The clock the statistics read (a name of its own so a test can drive it)."""
    return time.monotonic()


def reset() -> None:
    """Start a new window: forget every hold recorded so far.

    The live gauge is NOT touched: a hold open across a pass boundary is still held, and its totals are cumulative
    on purpose (a reader takes differences)."""
    with _STATS_LOCK:
        _state.update(_EMPTY)  # every key stays present, so an unlocked read in record() never meets a gap


def _mark(step: Callable[[float, int], None]) -> float | None:
    """Run one mark of the live gauge under its private lock, with the clock read under that lock; returns that clock
    reading, or ``None`` when the mark failed.

    The one place the gauge swallows a failure: a statistic never replaces an extraction's result (nor, for the two
    marks inside the hold, lengthens it by raising). A failed mark leaves the totals as they were. Only ``Exception``
    is caught: an interrupt in the main thread propagates. WHAT AN INTERRUPT CAN STILL DO (``KeyboardInterrupt`` lands
    in the main thread, ``MemoryError`` anywhere): CPython 3.13 checks for one at a call's return, at the start of
    a Python frame and at a backward jump, so the step bodies below are written with none of those in them (one mark is
    applied whole or not at all) and compute every new total before storing any (a step that raises changes nothing),
    but a mark can still be skipped by an interrupt at its own entry. A skipped ``holding`` (after ``asking`` registered
    the wait; a skipped ``asking`` registers nothing) leaves a waiter that :func:`record` and the thread's next
    :func:`asking` close; a skipped ``released`` (or one that failed) leaves its hold OPEN, a phantom holder, which the next
    ``holding`` from ANOTHER thread closes (the lock cannot be held by two). Two cases are NOT healed and last until restart: the same thread's next ``holding``
    DEEPENS the phantom instead (so its age keeps growing while the lock is free, and every later hold by that thread is
    booked inside it), and a new thread that reuses a dead holder's ``get_ident()`` value is not "another thread". Best
    effort, said so: it needs a signal exactly at a mark's entry."""
    ident = threading.get_ident()
    try:
        with _LIVE_LOCK:
            t = now()
            step(t, ident)
            return t
    except Exception:  # noqa: BLE001 - a statistic never replaces an extraction's result
        return None


# The step bodies have no interrupt point of their own (no call, no backward jump, no ``with``: see :func:`_mark`) and
# compute every new total BEFORE they store any: the only things that can raise are the subtractions and additions (a float
# is allocated), and by then nothing has changed. The stores that follow touch keys that already exist or delete one that
# does, which allocates nothing.
def _on_ask(t: float, ident: int) -> None:
    waited = _live["waited_s"]
    if ident in _waiters:  # a wait that was never closed (a skipped mark): close it here so the total never goes backwards
        asked = _waiters[ident]
        if t > asked:
            waited = waited + (t - asked)
    _waiters[ident] = t  # may allocate (a dict resize); if it raises, nothing has been stored
    _live["waited_s"] = waited


def _on_give_up(t: float, ident: int) -> None:
    if ident in _waiters:
        asked = _waiters[ident]
        waited = _live["waited_s"]
        if t > asked:
            waited = waited + (t - asked)
        _live["waited_s"] = waited
        del _waiters[ident]


def _on_hold(t: float, ident: int) -> None:
    waited = _live["waited_s"]
    if ident in _waiters:  # the wait ends where the hold begins (the body of _on_give_up, inlined: a call here is a window)
        asked = _waiters[ident]
        if t > asked:
            waited = waited + (t - asked)
    depth = _live["depth"]
    occupied = _live["occupied_s"]
    if depth > 0 and _live["holder"] != ident:  # the lock cannot be held by two threads: the earlier hold's release was skipped
        since = _live["since"]
        if since is not None and t > since:
            occupied = occupied + (t - since)  # a reading already counted it as open until now, so the total stays continuous
        depth = 0
    # every new total is computed: the stores follow
    if ident in _waiters:
        del _waiters[ident]
    _live["waited_s"] = waited
    _live["occupied_s"] = occupied
    _live["depth"] = depth + 1
    if depth == 0:
        _live["since"] = t
        _live["holder"] = ident


def _on_release(t: float, ident: int) -> None:
    depth = _live["depth"]
    if depth <= 0:  # an unmatched release (its ``holding`` was skipped): nothing to close, never negative
        return
    if depth == 1:
        since = _live["since"]
        occupied = _live["occupied_s"]
        if since is not None and t > since:
            occupied = occupied + (t - since)
        _live["occupied_s"] = occupied
        _live["since"] = None
        _live["holder"] = None
    _live["depth"] = depth - 1


def asking() -> None:
    """The calling thread is about to ask for the extraction lock. Call it BEFORE the lock, outside every hold."""
    _mark(_on_ask)


def gave_up() -> None:
    """The calling thread is not waiting for the lock any more (its acquire raised, or :func:`holding` never closed the
    wait). Idempotent: a thread that is not waiting is left alone."""
    _mark(_on_give_up)


def holding() -> None:
    """The calling thread has just taken the lock (its wait ends here). Call it as the first statement INSIDE the hold.
    A nested call by the thread that already holds the lock deepens the hold and does not restart it."""
    _mark(_on_hold)


def released() -> float:
    """The calling thread is giving the lock up: close its hold in the gauge and return the clock reading the hold ended
    at (the ``released`` stamp :func:`record` takes, so the pass window and the gauge end a hold at the same instant,
    with no call between the stamp and the close). Call it as the first statement of the ``finally`` INSIDE the hold; the
    outermost release adds the hold's length to the total. A failed mark still returns a reading (the pass window keeps
    the hold)."""
    t = _mark(_on_release)
    return now() if t is None else t


def live_reading() -> dict:
    """The gauge at this instant, taken under one lock and one clock read: ``now`` (the monotonic clock),
    ``occupied_s`` (seconds the lock has been held in the life of the process, the part of an open hold included),
    ``waited_s`` (thread-seconds spent waiting for it, open waits included), ``holder_age_s`` (how long the current
    holder has held it, ``None`` = nobody does) and ``waiting`` (how many threads are waiting right now).

    The totals only grow, so ``(occupied_s_2 - occupied_s_1) / (now_2 - now_1)`` is the share of the interval the lock
    was held, exactly, and the same difference of ``waited_s`` is the mean number of threads waiting. Raises if the
    gauge's lock is broken: the caller says so by class and never writes a zero in its place."""
    with _LIVE_LOCK:
        t = now()
        since = _live["since"]
        open_hold = max(0.0, t - since) if since is not None else 0.0
        return {
            "now": t,
            "occupied_s": _live["occupied_s"] + open_hold,
            "waited_s": _live["waited_s"] + sum(max(0.0, t - asked) for asked in _waiters.values()),
            "holder_age_s": open_hold if since is not None else None,
            "waiting": len(_waiters),
        }


def _utf8_size(html: str) -> int | None:
    """The UTF-8 length of ``html`` (unencodable characters count as the one byte ``?`` they are replaced by),
    or ``None`` when it cannot be measured."""
    try:
        if html.isascii():
            return len(html)
        return sum(len(html[i : i + _CHUNK].encode("utf-8", "replace")) for i in range(0, len(html), _CHUNK))
    except Exception:  # noqa: BLE001 - a size that cannot be measured is absent, never a guess
        return None


def record(*, asked: float, got: float | None, released: float | None, html: str) -> None:
    """Add one finished hold. ``got``/``released`` are ``None`` when the lock was never taken."""
    gave_up()  # idempotent: a thread that asked and never held (the acquire raised), or whose holding() was skipped, stays a waiter otherwise
    if got is None or released is None:
        return
    try:
        wait = max(0.0, got - asked)
        hold = max(0.0, released - got)
        # The page is measured outside the private lock, and only for a hold that may be the longest. The
        # reading of the current longest is unlocked (a float): a stale one costs one measurement too many or
        # one too few, never a wrong pairing, because WHICH hold is the longest is decided under the lock below
        # and the size is always that hold's own.
        size: object = _utf8_size(html) if hold > _state["hold_max_s"] else _UNMEASURED
        with _STATS_LOCK:
            first = _state["holds"] == 0
            _state["holds"] += 1
            _state["wait_total_s"] += wait
            _state["hold_total_s"] += hold
            if wait > _state["wait_max_s"]:
                _state["wait_max_s"] = wait
            if first or hold > _state["hold_max_s"]:
                if size is _UNMEASURED:  # the window was reset, or this is its first hold (which may be of zero length)
                    size = _utf8_size(html)
                _state["hold_max_s"] = hold
                _state["hold_max_html_utf8_bytes"] = size
    except Exception:  # noqa: BLE001 - a statistic never replaces an extraction's result
        return


def snapshot() -> dict:
    """The window so far, as plain numbers. A window with no hold says only ``holds: 0``; a longest hold whose
    page could not be measured says so beside the missing size."""
    with _STATS_LOCK:
        if not _state["holds"]:
            return {"holds": 0}
        out = {
            "holds": _state["holds"],
            "wait_max_s": round(_state["wait_max_s"], 3),
            "wait_total_s": round(_state["wait_total_s"], 3),
            "hold_max_s": round(_state["hold_max_s"], 3),
            "hold_total_s": round(_state["hold_total_s"], 3),
            "hold_max_html_utf8_bytes": _state["hold_max_html_utf8_bytes"],
            "method": METHOD,
        }
        if out["hold_max_html_utf8_bytes"] is None:
            out["hold_max_html_utf8_bytes_note"] = "not measured: the page's size could not be computed"
        return out


def safe_snapshot() -> dict:
    """:func:`snapshot`, or the class of the failure that kept it from being read (never its words, never a zero)."""
    try:
        return snapshot()
    except Exception as exc:  # noqa: BLE001 - the pass is written without the figures, saying so
        return {"unavailable": type(exc).__name__}
