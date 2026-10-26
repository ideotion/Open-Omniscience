"""
The in-progress marker of a whole-corpus rollup build: how a killed build is told from a finished one.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why this exists (diagnostics of 2026-10-06): on eight 4.81 GiB VMs the in-memory keyword rollup
build was killed by the kernel 12 times in 4.7 days and started again, identically, after every
restart. A process that is killed leaves no record of what it was doing, so the next boot cannot tell
"the last build died" from "no build has run": this file is that record. A build writes it when it
starts, refreshes it as batches complete and removes it when it ends by any path Python can see (a
success, a clean decline, an error). A marker still on disk at the next boot, written by a
DIFFERENT process, therefore means the previous build was killed.

What a killed build costs is decided by MEASUREMENT, never by a count or a fixed pause: the marker
keeps the last resident size and available memory it saw, and a new build is allowed once the
machine has at least what the dead process held, plus the memory guard's own floor. A machine that
frees memory (or a build that now fits) retries by itself; one that does not is not sent into the
same kill again, and the reason and the numbers are visible in the diagnostics.

A NORMAL QUIT IS NOT A KILL: both build threads are daemon threads, so an orderly shutdown during a
build never reaches the build's ``finally``. ``begin`` therefore registers an ``atexit`` clear, which runs
on every exit Python gets to handle and never after a SIGKILL or the kernel's OOM killer, which is exactly
the difference this file exists to see.

SEVERAL SERVERS ON ONE DATA FOLDER (R176, R183): the record carries its owner (pid, start time, host, machine tag). A record whose owner is DEAD is a killed build (above). A record
whose owner is ALIVE, or one this machine cannot judge (another host on a shared drive), is a build RUNNING ELSEWHERE: it is not a kill, so it never holds this server back as one;
a second whole-corpus build beside it is what the memory guard exists to prevent, so it is declined, named ``build_running_elsewhere``, and tried again at the next request. A record
with no owner (written before this field existed) is judged as before: a different process's record is a killed build.

Honesty: counts and sizes only, written to ONE small JSON file in the data directory, replaced
atomically. No path, no term, no article. A marker that cannot be written or read never blocks a
build (a missing record is not evidence of a kill): the failure is logged and the build proceeds.
"""

from __future__ import annotations

import atexit
import json
import logging
import threading
import time
import uuid
from pathlib import Path

from src.monitoring.secret_scrub import log_failure
from src.safety import process_owner
from src.safety.file_lock import atomic_replace, file_lock

_LOG = logging.getLogger(__name__)

_FILENAME = "rollup_build.json"
#: Written into the marker so a reader of a future format can tell it apart.
FORMAT = 1
#: One id per process, so "written by this process" is told from "written by one that is gone"
#: without trusting a pid (a restart inside a container can reuse one).
_PROCESS_ID = uuid.uuid4().hex
#: At most one write this often while a build reports progress.
_WRITE_EVERY_S = 10.0

_last_write = float("-inf")
#: The largest resident size this process reported during the current build, and the one it began with.
#: The marker keeps the PEAK (a reading taken between two writes is otherwise lost), and the retry rule
#: asks for what the build GREW by, never for the app's own baseline a second time.
_peak_rss: float | None = None
_begin_rss: float | None = None
_exit_hook_registered = False
_last_stage: str | None = None


def _path() -> Path:
    from src.paths import data_dir

    return data_dir() / _FILENAME


#: Held for every write and for the exit clear. CPython runs ``atexit`` callbacks BEFORE it stops daemon
#: threads, so a build thread could otherwise write the marker back after the exit hook had removed it
#: (reproduced: 3 of 20 runs of a stand-in left the file behind after a normal exit).
_WRITE_LOCK = threading.Lock()
_closed = False


ELSEWHERE = "build_running_elsewhere"


def _write(record: dict) -> None:
    with _WRITE_LOCK:
        if _closed:
            return  # the process is exiting normally: nothing may put the marker back
        atomic_replace(_path(), json.dumps(record, sort_keys=True), fsync=False)


def _owner_state(rec: dict) -> str | None:
    """``alive`` / ``dead`` / ``unknown`` for the process that wrote ``rec``; ``None`` for a record with no owner field."""
    owner = rec.get("owner")
    if not isinstance(owner, dict) or not owner:
        return None
    return process_owner.record_state(owner, machine=process_owner.machine_tag())


def running_elsewhere() -> dict | None:
    """The record of a build ANOTHER process is running now (its owner alive, or one this machine cannot judge), else ``None``."""
    rec = read()
    if rec is None or rec.get("process") == _PROCESS_ID:
        return None
    return rec if _owner_state(rec) in ("alive", "unknown") else None


def _exit_clear() -> None:
    """The ``atexit`` hook: stop all later writes, then remove the record."""
    global _closed
    with _WRITE_LOCK:
        _closed = True
    clear()


