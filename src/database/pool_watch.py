"""
S2.6 (b): which thread is holding a pooled connection, and for how long.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The write gate names whoever is inside the WRITE window (src/database/writer.py).
It cannot name a thread that is merely holding a checked-out connection -- and
that is the thread that pins the WAL: an open read transaction stops
``PRAGMA wal_checkpoint(TRUNCATE)`` from reclaiming anything, which is how the
field's WAL reached three hours of growth with the gate free the whole time.

So: a checkout/checkin/detach trio, recording ONLY ``{thread, ident, checkout_at}`` per
live connection. Three properties are load-bearing.

* It records at CHECKOUT and forgets at CHECKIN, so a RETURNED connection is
  never listed. An instrument that keeps naming an innocent thread after it has
  handed the connection back is worse than no instrument: every reading would
  accuse whoever ran last.
* It stores no statement text and no stack -- this is on the pool's hot path.
  The age is what identifies a pinner; :func:`stacks_for` takes a stack for the named
  thread ON DEMAND (the storage guard asks for it when a WAL will not reset).
* It is keyed on the pool's connection RECORD and re-verified at read time, so a
  connection SQLAlchemy invalidated or detached can never linger as an immortal
  "oldest checkout" (see ``_LIVE``).

``checked_out()`` is a point-in-time copy, oldest first, so the top row of the
diagnostics member is the candidate WAL pinner.
"""

from __future__ import annotations

import threading
import time
import weakref
from typing import Any

# keyed by id(connection RECORD), never by id(dbapi_connection). SQLAlchemy clears
# ``record.dbapi_connection`` BEFORE it fires ``checkin`` when a connection is
# invalidated (a failed rollback on return, ``invalidate()``, a disconnect) and a
# DETACHED connection never checks in at all, so a table keyed on the DBAPI object
# misses both and keeps the row forever -- an immortal "oldest checkout" that every
# WAL diagnosis then names as the pinner (reproduced against SQLAlchemy 2.1.1; the
# same hole ``pool_reserve.py`` documents for its slot table). The record is the one
# object ``checkout``, ``checkin``, ``detach`` and ``invalidate`` are all handed.
_LIVE: dict[int, dict[str, Any]] = {}
_LOCK = threading.Lock()
_REGISTERED = False
# Rows dropped at READ time because their record is no longer checked out -- the
# phantoms the event keys above could not prevent (a listener attached late, an id
# reused after a record was collected). A reading, never a control input.
_PRUNED = 0


def _on_checkout(dbapi_connection, connection_record, _connection_proxy) -> None:
    thread = threading.current_thread()
    with _LOCK:
        _LIVE[id(connection_record)] = {
            "thread": thread.name,
            "ident": thread.ident,
            "checkout_at": time.monotonic(),
            "record": weakref.ref(connection_record),
        }


def _on_checkin(dbapi_connection, connection_record) -> None:
    with _LOCK:
        _LIVE.pop(id(connection_record), None)


def _on_detach(dbapi_connection, connection_record) -> None:
    # A detached connection leaves the pool for good and never reaches ``checkin``.
    with _LOCK:
        _LIVE.pop(id(connection_record), None)


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

    Each row is ``{thread, ident, age_s}``; ``ident`` lets a caller ask for that
    thread's stack on demand (:func:`stacks_for`) without this module ever storing one.
    """
    global _PRUNED
    now = time.monotonic()
    with _LOCK:
        dead = [k for k, rec in _LIVE.items() if not _still_out(rec)]
        for k in dead:
            del _LIVE[k]
        _PRUNED += len(dead)
        rows = [
            {
                "thread": rec["thread"],
                "ident": rec["ident"],
                "age_s": round(now - rec["checkout_at"], 3),
            }
            for rec in _LIVE.values()
        ]
    rows.sort(key=lambda r: r["age_s"], reverse=True)
    return rows


def pruned_total() -> int:
    """How many phantom rows reads have dropped since the process started."""
    with _LOCK:
        return _PRUNED


def stacks_for(idents: list[int], *, depth: int = 12) -> dict[int, list[str]]:
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
        _REGISTERED = True
        return True
    except Exception:  # noqa: BLE001 - an instrument must never break a boot
        return False


def _reset_for_tests() -> None:
    """Test-only: forget every recorded checkout (the listeners stay attached)."""
    global _PRUNED
    with _LOCK:
        _LIVE.clear()
        _PRUNED = 0
