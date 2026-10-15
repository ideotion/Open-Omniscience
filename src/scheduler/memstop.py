"""The clean stop: when the memory guard has stayed engaged and available memory has not come back, the app ends itself
deliberately and says why (question 22a, B2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY. The guard's pause stops NEW work; the memory the process already holds does not return. On the recorded 2026-09-30 plateau the
machine sat at 64 MB or less for 12 minutes and the kernel then killed the process with no trace of why. A stop the app chooses
keeps the evidence, ends the work through the path the power button uses (workers reaped, the pool disposed, SIGTERM to self, the
lifespan's own shutdown), and tells the person at the next start. Nothing in the corpus is touched.

THE CRITERION is ``memguard.stall_decision`` (pure, replayed against the recorded series); this module is only the sequence
that runs once it holds. ONE SHOT per process. EVERY STEP IS ISOLATED: a step that fails is logged and the rest still run,
because the machine is already in trouble and the evidence is worth more than a tidy exit. NO FORCED EXIT AND NO RELAUNCH: if the
kernel kills the teardown first, the next boot reads "ended during shutdown" with the reason, which is itself the evidence. A stop
that has begun is NOT cancelled by a recovery (the pause is what a recovery cancels; the stop has already taken the evidence).

THE RECORD (``memory_stop.json`` beside the data) holds numbers, step names and the guard's own words, never an engine's text and
never a thread's name: it is written before anything is released (a machine at 48 MB may not get a second write), and written
again, atomically, once the ladder has run. It rides the next start in the session-forensics member through
``forensics.previous_memory_stop``, which reads it back through an allow-list and states the size it read.

``OO_MEM_STOP=0`` turns the whole thing off (the guard still pauses).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.monitoring.secret_scrub import log_failure
from src.paths import data_dir

_LOG = logging.getLogger("scheduler.memstop")

#: The reason the sentinel and the ledger carry for this ending (``forensics.record_shutdown_phase(reason=...)``).
SHUTDOWN_REASON = "memory exhausted"
#: The scheduler's phase while the stop runs (the task manager words it, in every locale).
PHASE = "memory-stop"
#: How long the scheduler is given to stop taking new work before the shutdown starts (the pause a restore takes).
PAUSE_TIMEOUT_S = 10.0
#: How long the stop waits for an exclusive operation (an import run, a restore or merge) to finish before it goes on: its writes are
#: the user's data, and the normal shutdown path rolls an unfinished transaction back, so the wait is a courtesy to a write that is
#: nearly done, not a condition. What bounds it: the teardown needs room on a machine that is already at the floor.
EXCLUSIVE_WAIT_S = 60.0
EXCLUSIVE_POLL_S = 1.0
#: What the record may hold, so a reader (and the bundle) can count on its size: the file is read back through
#: :func:`read_record`, which keeps only these keys and states how many bytes it read.
RECORD_KEYS = (
    "kind",
    "session_id",
    "pid",
    "at",
    "uptime_s",
    "decision",
    "guard",
    "release_at_engage",
    "release_again",
    "exclusive",
    "scheduler_stopped",
    "steps",
    "bytes_written",
)

#: The most bytes the record may be, written and read. What it protects: the record rides the Diagnostics zip inside the
#: session-forensics member (zips stay under 4 MB, R119), and a stop is written on a machine at the floor, where a large write is
#: the one that does not finish. The largest record this code writes with every field full measures about 2 KB
#: (``tests/test_memstop_sequence.py``); the bound leaves room for the guard's reason and the step list to grow, not for text.
RECORD_MAX_BYTES = 8192

#: The most characters of the guard's own sentence ("only 48 MB of system memory available"): one line built from readings.
GUARD_REASON_CHARS = 200

_LOCK = threading.Lock()
_STARTED = False


def _path() -> Path:
    return data_dir() / "memory_stop.json"


def _write(record: dict[str, Any]) -> int | None:
    """Write the record atomically; returns the bytes written, or ``None`` when it could not be written. Never raises."""
    try:
        text = json.dumps(record, indent=1, default=str)
        if len(text.encode("utf-8")) > RECORD_MAX_BYTES:
            # Measured as it is written: over the bound, the bulky blocks go and the record SAYS they did, so the size is a fact
            # about what is in the file and never a surprise in the zip.
            dropped = [k for k in ("release_at_engage", "release_again", "guard") if k in record]
            record = {k: v for k, v in record.items() if k not in dropped}
            record["cut"] = {"left_out": dropped, "because": "the record was larger than the bound it is written within"}
            text = json.dumps(record, indent=1, default=str)
        tmp = _path().with_suffix(".json.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, _path())
        return len(text.encode("utf-8"))
    except OSError as exc:
        log_failure(_LOG, "memory stop: the record could not be written", exc, level=logging.WARNING)
        return None


def _step(record: dict[str, Any], name: str, fn) -> Any:
    """Run one step, isolated: its outcome (``ok`` or the exception's class) goes in ``record["steps"]``, its words in the log
    through ``log_failure``. Returns the step's value, or ``None`` when it raised."""
    t0 = time.monotonic()
    try:
        value = fn()
    except Exception as exc:  # noqa: BLE001 - every step is isolated; the rest still run
        log_failure(_LOG, f"memory stop: {name} failed", exc, level=logging.WARNING)
        record["steps"][name] = {"ok": False, "error": type(exc).__name__}
        return None
    record["steps"][name] = {"ok": True, "took_ms": round(1000 * (time.monotonic() - t0), 1)}
    return value


def _guard_numbers(guard: Any) -> dict[str, Any]:
    """The guard's own state as numbers (its reason is the guard's sentence, built from readings, never an exception)."""
    st = guard.state()
    last = st.get("last_reading") or {}
    return {
        "since": st.get("since"),
        "reason": str(st.get("reason") or "")[:GUARD_REASON_CHARS] or None,
        "engagements": st.get("engagements"),
        "thresholds": st.get("thresholds"),
        "rss_mb": last.get("rss_mb"),
        "mem_avail_mb": last.get("mem_avail_mb"),
        "mem_total_mb": last.get("mem_total_mb"),
        "proc_swap_mb": last.get("proc_swap_mb"),
    }


def _allow_listed(release: Any) -> Any:
    from src.monitoring.release_view import allow_listed

    return allow_listed(release)


def execute(decision: dict[str, Any], guard: Any) -> dict[str, Any] | None:
    """Run the clean stop ONCE. Returns the record, or ``None`` when a stop had already begun in this process.

    Called by the guard, outside its lock, on the thread that fed it the sample. Never raises."""
    global _STARTED
    with _LOCK:
        if _STARTED:
            return None
        _STARTED = True
    record: dict[str, Any] = {"kind": "memory-stop", "at": datetime.now(UTC).isoformat(timespec="seconds"), "steps": {}}
    try:
        from src.monitoring import session_history

        cur = session_history.current_session()
        record["session_id"] = cur.get("session_id")
        record["pid"] = os.getpid()
        record["uptime_s"] = cur.get("uptime_s")
    except Exception as exc:  # noqa: BLE001 - the identity is a nicety; the stop does not wait on it
        log_failure(_LOG, "memory stop: the session identity could not be read", exc, level=logging.DEBUG)
    _LOG.warning(
        "MEMORY STOP: the guard has stayed engaged and available memory has not come back (%s of %s readings at the floor); "
        "stopping the app to keep the corpus safe",
        decision.get("low_share"),
        decision.get("samples"),
    )
    record["decision"] = {k: v for k, v in decision.items() if k != "why"}
    record["guard"] = _step(record, "guard", lambda: _guard_numbers(guard))
    record["release_at_engage"] = _step(record, "release_record", lambda: _allow_listed(guard.last_release()))

    # 1. Evidence first: before anything is released, because a machine at 48 MB may not get a second write.
    def _snapshot() -> None:
        from src.monitoring import session_hwm

        session_hwm.observe(phase="memory stop", may_snapshot_threads=True, force_why="memory stop")
        session_hwm.flush()

    _step(record, "snapshot", _snapshot)

    def _event() -> None:
        from src.monitoring import session_history

        session_history.record_event("memory-stop", reason=SHUTDOWN_REASON, decision=record["decision"])

    _step(record, "ledger_event", _event)
    record["bytes_written"] = _write(record)

    # 2. The ladder once more, never to cancel the stop but to give the teardown room to finish.
    def _ladder() -> dict[str, Any] | None:
        from src.scheduler.release import release_residents

        return _allow_listed(release_residents())

    record["release_again"] = _step(record, "release_again", _ladder)

    # 3. No new work starts; the phase tells the person why the app is pausing.
    def _phase() -> None:
        from src.scheduler import runner

        runner._phase_set(PHASE)

    _step(record, "phase", _phase)

    def _pause() -> bool:
        from src.scheduler.runner import pause_for_exclusive_operation

        # False: the loop was not running, or it did not stop inside the bound (an operation in flight): said, not assumed.
        record["scheduler_stopped"] = bool(pause_for_exclusive_operation(PAUSE_TIMEOUT_S))
        return record["scheduler_stopped"]

    _step(record, "pause", _pause)

    # 3b. An exclusive operation in flight (the pause above cannot stop it): its transaction is the user's data. Wait for it to
    # close, bounded, and say what happened; then the NORMAL shutdown path runs (an unfinished transaction is rolled back, the
    # pool disposed, nothing forced).
    def _exclusive() -> None:
        from src.scheduler.runner import exclusive_window_open

        waited = 0.0
        open_at_start = bool(exclusive_window_open())
        while exclusive_window_open() and waited < EXCLUSIVE_WAIT_S:
            time.sleep(EXCLUSIVE_POLL_S)
            waited += EXCLUSIVE_POLL_S
        record["exclusive"] = {"open_at_start": open_at_start, "waited_s": waited, "still_open": bool(exclusive_window_open())}

    _step(record, "exclusive_wait", _exclusive)
    _write(record)

    # 4. The path the power button and the data-drive precedent use.
    def _phase_state() -> None:
        from src.monitoring import forensics

        forensics.record_shutdown_phase("shutting-down", reason=SHUTDOWN_REASON)

    _step(record, "sentinel", _phase_state)

    def _shutdown() -> None:
        from src.safety.shutdown import request_shutdown

        request_shutdown(confirm=True)

    _step(record, "shutdown", _shutdown)
    record["bytes_written"] = _write(record)
    return record


def reset_for_tests() -> None:
    """Allow a second stop in one process (tests only)."""
    global _STARTED
    with _LOCK:
        _STARTED = False


def read_record(session_id: str | None) -> dict[str, Any] | None:
    """The record of the stop that ended session ``session_id``, through the allow-list (:data:`RECORD_KEYS`), with the size read
    named (``bytes_read``); ``None`` when there is none, it is another session's, or it cannot be read. A record belongs to a
    session only if it names it: an older file never reads as the previous session's. Never raises."""
    try:
        raw = _path().read_bytes()
        got = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError):
        return None
    try:
        if not isinstance(got, dict) or not session_id or got.get("session_id") != session_id:
            return None
        out = {k: got[k] for k in RECORD_KEYS if k in got}
        if len(raw) > RECORD_MAX_BYTES:
            # Not a record this code wrote: its identity is kept and everything else is replaced by the size, named.
            out = {k: out[k] for k in ("kind", "session_id", "pid", "at", "uptime_s") if k in out}
            out["decision"] = {"cut": "the record was larger than the bound it is written within", "bytes": len(raw)}
        elif "cut" in got and isinstance(got["cut"], dict):
            out["cut"] = {k: got["cut"].get(k) for k in ("left_out", "because")}
        out["bytes_read"] = len(raw)
        return out
    except Exception:  # noqa: BLE001 - a diagnostic never fails its caller
        return None
