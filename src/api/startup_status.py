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
