"""Post-unlock startup progress — a tiny, thread-safe status the unlock page polls.

Why this exists (maintainer field report, 2026-07-02): unlocking a large encrypted
corpus ran the whole deferred startup (schema self-heal + a bounded ANALYZE + catalog
seeding + full-table COUNTs that drag every page through the SQLCipher codec + a cache
warm) *synchronously inside the /unlock request*, so the Unlock button sat frozen with
no feedback — and, on a single worker, any other tab opened in that window hung too.
The unlock path now returns as soon as the DB is queryable and runs the expensive
upkeep in a background thread; the unlock page shows honest progress and redirects only
when this reports ``ready``. No fabricated percentage — just the real current phase.
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
# state: "idle" (never unlocked this process) | "running" | "ready" | "error"
_state: dict[str, str | None] = {"state": "idle", "phase": "", "error": None}


def set_startup(state: str, phase: str | None = None, error: str | None = None) -> None:
    with _lock:
        _state["state"] = state
        if phase is not None:
            _state["phase"] = phase
        _state["error"] = error


def mark_phase(phase: str) -> None:
    """Update the human-readable phase without changing the state (still running)."""
    with _lock:
        _state["phase"] = phase


def get_startup() -> dict[str, str | None]:
    with _lock:
        return dict(_state)