def begin(*, rss_mb: float | None, avail_mb: float | None, limit_mb: float | None) -> bool:
    """Record that a build is starting, with what this process holds and what the machine has.

    Returns ``False`` without writing when another process's build is running (checked and claimed under one file lock, so two servers that passed the pre-build check
    together cannot both start); ``True`` otherwise, including when the record cannot be written (a missing record is not evidence of a kill)."""
    global _last_write, _peak_rss, _begin_rss, _exit_hook_registered, _last_stage
    _peak_rss = _begin_rss = rss_mb
    _last_stage = "start"
    if not _exit_hook_registered:
        _exit_hook_registered = True
        atexit.register(_exit_clear)
    try:
        with file_lock(_path()):
            if running_elsewhere() is not None:
                return False
            _write({
                "format": FORMAT,
                "process": _PROCESS_ID,
                "owner": process_owner.owner_record(),
                "started_at": time.time(),
                "stage": "start",
                "rows_done": 0,
                "rss_mb": rss_mb,
                "rss_begin_mb": rss_mb,
                "rss_peak_mb": rss_mb,
                "avail_mb": avail_mb,
                "duckdb_limit_mb": limit_mb,
                "written_at": time.time(),
            })
            _last_write = time.monotonic()
    except Exception as exc:  # noqa: BLE001 - a marker that cannot be written must not stop the build
        log_failure(_LOG, "rollup marker: could not write the in-progress record", exc, level=logging.WARNING)
    return True


def progress(stage: str, rows_done: int, *, rss_mb: float | None, avail_mb: float | None) -> None:
    """Refresh the record (throttled): the last readings before a kill are the ones that matter.

    The throttle is bypassed when the STAGE changes (the final aggregation is the build's peak and has no
    batches of its own), and the peak resident size seen since ``begin`` is kept even from the reads the
    throttle skipped."""
    global _last_write, _peak_rss, _last_stage
    if isinstance(rss_mb, (int, float)) and (_peak_rss is None or rss_mb > _peak_rss):
        _peak_rss = float(rss_mb)
    changed = stage != _last_stage
    _last_stage = stage
    if not changed and time.monotonic() - _last_write < _WRITE_EVERY_S:
        return
    try:
        with file_lock(_path()):  # read-change-write: a second server's begin() checks this file under the same lock
            rec = read()
            if rec is None or rec.get("process") != _PROCESS_ID:
                return  # not ours to refresh
            rec.update({
                "stage": stage, "rows_done": int(rows_done), "rss_mb": rss_mb,
                "rss_peak_mb": _peak_rss, "avail_mb": avail_mb, "written_at": time.time(),
            })
            _write(rec)
        _last_write = time.monotonic()
    except Exception as exc:  # noqa: BLE001
        log_failure(_LOG, "rollup marker: progress write failed", exc, level=logging.DEBUG)


def clear() -> None:
    """The build ended by a path Python saw (done, declined, failed): remove our record."""
    try:
        with file_lock(_path()):
            rec = read()
            if rec is not None and rec.get("process") != _PROCESS_ID:
                return  # a record of another process's build is not ours to remove
            _path().unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        log_failure(_LOG, "rollup marker: clear failed", exc, level=logging.DEBUG)


def read() -> dict | None:
    """The record on disk, or ``None`` when there is none or it cannot be read."""
    try:
        rec = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) and rec.get("format") == FORMAT else None


def killed_build() -> dict | None:
    """The record of a build that a DIFFERENT process started and never finished (its owner is dead, or the record names none), else ``None``."""
    rec = read()
    if rec is None or rec.get("process") == _PROCESS_ID:
        return None
    return rec if _owner_state(rec) in (None, "dead") else None


def retry_verdict(avail_mb: float | None, floor_mb: float) -> dict | None:
    """A skip record while a killed build's growth does not fit the machine now, else ``None``.

    What the dead build ADDED to its process is its peak resident size minus the size it began with
    (the app's own baseline is already taken out of the available figure by the new process, so counting
    it again would make an ordinary restart look unaffordable); a retry needs that much available plus
    the guard's floor. An unreadable reading is no evidence either way, so it never blocks."""
    elsewhere = running_elsewhere()
    if elsewhere is not None:
        return {
            "reason": ELSEWHERE,
            "at": time.time(),
            "other_started_at": elsewhere.get("started_at"),
            "other_stage": elsewhere.get("stage"),
            "other_rows_done": elsewhere.get("rows_done"),
            "other_written_at": elsewhere.get("written_at"),
        }
    rec = killed_build()
    if rec is None or avail_mb is None:
        return None
    peak = rec.get("rss_peak_mb", rec.get("rss_mb"))
    begin = rec.get("rss_begin_mb")
    if not isinstance(peak, (int, float)):
        peak = 0.0
    grew = max(0.0, float(peak) - float(begin if isinstance(begin, (int, float)) else 0.0))
    need = grew + float(floor_mb)
    if avail_mb >= need:
        return None
    return {
        "reason": "last_build_killed",
        "at": time.time(),
        "killed_stage": rec.get("stage"),
        "killed_rows_done": rec.get("rows_done"),
        "killed_started_at": rec.get("started_at"),
        "killed_rss_mb": peak,
        "killed_grew_mb": round(grew, 1),
        "needs_available_mb": round(need, 1),
        "available_mb": avail_mb,
    }
