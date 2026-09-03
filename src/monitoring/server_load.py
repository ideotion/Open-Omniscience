"""What the server can honestly say about its own load (S3.4, ruling 7).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Ruling 7 asks for BOTH ends under load: the server publishes an honest reading,
and the client backs off. This is the server half, and it rides
``/api/scheduler/status`` for the same reason ``online`` and ``machine_floor``
already do -- a load disclosure behind a poll the UI might never make is a
disclosure nobody reads.

It is a DISCLOSURE, not the client's trigger. The client backs off on what it
observes itself (its own latencies, and the 429/503 it was actually served),
because a server too loaded to answer cannot tell anyone it is loaded -- routing
the backoff through this payload would make it fail exactly when it is needed.

THREE INDEPENDENT READINGS, each from the subsystem that owns it:
  * ``loop_lag``   -- the event-loop watchdog's own samples (latest + window peak)
  * ``heavy``      -- the heavy-read admission guard's in-flight count and its cap
  * ``memory_guard`` -- whether the RSS guard has engaged

Each is wrapped separately so a subsystem that cannot answer degrades ALONE.
A failed section reports ``{"read": False, "reason": ...}``: "we could not read
it" and "we read it and it is quiet" are opposite facts, so they never share a
key or a value. Nothing here is a score, a blend, or a verdict -- three
measurements, published side by side, for a reader to judge.

No network, no database, no allocation beyond a small dict. Cheap enough to
recompute on the polled status rather than cache, which matters: a STALE load
reading is precisely the wrong thing on a server whose load is moving.
"""

from __future__ import annotations

import logging
from typing import Any

_LOG = logging.getLogger(__name__)


def _section(name: str, fn) -> dict[str, Any]:
    try:
        out = fn()
        out["read"] = True
        return out
    except Exception as exc:  # noqa: BLE001 - a load reading must never break a poll
        _LOG.debug("server_load: could not read %s", name, exc_info=True)
        return {"read": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}


def _loop_lag() -> dict[str, Any]:
    from src.monitoring.latency import loop_lag

    return dict(loop_lag())


def _heavy() -> dict[str, Any]:
    from src.api.heavy import status

    st = status()
    return {
        # in_flight_keys counts distinct heavy computes in flight -- which is what
        # the cap governs (identical concurrent requests share one flight), so it
        # is the number that reads against `cap`, not a request count.
        "in_flight": st.get("in_flight_keys"),
        "cap": st.get("cap"),
        "busy_refusals": (st.get("counters") or {}).get("busy"),
    }


def _memory_guard() -> dict[str, Any]:
    from src.scheduler import memguard

    # `engaged` is a PROPERTY, not a method: calling it returns a bool that is
    # then not callable. Caught by this module's own per-section degrade,
    # which reported the TypeError rather than a quiet "engaged: False".
    return {"engaged": bool(memguard.memory_guard.engaged)}


def server_load() -> dict[str, Any]:
    """A snapshot of the three load readings the server can honestly make."""
    return {
        "loop_lag": _section("loop_lag", _loop_lag),
        "heavy": _section("heavy", _heavy),
        "memory_guard": _section("memory_guard", _memory_guard),
        "method": (
            "Three independent measurements read at request time -- event-loop "
            "scheduling delay, heavy-read admission occupancy, and the RSS guard's "
            "engaged state. Not combined, not scored; a section that could not be "
            "read says so rather than reporting a quiet value."
        ),
    }
