"""
When the last unlock finished -- ONE shared fact for the instruments that say how far a
request began from it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY IT EXISTS (diagnostics round of 2026-09-30, ranks 9 and 10). Summed over the sixteen
bundles, 287 of the 306 over-the-bar route entries rested on a window thinner than 20 samples,
and on eight instances the coordinator's check of the hand-off (V42) read the slowest
article-list call as starting 8 to 28 s after the unlock finished, from stall-forensics.json. The
latency summary could not say whether those thin windows were the first calls after an unlock,
because it recorded no timestamp for any call. This module is the clock that makes the
question answerable: the unlock path stamps the moment its synchronous work finished (the corpus
queryable and the airplane guard engaged, a moment after the corpus first could be read), and
the request-latency log and the search-timing log each read their own call's distance from it.

``note_unlock_done`` is called from ``forensics.record_unlock_timing`` -- the one place every
finished unlock already passes through -- so ``api/unlock.py`` is not touched.

HONESTY. A process that never finished an unlock (a plaintext store, or a passphrase handed in
from the environment at boot) has NO stamp, and every reading then says so: the distance is
``None`` with a reason, never ``0``. A zero would read as "this call was the unlock itself",
which is a different claim. The distance is SIGNED, because the request that performs the unlock
begins before the unlock is finished: a negative figure means the call began before the stamp.

Stdlib only, so every instrument can import it without pulling in an event loop.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from typing import Any

# The route keys (``METHOD template``, as latency.py keys them) of the two requests that PERFORM an
# unlock. Each stamps while it runs, so each begins before its own stamp: a negative distance on one
# of these is the unlock's own request, and on any other route it is a call that merely overlapped
# an unlock.
UNLOCK_ROUTES = frozenset({"POST /api/system/unlock", "POST /api/system/create-db"})

_LOCK = threading.Lock()
_done_at: float | None = None  # epoch seconds of the most recent finished unlock
_count = 0  # unlocks finished in THIS process


def note_unlock_done(at: float | None = None) -> None:
    """Stamp "an unlock just finished" (the corpus is queryable). ``at`` is for tests."""
    global _done_at, _count
    with _LOCK:
        _done_at = float(at) if at is not None else time.time()
        _count += 1


def last_done_at() -> float | None:
    with _LOCK:
        return _done_at


def started_after_unlock_s(started_epoch: float) -> float | None:
    """Seconds from the last finished unlock to ``started_epoch`` (signed), or ``None`` when
    this process has not finished one. Rounded to a tenth of a second."""
    with _LOCK:
        done = _done_at
    if done is None:
        return None
    return round(float(started_epoch) - done, 1)


def summary() -> dict[str, Any]:
    """What a report says about the stamp: how many unlocks this process has finished, when the
    last one did, and -- when it has finished none -- why every distance beside it is absent."""
    with _LOCK:
        done, count = _done_at, _count
    if done is None:
        return {
            "count": 0,
            "last_done_at": None,
            "reason": (
                "no unlock has finished in this process (the store was open at start, or "
                "this process has not been unlocked yet), so a call's distance from an "
                "unlock is unknown; it is absent below, never zero"
            ),
        }
    return {
        "count": count,
        "last_done_at": datetime.fromtimestamp(done, tz=UTC).isoformat(timespec="seconds"),
        "reason": None,
    }


def _reset_for_tests() -> None:
    global _done_at, _count
    with _LOCK:
        _done_at = None
        _count = 0
