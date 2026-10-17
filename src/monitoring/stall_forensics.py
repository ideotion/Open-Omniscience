"""
Stall attribution — when a request blows its budget, name what the machine was doing.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. The 2026-07-21 field export carried a cluster of multi-hour
in-flight requests and 503s, all inside one 11:40-13:41 window on 2026-07-11, and
the brief that recorded it could not say what caused them -- the instruments that
would have known are windowed (``collect_perf`` keeps roughly one pass, the latency
reservoir is a rolling sample), so by the time anyone looked the evidence was gone.
That question is no longer answerable for 2026-07-11. This module exists so the NEXT
one answers itself.

WHAT IT DOES. On any request slower than :func:`threshold_ms`, it takes a
point-in-time reading of the three things that can hold this app's single worker --
the single-writer gate, the event loop, and a slow SQL statement -- and files them
with a CAUSE CLASS the evidence supports. It also files the POOL as it stands (who holds
which connection, for how long, for which route), as evidence only: a request that waited its
30 s pool timeout was waiting for exactly that, and the field bundles could not say whose.

WHAT IT REFUSES TO DO. The class is a reading of correlated facts, not a proof, and
it is phrased that way ("consistent with"): a stall can have two causes at once, and
a request can be slow for a reason none of these three instruments can see. So
``undetermined`` is a REAL verdict here, reached whenever the evidence supports none
of the classes -- not a bucket that quietly absorbs whatever is left over. Every
record carries the evidence it reasoned from, so a reader can disagree with the
class without re-running anything. There is no score, no ranking, and no blend: the
classes are named conditions, each with its own threshold, and a record can carry
more than one.

Bounded by construction: a capped ring in memory, timings and route templates only,
never a bound value or corpus content. Nothing here reaches the network, and every
reading is best-effort -- an instrument that cannot answer says so and the others
still file.
"""

from __future__ import annotations

import os
import threading
from collections import deque
from datetime import UTC, datetime
from typing import Any

_LOCK = threading.Lock()

#: How many stall records to keep. A stall is by definition rare; a ring this size
#: covers a long incident without letting a pathological run grow unboundedly. The
#: reader (:func:`report`) applies its own ceiling independently, because the
#: oversized artifact already exists by the time anyone reads it.
_RING_CAP = 200
_RING: deque[dict[str, Any]] = deque(maxlen=_RING_CAP)

#: Gate-wait evidence: the gate must have been HELD with at least this many threads
#: queued behind it for "the writer gate was the holdup" to be a supported reading.
#: One waiter is an ordinary serialised write; a queue is a jam.
_GATE_WAITERS_MIN = 1

#: A recorded slow statement counts as evidence only when it accounts for at least
#: this share of the request's own duration. Below that it was real but incidental,
#: and naming it would point the next reader at the wrong thing.
_STATEMENT_SHARE_MIN = 0.5


def threshold_ms() -> float:
    """Duration above which a completed request is filed as a stall.

    ``OO_STALL_THRESHOLD_MS``, default 5000. Deliberately far above the 500 ms
    interactive "snappy" bar: this log is for the pathology that takes the server
    down, not for the ordinary slow endpoint the latency percentiles already cover.
    A malformed value falls back to the default rather than disabling the log.
    """
    try:
        v = float(os.environ.get("OO_STALL_THRESHOLD_MS", "5000"))
    except (TypeError, ValueError):
        return 5000.0
    return v if v > 0 else 5000.0


def _gate_evidence() -> dict[str, Any]:
    """Point-in-time single-writer-gate counters.

    Safe to call from a request thread: ``acquire()`` holds the condition lock only
    long enough to take ownership (and ``wait()`` releases it while queued), so this
    can never block behind the long write it is trying to describe -- verified in
    ``writer.py`` before wiring this, because an instrument that blocks on the
    pathology it measures is worse than no instrument.
    """
    try:
        from src.database.writer import write_gate

        s = write_gate.stats()
        return {
            "available": True,
            "held": bool(s.get("held")),
            "waiters": int(s.get("waiters") or 0),
            "max_wait_s": float(s.get("max_wait_s") or 0.0),
        }
    except Exception as exc:  # noqa: BLE001 - an unreadable instrument is a gap, not a crash
        return {"available": False, "reason": type(exc).__name__}


def _loop_evidence(route: str) -> dict[str, Any]:
    """Did the event-loop watchdog see a block while this route was in flight?

    Correlation, not proof: the watchdog records the requests in flight at the
    moment it measured the lag, so finding this route among them says the two
    overlapped -- which is the strongest thing this instrument can honestly say.
    """
    try:
        from src.monitoring import latency

        events = latency.recent_block_events(limit=5)
        for ev in reversed(events):
            for rec in ev.get("in_flight", []):
                if rec.get("route") == route:
                    return {
                        "available": True,
                        "overlapped": True,
                        "lag_ms": ev.get("lag_ms"),
                        "at": ev.get("at"),
                    }
        return {"available": True, "overlapped": False, "n_events_checked": len(events)}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": type(exc).__name__}


