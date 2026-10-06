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

Honesty: counts and sizes only, written to ONE small JSON file in the data directory, replaced
atomically. No path, no term, no article. A marker that cannot be written or read never blocks a
build (a missing record is not evidence of a kill): the failure is logged and the build proceeds.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path

_LOG = logging.getLogger(__name__)

_FILENAME = "rollup_build.json"
#: Written into the marker so a reader of a future format can tell it apart.
FORMAT = 1
#: One id per process, so "written by this process" is told from "written by one that is gone"
#: without trusting a pid (a restart inside a container can reuse one).
_PROCESS_ID = uuid.uuid4().hex
#: At most one write this often while a build reports progress.
_WRITE_EVERY_S = 10.0

_last_write = 0.0


def _path() -> Path:
    from src.paths import data_dir

    return data_dir() / _FILENAME


def _write(record: dict) -> None:
    path = _path()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def begin(*, rss_mb: float | None, avail_mb: float | None, limit_mb: float | None) -> None:
    """Record that a build is starting, with what this process holds and what the machine has."""
    global _last_write
    try:
        _write({
            "format": FORMAT,
            "process": _PROCESS_ID,
            "started_at": time.time(),
            "stage": "start",
            "rows_done": 0,
            "rss_mb": rss_mb,
            "avail_mb": avail_mb,
            "duckdb_limit_mb": limit_mb,
            "written_at": time.time(),
        })
        _last_write = time.monotonic()
    except Exception:  # noqa: BLE001 - a marker that cannot be written must not stop the build
        _LOG.warning("rollup marker: could not write the in-progress record", exc_info=True)


def progress(stage: str, rows_done: int, *, rss_mb: float | None, avail_mb: float | None) -> None:
    """Refresh the record (throttled): the last readings before a kill are the ones that matter."""
    global _last_write
    if time.monotonic() - _last_write < _WRITE_EVERY_S:
        return
    try:
        rec = read()
        if rec is None or rec.get("process") != _PROCESS_ID:
            return  # not ours to refresh
        rec.update({
            "stage": stage, "rows_done": int(rows_done), "rss_mb": rss_mb,
            "avail_mb": avail_mb, "written_at": time.time(),
        })
        _write(rec)
        _last_write = time.monotonic()
    except Exception:  # noqa: BLE001
        _LOG.debug("rollup marker: progress write failed", exc_info=True)


def clear() -> None:
    """The build ended by a path Python saw (done, declined, failed): remove our record."""
    try:
        rec = read()
        if rec is not None and rec.get("process") != _PROCESS_ID:
            return  # a record of another process's build is not ours to remove
        _path().unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        _LOG.debug("rollup marker: clear failed", exc_info=True)


def read() -> dict | None:
    """The record on disk, or ``None`` when there is none or it cannot be read."""
    try:
        rec = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) and rec.get("format") == FORMAT else None


def killed_build() -> dict | None:
    """The record of a build that a DIFFERENT process started and never finished, else ``None``."""
    rec = read()
    if rec is None or rec.get("process") == _PROCESS_ID:
        return None
    return rec


def retry_verdict(avail_mb: float | None, floor_mb: float) -> dict | None:
    """A skip record while a killed build's footprint does not fit the machine now, else ``None``.

    The dead process held ``rss_mb`` at its last report; a retry needs that much available plus the
    guard's floor. An unreadable reading is no evidence either way, so it never blocks."""
    rec = killed_build()
    if rec is None or avail_mb is None:
        return None
    held = rec.get("rss_mb")
    if not isinstance(held, (int, float)):
        held = 0.0
    need = float(held) + float(floor_mb)
    if avail_mb >= need:
        return None
    return {
        "reason": "last_build_killed",
        "at": time.time(),
        "killed_stage": rec.get("stage"),
        "killed_rows_done": rec.get("rows_done"),
        "killed_started_at": rec.get("started_at"),
        "killed_rss_mb": rec.get("rss_mb"),
        "needs_available_mb": round(need, 1),
        "available_mb": avail_mb,
    }
