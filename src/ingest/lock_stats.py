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

Best-effort by construction: arithmetic under a private lock, no I/O, taken AFTER the extraction lock
is given up so it adds nothing to a hold. :func:`record` swallows its own ``Exception``, so a fault in
the statistic cannot replace an extraction's result. It is not free: a hold that may be the longest
costs its caller one pass over the page (:func:`_utf8_size`, a few milliseconds for a 10 MiB page,
no copy of it).
"""

from __future__ import annotations

import threading
import time

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


def now() -> float:
    """The clock the statistics read (a name of its own so a test can drive it)."""
    return time.monotonic()


def reset() -> None:
    """Start a new window: forget every hold recorded so far."""
    with _STATS_LOCK:
        _state.update(_EMPTY)  # every key stays present, so an unlocked read in record() never meets a gap


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
