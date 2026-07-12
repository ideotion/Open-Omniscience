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
from datetime import UTC, datetime
from typing import Any

_LOCK = threading.Lock()
_RES_CAP = 512  # recent durations kept per route (the percentile reservoir)
_EVENTS_CAP = 100  # loop-block events kept

# route key ("GET /api/articles/{id}/view") -> {"durations": deque, "count": int,
# "max_ms": float, "statuses": {code: n}}
_ROUTES: dict[str, dict[str, Any]] = {}
# in-flight requests: id -> {"route": str, "started": float}
_INFLIGHT: dict[int, dict[str, Any]] = {}
_EVENTS: deque[dict[str, Any]] = deque(maxlen=_EVENTS_CAP)

_watchdog_started = False


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


def record(req_id: int, route: str, status: int, duration_ms: float) -> None:
    """Record one completed request. Best-effort; never raises."""
    try:
        with _LOCK:
            _INFLIGHT.pop(req_id, None)
            r = _ROUTES.get(route)
            if r is None:
                if len(_ROUTES) >= 2048:  # bound the keyspace (route templates are few)
                    return
                r = {"durations": deque(maxlen=_RES_CAP), "count": 0, "max_ms": 0.0, "statuses": {}}
                _ROUTES[route] = r
            r["durations"].append(duration_ms)
            r["count"] += 1
            r["max_ms"] = max(r["max_ms"], duration_ms)
            sc = str(status)
            r["statuses"][sc] = r["statuses"].get(sc, 0) + 1
    except Exception:  # noqa: BLE001 - instrumentation must never break the response
        return


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
        if lag_ms >= _loop_block_ms():
            _record_block(lag_ms)


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
    """Drop all recorded per-route reservoirs / events (test hook)."""
    with _LOCK:
        _ROUTES.clear()
        _INFLIGHT.clear()
        _EVENTS.clear()


def summary() -> dict[str, Any]:
    """The latency log: per-route p50/p95/p99 over the recent window + the loop-block
    events. Sorted by p99 so the slowest routes surface first."""
    bar_ms = _snappy_bar_ms()
    with _LOCK:
        routes = []
        for key, r in _ROUTES.items():
            vals = sorted(r["durations"])
            p95 = _pct(vals, 95)
            routes.append(
                {
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
                }
            )
        events = list(_EVENTS)
        in_flight_now = len(_INFLIGHT)
    routes.sort(key=lambda x: x["p99_ms"], reverse=True)
    # S2.7 top-level roll-up: how the INTERACTIVE routes stand against the bar, so a field
    # export shows pass/fail directly. `failing` lists the offenders (interactive routes
    # whose measured p95 breaches the bar) — the maintainer's snappiness worklist.
    interactive = [r for r in routes if r["snappy"] != "exempt"]
    passing = [r for r in interactive if r["snappy"] == "pass"]
    failing = [r for r in interactive if r["snappy"] == "fail"]
    low_n = [r for r in interactive if r["snappy"] == "low-n"]
    snappy = {
        "bar_ms": bar_ms,
        "interactive_routes": len(interactive),
        "passing": len(passing),
        "failing": len(failing),
        "low_n": len(low_n),
        "all_interactive_pass": len(failing) == 0 and len(interactive) > 0,
        "failing_routes": [
            {"route": r["route"], "p95_ms": r["p95_ms"], "window_n": r["window_n"]}
            for r in sorted(failing, key=lambda x: -x["p95_ms"])
        ][:20],
        "method": (
            f"Each interactive route's measured p95 vs the {bar_ms:.0f} ms 'snappy' bar "
            "(ROADMAP/SCALE_ROADMAP): pass | fail | low-n (window < "
            f"{_SNAPPY_MIN_N}) | exempt (heavy/on-demand routes the bar does not cover). "
            "Measurements only; no fabricated number, no score."
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
        "snappy_bar": snappy,
        "routes": routes[:60],
        "method": (
            "Per-route latency percentiles over a recent-window reservoir + an event-loop "
            "watchdog that flags loop lag (heavy sync work on the async loop — the "
            "unlock/restore/task-manager freeze family) + a per-route p95-vs-bar snappy "
            "verdict. Route templates only, no bound values; read-only; no score."
        ),
    }