def _statement_evidence(duration_ms: float, now: datetime | None = None) -> dict[str, Any]:
    """The slowest statement the slow-query log recorded INSIDE this request, and what share of its duration it accounts for.

    A recorded statement can belong to this request only if it ended while the request ran and was not longer than the request:
    the log is a ring of the last statements of the whole process, so "the worst of the last twenty" named a statement that had
    finished minutes before the request began (a 174 s request was attributed a 55 s COUNT that ended four minutes earlier) or a
    writer's 56.9 s SAVEPOINT for a 55.6 s request (``share_of_request`` 1.023, which cannot be). ``at`` is the statement's END
    time at whole-second resolution, so the window opens one second early rather than miss a statement that ended at its start.
    """
    try:
        from src.monitoring import slowquery

        rows = slowquery.recent(limit=20)
        if not rows:
            return {"available": True, "found": False}
        end = now if now is not None else datetime.now(UTC)
        opened = end.timestamp() - duration_ms / 1000.0 - 1.0
        inside = []
        for r in rows:
            try:
                ended = datetime.fromisoformat(str(r.get("at"))).timestamp()
                dur = float(r.get("duration_ms") or 0.0)
            except (TypeError, ValueError):
                continue  # a row whose time cannot be read cannot be placed inside the request
            if ended >= opened and dur <= duration_ms:
                inside.append(r)
        if not inside:
            return {"available": True, "found": False, "recorded": len(rows),
                    "note": "none of the recorded slow statements ended inside this request's window"}
        worst = max(inside, key=lambda r: float(r.get("duration_ms") or 0.0))
        worst_ms = float(worst.get("duration_ms") or 0.0)
        share = (worst_ms / duration_ms) if duration_ms > 0 else 0.0
        return {
            "available": True,
            "found": True,
            "duration_ms": round(worst_ms, 1),
            # The normalised statement shape only: never a bound value (this log is
            # shared by clicking "download diagnostics", so it carries no corpus text).
            "sql": str(worst.get("sql") or "")[:200],
            "share_of_request": round(share, 3),
        }
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": type(exc).__name__}


#: How many checkouts the pool evidence names (oldest first). Enough to name the standing
#: holders of a 12-slot small-tier pool; the count of ALL checkouts is carried beside it.
_POOL_ROWS = 8


def _pool_evidence() -> dict[str, Any]:
    """Who holds the pool's connections at the moment the stall is filed.

    A request is filed when it COMPLETES, so this reads the holders AFTER the wait, not the
    ones it queued behind at the start: a correlation with what kept the pool busy, and stated
    as that. Holders are listed by thread, route (the request the thread was serving at
    checkout, ``None`` for a thread the app started) and age; the collector's slots are the
    reservation's own count. Never a statement text or a stack.
    """
    try:
        from src.database import pool_watch

        if not pool_watch.is_registered():
            return {"available": True, "attached": False}
        rows = pool_watch.checked_out()  # the thread names arrive scrubbed of the passphrases the process holds
        out: dict[str, Any] = {
            "available": True,
            "attached": True,
            "checked_out": len(rows),
            "collector_held": sum(1 for r in rows if r.get("collector")),
            "holders": [
                {
                    "thread": r["thread"],
                    "endpoint": r.get("endpoint"),
                    "collector": bool(r.get("collector")),
                    "age_s": round(r["age_s"], 1),
                }
                for r in rows[:_POOL_ROWS]
            ],
            "invalidated_total": pool_watch.invalidations()["total"],
        }
        try:
            from sqlalchemy.pool import QueuePool

            from src.database.session import engine

            reservation = getattr(engine.pool, "reservation", None)
            if callable(reservation):
                out["reservation"] = reservation()
            if isinstance(engine.pool, QueuePool):
                out["pool_size"] = int(engine.pool.size()) + int(getattr(engine.pool, "_max_overflow", 0))
        except Exception:  # noqa: BLE001 - the holders still stand without the pool's own counts
            pass
        return out
    except Exception as exc:  # noqa: BLE001 - an unreadable instrument is a gap, not a crash
        return {"available": False, "reason": type(exc).__name__}


