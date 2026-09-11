"""Soak-window report — what the machine did over the window this process has been up.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. The 0.3 gate's row 7 asks for a multi-day collector soak, and the
0.4 board carries that forward as its own row. Nothing in the app could answer it
after the fact. ``collect_perf.jsonl`` is a 5,000-line ring that covers roughly one
pass, which is exactly why the 2026-07 multi-hour stalls were undiagnosable once they
had ended; the latency reservoir keeps the last 512 requests per route; the error log
is a rolling 2,000 records. Each of those is the right shape for its own job and none
of them is a window a soak can be read against.

So this member does not add a new sampler. It composes the durable readings that
already exist and states, for each one, THE WINDOW IT ACTUALLY READ:

- process uptime (``forensics.session_uptime``) is the soak's own clock;
- the memory-guard engage counters and the write-gate counters are
  process-cumulative, so they align with that clock exactly;
- ``wal_bytes`` is an AT-MOST-hourly snapshot with infinite retention, so it spans
  restarts (at most: the recorder rides the scheduler's off-peak window opportunistically
  and yields it whenever a collect pass owns the lock -- see C6, 2026-09-11)
  and is filtered back down to this window;
- the ``/api/database/stats`` p95 comes from a 512-request reservoir, so it is a
  reading about recent requests and NOT about the soak, and says so;
- the interrupted-statement count comes from a rolling log, so it is a FLOOR
  whenever that log is at capacity.

A member that quietly read a two-hour window and reported on a three-day soak would
be the fabricated-pass shape. Hence: every block carries ``measured``, its own
denominator, and a ``reason`` when it cannot speak. There is deliberately NO verdict
here — whether a soak passes is the maintainer's reading of these numbers, and a
composite would be exactly the score this project does not publish.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

_LOG = logging.getLogger(__name__)

# The bar the gate names. Reported as a property of the WINDOW ("is this window long
# enough to be read against the bar"), never as a verdict about the machine.
SOAK_BAR_HOURS = 72.0

# Below this much uptime a per-day rate is arithmetic noise, not a measurement: one
# engagement in the first ten seconds extrapolates to 8,640 a day, which would be a
# fabricated alarm. The COUNTS are still real and are published either way.
_RATE_FLOOR_S = 300.0

# The route whose p95 the gate row names.
_DB_STATS_ROUTE = "GET /api/database/stats"

# The read window handed to metric_history, clamped. Infinite retention is a storage
# property; the RESPONSE is always bounded.
_WAL_DAYS_MAX = 30
_WAL_DAYS_DEFAULT = 7


def _parse_ts(raw: Any) -> datetime | None:
    """Parse an ISO timestamp, treating a naive one as UTC.

    ``StatSnapshotRow.taken_at`` is stored naive-UTC (the hour bucket), while the
    session stamp is timezone-aware. Comparing the two without normalising raises,
    and a raise inside a diagnostic is a second failure layered on the first.
    """
    if not isinstance(raw, str) or not raw:
        return None
    try:
        got = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return got if got.tzinfo is not None else got.replace(tzinfo=UTC)


def _window(bar_hours: float) -> dict[str, Any]:
    """The soak's own clock: how long this process has been up, and whether that
    reaches the bar. ``reaches_bar`` is a fact about the WINDOW's length, not a
    judgement about what happened inside it."""
    from src.monitoring.forensics import session_uptime

    up = session_uptime()
    seconds = up.get("seconds")
    if not up.get("measured") or not isinstance(seconds, (int, float)):
        return {
            "measured": False,
            "basis": "process uptime",
            "started_at": up.get("started_at"),
            "seconds": None,
            "hours": None,
            "bar_hours": bar_hours,
            "reaches_bar": None,
            "reason": up.get("reason") or "process uptime is unavailable",
        }
    hours = seconds / 3600.0
    return {
        "measured": True,
        "basis": "process uptime",
        "started_at": up.get("started_at"),
        "seconds": round(float(seconds), 1),
        "hours": round(hours, 2),
        "bar_hours": bar_hours,
        "reaches_bar": hours >= bar_hours,
        "note": (
            "A restart ends the soak. Every process-cumulative counter below resets "
            "with it, which is why they can be read against this window and only this "
            "window."
        ),
    }


def _memory_guard(window: dict[str, Any]) -> dict[str, Any]:
    """Engage cycles and paused time over the window.

    Two separate ways this can fail to be a measurement, and they are not the same:
    the window may be unknown (no rate), or the guard may be BLIND — enabled with no
    psutil readings — in which case zero engagements says nothing at all about memory
    pressure and must not be read as "the machine was fine".
    """
    try:
        from src.scheduler import memguard

        state = memguard.memory_guard.state()
    except Exception as exc:  # noqa: BLE001 - a diagnostic read degrades, never raises
        _LOG.debug("memory-guard state unavailable", exc_info=True)
        return {"measured": False, "reason": f"memory-guard state unavailable: {exc}"}

    engagements = state.get("engagements")
    engaged_s = state.get("total_engaged_s")
    out: dict[str, Any] = {
        "enabled": state.get("enabled"),
        "engaged_now": state.get("engaged"),
        "engagements": engagements,
        "total_engaged_s": engaged_s,
        "readings_available": state.get("readings_available"),
        "counter_basis": (
            "process-cumulative; closed episodes only, so an episode still open is "
            "engaged_now and is not folded into total_engaged_s"
        ),
    }
    if state.get("enabled") and state.get("readings_available") is False:
        out["measured"] = False
        out["reason"] = (
            "the guard is enabled but has no memory readings (psutil is unavailable), "
            "so it is blind — its zero engagements are not evidence of low pressure"
        )
        return out
    seconds = window.get("seconds")
    if not window.get("measured") or not isinstance(seconds, (int, float)):
        out["measured"] = False
        out["reason"] = "the window is unknown, so a per-day rate has no denominator"
        return out
    if seconds < _RATE_FLOOR_S:
        out["measured"] = False
        out["reason"] = (
            f"uptime is {round(float(seconds), 1)} s, under the {int(_RATE_FLOOR_S)} s "
            "floor a per-day rate needs to mean anything"
        )
        return out
    days = float(seconds) / 86400.0
    out["measured"] = True
    out["window_days"] = round(days, 4)
    out["engagements_per_day"] = round(float(engagements or 0) / days, 2)
    out["paused_share"] = round(float(engaged_s or 0.0) / float(seconds), 4)
    return out


def _wal(session: Session, window: dict[str, Any]) -> dict[str, Any]:
    """The recorded ``wal_bytes`` maximum inside the window.

    The series has its OWN window — AT-MOST-hourly snapshots, infinite retention, spanning
    restarts — so the wider history is reported beside the in-window figure rather
    than being silently conflated with it.
    """
    seconds = window.get("seconds")
    if window.get("measured") and isinstance(seconds, (int, float)):
        days = max(1, min(_WAL_DAYS_MAX, math.ceil(float(seconds) / 86400.0) + 1))
    else:
        days = _WAL_DAYS_DEFAULT
    try:
        from src.database.snapshots import metric_history

        hist = metric_history(session, metric="wal_bytes", days=days)
    except Exception as exc:  # noqa: BLE001 - a diagnostic read degrades, never raises
        _LOG.debug("wal_bytes history unavailable", exc_info=True)
        return {"measured": False, "reason": f"wal_bytes history unavailable: {exc}"}
    if hist.get("error"):
        return {"measured": False, "reason": str(hist["error"])}

    series = hist.get("series") or []
    out: dict[str, Any] = {
        "recording_began_at": hist.get("recording_began_at"),
        "read_days": days,
        "series_points_read": len(series),
        "series_basis": (
            "snapshots bucketed by hour (AT MOST one per hour, and fewer when the "
            "recorder's off-peak window is yielded -- see scheduler maintenance_skips) "
            "with infinite retention; the series survives restarts, "
            "so it is wider than this process's window and is filtered to it below"
        ),
    }
    if not series:
        out["measured"] = False
        out["reason"] = (
            "no wal_bytes snapshot has been recorded in the read window"
            if hist.get("recording_began_at")
            else "wal_bytes has never been recorded on this install"
        )
        return out

    start = _parse_ts(window.get("started_at"))
    if not window.get("measured") or start is None:
        out["measured"] = False
        out["reason"] = "the window is unknown, so the series cannot be filtered to it"
        return out
    # The series is bucketed to the top of the hour, so a reading genuinely taken
    # inside this window carries a timestamp up to 59 minutes BEFORE the process
    # started. Widening the boundary to the containing hour keeps that reading rather
    # than dropping it -- under-reporting a WAL maximum is the dangerous direction for
    # a growth hazard -- and the widening is disclosed rather than assumed away.
    edge = start.replace(minute=0, second=0, microsecond=0)
    inside = []
    unreadable = 0
    for point in series:
        when = _parse_ts(point.get("t"))
        if when is None:
            # A point whose time cannot be read may not be attributed to this window --
            # its value could become the maximum, and a maximum attributed to the wrong
            # session is exactly the misattribution the filtering exists to prevent. It
            # is counted rather than dropped silently.
            unreadable += 1
            continue
        if when >= edge:
            inside.append(point)
    if unreadable:
        out["points_unreadable"] = unreadable
    if not inside:
        out["measured"] = False
        out["reason"] = (
            "no snapshot has been recorded since this process started; the "
            "series above is earlier history and describes other sessions"
        )
        return out
    values = []
    for point in inside:
        try:
            values.append(int(point["n"]))
        except (KeyError, TypeError, ValueError):
            # A malformed value is not a reading. Raising here would take the whole
            # report down over one row: a diagnostic degrades, it never 500s.
            unreadable += 1
    if unreadable:
        out["points_unreadable"] = unreadable
    if not values:
        out["measured"] = False
        out["reason"] = "the in-window snapshots carry no values"
        return out
    out["measured"] = True
    out["points_in_window"] = len(values)
    out["hours_in_window"] = window.get("hours")
    out["first_point_at"] = inside[0].get("t")
    out["last_point_at"] = inside[-1].get("t")
    out["max_bytes"] = max(values)
    out["min_bytes"] = min(values)
    out["boundary_note"] = (
        "the window boundary is widened to the top of the hour this process started "
        f"in ({edge.isoformat()}), because the series is bucketed hourly; the first "
        "point may therefore include readings from up to 59 minutes before the start"
    )
    return out


def _write_gate(window: dict[str, Any]) -> dict[str, Any]:
    """The share of the window the single-writer gate was held, and the contention
    beside it."""
    try:
        from src.database.writer import write_gate

        stats = write_gate.stats()
    except Exception as exc:  # noqa: BLE001 - a diagnostic read degrades, never raises
        _LOG.debug("write-gate stats unavailable", exc_info=True)
        return {"measured": False, "reason": f"write-gate stats unavailable: {exc}"}

    out: dict[str, Any] = {
        "grants": stats.get("grants"),
        "contended": stats.get("contended"),
        "total_held_s": stats.get("total_held_s"),
        "max_hold_s": stats.get("max_hold_s"),
        "max_hold_holder": stats.get("max_hold_holder"),
        "total_wait_s": stats.get("total_wait_s"),
        "max_wait_s": stats.get("max_wait_s"),
        "timeouts": stats.get("timeouts"),
        "held_now": stats.get("held"),
        "held_for_s": stats.get("held_for_s"),
        "counter_basis": (
            "process-cumulative; total_held_s is accumulated on release, so a hold in "
            "flight right now is in held_for_s and not in it"
        ),
        "wait_note": (
            "total_wait_s sums across waiters, so it can exceed wall time and is NOT "
            "divided by the window: it is aggregate waiting, not a share of it"
        ),
    }
    seconds = window.get("seconds")
    if not window.get("measured") or not isinstance(seconds, (int, float)) or seconds <= 0:
        out["measured"] = False
        out["reason"] = "the window is unknown, so a busy share has no denominator"
        return out
    held = stats.get("total_held_s")
    if not isinstance(held, (int, float)):
        out["measured"] = False
        out["reason"] = "the gate reports no accumulated hold time"
        return out
    out["measured"] = True
    # The gate is exclusive -- at most one holder at a time -- so held time is bounded
    # by wall time and this really is a share. That is why only this figure is divided.
    out["busy_share"] = round(float(held) / float(seconds), 4)
    if stats.get("grants"):
        out["contended_share_of_grants"] = round(
            float(stats.get("contended") or 0) / float(stats["grants"]), 4
        )
    return out


def _db_stats_latency() -> dict[str, Any]:
    """The ``/api/database/stats`` p95 — over the latency reservoir, which is a
    RECENT-REQUEST window and not the soak window."""
    try:
        from src.monitoring.latency import summary as _summary

        rows = (_summary() or {}).get("routes") or []
    except Exception as exc:  # noqa: BLE001 - a diagnostic read degrades, never raises
        _LOG.debug("latency summary unavailable", exc_info=True)
        return {"measured": False, "reason": f"latency summary unavailable: {exc}"}

    row = next((r for r in rows if r.get("route") == _DB_STATS_ROUTE), None)
    base: dict[str, Any] = {
        "route": _DB_STATS_ROUTE,
        "window_basis": (
            "the most recent requests to this route in this process (a bounded "
            "reservoir), NOT the soak window: a quiet route's p95 describes whenever "
            "it was last called"
        ),
    }
    if row is None:
        base["measured"] = False
        base["reason"] = "this route has not been called in this process"
        return base
    base.update(
        {
            "measured": True,
            "requests_total": row.get("count"),
            "window_n": row.get("window_n"),
            "p50_ms": row.get("p50_ms"),
            "p95_ms": row.get("p95_ms"),
            "p99_ms": row.get("p99_ms"),
            "max_ms": row.get("max_ms"),
        }
    )
    return base


def _interrupted() -> dict[str, Any]:
    """Statements aborted mid-flight during this session, with the retention that
    bounds the count."""
    try:
        from src.monitoring.errorlog import summary as _errsummary

        summ = _errsummary() or {}
    except Exception as exc:  # noqa: BLE001 - a diagnostic read degrades, never raises
        _LOG.debug("error-log summary unavailable", exc_info=True)
        return {"measured": False, "reason": f"error-log summary unavailable: {exc}"}

    records = summ.get("records")
    cap = summ.get("records_cap")
    at_capacity = bool(
        isinstance(records, int) and isinstance(cap, int) and cap > 0 and records >= cap
    )
    out: dict[str, Any] = {
        "measured": True,
        "this_session": summ.get("interrupted_errors_this_session"),
        "total_in_log": summ.get("interrupted_errors_total"),
        "log_records": records,
        "log_records_cap": cap,
        "at_capacity": at_capacity,
        "counter_basis": (
            "counted over a rolling log of the newest records; a session boundary is "
            "only recognised once a boot marker exists in it"
        ),
    }
    if at_capacity:
        out["floor_note"] = (
            "the log is at its retention cap, so older records have been trimmed and "
            "these counts are a floor, not a census"
        )
    if not summ.get("last_session_started_at"):
        out["session_note"] = (
            "no boot marker is present in the log, so nothing is attributed to this "
            "session; read total_in_log instead"
        )
    return out


def _block(name: str, fn: Any) -> dict[str, Any]:
    """Run one block, and turn a crash into an honest absence.

    The sentinel deliberately does NOT reuse ``reason`` alone: "we read this and there was
    nothing there" and "this block itself broke" are opposite facts, and collapsing them is
    how a degrade wrapper becomes the hiding place for the bug it survives (the recorded
    ``section_ok`` lesson). ``block_error`` is present only in the second case.
    """
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - a diagnostic degrades, never 500s
        _LOG.debug("soak-window block %s failed", name, exc_info=True)
        return {
            "measured": False,
            "block_error": f"{type(exc).__name__}: {exc}",
            "reason": f"the {name} block could not be computed -- this is not a reading of zero",
        }


def soak_window(session: Session, *, bar_hours: float = SOAK_BAR_HOURS) -> dict[str, Any]:
    """The soak report: five readings, each with its own window and denominator.

    Deliberately verdict-free. ``window.reaches_bar`` says whether the window is long
    enough to be read against the gate's bar; what the numbers inside it mean is the
    maintainer's call, and a composite would be a score this project does not publish.
    """
    window = _block("window", lambda: _window(bar_hours))
    blocks: dict[str, Any] = {
        "memory_guard": _block("memory_guard", lambda: _memory_guard(window)),
        "wal": _block("wal", lambda: _wal(session, window)),
        "write_gate": _block("write_gate", lambda: _write_gate(window)),
        "database_stats_latency": _block("database_stats_latency", _db_stats_latency),
        "interrupted": _block("interrupted", _interrupted),
    }
    unmeasured = sorted(k for k, v in blocks.items() if not v.get("measured"))
    return {
        "window": window,
        **blocks,
        # Named so a reader does not have to walk five blocks to find the gaps. A
        # list of absences, never a verdict about what the present numbers mean.
        "unmeasured": unmeasured,
        "method": (
            "Composes readings that already exist: process uptime (the soak clock), "
            "the memory-guard and write-gate process-cumulative counters, the at-most-hourly "
            "wal_bytes snapshot series filtered to this window, the "
            f"{_DB_STATS_ROUTE} latency reservoir, and the rolling error log. No new "
            "sampler, no estimate, no composite."
        ),
        "caveat": (
            "Each block reports the window it actually read, and they differ. A "
            "restart ends the soak and resets the cumulative counters. A block listed "
            "in unmeasured has no reading here — that is not the same as a reading of "
            "zero."
        ),
    }
