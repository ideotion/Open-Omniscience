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
available memory, peak swap used, the last phase seen, and when -- and, since
2026-09-26, what the memory was MADE OF at the peak (``at_peak``: anonymous vs
file-backed RSS, how much was swapped out, glibc's heap in use vs free-but-held,
CPython's allocated blocks, the thread count). Two field instances died at 2.8 GB on
4 GB machines, and "how big" alone could not say whether that was Python objects, C
memory in use, or memory freed and never returned. At boot the file is
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

import ctypes
import json
import logging
import os
import sys
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
# What the memory is MADE OF is re-read at a new RSS peak, at most this often.
_MIN_COMPOSITION_INTERVAL_S = 30.0
# glibc's heap walk touches free chunks all over the heap, so on a machine that is
# already swapping it would page them back in at the worst moment. Below this share of
# available memory only the kernel's own counters (which touch nothing) are read.
_HEAP_WALK_MIN_AVAIL_SHARE = 0.15

_LOCK = threading.Lock()
_MARKS: dict[str, Any] = {}
_LAST_WRITE = 0.0
_LAST_COMPOSITION = 0.0
_PREV: dict[str, Any] | None = None
_PREV_LOADED = False

# /proc/self/status fields -> the names the record uses (all in kB there).
_STATUS_FIELDS = {
    "RssAnon": "rss_anon_mb",
    "RssFile": "rss_file_mb",
    "RssShmem": "rss_shmem_mb",
    "VmSwap": "swapped_out_mb",
}


class _MallInfo2(ctypes.Structure):
    """glibc's ``struct mallinfo2`` (2.33+): size_t fields, so no 2 GiB wrap."""

    _fields_ = [
        (name, ctypes.c_size_t)
        for name in (
            "arena", "ordblks", "smblks", "hblks", "hblkhd",
            "usmblks", "fsmblks", "uordblks", "fordblks", "keepcost",
        )
    ]


def _glibc_heap() -> dict[str, float] | None:
    """glibc's own account of its heap: bytes in use vs bytes FREE BUT HELD.

    The second number is the one that separates a leak from fragmentation: memory a
    many-threaded process freed but glibc's per-thread arenas never returned to the
    system still counts as RSS. None on anything but glibc 2.33+ (musl, macOS,
    Windows) -- absent, never zero."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        fn = ctypes.CDLL(None).mallinfo2
    except (OSError, AttributeError):
        return None
    fn.restype = _MallInfo2
    fn.argtypes = []
    mi = fn()
    mb = 1024 * 1024
    return {
        "heap_in_use_mb": round(mi.uordblks / mb, 1),
        "heap_free_held_mb": round(mi.fordblks / mb, 1),
        "heap_mmapped_mb": round(mi.hblkhd / mb, 1),
    }


def composition(*, walk_heap: bool = True) -> dict[str, Any]:
    """What this process's resident memory is made of, right now.

    From the kernel's counters: anonymous vs file-backed RSS, how much of the process
    is swapped out, the thread count. From glibc (when ``walk_heap``): heap in use vs
    free-but-held. From CPython: allocated blocks. Every reading that cannot be taken
    is absent. This is what tells a crash at 2.8 GB apart: Python objects, C memory
    in use (SQLite caches, parsers), or memory freed but never given back."""
    out: dict[str, Any] = {}
    try:
        text = Path("/proc/self/status").read_text(encoding="ascii", errors="replace")
        for line in text.splitlines():
            key, _, value = line.partition(":")
            parts = value.split()
            if not parts:
                continue
            if key in _STATUS_FIELDS:
                out[_STATUS_FIELDS[key]] = round(int(parts[0]) / 1024, 1)
            elif key == "Threads":
                out["threads"] = int(parts[0])
    except (OSError, ValueError):
        pass
    if walk_heap:
        try:
            heap = _glibc_heap()
        except Exception:  # noqa: BLE001 - an optional reading
            heap = None
        if heap:
            out.update(heap)
    blocks = getattr(sys, "getallocatedblocks", None)  # CPython only
    if blocks is not None:
        out["py_alloc_blocks"] = blocks()
    return out


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


def _heap_walk_is_safe(readings: dict[str, float]) -> bool:
    """False once available memory is below ``_HEAP_WALK_MIN_AVAIL_SHARE`` of RAM (or
    cannot be read): then only the kernel's counters are taken, never the heap walk."""
    avail = readings.get("avail_mb")
    if avail is None:
        return False
    try:
        import psutil

        total_mb = psutil.virtual_memory().total / (1024 * 1024)
    except Exception:  # noqa: BLE001
        return False
    return total_mb > 0 and avail / total_mb >= _HEAP_WALK_MIN_AVAIL_SHARE


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
    global _LAST_WRITE, _LAST_COMPOSITION
    try:
        readings = _readings()
        now = time.monotonic()
        # At a new RSS peak, what the memory is made of (2026-09-26). Read OUTSIDE the
        # lock -- the heap walk is the slow part -- and at most once per interval.
        at_peak = None
        rss = readings.get("rss_mb")
        if rss is not None and (now - _LAST_COMPOSITION) >= _MIN_COMPOSITION_INTERVAL_S:
            with _LOCK:
                peak_so_far = _MARKS.get("rss_max_mb")
            if peak_so_far is None or rss > peak_so_far:
                _LAST_COMPOSITION = now
                at_peak = composition(walk_heap=_heap_walk_is_safe(readings))
                at_peak["rss_mb"] = rss
                at_peak["at"] = _now()
        with _LOCK:
            if not _MARKS:
                _MARKS.update({"pid": os.getpid(), "started_at": _now()})
            if at_peak is not None:
                _MARKS["at_peak"] = at_peak
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
    global _PREV, _PREV_LOADED, _MARKS, _LAST_WRITE, _LAST_COMPOSITION
    with _LOCK:
        _PREV = None
        _PREV_LOADED = False
        _MARKS = {}
        _LAST_WRITE = 0.0
        _LAST_COMPOSITION = 0.0
