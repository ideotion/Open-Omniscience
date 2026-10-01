"""Post-unlock startup progress — a tiny, thread-safe status the unlock page polls.

Why this exists (maintainer field report, 2026-07-02): unlocking a large encrypted
corpus ran the whole deferred startup (schema self-heal + a bounded ANALYZE + catalog
seeding + full-table COUNTs that drag every page through the SQLCipher codec + a cache
warm) *synchronously inside the /unlock request*, so the Unlock button sat frozen with
no feedback — and, on a single worker, any other tab opened in that window hung too.
The unlock path now returns as soon as the DB is queryable and runs the expensive
upkeep in a background thread; the unlock page shows honest progress and redirects only
when this reports ``ready``. No fabricated percentage — just the real current phase.

``queryable`` (2026-07-02, field report "unlocking takes ages / CPU at 12%"): the
corpus is fully usable the instant ``init_db`` finishes — every step after that
(ANALYZE, catalog seed-dedup, COUNTs, cache warm) is best-effort optimization the app
does not need to open. The single serial upkeep left CPU + SSD idle while the user
waited on the ``ready`` gate. The unlock page now enters the Console as soon as
``queryable`` is true and lets the upkeep finish in the background, so unlock feels
instant on a large corpus. ``ready`` still marks "all tidying done".
"""

from __future__ import annotations

import threading
from typing import Any

_lock = threading.Lock()
# state: "idle" (never unlocked this process) | "running" | "ready" | "error"
# queryable: the DB is open and usable (init_db done) — the app can be entered even
# while the best-effort upkeep is still running in the background.
_state: dict[str, object] = {"state": "idle", "phase": "", "error": None, "queryable": False}


def set_startup(
    state: str, phase: str | None = None, error: str | None = None, *, queryable: bool | None = None
) -> None:
    with _lock:
        _state["state"] = state
        if phase is not None:
            _state["phase"] = phase
        _state["error"] = error
        if queryable is not None:
            _state["queryable"] = queryable
        elif state == "ready":
            # Reaching "ready" implies the DB has long been queryable.
            _state["queryable"] = True


def mark_phase(phase: str) -> None:
    """Update the human-readable phase without changing the state (still running)."""
    with _lock:
        _state["phase"] = phase


def mark_queryable() -> None:
    """The DB is open and usable — the app may be entered now (upkeep continues)."""
    with _lock:
        _state["queryable"] = True


def get_startup() -> dict[str, object]:
    with _lock:
        return dict(_state)


# --- the recovery step BEFORE the store is open (rank 5, phase 0) --------------------------
#
# ``POST /unlock`` opens and closes one verify connection before it reports anything, and a
# store that boots with a large -wal pays for it inside that one call: the first read RECOVERS
# the log (every frame is read and its checksum chain validated) and the last close writes it
# back into the database file. On the field's S3 boot that was 24.7 s; on the 981 s unlock it was
# the longest unlabelled stretch. The page showed an elapsed clock and nothing else, because the
# status above is unreachable while the app is still locked (the lock gate answers 503 for it) and
# is only set after the verify connection has already returned.
#
# So this is its own small record, read through ``GET /api/system/unlock-progress`` (the one
# path a locked app adds, and it answers only while an unlock attempt is running). It holds
# numbers only -- no path, no name -- and is cleared in a ``finally`` so a wrong passphrase or a
# crash inside the verify leaves nothing behind that reads as "still recovering".
_recovery: dict[str, Any] | None = None
_recovery_token = 0


def begin_recovery(wal_bytes: int, eta_s: float | None, basis: dict[str, float] | None) -> int:
    """Record that the verify connection is about to recover a ``wal_bytes`` log. ``eta_s`` and
    ``basis`` come from this machine's own last measured recovery (``None`` when there is none:
    an unmeasured estimate is absent, never zero). Returns a token for ``end_recovery``."""
    import time

    global _recovery, _recovery_token
    with _lock:
        _recovery_token += 1
        _recovery = {
            "wal_bytes": int(wal_bytes),
            "eta_s": eta_s,
            "basis": basis,
            "started_mono": time.monotonic(),
        }
        return _recovery_token


def end_recovery(token: int | None) -> None:
    """Clear the record -- only the attempt that set it (a second attempt that began since keeps
    its own)."""
    global _recovery
    with _lock:
        if token is not None and token == _recovery_token:
            _recovery = None


def get_recovery() -> dict[str, Any]:
    """What the unlock page may show while the verify connection runs: ``{"active": False}`` when
    none is, else the log's size, the estimate with the measurement it came from, and the seconds
    elapsed so far. Numbers only."""
    import time

    with _lock:
        if _recovery is None:
            return {"active": False}
        return {
            "active": True,
            "wal_bytes": _recovery["wal_bytes"],
            "eta_s": _recovery["eta_s"],
            "basis": _recovery["basis"],
            "elapsed_s": round(time.monotonic() - _recovery["started_mono"], 1),
        }