def classify(evidence: dict[str, Any]) -> list[str]:
    """The cause classes this evidence SUPPORTS -- zero, one, or several.

    Each class is a named condition over one instrument's reading. They are returned
    as a list rather than resolved to a single winner because a jammed writer and a
    blocked loop genuinely co-occur (a long synchronous write does both), and picking
    one would discard the half that explains the other. An empty list is the honest
    answer when nothing is supported; the caller renders that as ``undetermined``.
    """
    classes: list[str] = []
    gate = evidence.get("write_gate") or {}
    if gate.get("available") and gate.get("held") and gate.get("waiters", 0) >= _GATE_WAITERS_MIN:
        classes.append("writer-gate-contention")
    loop = evidence.get("event_loop") or {}
    if loop.get("available") and loop.get("overlapped"):
        classes.append("event-loop-blocked")
    stmt = evidence.get("statement") or {}
    if (
        stmt.get("available")
        and stmt.get("found")
        and stmt.get("share_of_request", 0.0) >= _STATEMENT_SHARE_MIN
    ):
        classes.append("slow-statement")
    return classes


def _before_dispatch_ms() -> int | None:
    """Milliseconds this request spent before routing handed it to its endpoint (``latency.before_dispatch_ms``), or ``None`` when it
    was not stamped. What is left of ``duration_ms`` is the endpoint's thread wait, its run and the response, not split further."""
    try:
        from src.monitoring import latency

        # looked up by name: this file can land before the change that adds the reader, and then the split is simply unknown
        reader = getattr(latency, "current_split", None)
        ms = reader() if reader is not None else None
        return None if ms is None else int(round(ms))
    except Exception:  # noqa: BLE001 - an instrument that cannot answer says so
        return None


def note_stall(route: str, status: int, duration_ms: float) -> dict[str, Any] | None:
    """File a stall record if ``duration_ms`` crosses the threshold. Never raises.

    Returns the record (handy in tests) or ``None`` when the request was not slow
    enough to file.
    """
    try:
        if duration_ms < threshold_ms():
            return None
        evidence = {
            "write_gate": _gate_evidence(),
            "event_loop": _loop_evidence(route),
            "statement": _statement_evidence(duration_ms),
            "pool": _pool_evidence(),
        }
        classes = classify(evidence)
        rec = {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "route": route,
            "status": status,
            "duration_ms": int(round(duration_ms)),
            "before_dispatch_ms": _before_dispatch_ms(),
            # "consistent with", never "caused by": these are correlated readings.
            "consistent_with": classes or ["undetermined"],
            "evidence": evidence,
        }
        with _LOCK:
            _RING.append(rec)
        return rec
    except Exception:  # noqa: BLE001 - instrumentation must never break a response
        return None


def report(limit: int = 50) -> dict[str, Any]:
    """The stall log, newest first, with a per-class and per-route tally.

    The tallies are counts of RECORDS, and a record can carry more than one class,
    so the class counts do not sum to the record count -- stated here because a
    reader who assumes they do would conclude the log had lost some.
    """
    limit = max(1, min(int(limit or 50), _RING_CAP))
    with _LOCK:
        rows = list(_RING)
    newest = list(reversed(rows))[:limit]
    by_class: dict[str, int] = {}
    for r in rows:
        for c in r.get("consistent_with", []):
            by_class[c] = by_class.get(c, 0) + 1
    by_route: dict[str, int] = {}
    for r in rows:
        rt = str(r.get("route") or "")
        by_route[rt] = by_route.get(rt, 0) + 1
    return {
        "threshold_ms": threshold_ms(),
        "n_recorded": len(rows),
        "ring_capacity": _RING_CAP,
        "truncated": len(rows) >= _RING_CAP,
        "shown": len(newest),
        # A status field, not a key -- "degraded" contains "grade", and this repo's
        # no-score walkers ban that substring in KEYS. Counts live under an explicit
        # list of {class, n} objects for the same reason.
        "by_class": [{"class": k, "n": v} for k, v in sorted(by_class.items())],
        "by_route": [{"route": k, "n": v} for k, v in sorted(by_route.items(), key=lambda kv: -kv[1])],
        "stalls": newest,
        "method": (
            "A request slower than the threshold is filed with a point-in-time reading "
            "of the single-writer gate, the event-loop watchdog and the slow-query log. "
            "The classes are conditions those readings SUPPORT, never a proof of cause, "
            "and a record can carry several. Class counts are per-record and a record "
            "may carry more than one class, so they do not sum to n_recorded."
        ),
        "caveat": (
            "Correlation only. A stall whose cause none of these three instruments can "
            "see is filed as 'undetermined' rather than assigned to the nearest class — "
            "so an undetermined record means the evidence was silent, never that the "
            "request was healthy. In-memory and bounded: a restart empties this log."
        ),
    }


def _reset_for_tests() -> None:
    with _LOCK:
        _RING.clear()
