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
memory in use, or memory freed and never returned. The same day added the question
after that one: WHO. The fatal stretch on one of them was a burst -- +15 M Python
blocks and +930 MB in 45 s, on top of a slow climb -- and nothing recorded which code
was running. So once available memory falls below a line, a second sidecar
(``session_pressure.json``) keeps what EVERY THREAD was doing, by name, with its CPU
time: at the crossing and at each new low below it, written through at once, the
newest few kept. At boot both files are read as the PREVIOUS session's record and
then reset — so the previous session's own peaks travel into the next boot's report,
and nothing the current session does can overwrite them.

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
import types
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

# Below this share of RAM available (at most _PRESSURE_CAP_MB), what every thread is
# doing is recorded. On a 4 GB machine that is ~590 MB: in the field burst it would
# have fired 11 s before the memory guard engaged and ~30 s before the death.
_PRESSURE_FILE = "session_pressure.json"
_PRESSURE_AVAIL_SHARE = 0.15
_PRESSURE_CAP_MB = 1024.0
# One snapshot at the crossing, then one at each new low this share of the line further
# down, until memory is back above the line by the re-arm margin. A machine that sits
# under the line all day records its crossing, not a snapshot every few seconds; a
# machine in a fatal slide records the slide (~20 MB/s in the field: one every tick).
_PRESSURE_STEP_SHARE = 0.125
_PRESSURE_REARM_SHARE = 1.25
_PRESSURE_MIN_INTERVAL_S = 4.0
# The NEWEST are kept: the last ones before a death are the ones that name its cause.
_PRESSURE_KEEP = 8
# A thread whose innermost frame is in one of these is waiting, not working: a lock, a
# queue, a socket, the event loop's select.
_WAITING_IN = ("threading.py", "queue.py", "selectors.py", "socket.py", "ssl.py")
# How much of each thread's stack is kept: the innermost frame (where it IS), then the
# innermost frames of the app's own code (what it is doing it FOR).
_STACK_APP_FRAMES = 5
_STACK_WALK_MAX = 80
# The app's own source directory, as its modules' code objects name it.
_APP_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")

_LOCK = threading.Lock()
_MARKS: dict[str, Any] = {}
_LAST_WRITE = 0.0
_LAST_COMPOSITION = 0.0
_LAST_PRESSURE = 0.0
_PRESSURE: list[dict[str, Any]] = []
_PRESSURE_TAKEN = 0
_EPISODE_LOW: float | None = None  # lowest available at a snapshot; None = no episode
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


def _short_path(filename: str) -> str:
    """``src/...`` for the app's own code, ``pkg/...`` for an installed package, the
    bare name for the standard library -- short enough to read, exact enough to find.
    The app's code is recognised by its real directory, not by a ``/src/`` anywhere in
    the path: a Python built under ``/usr/local/src`` is not the app."""
    f = filename.replace("\\", "/")
    if f.startswith(_APP_SRC + "/"):
        return "src/" + f[len(_APP_SRC) + 1:]
    for marker in ("/site-packages/", "/dist-packages/"):
        if marker in f:
            return f.rsplit(marker, 1)[1]
    return f.rsplit("/", 1)[-1]


def _frame_line(frame: types.FrameType) -> str:
    return f"{_short_path(frame.f_code.co_filename)}:{frame.f_lineno} {frame.f_code.co_name}"


def _thread_cpu(tids: list[int]) -> dict[int, float]:
    """CPU seconds (user + system) of the given kernel thread ids; a thread whose time
    cannot be read is absent.

    Only the threads asked for: every file read releases the GIL, and under a thread
    that holds it (the very burst being recorded) each one waits a switch interval --
    psutil's scan of all forty-odd threads measured 0.5-0.7 s that way, against a few
    ms for the handful that are working. On Linux one ``/proc`` read each; elsewhere
    psutil, whose thread list there is one native call (on macOS its ids are not the
    ones ``threading`` reports, so nothing matches and the time is absent)."""
    out: dict[int, float] = {}
    if not tids:
        return out
    if sys.platform.startswith("linux"):
        try:
            tick = float(os.sysconf("SC_CLK_TCK"))
        except (ValueError, OSError):
            return out
        for tid in tids:
            try:
                raw = Path(f"/proc/self/task/{tid}/stat").read_bytes()
                # fields after the ")" that closes the name: utime and stime are the
                # 12th and 13th (fields 14 and 15 of proc(5)), in clock ticks
                fields = raw.rsplit(b")", 1)[1].split()
                out[tid] = round((int(fields[11]) + int(fields[12])) / tick, 1)
            except (OSError, IndexError, ValueError):
                continue
        return out
    try:
        import psutil

        want = set(tids)
        for t in psutil.Process().threads():
            if int(t.id) in want:
                out[int(t.id)] = round(float(t.user_time) + float(t.system_time), 1)
    except Exception:  # noqa: BLE001 - CPU time is an optional reading
        return {}
    return out


def _is_waiting(innermost: str) -> bool:
    return innermost.split(":", 1)[0] in _WAITING_IN


