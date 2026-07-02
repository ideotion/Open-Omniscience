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


def summary() -> dict[str, Any]:
    """The latency log: per-route p50/p95/p99 over the recent window + the loop-block
    events. Sorted by p99 so the slowest routes surface first."""
    with _LOCK:
        routes = []
        for key, r in _ROUTES.items():
            vals = sorted(r["durations"])
            routes.append(
                {
                    "route": key,
                    "count": r["count"],
                    "window_n": len(vals),
                    "p50_ms": _pct(vals, 50),
                    "p95_ms": _pct(vals, 95),
                    "p99_ms": _pct(vals, 99),
                    "max_ms": round(r["max_ms"], 1),
                    "statuses": dict(r["statuses"]),
                }
            )
        events = list(_EVENTS)
        in_flight_now = len(_INFLIGHT)
    routes.sort(key=lambda x: x["p99_ms"], reverse=True)
    return {
        "watchdog": {
            "running": _watchdog_started,
            "block_threshold_ms": _loop_block_ms(),
            "events": events[-50:],
            "events_captured": len(events),
        },
        "in_flight_now": in_flight_now,
        "routes": routes[:60],
        "method": (
            "Per-route latency percentiles over a recent-window reservoir + an event-loop "
            "watchdog that flags loop lag (heavy sync work on the async loop — the "
            "unlock/restore/task-manager freeze family). Route templates only, no bound "
            "values; read-only; no score."
        ),
    }
