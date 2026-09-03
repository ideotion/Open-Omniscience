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
from contextlib import suppress
from pathlib import Path

# Module level, not lazy inside checkpoint_wal: an ``except WriteGateBusy``
# clause is evaluated when an exception propagates, so a name bound by an import
# INSIDE the try would be unbound for any failure raised before that line --
# turning a real error into a NameError from the handler.
from src.database.writer import WriteGateBusy

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
    with suppress(Exception):
        gc_collected = gc.collect()

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


def _ckpt_gate_timeout_s() -> float:
    # S2.5: the checkpoint takes the single-writer gate, and until this bound
    # existed it waited on an unbounded Condition -- so a long writer held the
    # whole pass tail, and record_run (BELOW it) was never reached, which is why
    # a stalled pass left no run record at all. 30 s bounds the wait; giving up
    # records an honest skip and the checkpoint is retried next pass boundary.
    # <=0 restores the unbounded wait (an escape hatch, not a default).
    try:
        return max(0.0, float(os.getenv("OO_CKPT_GATE_TIMEOUT_S", "") or 30.0))
    except (TypeError, ValueError):
        return 30.0


def _ckpt_busy_timeout_ms() -> int:
    # S4.1: ZERO by default -- never wait. Measured against a WAL pinned by a
    # reader with an unexhausted cursor (4.1 MB WAL, 423 frames):
    #
    #   TRUNCATE busy_timeout=5000 -> 5012.4 ms, busy=1, wal UNCHANGED
    #   PASSIVE  busy_timeout=5000 ->    0.0 ms, busy=0, 423/423 backfilled
    #   TRUNCATE busy_timeout=0    ->    0.0 ms, busy=1, wal UNCHANGED
    #   (reader closed) TRUNCATE   ->    0.8 ms, busy=0, wal 0
    #
    # So the whole hold WAS the busy handler, and waiting bought nothing: the
    # pinned attempt returns the same busy=1 instantly. What actually bounds the
    # WAL while a reader is pinning it is the PASSIVE backfill below, which is
    # free and needs no wait at all. The cost of not waiting is that a lock held
    # only momentarily is no longer waited out -- and a reader that would clear
    # inside half a second is also gone by the next boundary, 300 s later.
    # OO_WAL_CHECKPOINT_BUSY_MS restores an allowance for anyone who wants one.
    try:
        return max(0, int(os.getenv("OO_WAL_CHECKPOINT_BUSY_MS", "") or 0))
    except (TypeError, ValueError):
        return 0


def _reader_snapshot() -> dict:
    """The oldest live connection checkout, or an honest "nobody is watching".

    A busy checkpoint says the WAL is pinned and cannot say by whom; pool_watch
    (S2.6 b) can. An UNATTACHED pool_watch returns the same empty list as a
    genuinely idle pool, so the attached-ness is reported rather than inferred --
    otherwise a checkpoint diagnosis would read "no reader is pinning this"
    from an instrument that is not running.
    """
    try:
        from src.database import pool_watch

        if not pool_watch.is_registered():
            return {"instrument": "unattached"}
        rows = pool_watch.checked_out()
        return {
            "n": len(rows),
            "oldest_age_s": rows[0]["age_s"] if rows else None,
            "oldest_thread": rows[0]["thread"] if rows else None,
        }
    except Exception:  # noqa: BLE001 - an instrument must never break the tail
        return {"instrument": "unreadable"}


