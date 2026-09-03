"""
S1.2: when the memory guard engages, actually RELEASE something.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The guard pauses collection, which stops NEW work and frees nothing resident.
``hygiene.release_pass_state`` — the only release the app had — resets
trafilatura's caches, runs ``gc.collect()`` and ``malloc_trim``, and none of that
touches the two structures that actually hold the memory: the pool's SQLite page
caches and the in-memory columnar serve connections.

WHAT EACH STEP IS WORTH, measured here rather than assumed (64 MiB cache, a warm
connection over a 160 MB database):

    warm                                  RSS 112.5 MB
    rollback (returning the connection)   RSS 112.5 MB   <- frees NOTHING
    PRAGMA shrink_memory                  RSS  46.2 MB
    close (engine.dispose)                RSS  46.0 MB

So the ladder disposes the pool's IDLE connections (checked-out ones close on
return, which is why this is idle-only and safe under load) and then asks SQLite
to hand back what the remaining connections are holding. The columnar serves are
closed and marked not-built; both already fall back to live queries by design, so
this costs latency, never an answer.

``gc.collect()`` is DELIBERATELY SKIPPED while our own pages are in swap: a full
heap walk faults them back in, and the field measurement of that is a pass whose
RSS ROSE 1668 -> 1751 MB. Where swap cannot be measured the collection is skipped
too, with the reason recorded — a guess in either direction would be worse than
the honest gap.

Every step reports its own ``freed_mb``, measured before and after. ``None``
means the RSS reading was unavailable — never 0, which would read as "this step
freed nothing".
"""

from __future__ import annotations

import logging
import time
from contextlib import suppress
from typing import Any

_LOG = logging.getLogger("scheduler.release")


def _rss_mb() -> float | None:
    try:
        import psutil

        return round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001 - a reading is best-effort
        return None


def _freed(before: float | None, after: float | None) -> float | None:
    if before is None or after is None:
        return None
    return round(before - after, 1)


def _dispose_idle_pool() -> dict[str, Any]:
    """Close the pool's IDLE connections; each takes its page cache with it.

    Idle-only by construction: ``Pool.dispose()`` closes what is checked IN and
    lets checked-out connections close when they are returned, so a worker
    mid-statement is never cut off.
    """
    out: dict[str, Any] = {"step": "dispose_idle_pool"}
    try:
        from src.database.session import engine

        pool = engine.pool
        checkedin = getattr(pool, "checkedin", None)
        out["closed"] = int(checkedin()) if checkedin is not None else None
        pool.dispose()
        out["ok"] = True
    except Exception as exc:  # noqa: BLE001 - a release is never worth a crash
        out["ok"] = False
        out["error"] = f"{type(exc).__name__}: {exc}"[:200]
    return out


def _shrink_sqlite() -> dict[str, Any]:
    """``PRAGMA shrink_memory`` on a short-lived connection.

    The step that measurably frees the most: SQLite's page cache belongs to the
    connection and is not given back by ending a transaction.
    """
    out: dict[str, Any] = {"step": "shrink_memory"}
    try:
        from src.database.session import engine

        raw = engine.raw_connection()
        try:
            raw.execute("PRAGMA shrink_memory")
        finally:
            raw.close()
        out["ok"] = True
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["error"] = f"{type(exc).__name__}: {exc}"[:200]
    return out


def _close_serves() -> dict[str, Any]:
    """Close the columnar serve connections and mark them not-built.

    Both serves already fall back to live queries when nothing is built, so this
    costs query latency and never an answer.
    """
    out: dict[str, Any] = {"step": "close_serves", "closed": []}
    for name in ("rollup_serve", "map_serve"):
        try:
            mod = __import__(f"src.analytics.{name}", fromlist=[name])
            with mod._LOCK:
                con = mod._STATE.get("con")
                if con is not None:
                    with suppress(Exception):
                        con.close()
                    mod._STATE["con"] = None
                    mod._STATE["built_at"] = 0.0
                    out["closed"].append(name)
        except Exception as exc:  # noqa: BLE001
            out.setdefault("errors", {})[name] = f"{type(exc).__name__}: {exc}"[:120]
    out["ok"] = "errors" not in out
    return out


def _collect_garbage(swapping: bool | None) -> dict[str, Any]:
    """``gc.collect()`` — skipped while our pages are in swap, or unmeasurable.

    A full heap walk faults swapped pages back in; the field measurement of doing
    it anyway is a pass whose RSS ROSE 1668 -> 1751 MB.
    """
    out: dict[str, Any] = {"step": "gc_collect"}
    if swapping is None:
        out["skipped"] = "swap unmeasurable — a heap walk could fault pages back in"
        return out
    if swapping:
        out["skipped"] = "this process has pages in swap"
        return out
    import gc

    try:
        out["collected"] = gc.collect()
        out["ok"] = True
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["error"] = f"{type(exc).__name__}: {exc}"[:200]
    return out


def _malloc_trim() -> dict[str, Any]:
    """Return glibc's freed arenas to the OS (a no-op elsewhere)."""
    out: dict[str, Any] = {"step": "malloc_trim"}
    try:
        import ctypes

        ctypes.CDLL("libc.so.6").malloc_trim(0)
        out["ok"] = True
    except Exception as exc:  # noqa: BLE001 - not glibc
        out["ok"] = False
        out["error"] = f"{type(exc).__name__}: {exc}"[:120]
    return out


def release_residents() -> dict[str, Any]:
    """Run the release ladder, measuring what each step actually frees.

    Never raises: this runs when the machine is already in trouble, and a release
    that fails must leave the guard's pause in place rather than take the process
    down with it.
    """
    from src.monitoring.swap import process_swapping, swap_readings

    t0 = time.monotonic()
    swapping = process_swapping()
    rss_start = _rss_mb()
    steps: list[dict[str, Any]] = []

    for fn in (
        _dispose_idle_pool,
        _shrink_sqlite,
        _close_serves,
        lambda: _collect_garbage(swapping),
        _malloc_trim,
    ):
        before = _rss_mb()
        try:
            rec = fn()
        except Exception as exc:  # noqa: BLE001 - one step must not stop the ladder
            rec = {"step": "unknown", "ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
        rec["freed_mb"] = _freed(before, _rss_mb())
        steps.append(rec)

    rss_end = _rss_mb()
    out: dict[str, Any] = {
        "rss_mb_before": rss_start,
        "rss_mb_after": rss_end,
        "freed_mb": _freed(rss_start, rss_end),
        "process_swapping": swapping,
        "steps": steps,
        "duration_ms": round((time.monotonic() - t0) * 1000.0, 1),
    }
    out.update(swap_readings())
    _LOG.info(
        "memory guard release: rss %s -> %s MB (freed %s, swapping=%s, %.0f ms)",
        rss_start,
        rss_end,
        out["freed_mb"],
        swapping,
        out["duration_ms"],
    )
    return out
