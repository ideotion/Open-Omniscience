"""
S2.6 (b): which thread is holding a pooled connection, and for how long.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The write gate names whoever is inside the WRITE window (src/database/writer.py).
It cannot name a thread that is merely holding a checked-out connection -- and
that thread is a CANDIDATE for the one that pins the WAL: a statement or a cursor still running
on the connection, an uncommitted write, or (on the ``read_snapshot`` pool) a snapshot held from
the first read, stops ``PRAGMA wal_checkpoint(TRUNCATE)`` from reclaiming anything, which is how
the field's WAL reached three hours of growth with the gate free the whole time. A plain read on
the corpus pool starts no transaction in the driver's legacy mode, so a listed checkout there is
a candidate, never a measured holder.

So: a checkout/checkin/detach trio, recording per live connection ``{thread, ident, endpoint,
collector, pool, checkout_at}`` and a weak reference to its record (to re-verify it at read time),
and nothing else. Three properties are load-bearing.

* It records at CHECKOUT and forgets at CHECKIN, so a RETURNED connection is
  never listed. An instrument that keeps naming an innocent thread after it has
  handed the connection back is worse than no instrument: every reading would
  accuse whoever ran last.
* It stores no statement text and no stack by default -- this is on the pool's hot path.
  The age and the ENDPOINT identify a candidate (the endpoint is the route the request
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
_ENDPOINT: contextvars.ContextVar[tuple[str, str | None, Any] | None] = contextvars.ContextVar(
    "oo_pool_endpoint", default=None
)


def set_endpoint(
    label: str | None, *, method: str | None = None, scope: Any = None
) -> contextvars.Token:
    """Name the request this context is serving; returns the token for :func:`reset_endpoint`.

    ``label`` is the raw "METHOD /path" the middleware knows before routing. The route TEMPLATE
    ("GET /api/articles/{id}/view") is only known once routing has run, which is after this set,
    so the request's ASGI ``scope`` (the dict routing fills in, shared with the endpoint's
    context) is kept with the ``method`` and the template is read from it at checkout. Without it
    the label stays the raw path, which would carry an article id or an edition's file name into
    the bundle, where the latency log keys on the template."""
    return _ENDPOINT.set(None if label is None else (label, method, scope))


def _endpoint_label() -> str | None:
    cur = _ENDPOINT.get()
    if cur is None:
        return None
    label, method, scope = cur
    try:
        if scope is not None and method:
            template = getattr(scope.get("route"), "path", None)
            if isinstance(template, str) and template:
                return f"{method} {template}"
    except Exception:  # noqa: BLE001 - an instrument must never break a checkout
        pass
    return label


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
# Which pool a checkout came from: ``id(pool) -> (weak reference to it, label)``. The corpus pool
# is the one whose slots the D44 reservation counts; the read-snapshot engines (a streamed
# export's read, a NullPool of their own) are watched too but are not slots of it. A pool nobody
# labelled reads as "corpus", the app's own.
_POOL_LABELS: dict[int, tuple[Any, str]] = {}
# The last connections the POOL invalidated (a failed rollback on return, an explicit
# ``invalidate()``, a disconnect): who held it, which route, and what the DBAPI said. The
# phantom rows above were the false positive; this is the open question behind them -- what
# invalidates a connection in production -- so the next bundle can answer it. Bounded,
# in-memory, and carries the DBAPI exception's own message only (never a statement or a
# bound parameter). Twenty because the question it answers is "what invalidates connections",
# which a handful of recent, named examples answers and a longer list repeats; the TOTAL keeps
# counting past it, so an incident's size is never read off the ring's length.
_INVALIDATIONS: deque[dict[str, Any]] = deque(maxlen=20)
_INVALIDATED = 0
#: At most one WARNING line per this many seconds (the ring above keeps the last 20 and the
#: total counts every one): a disk incident can invalidate a connection on every checkin, and an unthrottled line
#: per invalidation would fill the 2,000-record error ring the diagnostics bundle carries.
INVALIDATION_LOG_EVERY_S = 30.0
_INVAL_LOGGED_AT: float | None = None
_INVAL_SUPPRESSED = 0
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


def _pool_label(proxy: Any) -> str:
    """The label ``register`` gave the pool a checkout came from ("corpus" when unlabelled)."""
    try:
        pool = getattr(proxy, "_pool", None)
        ent = _POOL_LABELS.get(id(pool))
        if ent is not None and ent[0]() is pool:
            return ent[1]
    except Exception:  # noqa: BLE001 - an instrument must never break a checkout
        pass
    return "corpus"


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
            "endpoint": _endpoint_label(),
            "collector": _is_collector(),
            "pool": _pool_label(_connection_proxy),
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
    global _INVALIDATED, _INVAL_LOGGED_AT, _INVAL_SUPPRESSED
    try:
        thread = threading.current_thread()
        # Everything that runs foreign code (``str()`` of an exception) happens BEFORE the lock
        # is taken: a ``__str__`` that raises used to lose the invalidation altogether (4 of 6
        # hostile inputs in the coordinator's check), and one that is slow held the table.
        orig = getattr(exception, "orig", exception)
        try:
            message = str(orig)[:160] if orig is not None else None
        except Exception:  # noqa: BLE001 - a hostile __str__ must not lose the record
            message = "(the exception's message could not be read)"
        exc_name = type(orig).__name__ if orig is not None else None
        with _LOCK:
            live = _LIVE.get(id(connection_record)) or {}
            held_by = {
                "thread": live.get("thread"),
                "endpoint": live.get("endpoint"),
                "age_s": round(time.monotonic() - live["checkout_at"], 3) if live else None,
            }
            rec = {
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
                "by_thread": thread.name,
                "held_by": held_by,
                "exception": exc_name,
                # The DBAPI's own message, trimmed: SQLAlchemy's wrapper carries the SQL
                # text and its parameters, which this record never keeps.
                "message": message,
            }
            _INVALIDATIONS.append(rec)
            _INVALIDATED += 1
            now = time.monotonic()
            log_it = _INVAL_LOGGED_AT is None or now - _INVAL_LOGGED_AT >= INVALIDATION_LOG_EVERY_S
            skipped = _INVAL_SUPPRESSED
            if log_it:
                _INVAL_LOGGED_AT, _INVAL_SUPPRESSED = now, 0
            else:
                _INVAL_SUPPRESSED += 1
        if log_it:
            _LOG.warning(
                "pool connection invalidated: held by %s (route %s), %s: %s%s",
                held_by["thread"],
                held_by["endpoint"],
                rec["exception"],
                rec["message"],
                f" (+{skipped} more since the last line; the last 20 and the total are in the pool-watch record)"
                if skipped
                else "",
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

    Each row is ``{thread, ident, endpoint, collector, pool, age_s}``; ``pool`` says which watched
    pool it came from ("corpus", or the label ``register`` was given); ``endpoint`` is the route the request
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
                "pool": rec.get("pool", "corpus"),
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
    """How many pooled connections of the CORPUS pool the APP's own threads (not the collector,
    whose slots the D44 reservation already counts) have held for at least ``min_age_s``. A
    watched pool that is not the corpus pool (a streamed export's own read-snapshot engine, whose
    read can legitimately last minutes) is not one of the slots the headroom reading is about, so
    it is not counted: it used to be, and a long export made a healthy pool read "insufficient".

    ``None`` when the instrument is not attached: "nothing is held" and "nobody is watching"
    are opposite facts, and a caller must be able to tell them apart.
    """
    if not _REGISTERED:
        return None
    return sum(
        1
        for r in checked_out()
        if not r["collector"] and r["pool"] == "corpus" and r["age_s"] >= min_age_s
    )


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


def register(engine, *, label: str = "corpus") -> bool:
    """Attach the listeners to ``engine``'s pool. Idempotent per engine; never raises.

    More than one engine may be watched (the corpus engine and the read-snapshot engines
    whose streamed reads hold a WAL snapshot); ``checked_out()`` lists them together, each row
    carrying the ``label`` its pool was registered under (only "corpus" rows are slots of the
    corpus pool).
    """
    global _REGISTERED
    try:
        from sqlalchemy import event

        if event.contains(engine, "checkout", _on_checkout):
            return False
        pool = engine.pool
        with _LOCK:
            for k in [k for k, (ref, _l) in _POOL_LABELS.items() if ref() is None]:
                _POOL_LABELS.pop(k, None)  # a collected pool's id may be reused
            _POOL_LABELS[id(pool)] = (weakref.ref(pool), label)
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
    global _PRUNED, _INVALIDATED, _INVAL_LOGGED_AT, _INVAL_SUPPRESSED
    with _LOCK:
        _LIVE.clear()
        _PRUNED = 0
        _INVALIDATED = 0
        _INVALIDATIONS.clear()
        _INVAL_LOGGED_AT, _INVAL_SUPPRESSED = None, 0
