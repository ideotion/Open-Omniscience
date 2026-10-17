"""
What the extraction lock cost: how long extractions waited for it, and how long each held it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``src/ingest/extract.py`` runs one extraction at a time in the whole process (``_LXML_LOCK``), and
nothing times a long page out: a 10 MiB nav-heavy page measured 85 s, during which every other
extraction waits. On a real install that would read as a stalled collector. This module keeps the
numbers that tell the two apart, for the window between :func:`reset` and :func:`snapshot`; the
collection monitor resets it when a pass starts and writes the snapshot into the pass's summary
line in ``collect_perf.jsonl`` (``extraction_lock``), which the debug bundle already carries.

What is recorded, and what is not:

* the COUNT of holds that finished in the window, the longest and the total WAIT (seconds between
  asking for the lock and getting it), the longest and the total HOLD (seconds between getting it
  and giving it up), and for the longest hold the UTF-8 length of the text handed to
  ``extract_article`` -- not the bytes the server sent, which this function is never told;
* NOT the URL, the title, the text or any exception text: the record is numbers only, so it carries
  nothing the host allowlist or the passphrase rule would have to be applied to;
* a hold counts when it ENDS, so one that began before :func:`reset` and ended after it is in the
  new window, with its full length: it did occupy the lock there. Extractions from any thread are
  counted (the collector's pool, the crawl lane, a manual add), because the lock is process-wide.

Best-effort by construction: arithmetic under a private lock, no I/O, and :func:`record` swallows
its own faults, so a statistic can never break or slow an extraction (it is called AFTER the
extraction lock is given up, so it adds nothing to a hold).
"""

from __future__ import annotations

import threading
import time

#: A leaf lock: nothing is called while it is held, and it is never taken inside the extraction lock.
_STATS_LOCK = threading.Lock()

_EMPTY: dict = {
    "extractions": 0,
    "wait_max_s": 0.0,
    "wait_total_s": 0.0,
    "hold_max_s": 0.0,
    "hold_total_s": 0.0,
    "hold_max_html_utf8_bytes": None,
}
_state: dict = dict(_EMPTY)

#: What the numbers mean, carried in every snapshot that has any (the repo's rule: a signal says its
#: method with it).
METHOD = (
    "seconds on a monotonic clock; wait = from asking for the extraction lock to getting it, hold = from "
    "getting it to giving it up; extractions = holds that ended in this pass's window; "
    "hold_max_html_utf8_bytes = UTF-8 length of the text handed to extract_article for the longest hold"
)


def now() -> float:
    """The clock the statistics read (a name of its own so a test can drive it)."""
    return time.monotonic()


def reset() -> None:
    """Start a new window: forget every hold recorded so far."""
    with _STATS_LOCK:
        _state.clear()
        _state.update(_EMPTY)


def record(*, asked: float, got: float | None, released: float | None, html: str) -> None:
    """Add one finished hold. ``got``/``released`` are ``None`` when the lock was never taken."""
    if got is None or released is None:
        return
    try:
        wait = max(0.0, got - asked)
        hold = max(0.0, released - got)
        with _STATS_LOCK:
            first = _state["extractions"] == 0
            _state["extractions"] += 1
            _state["wait_total_s"] += wait
            _state["hold_total_s"] += hold
            if wait > _state["wait_max_s"]:
                _state["wait_max_s"] = wait
            longest = first or hold > _state["hold_max_s"]
            if longest:
                _state["hold_max_s"] = hold
        if longest:
            # Encoding a page that may be megabytes happens outside the private lock and only for a new
            # longest hold. A later hold that beat this one in between wins the race by being longer.
            size = len(html.encode("utf-8", "replace"))
            with _STATS_LOCK:
                if _state["hold_max_s"] == hold:
                    _state["hold_max_html_utf8_bytes"] = size
    except Exception:  # noqa: BLE001 - a statistic never breaks an extraction
        return


def snapshot() -> dict:
    """The window so far, as plain numbers. A window with no extraction says only ``extractions: 0``."""
    with _STATS_LOCK:
        if not _state["extractions"]:
            return {"extractions": 0}
        return {
            "extractions": _state["extractions"],
            "wait_max_s": round(_state["wait_max_s"], 3),
            "wait_total_s": round(_state["wait_total_s"], 3),
            "hold_max_s": round(_state["hold_max_s"], 3),
            "hold_total_s": round(_state["hold_total_s"], 3),
            "hold_max_html_utf8_bytes": _state["hold_max_html_utf8_bytes"],
            "method": METHOD,
        }
