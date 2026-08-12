"""How many local-model calls are in flight right now — the structural answer.

The top-bar pill has to distinguish "a backend is serving" from "a backend is
WORKING", and the tempting way to answer the second is to enumerate the things that
run models: the coordinator's lane, the AI check, a bulk run, the sweeps. That is an
enumeration, and enumerations are wrong — they are wrong the day someone adds a
caller and does not think of this file, which is exactly the failure mode the ledger
records for the airplane backstop ("every real fetch path refuses itself at its own
gate" was an enumeration, and two modules were absent from it).

So this counts at the SEAM every inference must cross instead: the clients'
``generate()``. A caller cannot run a model without passing through one of them, so
a call that is not counted here is a call that did not happen. New sweeps, new
endpoints and code not yet written are covered by construction rather than by
memory.

WHAT IT IS NOT. It is not a progress figure and cannot become one: it knows how many
calls are open and when the oldest started, never how far along any of them is or
how long it will take. A model gives no such signal, and a bar drawn from a guess
would be a fabricated measurement on a status pill.

Cost: two integers and a dict behind one lock, touched twice per generate() call.
Nothing here reads a database, spawns a process or opens a socket — which is the
property that makes the pill able to poll it at all.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import itertools
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

_LOCK = threading.Lock()
_SEQ = itertools.count(1)
#: token -> {"model": str, "backend": str, "started_at": float}
_OPEN: dict[int, dict] = {}


@contextmanager
def generating(model: str | None, *, backend: str) -> Iterator[None]:
    """Mark one model call as in flight for as long as the block runs.

    The decrement is in a ``finally``, so a call that raises — an unreachable
    backend, a 500, a timeout — still clears. A leaked entry would pin the pill on
    "working" forever, which is a worse lie than showing nothing.
    """
    tok = next(_SEQ)
    with _LOCK:
        _OPEN[tok] = {
            "model": (model or "").strip() or None,
            "backend": backend,
            "started_at": time.time(),
        }
    try:
        yield
    finally:
        with _LOCK:
            _OPEN.pop(tok, None)


def inflight() -> dict:
    """A point-in-time count of open model calls, with the models they name.

    ``oldest_elapsed_s`` is a real measured age, not an estimate of anything
    remaining — see the module docstring on why no progress figure exists here.
    """
    now = time.time()
    with _LOCK:
        rows = list(_OPEN.values())
    models = sorted({r["model"] for r in rows if r.get("model")})
    backends = sorted({r["backend"] for r in rows if r.get("backend")})
    oldest = min((r["started_at"] for r in rows), default=None)
    return {
        "n": len(rows),
        "models": models,
        "backends": backends,
        "oldest_elapsed_s": round(now - oldest, 1) if oldest is not None else None,
    }


def _reset_for_tests() -> None:
    """Drop every open entry. Tests only — production never needs this."""
    with _LOCK:
        _OPEN.clear()


__all__ = ["generating", "inflight"]
