"""
Where a collector flush spends the single-writer gate: the phases of :meth:`ArticleBatch._flush_batched`.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Row 446 / docket row 451. The November field analysis measured a collector flush holding the writer for 74 s on average on one
Linux install, with the gate busy 98 to 99 % of the time, and could not say which statements the hold was made of. This keeps
that breakdown for the window between :func:`reset` and :func:`snapshot`. The collection monitor opens the window when a pass
starts and writes the snapshot into the pass's summary line in ``collect_perf.jsonl`` (``collector_flush``).

The phases, in the order a flush runs them:

* OUTSIDE the gate: ``exists`` (the duplicate re-check, reads only), ``precompute`` (keyword, sentiment and place extraction,
  :meth:`ArticleBatch._precompute`), and after the commit ``after_commit`` (the custody log and the dedup front);
* INSIDE the gate, which the first write takes and the commit gives back: ``insert`` (the session flush that inserts the
  articles and gives them ids), ``index`` (every article's keyword, mention, date, place and entity writes, with the one
  stored-mention read before them), ``links`` (the outbound-link rows) and ``commit``.

``hold`` is ``insert + index + links + commit`` of one flush, measured as one interval. A flush that raised is NOT recorded:
its batch is redone one article at a time, and that path has its own timings in no window here. Numbers only: no URL, no
title, no text, no exception words. Arithmetic under a private leaf lock, no I/O; every entry point swallows its own
``Exception``, so a statistic can never replace a flush's result.
"""

from __future__ import annotations

import threading

from src.shared import snapshot_or_unavailable

_LOCK = threading.Lock()

#: The phases a flush reports, in the order it runs them; the first three of the gate's are inside it, with ``commit``.
PHASES = ("exists", "precompute", "insert", "index", "links", "commit", "after_commit")

#: The method, as an identifier rather than a sentence: this block goes to a report file (``collect_perf.jsonl``), and a bare English
#: sentence there would be one more for the server-text ratchet (tests/test_server_text_keyed.py). Spelled out: seconds on a
#: monotonic clock, summed over the collector flushes that committed in this pass's window; hold = from the insert that takes the
#: single-writer gate to the end of the commit that gives it back (insert + index + links + commit); exists, precompute and
#: after_commit run outside the gate; a flush that failed and was redone article by article is not counted.
METHOD = "monotonic_s;committed_flushes_only;hold=insert+index+links+commit;outside_gate=exists,precompute,after_commit"


def _empty() -> dict:
    return {
        "flushes": 0,
        "articles": 0,
        "hold_total_s": 0.0,
        "hold_max_s": 0.0,
        "hold_max_articles": 0,
        "phases_s": dict.fromkeys(PHASES, 0.0),
    }


_state: dict = _empty()


def reset() -> None:
    """Start a new window: forget every flush recorded so far."""
    global _state
    with _LOCK:
        _state = _empty()


def record(phases: dict[str, float], *, articles: int, hold_s: float) -> None:
    """Add one committed flush. ``phases`` maps names of :data:`PHASES` to seconds; an unknown name is ignored."""
    try:
        with _LOCK:
            s = _state
            s["flushes"] += 1
            s["articles"] += int(articles)
            s["hold_total_s"] += float(hold_s)
            if hold_s > s["hold_max_s"]:
                s["hold_max_s"] = float(hold_s)
                s["hold_max_articles"] = int(articles)
            for k, v in phases.items():
                if k in s["phases_s"]:
                    s["phases_s"][k] += float(v)
    except Exception:  # noqa: BLE001 - a statistic never replaces a flush's result
        return


def snapshot() -> dict:
    """The window's figures, rounded to milliseconds, with :data:`METHOD`. A window with no flush says so (``flushes: 0``)
    and carries no means."""
    with _LOCK:
        s = {**_state, "phases_s": dict(_state["phases_s"])}
    out: dict = {
        "flushes": s["flushes"],
        "articles": s["articles"],
        "hold_total_s": round(s["hold_total_s"], 3),
        "hold_max_s": round(s["hold_max_s"], 3),
        "hold_max_articles": s["hold_max_articles"],
        "phases_s": {k: round(v, 3) for k, v in s["phases_s"].items()},
        "method": METHOD,
    }
    if s["flushes"]:
        out["hold_mean_s"] = round(s["hold_total_s"] / s["flushes"], 3)
    return out


def safe_snapshot() -> dict:
    """:func:`snapshot`, or the class of the failure that kept it from being read (never its words, never a zero)."""
    return snapshot_or_unavailable(snapshot)
