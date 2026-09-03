"""Per-session high-water marks — the crashed session's OWN numbers.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS (2026-09-02, S0.4). ``forensics.previous_session_report`` reported
``last_collector_sample`` beside its unclean-end verdict, read as the last line of
``collect_perf.jsonl``. That file is appended by EVERY session, so by the time an
operator exports a bundle the "last sample" belongs to the *current* process — the
numbers a reader naturally attributes to the crash are the numbers of the run that
survived it. An OOM was "inferred" that way from the wrong process's memory.

So this module keeps a tiny sidecar that is scoped to ONE session: peak RSS, minimum
available memory, peak swap used, the last phase seen, and when. At boot the file is
read as the PREVIOUS session's record and then reset — so the previous session's own
peaks travel into the next boot's report, and nothing the current session does can
overwrite them.

HONESTY RULES BAKED IN
- A field that cannot be measured is OMITTED, never written as 0. ``rss_max_mb: 0``
  would read as "the process used no memory", which is the opposite of unmeasured
  (the recorded ``.get(key, 0)`` lesson).
- The writes are throttled and atomic (``os.replace``) but never fsynced: this is a
  forensic convenience, and an instrument on a periodic path must not become a load
  source (the 2026-08-06 run-journal lesson).
- Every call is best-effort. A sidecar that raises would be a second failure layered
  on the one it exists to explain.
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

from src.paths import data_dir

_LOG = logging.getLogger(__name__)

_FILE = "session_hwm.json"
# The sidecar is written at most this often. A high-water mark loses nothing by
# being persisted lazily: the marks live in memory and only the last flush before a
# kill is lost, which is bounded by this interval.
_MIN_WRITE_INTERVAL_S = 30.0

_LOCK = threading.Lock()
_MARKS: dict[str, Any] = {}
_LAST_WRITE = 0.0
_PREV: dict[str, Any] | None = None
_PREV_LOADED = False


def _path() -> Path:
    return data_dir() / _FILE


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _read() -> dict[str, Any] | None:
    try:
        got = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return got if isinstance(got, dict) else None


def _write(state: dict[str, Any]) -> None:
    try:
        tmp = _path().with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
        os.replace(tmp, _path())
    except OSError:
        _LOG.debug("could not persist %s", _FILE, exc_info=True)


def _readings() -> dict[str, float]:
    """Current RSS / available / swap-used in MB. A reading that cannot be taken is
    ABSENT from the dict — never present as zero."""
    out: dict[str, float] = {}
    try:
        import psutil
    except Exception:  # noqa: BLE001 - psutil is an optional extra
        return out
    try:
        out["rss_mb"] = round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001
        pass
    try:
        out["avail_mb"] = round(psutil.virtual_memory().available / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001
        pass
    try:
        # Swap is the reading that separates "the kernel killed us" from "the machine
        # thrashed": it was sampled NOWHERE in the app before this (2026-09-02 §1.3).
        out["swap_used_mb"] = round(psutil.swap_memory().used / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001
        pass
    return out


def capture_previous() -> dict[str, Any] | None:
    """Read the PREVIOUS session's marks and start this session's record.

    Call once at boot, before anything can observe. Returns the previous marks (or
    None when there are none — a first boot, or a removed file)."""
    global _PREV, _PREV_LOADED, _MARKS, _LAST_WRITE
    with _LOCK:
        if not _PREV_LOADED:
            _PREV = _read()
            _PREV_LOADED = True
        _MARKS = {"pid": os.getpid(), "started_at": _now()}
        _LAST_WRITE = 0.0
        _write(dict(_MARKS))
        return _PREV


def previous() -> dict[str, Any] | None:
    """The previous session's marks as captured at boot, or None."""
    if _PREV_LOADED:
        return _PREV
    return _read()


def observe(phase: str | None = None) -> None:
    """Fold one reading into this session's high-water marks. Best-effort, throttled.

    ``phase`` is a free-text label of what the app was doing (the collector pass, the
    pass tail, a restore). It is recorded as the LAST phase seen, so a crashed
    session's record says where it was, not only how big it got."""
    global _LAST_WRITE
    try:
        readings = _readings()
        now = time.monotonic()
        with _LOCK:
            if not _MARKS:
                _MARKS.update({"pid": os.getpid(), "started_at": _now()})
            rss = readings.get("rss_mb")
            if rss is not None:
                prev = _MARKS.get("rss_max_mb")
                if prev is None or rss > prev:
                    _MARKS["rss_max_mb"] = rss
            avail = readings.get("avail_mb")
            if avail is not None:
                prev_a = _MARKS.get("avail_min_mb")
                if prev_a is None or avail < prev_a:
                    _MARKS["avail_min_mb"] = avail
            swap = readings.get("swap_used_mb")
            if swap is not None:
                prev_s = _MARKS.get("swap_used_max_mb")
                if prev_s is None or swap > prev_s:
                    _MARKS["swap_used_max_mb"] = swap
            if phase:
                _MARKS["phase"] = phase
            _MARKS["last_ts"] = _now()
            due = (now - _LAST_WRITE) >= _MIN_WRITE_INTERVAL_S
            if due:
                _LAST_WRITE = now
                snapshot = dict(_MARKS)
            else:
                snapshot = {}
        if snapshot:
            _write(snapshot)
    except Exception:  # noqa: BLE001 - a forensic sidecar never raises into its caller
        _LOG.debug("session high-water observe failed", exc_info=True)


def flush() -> None:
    """Persist the marks now, regardless of the throttle (used at shutdown)."""
    global _LAST_WRITE
    try:
        with _LOCK:
            if not _MARKS:
                return
            _LAST_WRITE = time.monotonic()
            snapshot = dict(_MARKS)
        _write(snapshot)
    except Exception:  # noqa: BLE001
        _LOG.debug("session high-water flush failed", exc_info=True)


def current() -> dict[str, Any]:
    """This session's marks so far (a copy)."""
    with _LOCK:
        return dict(_MARKS)


def reset_for_tests() -> None:
    """Clear the module state. Test-only; the suite shares one process."""
    global _PREV, _PREV_LOADED, _MARKS, _LAST_WRITE
    with _LOCK:
        _PREV = None
        _PREV_LOADED = False
        _MARKS = {}
        _LAST_WRITE = 0.0