def thread_snapshot() -> list[dict[str, Any]]:
    """Every thread's name and where it is; the working ones with their CPU time,
    busiest first.

    Where it is: the innermost frame, then up to ``_STACK_APP_FRAMES`` of the app's own
    frames above it (innermost first), so a thread inside SQLAlchemy still says which
    app function asked. Thread NAMES are the point -- ``oo-wiki-drain``, ``AnyIO worker
    thread``, the collector's workers -- which a faulthandler dump does not print. A
    thread whose innermost frame is a lock, a queue, a socket or the event loop's
    select is marked ``waiting``; the others get their CPU time (user + system, from
    the kernel; absent where it cannot be read) and ``tid``, the kernel's thread id,
    lets a reader take the CPU spent BETWEEN two snapshots. The frames are listed
    before any read that can wait on the GIL, so the stacks are the ones of the moment
    the snapshot was asked for (a line number is read as the stack is written out)."""
    frames = sys._current_frames()
    by_ident = {t.ident: t for t in threading.enumerate()}
    me = threading.get_ident()
    out: list[dict[str, Any]] = []
    for ident, frame in frames.items():
        thread = by_ident.get(ident)
        entry: dict[str, Any] = {"name": thread.name if thread else f"thread {ident}"}
        native = getattr(thread, "native_id", None) if thread else None
        if native is not None:
            entry["tid"] = native
        if ident == me:
            entry["sampler"] = True
        stack = [_frame_line(frame)]
        f: types.FrameType | None = frame.f_back
        seen = 0
        app_frames = 1 if stack[0].startswith("src/") else 0
        # With no app frame at all (a server loop, an idle pool worker), the thread's
        # own entry point is the next best name for what it is.
        entry_point: str | None = None
        while f is not None and seen < _STACK_WALK_MAX and app_frames < _STACK_APP_FRAMES:
            line = _frame_line(f)
            if line.startswith("src/"):
                stack.append(line)
                app_frames += 1
            elif not line.startswith("threading.py"):
                entry_point = line
            f = f.f_back
            seen += 1
        if app_frames == 0 and entry_point and entry_point != stack[0]:
            stack.append(entry_point)
        entry["stack"] = stack
        if _is_waiting(stack[0]):
            entry["waiting"] = True
        out.append(entry)
    del frames
    cpu = _thread_cpu([
        e["tid"] for e in out if "tid" in e and not e.get("waiting") and not e.get("sampler")
    ])
    for e in out:
        if e.get("tid") in cpu:
            e["cpu_s"] = cpu[e["tid"]]
    out.sort(key=lambda e: -(e.get("cpu_s") or 0.0))
    return out


def _pressure_line_mb(total_mb: float) -> float:
    return min(total_mb * _PRESSURE_AVAIL_SHARE, _PRESSURE_CAP_MB)


def _path() -> Path:
    return data_dir() / _FILE


