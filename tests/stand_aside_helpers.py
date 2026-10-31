"""A REAL storage guard that is engaged until a test says otherwise (the tests of the writers that stand aside, R398 B1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The guard is the real class, fed readings a test owns: no sampler thread, no real drive. With no supervisor running a waiter
takes the readings itself each turn (``poll_and_drain_unsupervised``), so flipping the readings back to healthy is all it takes
for the pause to end, exactly as in the field when the cause goes away. ``conftest.py`` switches the guard off for the suite
(``OO_STORAGE_GUARD=0``); ``install`` switches it on for one test and puts this guard where the writers look it up.

No clock is read for an order: a test waits for the writer to have REACHED its pause (``wait_until``, observed on the row it
publishes), asserts what has not happened yet, then ends the pause and waits for the writer to finish.
"""

from __future__ import annotations

from typing import Any

from src.scheduler import storage_guard as sg
from src.scheduler.storage_guard import GIB, MIB, StorageGuard

CORPUS = 10 * GIB
TOTAL = 500 * GIB
FREE_OK = 300 * GIB
#: How often a waiting writer looks again in these tests; the product's own is 2 s.
FAST_POLL_S = 0.01


class _Clock:
    def __call__(self) -> float:
        return 1000.0


def engaged_guard(monkeypatch: Any, kind: str = "wal") -> tuple[StorageGuard, dict[str, Any]]:
    """``(guard, readings)``: a guard already engaged for ``kind`` (``"wal"`` or ``"disk"``) whose readings keep saying so
    until ``healthy(readings)``. The guard is switched on for the test first: a switched-off guard takes no readings."""
    monkeypatch.setenv("OO_STORAGE_GUARD", "1")
    readings = {
        "wal_bytes": 2 * GIB if kind == "wal" else 0,
        "disk_free_bytes": FREE_OK if kind == "wal" else MIB,
    }

    def read() -> dict[str, Any]:
        return {"corpus_bytes": CORPUS, "disk_total_bytes": TOTAL, "lane_wal_bytes": {}, **readings}

    g = StorageGuard(clock=_Clock(), trip_after=2, resume_after=2, readings_fn=read, drain_fn=lambda: {"busy": 1, "skipped": None})
    g.poll()
    g.poll()
    assert g.engaged and g.kind() == kind
    return g, readings


def healthy(readings: dict[str, Any]) -> None:
    """The cause went away: the waiter's own next readings release the latch."""
    readings["wal_bytes"] = 0
    readings["disk_free_bytes"] = FREE_OK


def engage(guard: StorageGuard, readings: dict[str, Any], kind: str = "wal") -> None:
    """Engage a guard that was healthy (two readings trip it)."""
    readings["wal_bytes"] = 2 * GIB if kind == "wal" else 0
    readings["disk_free_bytes"] = FREE_OK if kind == "wal" else MIB
    guard.poll()
    guard.poll()
    assert guard.engaged


def install(monkeypatch: Any, guard: StorageGuard) -> StorageGuard:
    """Switch the guard on for this test and put ``guard`` where the writers look it up, polling fast."""
    monkeypatch.setenv("OO_STORAGE_GUARD", "1")
    monkeypatch.setattr(sg, "storage_guard", guard)
    real = guard.wait_if_engaged
    monkeypatch.setattr(guard, "wait_if_engaged", lambda *a, **kw: real(*a, **{"poll_s": FAST_POLL_S, **kw}))
    return guard


def healthy_guard(monkeypatch: Any) -> tuple[StorageGuard, dict[str, Any]]:
    """``(guard, readings)`` that is NOT engaged (engage it later with :func:`engage`)."""
    monkeypatch.setenv("OO_STORAGE_GUARD", "1")
    readings = {"wal_bytes": 0, "disk_free_bytes": FREE_OK}

    def read() -> dict[str, Any]:
        return {"corpus_bytes": CORPUS, "disk_total_bytes": TOTAL, "lane_wal_bytes": {}, **readings}

    g = StorageGuard(clock=_Clock(), trip_after=2, resume_after=2, readings_fn=read, drain_fn=lambda: {"busy": 1, "skipped": None})
    g.poll()
    g.poll()
    assert not g.engaged
    return g, readings
