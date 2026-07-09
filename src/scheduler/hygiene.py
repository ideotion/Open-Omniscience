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
import threading
import time
from pathlib import Path

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


# --------------------------------------------------------------------------- #
# WAL checkpoint hygiene (P0.3 E4): under multi-day continuous writes the -wal
# file can grow without bound (a runaway -wal is a named suspect in the field's
# unexplained ~120 GB data folder). Between passes — NEVER mid-worker — run
# ``PRAGMA wal_checkpoint(TRUNCATE)`` through ``write_lock()`` so it can never
# run concurrently with a gated writer, and report the MEASURED effect.
# --------------------------------------------------------------------------- #

_CKPT_STATE_LOCK = threading.Lock()
_LAST_CKPT_MONO: float | None = None


def wal_checkpoint_enabled() -> bool:
    return os.getenv("OO_WAL_CHECKPOINT", "1") != "0"


def _ckpt_min_interval_s() -> float:
    try:
        return max(0.0, float(os.getenv("OO_WAL_CHECKPOINT_MIN_S", "") or 300.0))
    except (TypeError, ValueError):
        return 300.0


def _ckpt_busy_timeout_ms() -> int:
    # Bounded on purpose: with an active long reader, TRUNCATE calls the busy
    # handler until the reader finishes — the default 30 s connection timeout
    # would hold the write gate that long between passes. 5 s bounds the hold;
    # an unfinished checkpoint returns the honest busy=1 and is retried next
    # pass boundary.
    try:
        return max(0, int(os.getenv("OO_WAL_CHECKPOINT_BUSY_MS", "") or 5000))
    except (TypeError, ValueError):
        return 5000


def checkpoint_wal(
    *, engine=None, force: bool = False, busy_timeout_ms: int | None = None
) -> dict | None:
    """Run ``PRAGMA wal_checkpoint(TRUNCATE)`` at a pass boundary, measured.

    Serialised through ``write_lock()`` (the same gate every writer takes), so
    it can NEVER run beside a gated writer — it queues behind one instead.
    Rate-limited by ``OO_WAL_CHECKPOINT_MIN_S`` (default 300 s) so fast
    recycled passes don't churn; ``force=True`` bypasses the cadence (tests /
    explicit maintenance). Returns the measured record — busy flag, frames,
    wal bytes before/after, duration — or None (disabled / not due /
    non-SQLite / error). Never raises.
    """
    global _LAST_CKPT_MONO
    if not wal_checkpoint_enabled():
        return None
    try:
        if engine is None:
            from src.database.session import engine as _global_engine

            engine = _global_engine
        if engine.url.get_backend_name() != "sqlite":
            return None  # WAL checkpointing is a SQLite concern only
        with _CKPT_STATE_LOCK:
            now = time.monotonic()
            if (
                not force
                and _LAST_CKPT_MONO is not None
                and (now - _LAST_CKPT_MONO) < _ckpt_min_interval_s()
            ):
                return None
            _LAST_CKPT_MONO = now

        db_path = engine.url.database
        wal = Path(str(db_path) + "-wal") if db_path and db_path != ":memory:" else None
        bytes_before = wal.stat().st_size if wal and wal.exists() else 0
        busy_ms = _ckpt_busy_timeout_ms() if busy_timeout_ms is None else busy_timeout_ms

        from src.database.writer import write_lock

        t0 = time.monotonic()
        raw = engine.raw_connection()
        try:
            cur = raw.cursor()
            with write_lock():
                # PRAGMAs are not DML, so pysqlite opens no implicit
                # transaction here — the checkpoint runs outside any BEGIN.
                cur.execute(f"PRAGMA busy_timeout={int(busy_ms)}")
                row = cur.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            cur.execute("PRAGMA busy_timeout=30000")  # restore before pool reuse
            cur.close()
        finally:
            raw.close()
        duration_ms = round((time.monotonic() - t0) * 1000.0, 1)
        bytes_after = wal.stat().st_size if wal and wal.exists() else 0
        busy, log_frames, ckpt_frames = (
            (int(row[0]), int(row[1]), int(row[2])) if row else (None, None, None)
        )
        out = {
            "busy": busy,  # 1 = an active reader pinned the WAL: honest partial
            "log_frames": log_frames,
            "checkpointed_frames": ckpt_frames,
            "wal_bytes_before": bytes_before,
            "wal_bytes_after": bytes_after,
            "duration_ms": duration_ms,
        }
        _LOG.info("wal checkpoint(TRUNCATE): %s", out)
        return out
    except Exception:  # noqa: BLE001 - hygiene must never break the run loop
        _LOG.warning("wal checkpoint failed; run loop continues", exc_info=True)
        return None


def run_pass_hygiene() -> dict | None:
    """The composed between-pass hygiene step (called from the scheduler's
    run boundary, never mid-worker): memory release + WAL checkpoint.
    Best-effort; never raises."""
    try:
        out = release_pass_state() or {}
        # Always present so the run report shows whether a checkpoint ran
        # (None = disabled / not due / skipped — never a silent omission).
        out["wal_checkpoint"] = checkpoint_wal()
        return out
    except Exception:  # noqa: BLE001 - hygiene must never break the run loop
        _LOG.warning("pass hygiene failed; run loop continues", exc_info=True)
        return None
