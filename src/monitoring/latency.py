"""
Request-latency + event-loop-block log — the "what froze the single-worker server?" log.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Recursive-augmentation log #2 (maintainer 2026-07-02): the unlock freeze, the
"Previewing… for an hour", and "the task manager never loads" were ALL one root cause —
heavy SYNCHRONOUS work on the single async event loop, which stalls every other request
until it finishes. This log makes that visible two ways: per-route latency percentiles
(p50/p95/p99 from a bounded recent-window reservoir) AND an event-loop WATCHDOG that
measures loop lag and records a blocking event (with the requests in flight at the time),
so the next such freeze points at itself instead of me reasoning it out.

Honesty + safety: local-only, network-free, timings + route templates only (never a
bound value or corpus content). Everything is bounded (recent-window reservoirs, a
capped events ring). The watchdog and the recorder never raise.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from src.monitoring import unlock_marker as _unlock

_LOCK = threading.Lock()
_RES_CAP = 512  # recent durations kept per route (the percentile reservoir)
_EVENTS_CAP = 100  # loop-block events kept
# Distinct route keys kept. This is the ONE bound on the published lists, and what it protects
# is memory (and the size of the export): route templates are few, but a request no route matched
# is keyed by its own path, so a scan of the loopback server could otherwise mint keys without
# limit. The lists themselves are NOT cut below it (see ``summary``); a request for a NEW key once
# the keyspace is full is counted in ``_KEYSPACE_DROPPED`` and published, never silently lost.
_ROUTES_CAP = 2048
_KEYSPACE_DROPPED = 0

# Wall clock, injectable in tests. The reservoir stores durations only, so without a stamp no
# call could be placed in time -- which is what the first-call and unlock readings below need.
_wall: Callable[[], float] = time.time

# Statuses that mean the server DECLINED or gave up rather than answered. Mostly that is what they
# are here: 503 is what every API but the unlock flow answers while the database is locked and what
# a statement that hit its deadline answers; 429 is the rate limiter's answer and a heavy
# computation that is already running; 423 is the Wikipedia lane's own locked answer. But the same
# codes also come from other places -- 503 from the language-model bridge and the custody anchor
# when their service is unavailable, and from the Wikipedia lane when its file cannot be read -- so
# the status says a request was declined, never which of these declined it. Any other 5xx is an
# ERROR; everything else, 4xx included, is a request that ran to a response.
# A refusal is not an error and not a completion, and a p95 that mixes the three cannot say which
# one made a route slow: that is the whole reason for the split below.
_REFUSAL_STATUSES = frozenset({423, 429, 503})

# route key ("GET /api/articles/{id}/view") -> {"durations": deque, "kinds": deque (the same
# window, one letter per sample: c completed / r refused / e error), "count": int,
# "max_ms": float, "statuses": {code: n}, "first": call | None, "slowest": call | None}
# where a ``call`` is {ms, status, ended_at, started_after_unlock_s}.
_ROUTES: dict[str, dict[str, Any]] = {}
# in-flight requests: id -> {"route": str, "started": float}
_INFLIGHT: dict[int, dict[str, Any]] = {}
_EVENTS: deque[dict[str, Any]] = deque(maxlen=_EVENTS_CAP)

# S3.4: EVERY watchdog sample, not just the ones that breach the block threshold.
# The events above record exceptional stalls; this is the continuous reading a
# client-facing "is the server busy" disclosure needs. (epoch, lag_ms) pairs at
# the watchdog's own cadence, bounded to the window below.
_LAG_WINDOW_S = 10.0
_LAG_CAP = 128
_LAG: deque[tuple[float, float]] = deque(maxlen=_LAG_CAP)

_watchdog_started = False

try:  # pragma: no cover - the fallback is unreachable in a healthy tree
    from src.monitoring.stall_forensics import note_stall as _note_stall
except Exception:  # noqa: BLE001
    # No cycle exists today (stall_forensics imports this module lazily, inside a
    # function), and this guard is not about that: it is the "instrumentation must
    # never break the response" rule applied one level up. A latency module that
    # cannot be IMPORTED takes the whole app with it, so a broken optional log
    # degrades to a no-op rather than to an unbootable server.
    def _note_stall(route: str, status: int, duration_ms: float) -> None:  # type: ignore[misc]
        return None


def _loop_block_ms() -> float:
    """Loop-lag threshold in ms above which a block is recorded (OO_LOOP_BLOCK_MS; 250)."""
    try:
        return float(os.environ.get("OO_LOOP_BLOCK_MS", "250"))
    except ValueError:
        return 250.0


# The "snappy" acceptance bar (SCALE_ROADMAP.md / ROADMAP.md): every INTERACTIVE endpoint
# p95 < ~500 ms. S2.7 renders each route's measured p95 as an explicit pass/fail against it,
# so the maintainer's next field export SHOWS the bar instead of eyeballing raw ms.
_SNAPPY_BAR_MS_DEFAULT = 500.0
_SNAPPY_MIN_N = 20  # min samples in the window before a route gets a pass/fail (else low-n)

# HEAVY / on-demand routes are NOT interactive and are NOT held to the 500 ms bar (they are
# deliberate exports / jobs / backups / diagnostics, expected to be slow or job-ified). They
# are reported with their p95 but marked "exempt", never a "fail" — the bar is for the reads
# a user waits on, per its written definition.
_EXEMPT_ROUTE_SUBSTRINGS = (
    "/diagnostics/",
    "/export",
    "/backup",
    "/jobs",
    "/dump",
    "/api/llm/",
    "/geo/",
    "/p0-validation",
    "/all",
    "/import",
    "/metrics",
)


def _snappy_bar_ms() -> float:
    """The p95 bar interactive endpoints are judged against (OO_SNAPPY_BAR_MS; 500)."""
    try:
        return float(os.environ.get("OO_SNAPPY_BAR_MS", str(_SNAPPY_BAR_MS_DEFAULT)))
    except ValueError:
        return _SNAPPY_BAR_MS_DEFAULT


def _snappy_verdict(route: str, p95_ms: float, window_n: int, bar_ms: float) -> str:
    """pass | fail | low-n | exempt — an HONEST mapping of a REAL measured p95 to the
    written bar (never a fabricated number; low-n when the window is too thin to judge;
    exempt for the heavy/on-demand routes the interactive bar does not cover)."""
    if any(sub in route for sub in _EXEMPT_ROUTE_SUBSTRINGS):
        return "exempt"
    if window_n < _SNAPPY_MIN_N:
        return "low-n"
    return "pass" if p95_ms < bar_ms else "fail"


def note_start(req_id: int, route: str) -> None:
    with _LOCK:
        if len(_INFLIGHT) < 4096:
            _INFLIGHT[req_id] = {"route": route, "started": time.monotonic()}


def _kind_of(status: int) -> str:
    """One letter for how a request ended: ``r`` refused, ``e`` errored, ``c`` completed."""
    if status in _REFUSAL_STATUSES:
        return "r"
    return "e" if status >= 500 else "c"


def _call_facts(status: int, duration_ms: float) -> dict[str, Any]:
    """What is worth keeping about ONE call: how long, how it ended, when, and how far from the
    latest unlock to have finished by then it began. Taken only for a route's first call and its
    slowest so far -- rare events -- so the wall-clock read costs nothing on the common path."""
    ms, code = round(float(duration_ms), 1), int(status)
    try:
        ended = _wall()
        return {
            "ms": ms,
            "status": code,
            "ended_at": datetime.fromtimestamp(ended, tz=UTC).isoformat(timespec="seconds"),
            # SIGNED, and None (never 0) when this process has finished no unlock; see unlock_marker.
            "started_after_unlock_s": _unlock.started_after_unlock_s(ended - ms / 1000.0),
        }
    except Exception:  # noqa: BLE001 - a clock that fails costs the stamp, never the sample
        return {"ms": ms, "status": code, "ended_at": None, "started_after_unlock_s": None}


def record(req_id: int, route: str, status: int, duration_ms: float) -> None:
    """Record one completed request. Best-effort; never raises."""
    global _KEYSPACE_DROPPED
    try:
        # Classified BEFORE any state is touched: ``durations`` and ``kinds`` are one window in
        # two deques, and a failure between their two appends would leave them uneven for good.
        kind = _kind_of(status)
        with _LOCK:
            _INFLIGHT.pop(req_id, None)
            r = _ROUTES.get(route)
            if r is None:
                if len(_ROUTES) >= _ROUTES_CAP:  # bound the keyspace (route templates are few)
                    _KEYSPACE_DROPPED += 1
                    return
                r = {
                    "durations": deque(maxlen=_RES_CAP),
                    "kinds": deque(maxlen=_RES_CAP),
                    "count": 0,
                    "max_ms": 0.0,
                    "statuses": {},
                    "first": None,
                    "slowest": None,
                }
                _ROUTES[route] = r
            if r["count"] == 0 or duration_ms > r["max_ms"]:
                call = _call_facts(status, duration_ms)
                if r["count"] == 0:
                    r["first"] = call
                # strictly slower only, so a tie keeps the EARLIER call as the slowest
                r["slowest"] = call
            r["durations"].append(duration_ms)
            r["kinds"].append(kind)
            r["count"] += 1
            r["max_ms"] = max(r["max_ms"], duration_ms)
            sc = str(status)
            r["statuses"][sc] = r["statuses"].get(sc, 0) + 1
    except Exception:  # noqa: BLE001 - instrumentation must never break the response
        return
    # A request slow enough to be a STALL gets its causes read while the machine is
    # still in the state that produced it -- the 2026-07-11 cluster was undiagnosable
    # precisely because nobody was looking at the moment. Deliberately OUTSIDE the
    # _LOCK above: the readings take other modules' locks, and holding this one across
    # them would let the stall log become its own source of contention. ``_note_stall``
    # is resolved once at import (see below), not per request: this runs on EVERY
    # response, and it returns immediately for all but the rare slow one.
    try:
        _note_stall(route, status, duration_ms)
    except Exception:  # noqa: BLE001 - instrumentation must never break the response
        return


def recent_block_events(limit: int = 5) -> list[dict[str, Any]]:
    """The most recent event-loop-block events, oldest-first within the window.

    A read-only accessor over the same ring :func:`summary` publishes, so a caller
    that needs to correlate one request against recent loop blocks (see
    ``src.monitoring.stall_forensics``) does not have to reach into module state.
    """
    with _LOCK:
        evs = list(_EVENTS)
    return evs[-max(1, int(limit or 1)) :]


def _pct(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = max(0, min(len(sorted_vals) - 1, int(round((p / 100.0) * (len(sorted_vals) - 1)))))
    return round(sorted_vals[k], 1)


def _record_block(lag_ms: float) -> None:
    try:
        with _LOCK:
            now = time.monotonic()
            in_flight = [
                {"route": v["route"], "elapsed_ms": round((now - v["started"]) * 1000.0, 1)}
                for v in _INFLIGHT.values()
            ]
        # Sort so the longest-running in-flight request (the likely culprit) is first.
        in_flight.sort(key=lambda x: x["elapsed_ms"], reverse=True)
        _EVENTS.append(
            {
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
                "lag_ms": round(lag_ms, 1),
                "in_flight": in_flight[:10],
            }
        )
    except Exception:  # noqa: BLE001
        return


async def _watchdog(interval_s: float = 0.2) -> None:
    """Ping the event loop every ``interval_s``; a large gap between the scheduled and
    the actual wake time means the loop was BLOCKED (a sync call monopolised it)."""
    while True:
        before = time.monotonic()
        try:
            await asyncio.sleep(interval_s)
        except asyncio.CancelledError:  # graceful shutdown
            return
        lag_ms = (time.monotonic() - before - interval_s) * 1000.0
        # A negative reading means the loop woke EARLY (clock granularity); floor at
        # 0 rather than publishing a negative lag, which describes nothing.
        with _LOCK:
            _LAG.append((time.monotonic(), max(0.0, lag_ms)))
        if lag_ms >= _loop_block_ms():
            _record_block(lag_ms)


def loop_lag() -> dict[str, Any]:
    """The event loop's recent scheduling delay -- a real measurement, or an
    honest absence.

    ``latest_ms`` is the most recent sample and ``peak_ms`` the largest in the
    window; they are published SEPARATELY because they answer different questions
    and one number cannot carry both. A single 200 ms sample can read near zero on
    a loaded server that happened to be free at that instant, so the peak is the
    one a "server busy" disclosure should read -- and calling the peak "the lag"
    would be the same key meaning two things.

    Every field is ``None`` when the watchdog has never sampled (no running loop,
    or it was never started). NOT zero: "the loop is not lagging" and "nobody
    measured" are opposite claims, and a zero here would publish the first while
    meaning the second.
    """
    now = time.monotonic()
    with _LOCK:
        samples = [(t, v) for (t, v) in _LAG if (now - t) <= _LAG_WINDOW_S]
        latest = _LAG[-1] if _LAG else None
    if not samples and latest is None:
        return {
            "latest_ms": None,
            "peak_ms": None,
            "window_s": _LAG_WINDOW_S,
            "samples": 0,
            "reason": "the event-loop watchdog has not sampled (no running loop)",
        }
    return {
        # `latest` can sit outside the window on an app that is idle enough for the
        # watchdog to be the only thing running; report it with its real age rather
        # than dropping the only reading there is.
        "latest_ms": round(latest[1], 1) if latest is not None else None,
        "latest_age_s": round(now - latest[0], 1) if latest is not None else None,
        "peak_ms": round(max(v for _, v in samples), 1) if samples else None,
        "window_s": _LAG_WINDOW_S,
        "samples": len(samples),
    }


_LOOP_MIN_SAMPLES = 10  # 2 s at the watchdog's 0.2 s cadence


def loop_pressure(
    threshold_ms: float,
    *,
    since: float | None = None,
    min_samples: int = _LOOP_MIN_SAMPLES,
) -> dict[str, Any]:
    """How much of the watchdog's recent window sat AT OR ABOVE ``threshold_ms``.

    P6 (2026-09-11). ``loop_lag()`` publishes ``latest`` and ``peak``, and neither can
    drive a control on its own -- which is why this is a third reading rather than a
    comparison bolted onto one of those two.

    ``peak_ms`` is STICKY: the window is 10 s and the collector's governor ticks every
    1.5 s, so ONE spike is still the peak seven ticks later and a control reading it would
    keep cutting workers long after the loop recovered. ``latest_ms`` is the opposite
    failure -- a single 200 ms probe reads near zero on a loaded server that happened to
    be free at that instant, which ``loop_lag``'s own docstring already says.

    The reading that separates a spike from sustained pressure is the FRACTION of the
    window that breached, and it is the one measurement that survives contact with what
    was actually observed: at 32 collector threads on a 4-core box the peak reached
    210 ms while the p50 stayed at 2 ms and only 3 % of samples passed 25 ms. A peak rule
    calls that starvation. The fraction calls it a spike, which is what it is.

    ``measured`` is False, with a reason, when the watchdog has no sample in the window --
    no running loop, or it was never started. The fraction is then ABSENT, never 0.0:
    "the loop is fine" and "nobody looked" are opposite claims and a control must not act
    on the second while believing the first.

    ``since`` (a ``time.monotonic`` stamp) drops samples taken BEFORE it, and it is not
    optional for a caller deciding something about a bounded piece of work. ``_LAG`` is
    process-global and the window is ten seconds of wall clock, so without it a reading
    can be about a stall that happened before the work being judged even began --
    measured, not theorised: a collect pass starting seconds after an unrelated
    synchronous burst read that burst as its own contention and cut workers for it.

    ``min_samples`` is the same refusal at the other end. A fraction over three readings
    is not a fraction, and the first seconds of any ``since``-scoped window hold only a
    few -- so below the floor this reports ABSENT with a reason rather than a number
    computed from too little. ``latency``'s own snappy verdict already draws that line
    ("low-n"); this is the same line in the same module.
    """
    now = time.monotonic()
    with _LOCK:
        vals = [
            v
            for (t, v) in _LAG
            if (now - t) <= _LAG_WINDOW_S and (since is None or t >= since)
        ]
    if len(vals) < max(1, int(min_samples)):
        return {
            "measured": False,
            "over": None,
            "samples": len(vals),
            "fraction": None,
            "peak_ms": None,
            "p50_ms": None,
            "threshold_ms": round(float(threshold_ms), 1),
            "window_s": _LAG_WINDOW_S,
            "reason": (
                "the event-loop watchdog has no sample in the window"
                if not vals
                else f"only {len(vals)} watchdog sample(s) in the window, below the "
                f"{int(min_samples)} a fraction needs to mean anything"
            ),
        }
    over = sum(1 for v in vals if v >= threshold_ms)
    return {
        "measured": True,
        "over": over,
        "samples": len(vals),
        "fraction": round(over / len(vals), 3),
        "peak_ms": round(max(vals), 1),
        "p50_ms": _pct(sorted(vals), 50),
        "threshold_ms": round(float(threshold_ms), 1),
        "window_s": _LAG_WINDOW_S,
    }


def start_watchdog() -> None:
    """Start the loop-block watchdog on the running event loop (idempotent).
    Safe to call from an async lifespan; a no-op if there is no running loop."""
    global _watchdog_started
    if _watchdog_started:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # no running loop (e.g. a sync test) — skip silently
    loop.create_task(_watchdog())
    _watchdog_started = True


def _reset_for_tests() -> None:
    """Drop all recorded per-route reservoirs / events / lag samples, the dropped-key count and
    the unlock stamp the readings here are measured from (test hook)."""
    global _KEYSPACE_DROPPED
    with _LOCK:
        _LAG.clear()
        _ROUTES.clear()
        _INFLIGHT.clear()
        _EVENTS.clear()
        _KEYSPACE_DROPPED = 0
    _unlock._reset_for_tests()


def _route_row(key: str, r: dict[str, Any], bar_ms: float) -> dict[str, Any]:
    """One route's published row. Called under ``_LOCK``.

    Every figure beside ``p95_ms`` ATTRIBUTES it and none replaces it: ``p95_ms`` still counts
    every request, refused ones included, because a person waited for them. What the extra
    fields add is the part a single percentile cannot carry -- how the window's requests ended,
    whether the route's first call is what made it slow, and where its slowest call sat
    relative to the latest unlock that had finished when it ended. All of them are over the SAME window as ``window_n``, except
    ``slowest`` and ``first_*``, which are since this process started (like ``max_ms``).
    """
    durations = list(r["durations"])
    kinds = list(r["kinds"])
    vals = sorted(durations)
    p95 = _pct(vals, 95)
    completed = sorted(d for d, k in zip(durations, kinds, strict=False) if k == "c")
    first = r.get("first")
    slowest = r.get("slowest")
    # The route's first call is still the window's oldest sample only while nothing has been
    # evicted from it; once a 513th request arrives the first call is gone and the figure that
    # excludes it is ABSENT rather than computed over a window that no longer contains it.
    first_in_window = bool(first) and r["count"] <= _RES_CAP and len(durations) >= 1
    after_first = sorted(durations[1:]) if first_in_window else []
    return {
        "route": key,
        "count": r["count"],
        "window_n": len(vals),
        "p50_ms": _pct(vals, 50),
        "p95_ms": p95,
        "p99_ms": _pct(vals, 99),
        "max_ms": round(r["max_ms"], 1),
        "statuses": dict(r["statuses"]),
        # S2.7: the p95-vs-500 ms snappy-bar verdict for THIS route.
        "snappy": _snappy_verdict(key, p95, len(vals), bar_ms),
        # How the window's requests ended: completed + refused + error == window_n.
        "completed_n": len(completed),
        "refused_n": kinds.count("r"),
        "error_n": kinds.count("e"),
        # None, not 0.0, when no request in the window completed: "nothing completed" and
        # "the completed ones were instant" are opposite claims.
        "p95_completed_ms": _pct(completed, 95) if completed else None,
        "first_ms": first["ms"] if first else None,
        "first_status": first["status"] if first else None,
        "first_in_window": first_in_window,
        # None when the first call has left the window, or when it is the only sample.
        "p95_without_first_ms": _pct(after_first, 95) if after_first else None,
        "slowest": dict(slowest) if slowest else None,
    }


def _breach_row(r: dict[str, Any]) -> dict[str, Any]:
    """The maintainer's worklist row: the route, its p95 and n, and the attribution beside them
    (the full row stays in ``routes``)."""
    return {
        "route": r["route"],
        "p95_ms": r["p95_ms"],
        "window_n": r["window_n"],
        "verdict": r["snappy"],
        "completed_n": r["completed_n"],
        "refused_n": r["refused_n"],
        "error_n": r["error_n"],
        "p95_completed_ms": r["p95_completed_ms"],
        "first_ms": r["first_ms"],
        "p95_without_first_ms": r["p95_without_first_ms"],
        "slowest": r["slowest"],
    }


def summary() -> dict[str, Any]:
    """The latency log: per-route p50/p95/p99 over the recent window + the loop-block
    events. Sorted by p99 so the slowest routes surface first. Nothing is cut: every route is
    listed, bounded only by the keyspace memory bound, whose dropped requests are published."""
    bar_ms = _snappy_bar_ms()
    with _LOCK:
        routes = [_route_row(key, r, bar_ms) for key, r in _ROUTES.items()]
        events = list(_EVENTS)
        in_flight_now = len(_INFLIGHT)
        dropped = _KEYSPACE_DROPPED
    routes.sort(key=lambda x: x["p99_ms"], reverse=True)
    # S2.7 top-level roll-up: how the INTERACTIVE routes stand against the bar, so a field
    # export shows pass/fail directly. `failing` lists the offenders (interactive routes
    # whose measured p95 breaches the bar) — the maintainer's snappiness worklist.
    interactive = [r for r in routes if r["snappy"] != "exempt"]
    passing = [r for r in interactive if r["snappy"] == "pass"]
    failing = [r for r in interactive if r["snappy"] == "fail"]
    low_n = [r for r in interactive if r["snappy"] == "low-n"]
    # THE BREACH SET, independent of window thickness (field bundle 2026-08-02).
    #
    # low-n withholds statistical CONFIDENCE, and that is right -- but it was being
    # read as "nothing was measured", which is false: a low-n route has a REAL p95.
    # Worse, window_n >= 20 is almost perfectly correlated with "is this a poller?",
    # because a human clicks the article list a handful of times a session while the
    # UI polls /api/system/network every 2 s. So the bar judged only pollers and
    # reported all_interactive_pass:true over 3 of them while GET /api/articles sat
    # at a measured p95 of 68,137 ms, /api/insights/trending-windows at 61,398 ms and
    # /api/insights/latest at 60,042 ms -- all excluded as "low-n". A verdict must map
    # to the bar it actually tested, so a blanket pass may not be claimed while ANY
    # measured interactive route is over the bar. n travels with every breach, so a
    # thin window stays visible rather than being silently promoted to a failure.
    breaching = [r for r in interactive if float(r["p95_ms"] or 0.0) >= bar_ms]
    breaching_low_n = [r for r in breaching if r["snappy"] == "low-n"]
    # ATTRIBUTION OF THE BREACHES (diagnostics round of 2026-09-30, rank 10). 306 routes were
    # over the bar across sixteen bundles and 287 of them had a window under 20, so "which of
    # these is a real slow read" was unanswerable from the export. These three counts do not
    # excuse a breach -- every one of them stays in `breaching` and keeps `all_interactive_pass`
    # false -- they say what kind of breach it is. They count ROUTES, not requests, and they
    # overlap (a one-call route whose only call was refused is in two of them).
    not_completed = [
        r for r in breaching if r["p95_completed_ms"] is None or r["p95_completed_ms"] < bar_ms
    ]
    first_call_only = [
        r
        for r in breaching
        if r["window_n"] >= 2
        and r["p95_without_first_ms"] is not None
        and r["p95_without_first_ms"] < bar_ms
    ]
    single_call = [r for r in breaching if r["window_n"] == 1]
    snappy = {
        "bar_ms": bar_ms,
        "min_n": _SNAPPY_MIN_N,
        "interactive_routes": len(interactive),
        "passing": len(passing),
        "failing": len(failing),
        "low_n": len(low_n),
        "breaching": len(breaching),
        "breaching_low_n": len(breaching_low_n),
        "breaching_refusal_or_error_driven": len(not_completed),
        "breaching_first_call_only": len(first_call_only),
        "breaching_single_call": len(single_call),
        "all_interactive_pass": len(breaching) == 0 and len(interactive) > 0,
        "breaching_routes": [
            _breach_row(r) for r in sorted(breaching, key=lambda x: -(x["p95_ms"] or 0.0))
        ],
        # Kept for callers that read it; same shape, now a SUBSET of breaching_routes.
        "failing_routes": [
            {"route": r["route"], "p95_ms": r["p95_ms"], "window_n": r["window_n"]}
            for r in sorted(failing, key=lambda x: -x["p95_ms"])
        ],
        "method": (
            f"Each interactive route's measured p95 vs the {bar_ms:.0f} ms 'snappy' bar "
            "(ROADMAP/SCALE_ROADMAP): pass | fail | low-n (window < "
            f"{_SNAPPY_MIN_N}) | exempt (heavy/on-demand routes the bar does not cover). "
            "low-n withholds statistical confidence, NOT the measurement: a low-n route "
            "over the bar is counted in 'breaching' with its n shown, and "
            "all_interactive_pass is false while any measured route breaches — the routes "
            "a human actually waits on are exactly the ones with thin windows. "
            "Measurements only; no fabricated number, no score. "
            "BREACHES ARE ATTRIBUTED, NEVER EXCUSED: p95_ms still counts every request, "
            "refused ones included, because a person waited for them. Beside it each route "
            "says how its window ended (completed_n; refused_n = 423, 429 or 503, which are "
            "mostly a locked database, a rate limit, a heavy computation already running or a "
            "statement that hit its deadline, but the same codes also come from the language-model "
            "bridge, the custody anchor and the Wikipedia lane, so the status alone does not say "
            "which one declined; error_n = any other 5xx), the p95 "
            "of the completed requests alone, its first call and the p95 without it (only "
            "while that call is still in the window), and its slowest call with when it ended "
            "and how far from the latest unlock to have finished by then it began (signed, "
            "fixed when the call was recorded; absent, not 0, when no unlock had finished by "
            "then). breaching_refusal_or_error_driven counts "
            "breaching routes whose completed requests alone are under the bar (or that have "
            "none); breaching_first_call_only those with two or more samples that fall under "
            "it without the first call; breaching_single_call those with exactly one sample. "
            "They count routes, not requests, and overlap."
        ),
    }
    return {
        "watchdog": {
            "running": _watchdog_started,
            "block_threshold_ms": _loop_block_ms(),
            "events": events[-50:],
            "events_captured": len(events),
        },
        "in_flight_now": in_flight_now,
        # The stamp record every `started_after_unlock_s` below is measured from (or the reason
        # it is absent): the unlock path's own moment, not this process's start. Each distance was
        # fixed against the latest stamp that existed when its call ended; a later unlock does not
        # move it.
        "unlock": _unlock.summary(),
        "snappy_bar": snappy,
        "routes_total": len(routes),
        "routes": routes,
        # The one bound that stays, and what it protects: distinct route keys, because a request
        # no route matched is keyed by its own path and a scan could otherwise mint keys without
        # limit. A request for a new key once it is full is counted here, never silently lost.
        "route_keyspace": {
            "cap": _ROUTES_CAP,
            "routes": len(routes),
            "dropped_requests": dropped,
        },
        "method": (
            "Per-route latency percentiles over a recent-window reservoir + an event-loop "
            "watchdog that flags loop lag (heavy sync work on the async loop — the "
            "unlock/restore/task-manager freeze family) + a per-route p95-vs-bar snappy "
            "verdict. Every route is listed (routes_total); the only bound is the route "
            "keyspace (route_keyspace). Route templates only, no bound values; read-only; "
            "no score."
        ),
    }
