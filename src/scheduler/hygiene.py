"""
Between-pass hygiene: release per-pass memory so a marathon run stays flat.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why this exists (P0.3, field event 2026-07-09): the app died by kernel OOM at
RSS 10,599 MB on a ~10,237 MB VM, 21.6 hours into ONE continuous crawl pass.
Memory accumulates ACROSS a pass — extractor/library caches, allocator arenas
fragmented by 50 worker threads churning multi-MB HTML strings, per-pass host
state — and nothing ever handed it back. Pass recycling (src/scheduler/runner)
bounds how long a pass may accumulate; THIS module is the release step that
runs between passes:

  * ``trafilatura``'s documented ``reset_caches()`` — the library's own lever
    for long-running processes (clears its internal LRU caches).
  * ``gc.collect()`` — collect reference cycles the pass created.
  * glibc ``malloc_trim(0)`` (Linux only, env-gated) — return freed arena
    memory to the OS. With many worker threads, per-thread arenas hold freed
    pages indefinitely; trim is the documented way to give them back.

Every step is measured (RSS before/after via psutil) and logged — never a
guessed effect — and everything is best-effort: a hygiene fault must never
break the pass that just succeeded. ``OO_PASS_HYGIENE=0`` disables the whole
step; ``OO_PASS_MALLOC_TRIM=0`` disables just the trim.
"""

from __future__ import annotations

import gc
import logging
import os
import sys
import time

_LOG = logging.getLogger("scheduler.hygiene")


def hygiene_enabled() -> bool:
    return os.getenv("OO_PASS_HYGIENE", "1") != "0"


def _rss_mb() -> float | None:
    """Process RSS in MiB via psutil, or None (never a fabricated number)."""
    try:
        import psutil

        return round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001 - instrumentation is best-effort
        return None


def _malloc_trim() -> bool:
    """glibc malloc_trim(0): return freed arena memory to the OS (Linux only).

    Returns True when the call was made (its own return value only says whether
    any memory was released; we log the measured RSS delta instead).
    """
    if os.getenv("OO_PASS_MALLOC_TRIM", "1") == "0":
        return False
    if not sys.platform.startswith("linux"):
        return False
    try:
        import ctypes

        ctypes.CDLL("libc.so.6").malloc_trim(0)
        return True
    except Exception:  # noqa: BLE001 - trim is an optimisation, never required
        return False


def release_pass_state() -> dict | None:
    """Release per-pass memory at a pass boundary. Measured, logged, best-effort.

    Returns the measured record (rides the run report / soak report), or None
    when disabled. Never raises.
    """
    if not hygiene_enabled():
        return None
    t0 = time.monotonic()
    rss_before = _rss_mb()

    caches_reset = False
    try:
        # trafilatura's own documented lever for long-running processes.
        from trafilatura.meta import reset_caches

        reset_caches()
        caches_reset = True
    except Exception:  # noqa: BLE001 - the library may be absent or change API
        _LOG.debug("trafilatura reset_caches unavailable", exc_info=True)

    gc_collected = None
    try:
        gc_collected = gc.collect()
    except Exception:  # noqa: BLE001
        pass

    trimmed = _malloc_trim()
    rss_after = _rss_mb()

    out = {
        "rss_mb_before": rss_before,
        "rss_mb_after": rss_after,
        "freed_mb": (
            round(rss_before - rss_after, 1)
            if rss_before is not None and rss_after is not None
            else None
        ),
        "caches_reset": caches_reset,
        "gc_collected": gc_collected,
        "malloc_trimmed": trimmed,
        "duration_ms": round((time.monotonic() - t0) * 1000.0, 1),
    }
    _LOG.info(
        "pass hygiene: rss %s -> %s MB (caches_reset=%s gc=%s trim=%s, %.0f ms)",
        rss_before,
        rss_after,
        caches_reset,
        gc_collected,
        trimmed,
        out["duration_ms"],
    )
    return out


def run_pass_hygiene() -> dict | None:
    """The composed between-pass hygiene step (called from the scheduler's
    run boundary, never mid-worker). Best-effort; never raises."""
    try:
        return release_pass_state()
    except Exception:  # noqa: BLE001 - hygiene must never break the run loop
        _LOG.warning("pass hygiene failed; run loop continues", exc_info=True)
        return None
