"""
S2.6 (b): which thread is holding a pooled connection, and for how long.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The write gate names whoever is inside the WRITE window (src/database/writer.py).
It cannot name a thread that is merely holding a checked-out connection -- and
that is the thread that pins the WAL: an open read transaction stops
``PRAGMA wal_checkpoint(TRUNCATE)`` from reclaiming anything, which is how the
field's WAL reached three hours of growth with the gate free the whole time.

So: a checkout/checkin pair, recording ONLY ``{thread, checkout_at}`` per live
connection. Two properties are load-bearing.

* It records at CHECKOUT and forgets at CHECKIN, so a RETURNED connection is
  never listed. An instrument that keeps naming an innocent thread after it has
  handed the connection back is worse than no instrument: every reading would
  accuse whoever ran last.
* It stores no statement text and no stack -- this is on the pool's hot path.
  The age is what identifies a pinner; a stack for the named thread can be taken
  on demand from the write gate's watchdog helper.

``checked_out()`` is a point-in-time copy, oldest first, so the top row of the
diagnostics member is the candidate WAL pinner.
"""

from __future__ import annotations

import threading
import time
from typing import Any

# keyed by id(dbapi_connection) -- the pool hands the SAME object back on
# checkin, and the record is removed there, so the id can never be stale for a
# live entry.
_LIVE: dict[int, dict[str, Any]] = {}
_LOCK = threading.Lock()
_REGISTERED = False


def _on_checkout(dbapi_connection, _connection_record, _connection_proxy) -> None:
    with _LOCK:
        _LIVE[id(dbapi_connection)] = {
            "thread": threading.current_thread().name,
            "checkout_at": time.monotonic(),
        }


def _on_checkin(dbapi_connection, _connection_record) -> None:
    with _LOCK:
        _LIVE.pop(id(dbapi_connection), None)


def checked_out() -> list[dict[str, Any]]:
    """Live checkouts, OLDEST FIRST. Empty when nothing is checked out."""
    now = time.monotonic()
    with _LOCK:
        rows = [
            {"thread": rec["thread"], "age_s": round(now - rec["checkout_at"], 3)}
            for rec in _LIVE.values()
        ]
    rows.sort(key=lambda r: r["age_s"], reverse=True)
    return rows


def register(engine) -> bool:
    """Attach the listeners to ``engine``'s pool. Idempotent; never raises."""
    global _REGISTERED
    if _REGISTERED:
        return False
    try:
        from sqlalchemy import event

        event.listen(engine, "checkout", _on_checkout)
        event.listen(engine, "checkin", _on_checkin)
        _REGISTERED = True
        return True
    except Exception:  # noqa: BLE001 - an instrument must never break a boot
        return False


def _reset_for_tests() -> None:
    """Test-only: forget every recorded checkout (the listeners stay attached)."""
    with _LOCK:
        _LIVE.clear()