def _pressure_path() -> Path:
    return data_dir() / _PRESSURE_FILE


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _read(path: Path | None = None) -> dict[str, Any] | None:
    try:
        got = json.loads((path or _path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return got if isinstance(got, dict) else None


def _write(state: dict[str, Any], path: Path | None = None) -> None:
    target = path or _path()
    try:
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        _LOG.debug("could not persist %s", target.name, exc_info=True)


def _read_record() -> dict[str, Any] | None:
    """The marks file, with the SAME session's pressure snapshots folded in.

    The pressure file is matched on pid and start time: one left behind by an older
    session (a failed reset) must never be read as the crashed session's."""
    got = _read()
    if got is None:
        return None
    pressure = _read(_pressure_path())
    if (
        pressure
        and pressure.get("pid") == got.get("pid")
        and pressure.get("started_at") == got.get("started_at")
        and isinstance(pressure.get("snapshots"), list)
    ):
        got["pressure"] = pressure["snapshots"]
        got["pressure_taken"] = pressure.get("taken")
    return got


def _readings() -> dict[str, float]:
    """Current RSS / available / total / swap-used in MB. A reading that cannot be
    taken is ABSENT from the dict — never present as zero."""
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
        vm = psutil.virtual_memory()
        out["avail_mb"] = round(vm.available / (1024 * 1024), 1)
        out["total_mb"] = round(vm.total / (1024 * 1024), 1)
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
    total_mb = readings.get("total_mb")
    if avail is None or not total_mb:
        return False
    return avail / total_mb >= _HEAP_WALK_MIN_AVAIL_SHARE


def _pressure_due(readings: dict[str, float], now: float) -> bool:
    """Whether this reading earns a snapshot, and if so CLAIM it (under the lock, so
    the collector's monitor and the liveness thread never take the same one twice).

    Due at the crossing below the line, and at each new low a step further down; the
    episode ends once memory is back above the line by the re-arm margin."""
    global _LAST_PRESSURE, _EPISODE_LOW
    avail = readings.get("avail_mb")
    total = readings.get("total_mb")
    if avail is None or not total:
        return False
    line = _pressure_line_mb(total)
    with _LOCK:
        if _EPISODE_LOW is not None and avail > line * _PRESSURE_REARM_SHARE:
            _EPISODE_LOW = None
        if avail > line:
            return False
        if _EPISODE_LOW is not None and avail > _EPISODE_LOW - line * _PRESSURE_STEP_SHARE:
            return False
        if (now - _LAST_PRESSURE) < _PRESSURE_MIN_INTERVAL_S:
            return False
        _LAST_PRESSURE = now
        _EPISODE_LOW = avail
        return True


def _pressure_snapshot(readings: dict[str, float]) -> dict[str, Any]:
    """What every thread was doing, with the memory readings it was taken at."""
    total = readings["total_mb"]
    snap: dict[str, Any] = {
        "at": _now(),
        "avail_mb": readings["avail_mb"],
        "total_mb": total,
        "line_mb": round(_pressure_line_mb(total), 1),
    }
    for key in ("rss_mb", "swap_used_mb"):
        if readings.get(key) is not None:
            snap[key] = readings[key]
    # The kernel's counters only: the heap walk is exactly what a short machine must
    # not do (see _HEAP_WALK_MIN_AVAIL_SHARE).
    snap["memory"] = composition(walk_heap=False)
    snap["threads"] = thread_snapshot()
    return snap


def capture_previous() -> dict[str, Any] | None:
    """Read the PREVIOUS session's marks and start this session's record.

    Call once at boot, before anything can observe. Returns the previous marks (or
    None when there are none — a first boot, or a removed file)."""
    global _PREV, _PREV_LOADED, _MARKS, _LAST_WRITE, _PRESSURE, _PRESSURE_TAKEN
    global _EPISODE_LOW, _LAST_PRESSURE
    with _LOCK:
        if not _PREV_LOADED:
            _PREV = _read_record()
            _PREV_LOADED = True
        _MARKS = {"pid": os.getpid(), "started_at": _now()}
        _LAST_WRITE = 0.0
        _PRESSURE, _PRESSURE_TAKEN, _EPISODE_LOW, _LAST_PRESSURE = [], 0, None, 0.0
        _write(dict(_MARKS))
        try:
            _pressure_path().unlink(missing_ok=True)
        except OSError:
            _LOG.debug("could not reset %s", _PRESSURE_FILE, exc_info=True)
        return _PREV


def previous() -> dict[str, Any] | None:
    """The previous session's marks as captured at boot, or None."""
    if _PREV_LOADED:
        return _PREV
    return _read_record()


def observe(phase: str | None = None, *, may_snapshot_threads: bool = False) -> None:
    """Fold one reading into this session's high-water marks. Best-effort, throttled.

    ``phase`` is a free-text label of what the app was doing (the collector pass, the
    pass tail, a restore). It is recorded as the LAST phase seen, so a crashed
    session's record says where it was, not only how big it got.

    ``may_snapshot_threads`` is for the session ledger's liveness thread alone. Under
    a burst that holds the GIL a snapshot measured 0.3-0.6 s, which that thread can
    spare and the collector's monitor -- which feeds the memory guard every 1.5 s, at
    exactly that moment -- cannot."""
    global _LAST_WRITE, _LAST_COMPOSITION, _PRESSURE_TAKEN
    try:
        readings = _readings()
        now = time.monotonic()
        pressure = None
        if may_snapshot_threads and _pressure_due(readings, now):
            pressure = _pressure_snapshot(readings)
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
            pressure_doc: dict[str, Any] = {}
            if pressure is not None:
                _PRESSURE.append(pressure)
                del _PRESSURE[:-_PRESSURE_KEEP]
                _PRESSURE_TAKEN += 1
                _MARKS["pressure_taken"] = _PRESSURE_TAKEN
                pressure_doc = {
                    "pid": _MARKS.get("pid"),
                    "started_at": _MARKS.get("started_at"),
                    "taken": _PRESSURE_TAKEN,
                    "kept": _PRESSURE_KEEP,
                    "snapshots": list(_PRESSURE),
                }
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
            # A pressure snapshot is written through at once, with the marks beside it:
            # the process it describes may be killed before the throttle comes round.
            due = bool(pressure_doc) or (now - _LAST_WRITE) >= _MIN_WRITE_INTERVAL_S
            if due:
                _LAST_WRITE = now
                snapshot = dict(_MARKS)
            else:
                snapshot = {}
        if pressure_doc:
            _write(pressure_doc, _pressure_path())
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
    """This session's marks so far (a copy), with its pressure snapshots when any."""
    with _LOCK:
        out = dict(_MARKS)
        if _PRESSURE:
            out["pressure"] = list(_PRESSURE)
        return out


def reset_for_tests() -> None:
    """Clear the module state. Test-only; the suite shares one process."""
    global _PREV, _PREV_LOADED, _MARKS, _LAST_WRITE, _LAST_COMPOSITION, _LAST_PRESSURE
    global _PRESSURE, _PRESSURE_TAKEN, _EPISODE_LOW
    with _LOCK:
        _PREV = None
        _PREV_LOADED = False
        _MARKS = {}
        _LAST_WRITE = 0.0
        _LAST_COMPOSITION = 0.0
        _LAST_PRESSURE = 0.0
        _PRESSURE = []
        _PRESSURE_TAKEN = 0
        _EPISODE_LOW = None
