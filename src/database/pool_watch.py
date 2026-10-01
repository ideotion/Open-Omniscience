"""
S2.6 (b): which thread is holding a pooled connection, and for how long.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The write gate names whoever is inside the WRITE window (src/database/writer.py).
It cannot name a thread that is merely holding a checked-out connection -- and
that is the thread that pins the WAL: an open read transaction stops
``PRAGMA wal_checkpoint(TRUNCATE)`` from reclaiming anything, which is how the
field's WAL reached three hours of growth with the gate free the whole time.

So: a checkout/checkin/detach trio, recording ONLY ``{thread, ident, endpoint, checkout_at}``
per live connection. Three properties are load-bearing.

* It records at CHECKOUT and forgets at CHECKIN, so a RETURNED connection is
  never listed. An instrument that keeps naming an innocent thread after it has
  handed the connection back is worse than no instrument: every reading would
  accuse whoever ran last.
* It stores no statement text and no stack by default -- this is on the pool's hot path.
  The age and the ENDPOINT identify a pinner (the endpoint is the route the request
  was serving at checkout, read from a ContextVar the request middleware sets, so a
  thread-pool worker names the route that took the connection, not just "AnyIO worker
  thread"); :func:`stacks_for` takes a stack for the named thread ON DEMAND (the storage
  guard asks for it when a WAL will not reset), and ``OO_POOL_WATCH_STACKS=1`` records
  the stack AT checkout for a diagnosis session that needs the line that took it.
* It is keyed on the pool's connection RECORD and re-verified at read time, so a
  connection SQLAlchemy invalidated or detached can never linger as an immortal
  "oldest checkout" (see ``_LIVE``).

``checked_out()`` is a point-in-time copy, oldest first, so the top row of the
diagnostics member is the candidate WAL pinner.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import os
import threading
import time
import weakref
from collections import deque
from datetime import UTC, datetime
from typing import Any

_LOG = logging.getLogger(__name__)

# The route the current request is serving, set by the request middleware BEFORE it
# calls the endpoint. Starlette runs the endpoint in a task created after the set and
# anyio's ``run_sync`` copies the context into the worker thread, so a checkout taken
# by a thread-pool worker reads the route it is working for. Threads the app starts
# itself (collector, briefing, rollups) carry no request and read ``None`` -- their
# thread NAME is the identifier there.
_ENDPOINT: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "oo_pool_endpoint", default=None
)


def set_endpoint(label: str | None) -> contextvars.Token:
    """Name the request this context is serving; returns the token for :func:`reset_endpoint`."""
    return _ENDPOINT.set(label)


def reset_endpoint(token: contextvars.Token) -> None:
    with contextlib.suppress(ValueError):  # a token from another context: leave it, never raise
        _ENDPOINT.reset(token)

# keyed by id(connection RECORD), never by id(dbapi_connection). SQLAlchemy clears
# ``record.dbapi_connection`` BEFORE it fires ``checkin`` when a connection is
# invalidated (a failed rollback on return, ``invalidate()``, a disconnect) and a
# DETACHED connection never checks in at all, so a table keyed on the DBAPI object
# misses both and keeps the row forever -- an immortal "oldest checkout" that every
# WAL diagnosis then names as the pinner (reproduced against SQLAlchemy 2.1.1; the
# same hole ``pool_reserve.py`` documents for its slot table). The record is the one
# object ``checkout``, ``checkin``, ``detach`` and ``invalidate`` are all handed.
_LIVE: dict[int, dict[str, Any]] = {}
# Re-entrant: a fairy collected by the garbage collector fires its ``checkin`` on whatever
# thread the collector interrupted, which may already hold this lock (a read pruning rows,
# say). A plain Lock would deadlock that thread; the table is never iterated live for the
# same reason (see ``checked_out``).
_LOCK = threading.RLock()
_REGISTERED = False
# The last connections the POOL invalidated (a failed rollback on return, an explicit
# ``invalidate()``, a disconnect): who held it, which route, and what the DBAPI said. The
# phantom rows above were the false positive; this is the open question behind them -- what
# invalidates a connection in production -- so the next bundle can answer it. Bounded,
# in-memory, and carries the DBAPI exception's own message only (never a statement or a
# bound parameter).
_INVALIDATIONS: deque[dict[str, Any]] = deque(maxlen=20)
_INVALIDATED = 0
# Rows dropped at READ time because their record no longer shows a checkout. Mostly the
# phantoms the event keys above could not prevent (a listener attached late, an id reused
# after a record was collected), but SQLAlchemy clears ``fairy_ref`` just BEFORE it fires
# ``checkin``, so a read in that instant also counts a legitimate return (its checkin then
# finds the row gone, harmlessly). A reading of how often the read path had to tidy, never a
# count of phantoms and never a control input.
_PRUNED = 0


def _is_collector() -> bool:
    """Whether the current thread holds the collector role (the D44 reservation's own mark)."""
    try:
        from src.database.pool_reserve import in_collector_role

        return bool(in_collector_role())
    except Exception:  # noqa: BLE001 - an instrument must never break a checkout
        return False


def _on_checkout(dbapi_connection, connection_record, _connection_proxy) -> None:
    # On the pool's hot path: an instrument must never be the reason a checkout fails.
    try:
        thread = threading.current_thread()
        try:
            ref: Any = weakref.ref(connection_record)
        except TypeError:  # a pool record that cannot be weak-referenced: keep the row unverifiable
            ref = None
        row: dict[str, Any] = {
            "thread": thread.name,
            "ident": thread.ident,
            "endpoint": _ENDPOINT.get(),
            "collector": _is_collector(),
            "checkout_at": time.monotonic(),
            "record": ref,
        }
        if os.environ.get("OO_POOL_WATCH_STACKS") == "1":
            import traceback

            row["stack"] = [
                f"{fs.filename}:{fs.lineno} {fs.name}" for fs in traceback.extract_stack()[-14:-1]
            ]
        with _LOCK:
            _LIVE[id(connection_record)] = row
    except Exception:  # noqa: BLE001
        pass


def _on_checkin(dbapi_connection, connection_record) -> None:
    with _LOCK:
        _LIVE.pop(id(connection_record), None)


def _on_detach(dbapi_connection, connection_record) -> None:
    # A detached connection leaves the pool for good and never reaches ``checkin``.
    with _LOCK:
        _LIVE.pop(id(connection_record), None)


def _on_invalidate(dbapi_connection, connection_record, exception) -> None:
    """Record WHAT invalidated a connection and who was holding it. Never raises."""
    global _INVALIDATED
    try:
        thread = threading.current_thread()
        with _LOCK:
            live = _LIVE.get(id(connection_record)) or {}
            held_by = {
                "thread": live.get("thread"),
                "endpoint": live.get("endpoint"),
                "age_s": round(time.monotonic() - live["checkout_at"], 3) if live else None,
            }
            orig = getattr(exception, "orig", exception)
            rec = {
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
                "by_thread": thread.name,
                "held_by": held_by,
                "exception": type(orig).__name__ if orig is not None else None,
                # The DBAPI's own message, trimmed: SQLAlchemy's wrapper carries the SQL
                # text and its parameters, which this record never keeps.
                "message": str(orig)[:160] if orig is not None else None,
            }
            _INVALIDATIONS.append(rec)
            _INVALIDATED += 1
        _LOG.warning(
            "pool connection invalidated: held by %s (route %s), %s: %s",
            held_by["thread"],
            held_by["endpoint"],
            rec["exception"],
            rec["message"],
        )
    except Exception:  # noqa: BLE001 - an instrument must never break the pool
        pass


def _still_out(rec: dict[str, Any]) -> bool:
    """Whether the recorded checkout is still a live one.

    ``fairy_ref`` is set at checkout and cleared at checkin, so a record that is gone
    (collected) or no longer has one is not a checkout, whatever the table remembers.
    A SQLAlchemy without the attribute is believed rather than pruned: an unverifiable
    row is kept, never silently dropped.
    """
    ref = rec.get("record")
    target = ref() if ref is not None else None
    if ref is not None and target is None:
        return False
    return getattr(target, "fairy_ref", True) is not None


def checked_out() -> list[dict[str, Any]]:
    """Live checkouts, OLDEST FIRST. Empty when nothing is checked out.

    Each row is ``{thread, ident, endpoint, age_s}``; ``endpoint`` is the route the request
    was serving at checkout (``None`` for a thread the app started itself), and ``ident``
    lets a caller ask for that thread's stack on demand (:func:`stacks_for`) without this
    module storing one (``stack_at_checkout`` appears only under ``OO_POOL_WATCH_STACKS=1``).
    """
    global _PRUNED
    now = time.monotonic()
    with _LOCK:
        # Snapshots, never the live dict: a collected fairy's checkin can pop a row from
        # inside this block (the lock is re-entrant).
        dead = [k for k, rec in list(_LIVE.items()) if not _still_out(rec)]
        for k in dead:
            _LIVE.pop(k, None)
        _PRUNED += len(dead)
        rows = []
        for rec in list(_LIVE.values()):
            row = {
                "thread": rec["thread"],
                "ident": rec["ident"],
                "endpoint": rec.get("endpoint"),
                "collector": bool(rec.get("collector")),
                "age_s": round(now - rec["checkout_at"], 3),
            }
            if rec.get("stack"):
                row["stack_at_checkout"] = list(rec["stack"])
            rows.append(row)
    rows.sort(key=lambda r: r["age_s"], reverse=True)
    return rows


#: A checkout older than this is a STANDING consumer of a pool slot, not a request or a step in
#: flight. It protects the reading's meaning: a healthy request finishes in well under the
#: pool's own 30 s checkout timeout, so a hold of twice that has already cost another thread
#: a 500 (the field's activity-poll timeouts), and anything younger is ordinary traffic that
#: would make the count flicker with every poll.
STANDING_AGE_S = 60.0


def standing_holders(min_age_s: float = STANDING_AGE_S) -> int | None:
    """How many pooled connections the APP's own threads (not the collector, whose slots the
    D44 reservation already counts) have held for at least ``min_age_s``.

    ``None`` when the instrument is not attached: "nothing is held" and "nobody is watching"
    are opposite facts, and a caller must be able to tell them apart.
    """
    if not _REGISTERED:
        return None
    return sum(1 for r in checked_out() if not r["collector"] and r["age_s"] >= min_age_s)


def invalidations() -> dict[str, Any]:
    """The last pool invalidations (newest last) and the total since start."""
    with _LOCK:
        return {"total": _INVALIDATED, "recent": list(_INVALIDATIONS)}


def pruned_total() -> int:
    """How many rows reads have pruned since the process started (phantoms, plus the odd
    return caught between SQLAlchemy clearing the record and firing ``checkin``)."""
    with _LOCK:
        return _PRUNED


#: Frames per stack by default; the storage guard's ``PIN_STACK_DEPTH`` is the same number
#: (a test pins that), so the one report and the one on-demand capture agree.
STACK_DEPTH = 12


def stacks_for(idents: list[int], *, depth: int = STACK_DEPTH) -> dict[int, list[str]]:
    """The current stack of each named thread, innermost last, trimmed to ``depth``.

    On demand only (a WAL that will not reset, a pool that timed out): a stack taken at
    checkout would be instrumentation on the pool's hot path, and a stack taken later
    at checkin-time would show an idle worker. A thread that has exited simply has no
    entry. Never raises.
    """
    import sys
    import traceback

    out: dict[int, list[str]] = {}
    try:
        frames = sys._current_frames()
        for ident in idents:
            frame = frames.get(ident)
            if frame is None:
                continue
            lines = [
                f"{fs.filename}:{fs.lineno} {fs.name}"
                for fs in traceback.extract_stack(frame)[-max(1, depth):]
            ]
            out[ident] = lines
    except Exception:  # noqa: BLE001 - an instrument must never raise
        return out
    return out


def is_registered() -> bool:
    """Whether the listeners are attached.

    Load-bearing for any consumer of :func:`checked_out`: an UNATTACHED instrument
    also returns an empty list, and "nothing is checked out" and "nobody is
    watching" are opposite facts. A reader that cannot tell them apart publishes a
    clean bill of health for an instrument that is not running.
    """
    return _REGISTERED


def register(engine) -> bool:
    """Attach the listeners to ``engine``'s pool. Idempotent per engine; never raises.

    More than one engine may be watched (the corpus engine and the read-snapshot engines
    whose streamed reads hold a WAL snapshot); ``checked_out()`` lists them together.
    """
    global _REGISTERED
    try:
        from sqlalchemy import event

        if event.contains(engine, "checkout", _on_checkout):
            return False
        event.listen(engine, "checkout", _on_checkout)
        event.listen(engine, "checkin", _on_checkin)
        event.listen(engine, "detach", _on_detach)
        event.listen(engine, "invalidate", _on_invalidate)
        _REGISTERED = True
        return True
    except Exception:  # noqa: BLE001 - an instrument must never break a boot
        return False


def _reset_for_tests() -> None:
    """Test-only: forget every recorded checkout (the listeners stay attached)."""
    global _PRUNED, _INVALIDATED
    with _LOCK:
        _LIVE.clear()
        _PRUNED = 0
        _INVALIDATED = 0
        _INVALIDATIONS.clear()
