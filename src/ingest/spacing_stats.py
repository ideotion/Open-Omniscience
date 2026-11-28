"""The politeness a pass actually applied: how far apart its requests to one host really were (row 465, the field report's Q8).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE GAP. The fetcher waits ``min_interval_s`` (or the host's declared Crawl-delay) between two requests to one host, and no
report said what spacing that produced in practice: whether hosts were asked once a second, once a minute, or were reached
only once a pass. :meth:`src.ingest.EthicalFetcher._respect_rate_limit` records here, for the window between :func:`reset` and
:func:`snapshot`, the spacing it let through. The collection monitor opens the window when a pass starts and writes the
snapshot into the pass's summary line in ``collect_perf.jsonl`` (``host_spacing``).

WHAT A GAP IS. From the end of the previous request to a host (the moment the fetcher stamps it) to the moment the next
request to that host is let go, after any politeness wait, on the fetcher's own monotonic clock. A host's first request in the
window has no gap and is counted as ``first_contact``. Two histograms over the same bins (:data:`BINS_S`): ``gaps`` counts
every gap, and ``host_min_gap`` counts each host once, by the smallest gap it saw, which is the politeness that host actually
got at its tightest. ``below_interval`` counts gaps shorter than the interval in force (it should stay 0: a non-zero count is
a politeness defect to report, never a figure to tune). A Crawl-delay too long to wait inline is counted in ``deferred``.

Counts and seconds only: no host name, no address, no text. Hosts are held in memory for the window only, to find each one's
smallest gap, and only their number leaves. Arithmetic under a private leaf lock, no I/O; every entry point swallows its own
``Exception``, so a statistic can never change a fetch.
"""

from __future__ import annotations

import threading

from src.shared import snapshot_or_unavailable

_LOCK = threading.Lock()

#: The upper edges of the bins, in seconds; a gap falls in the first bin whose edge it is below, and the last bin is open.
BINS_S = (1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 300.0, 1800.0)
#: The bins' labels, in order: ``<1``, ``1-2``, ... ``300-1800``, ``>=1800``.
BIN_LABELS = tuple(
    [f"<{BINS_S[0]:g}"] + [f"{lo:g}-{hi:g}" for lo, hi in zip(BINS_S, BINS_S[1:], strict=False)] + [f">={BINS_S[-1]:g}"]
)
#: At most this many hosts are held for their smallest gap; a gap from a host past it still counts in ``gaps``, and in
#: ``gaps_untracked`` (a window no collection pass resets would otherwise grow one entry per host for the process's life).
HOST_CAP = 50_000
#: A gap this much shorter than its interval still counts as kept: clock reads around a sleep differ by microseconds.
_TOLERANCE_S = 0.001

#: The method, as an identifier (it goes to a report file; see flush_stats.METHOD for why not a sentence).
METHOD = (
    "monotonic_s;gap=previous_request_end_to_next_request_start_same_host_after_wait;"
    "host_min_gap=one_count_per_host_by_its_smallest_gap;first_request_per_host_is_first_contact;"
    "every_fetcher_in_the_process_between_pass_start_and_summary;no_host_names"
)


def _empty() -> dict:
    return {
        "requests": 0,
        "first_contact": 0,
        "waited": 0,
        "wait_total_s": 0.0,
        "wait_max_s": 0.0,
        "below_interval": 0,
        "deferred": 0,
        "gaps": [0] * (len(BINS_S) + 1),
        "host_min": {},
        "gaps_untracked": 0,
    }


_state: dict = _empty()


def _bin(seconds: float) -> int:
    for i, edge in enumerate(BINS_S):
        if seconds < edge:
            return i
    return len(BINS_S)


def reset() -> None:
    """Start a new window: forget every request recorded so far."""
    global _state
    with _LOCK:
        _state = _empty()


def record(host: str, *, gap_s: float | None, waited_s: float, interval_s: float) -> None:
    """One request let go to ``host``: ``gap_s`` since its previous one (None on first contact), ``waited_s`` the politeness
    wait slept before it, ``interval_s`` the spacing in force. ``host`` stays in memory for the window and never leaves."""
    try:
        with _LOCK:
            s = _state
            s["requests"] += 1
            if waited_s > 0:
                s["waited"] += 1
                s["wait_total_s"] += float(waited_s)
                s["wait_max_s"] = max(s["wait_max_s"], float(waited_s))
            if gap_s is None:
                s["first_contact"] += 1
                return
            gap = max(0.0, float(gap_s))
            s["gaps"][_bin(gap)] += 1
            if gap + _TOLERANCE_S < float(interval_s):
                s["below_interval"] += 1
            prev = s["host_min"].get(host)
            if prev is None and len(s["host_min"]) >= HOST_CAP:
                s["gaps_untracked"] += 1
            elif prev is None or gap < prev:
                s["host_min"][host] = gap
    except Exception:  # noqa: BLE001 - a statistic never changes a fetch
        return


def record_deferred() -> None:
    """A request the host's Crawl-delay put off beyond the inline wait (no request was sent)."""
    try:
        with _LOCK:
            _state["deferred"] += 1
    except Exception:  # noqa: BLE001 - a statistic never changes a fetch
        return


def snapshot() -> dict:
    """The window's figures, seconds rounded to milliseconds, with the bin labels and :data:`METHOD`."""
    with _LOCK:
        s = {**_state, "gaps": list(_state["gaps"]), "host_min": dict(_state["host_min"])}
    host_min = [0] * (len(BINS_S) + 1)
    for gap in s["host_min"].values():
        host_min[_bin(gap)] += 1
    return {
        "requests": s["requests"],
        "first_contact": s["first_contact"],
        "hosts_with_a_gap": len(s["host_min"]),
        "waited": s["waited"],
        "wait_total_s": round(s["wait_total_s"], 3),
        "wait_max_s": round(s["wait_max_s"], 3),
        "below_interval": s["below_interval"],
        "deferred": s["deferred"],
        "gaps_untracked": s["gaps_untracked"],
        "bins_s": list(BIN_LABELS),
        "gaps": s["gaps"],
        "host_min_gap": host_min,
        "method": METHOD,
    }


def safe_snapshot() -> dict:
    """:func:`snapshot`, or the class of the failure that kept it from being read (never its words, never a zero)."""
    return snapshot_or_unavailable(snapshot)