def checkpoint_wal(
    *, engine=None, force: bool = False, busy_timeout_ms: int | None = None
) -> dict | None:
    """Run ``PRAGMA wal_checkpoint(TRUNCATE)`` at a pass boundary, measured.

    Serialised through ``write_lock()`` (the same gate every writer takes), so
    it can NEVER run beside a gated writer — it queues behind one instead.
    S2.5: that queue is now BOUNDED (``OO_CKPT_GATE_TIMEOUT_S``, 30 s). It used
    to be an unbounded wait, and ``record_run`` sits BELOW this call in the pass
    tail — so a long writer did not merely delay the checkpoint, it meant a
    stalled pass left no run record of itself at all.
    Rate-limited by ``OO_WAL_CHECKPOINT_MIN_S`` (default 300 s) so fast
    recycled passes don't churn; ``force=True`` bypasses the cadence (tests /
    explicit maintenance). Returns the measured record — busy flag, frames,
    wal bytes before/after, duration — or ``{'skipped': 'gate busy', ...}`` when
    the bound expired (its OWN outcome: a checkpoint that could not run and one
    that was never due are opposite facts), or None (disabled / not due /
    non-SQLite / error). Never raises. NOTE the cadence stamp is taken before
    the gate is attempted, so a gate-busy skip consumes that budget and the
    retry is at the NEXT boundary past the interval — matching every other
    failure path here, and visible in the returned record rather than silent.
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

        gate_timeout = _ckpt_gate_timeout_s()
        t0 = time.monotonic()
        raw = engine.raw_connection()
        try:
            cur = raw.cursor()
            try:
                with write_lock(timeout=gate_timeout or None):
                    # PRAGMAs are not DML, so pysqlite opens no implicit
                    # transaction here — the checkpoint runs outside any BEGIN.
                    cur.execute(f"PRAGMA busy_timeout={int(busy_ms)}")
                    # S4.1: PASSIVE first. It never blocks and never waits, and
                    # it backfills every frame up to the oldest reader's mark --
                    # so on a pinned WAL it is the step that actually bounds
                    # growth, while TRUNCATE can only reset the FILE, which no
                    # reader will allow. Then TRUNCATE, which at busy_timeout=0
                    # is free whichever way it goes.
                    #
                    # REFUTED, and recorded so it is not re-attempted: gating the
                    # TRUNCATE on `log_frames == checkpointed_frames` after the
                    # passive step does NOT mean "nothing is pinned". Measured, a
                    # reader whose snapshot is at the current end of the WAL
                    # satisfies it exactly (423 == 423) while still pinning the
                    # file. There is nothing to predict: not waiting is the fix.
                    passive_row = cur.execute(
                        "PRAGMA wal_checkpoint(PASSIVE)"
                    ).fetchone()
                    row = cur.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            finally:
                # ALWAYS restore before the connection returns to the pool
                # (skeptic finding: a raise between the two PRAGMAs would
                # otherwise hand later writers a silently shrunken lock
                # allowance — the exact 'database is locked' family the 30 s
                # default was shipped to prevent).
                with suppress(Exception):
                    cur.execute("PRAGMA busy_timeout=30000")
                    cur.close()
        finally:
            raw.close()
        duration_ms = round((time.monotonic() - t0) * 1000.0, 1)
        bytes_after = wal.stat().st_size if wal and wal.exists() else 0
        busy, log_frames, ckpt_frames = (
            (int(row[0]), int(row[1]), int(row[2])) if row else (None, None, None)
        )
        p_busy, p_log, p_ckpt = (
            (int(passive_row[0]), int(passive_row[1]), int(passive_row[2]))
            if passive_row
            else (None, None, None)
        )
        out = {
            "busy": busy,  # 1 = an active reader pinned the WAL: honest partial
            "log_frames": log_frames,
            "checkpointed_frames": ckpt_frames,
            "wal_bytes_before": bytes_before,
            "wal_bytes_after": bytes_after,
            "duration_ms": duration_ms,
            # S4.1: the passive step's own result. Separate keys, because a
            # busy TRUNCATE over a successful backfill and a busy TRUNCATE that
            # moved nothing are different outcomes, and the old record could not
            # tell them apart.
            "passive": {
                "busy": p_busy,
                "log_frames": p_log,
                "checkpointed_frames": p_ckpt,
            },
            # S4.1 + S2.6(b): when TRUNCATE comes back busy, this names the
            # candidate. Absent rather than zeroed when the instrument is not
            # attached -- see pool_watch.is_registered.
            "readers": _reader_snapshot(),
        }
        _LOG.info("wal checkpoint(TRUNCATE): %s", out)
        return out
    except WriteGateBusy as exc:
        # S2.5: NOT a failure -- another writer holds the gate, so the WAL stays
        # where it is and the next pass boundary tries again. Reported as its own
        # outcome rather than folded into None (which the run report reads as
        # "disabled / not due"): a checkpoint that could not run and one that was
        # never asked to run are opposite facts.
        _LOG.warning("wal checkpoint skipped: %s", exc)
        return {
            "skipped": "gate busy",
            "detail": str(exc),
            "waited_s": _ckpt_gate_timeout_s(),
        }
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
        # (None = disabled / not due / error; a dict with "skipped" = it was
        # REFUSED and by what — never a silent omission, and never the same
        # value for "could not run" and "was never asked to").
        out["wal_checkpoint"] = checkpoint_wal()
        return out
    except Exception:  # noqa: BLE001 - hygiene must never break the run loop
        _LOG.warning("pass hygiene failed; run loop continues", exc_info=True)
        return None
