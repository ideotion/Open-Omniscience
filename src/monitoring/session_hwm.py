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
CPython's allocated blocks, the thread count; and ``heap_at_peak``, the newest peak that
read glibc's heap, because a peak taken with memory already short skips that walk and
the last one before an out-of-memory death usually is such a peak). Two field instances
died at 2.8 GB on 4 GB machines, and "how big" alone could not say whether that was
Python objects, C memory in use, or memory freed and never returned. The same day added
the question after that one: WHO. The fatal stretch on one of them was a burst -- +15 M
Python blocks and +930 MB in 45 s, on top of a slow climb -- and nothing recorded which
code was running. So once available memory falls below a line, a second sidecar
(``session_pressure.json``) keeps what EVERY THREAD was doing, by name, with its CPU
time: at the crossing and at each new low below it, and at a burst of Python allocation
(another instance built and freed millions of objects every 40 s with memory flat),
written through at once, the newest few kept. At boot both files are read as the
PREVIOUS session's record and then reset — so the previous session's own peaks travel
into the next boot's report, and nothing the current session does can overwrite them.

Since 2026-10-01 (R114) the record also says which C allocator the session ran on and
whether its malloc arenas were capped (``allocator``): ``scripts/launch.sh`` starts the app
with ``MALLOC_ARENA_MAX=2``, only instances launched since an update carry it, and
"freed but held" memory (``heap_free_held_mb``) can only be read against the setting the
process started with.

Since 2026-10-01 a machine that STAYS short is recorded too. The crash that began 091717's
last night was a 17-minute plateau at 44-60 MB available with the memory guard engaged: the
slide into it was snapshotted (one per new low), the plateau -- where whatever was holding
the memory could be read -- was not, by design ("none while memory sits on a plateau"). So
the moment the memory guard engages is its own snapshot, and a machine that is still below
the line, or still engaged, is snapshotted again every ``_PLATEAU_INTERVAL_S``. A
snapshot taken while the guard was engaged says so (a ``guard`` block); one without it was taken
with the guard not engaged, off or unreadable, which this record does not tell apart.

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
import re
import sys
import threading
import time
import types
from collections.abc import Iterable
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
# A BURST of Python allocation is the other trigger: at least this many blocks gained
# between two of the liveness thread's readings (5 s apart). One field instance built
# and freed 3-7 M blocks every 40 s for hours, with available memory flat because the
# memory was being reused -- the line above never fired, and that churn is exactly
# what the snapshot exists to name. Normal collection moves by tens of thousands.
_BURST_BLOCKS = 1_000_000
# A burst that recurs every 40 s is one burst: at most one snapshot of it this often.
_BURST_MIN_INTERVAL_S = 300.0
# A machine that STAYS below the line (or with the memory guard engaged) is snapshotted again
# this often. A snapshot is 0.3-0.6 s of the liveness thread when a burst holds the GIL, plus a
# write-through of a small file, and a machine can sit short for days: every few seconds would
# make the instrument a load source on exactly the machine it watches, and one a day would miss
# a plateau of 17 minutes (the 091717 kill came 19 minutes after the guard engaged). Five minutes
# gives that plateau three snapshots and a day-long one a bounded 288, of which the newest
# ``_PRESSURE_KEEP`` stay on disk. Only the readings that already cost nothing are taken here:
# the kernel's counters and ``sys.getallocatedblocks()`` (a counter); never a walk of the
# heap's objects, which at 90 million blocks is the very work that could end the process.
_PLATEAU_INTERVAL_S = 300.0
# NEAR the memory guard's line, a LIGHT snapshot is taken far more often, because the heavy cadence
# above (five minutes) lets a kill come between two of them: the October VMs died within seconds of
# the last one, and a fatal slide measured ~20 MB/s, which is under 20 s from 384 MB available to
# none. "Near" is within 1.5 times the guard's own line (available memory at most 1.5 times its
# floor, or the process at least 1/1.5 of the share of RAM at which it trips), or the guard
# engaged. A light snapshot is the kernel's counters, the Python block count and what it gained
# since the previous light one, and the few threads that spent the most CPU since then, each with
# its stack: no walk of every thread, no heap. It is kept in its OWN ring and file, so a day of them
# never pushes the heavy snapshots out, and the heavy cadence is unchanged. A per-thread MEMORY
# figure cannot be had cheaply (CPython has no per-thread heap accounting and ``tracemalloc``
# multiplies the cost of every allocation on the machine about to be killed), so the blocks the
# process gained sit beside each thread's CPU delta and the pairing is labelled an INFERENCE.
_LIGHT_FILE = "session_pressure_light.json"
_LIGHT_INTERVAL_S = 15.0
_LIGHT_NEAR_FACTOR = 1.5
_LIGHT_KEEP = 8
_LIGHT_THREADS = 3
# CPU is read for at most this many working threads: every read waits for the GIL under a burst
# (see ``_thread_cpu``), so the cost is bounded by this, not by the thread count.
_LIGHT_CPU_CANDIDATES = 16
# Bytes kept back in :func:`diagnostics_member` for the digits of the counts it fills in after measuring.
_MEMBER_SLACK = 32
# What the light snapshots are, stated beside them wherever they are shown.
_LIGHT_METHOD = (
    "taken at most every 15 s (a tick that a heavy snapshot takes is skipped, so the gap can be "
    "longer) while available memory is within 1.5 times the memory guard's floor, the process "
    "holds at least 1/1.5 of the share of RAM at which the guard trips, or the guard is engaged: "
    "the kernel's memory counters, the Python block count and the blocks gained since the previous "
    "light snapshot (over_s says over how long, for the threads' CPU too), and the threads that "
    "spent the most CPU in that time, with their stacks, chosen among the first 16 working threads "
    "found (cpu_asked_for says how many the CPU was asked for and cpu_read_for how many it was read "
    "for, of working_threads; where the platform cannot read a thread's CPU, thread_cpu says so and "
    "the threads are not ranked). Memory is not measured per thread (CPython has no such counter): "
    "the pairing of the blocks gained with the busiest threads is an INFERENCE about who allocated. "
    "took_ms is the time to take the readings and choose the threads; writing the file is not in it. "
    "The file is replaced whole and atomically (it survives the process being killed) but is not "
    "fsynced: a hard stop of the machine itself can lose the newest seconds, or, on a filesystem that "
    "does not flush a replaced file when it is renamed, the whole file; and a replace that another "
    "program's hold on the file refuses (Windows) leaves that snapshot unwritten, with a log line."
)
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
# "Never", for the monotonic times of the last write, composition, snapshot and burst.
# Not 0.0: time.monotonic() counts from the MACHINE's boot, so 0.0 reads as "a moment
# ago" for an app started with its machine, and the first burst of its first five
# minutes was never snapshotted (found 2026-09-27 as two tests failing on a 284 s host).
_NEVER = float("-inf")
_LAST_WRITE = _NEVER
_LAST_COMPOSITION = _NEVER
_LAST_PRESSURE = _NEVER
_PRESSURE: list[dict[str, Any]] = []
_PRESSURE_TAKEN = 0
_EPISODE_LOW: float | None = None  # lowest available at a snapshot; None = no episode
_LAST_BLOCKS: tuple[float, int] | None = None  # (monotonic, blocks) at the last liveness read
_LAST_BURST = _NEVER
_GUARD_WAS_ENGAGED = False  # the memory guard's state at the previous liveness reading
_LIGHT: list[dict[str, Any]] = []
_LIGHT_TAKEN = 0
_LIGHT_FAILED = 0  # light snapshots that raised, this session (their count is in the marks)
_LAST_LIGHT = _NEVER
_LIGHT_BASELINE: dict[str, Any] | None = None  # {"at", "blocks", "cpu": {tid: s}} of the last light one
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


_ARENA_VAR = "MALLOC_ARENA_MAX"
_TUNABLES_VAR = "GLIBC_TUNABLES"
_PRELOAD_VAR = "LD_PRELOAD"
_STARTING_ENVIRONMENT = "the environment the process started with"

# Malloc replacements people preload to tame glibc's memory behaviour. They have no glibc
# arenas, so MALLOC_ARENA_MAX does nothing to them. Matched against the base name of a file the
# process has LOADED (``_loaded_files``); ``tbbmalloc_proxy`` is the one of Intel's two libraries
# that takes malloc over, and ``libtbbmalloc`` alone, which a threading runtime may load, does not.
_MALLOC_REPLACEMENTS = ("jemalloc", "tcmalloc", "mimalloc", "tbbmalloc_proxy", "snmalloc", "scudo")

# What glibc 2.39 was MEASURED to read as the same number a person would: blanks and tabs may
# come first; a leading 0 is read as octal ("010" is 8, "08" is ignored), 0x as hex, a value
# with anything after its digits (a trailing blank too) is ignored, and so is one that
# overflows. Only the plain decimal form is claimed; 18 digits stay well inside a 64-bit count.
_PLAIN_COUNT = re.compile(r"[ \t]*([1-9][0-9]{0,17})")


def _starting_values(*names: str) -> tuple[dict[str, str | None], str]:
    """The value each of ``names`` had when this process STARTED, and where that was read
    (``None`` for a variable that was not set).

    glibc reads its malloc variables once, before the process's first allocation, so a later
    change to ``os.environ`` can never have applied to it. On Linux ``/proc/self/environ`` is
    the block the process was started with and is read first: an EMPTY block is an ``env -i``
    start where nothing was set, not a failure. Only where it cannot be read at all (no
    procfs) does ``os.environ`` stand in, and the source says so. A variable set twice reads as
    its FIRST value, as ``os.environ`` does. glibc applies the first value it ACCEPTS (a first
    one it ignores, such as ``"4 "``, lets the second apply), which the number check does not
    claim: an ignored first value reads as not known, never as the second. ``GLIBC_TUNABLES``
    is the exception: glibc parses EVERY copy of it, so the copies are joined with ``:`` and a
    later one that names ``glibc.malloc.arena_max`` is not missed."""
    try:
        block = Path("/proc/self/environ").read_bytes()
    except OSError:
        return (
            {name: os.environ.get(name) for name in names},
            "os.environ (the starting environment could not be read)",
        )
    found: dict[str, str | None] = dict.fromkeys(names)
    wanted = {name.encode("ascii"): name for name in names}
    for entry in block.split(b"\0"):
        key, equals, value = entry.partition(b"=")
        name = wanted.get(key) if equals else None
        if name is None:
            continue
        text = value.decode("utf-8", errors="replace")
        if found[name] is None:
            found[name] = text
        elif name == _TUNABLES_VAR:
            found[name] = f"{found[name]}:{text}"
    return found, _STARTING_ENVIRONMENT


def _plain_count(raw: str | None) -> int | None:
    """``raw`` as a positive whole number glibc is known to read the same way, else None."""
    match = _PLAIN_COUNT.fullmatch(raw) if raw is not None else None
    return int(match.group(1)) if match else None


def _loaded_files() -> list[str] | None:
    """The base names of the files mapped into this process (``libjemalloc.so.2``), each once and in map
    order, or None where ``/proc/self/maps`` cannot be read.

    What is LOADED is what decides which malloc a process runs, and ``LD_PRELOAD`` is only one way to ask
    for it: the entry may not load (a path that is not there is skipped with a message on stderr), may
    be a symlink with another name, and ``/etc/ld.so.preload`` names libraries the environment never
    mentions. The kernel lists the file a library was really loaded from, so each of those reads right.
    Measured on glibc 2.39 with a real jemalloc: a nonexistent ``LD_PRELOAD`` path is absent from the
    map and the process ran on glibc's arenas; the same library through a symlink named
    ``libfastalloc.so`` is listed as ``libjemalloc.so.2`` and the process ran on one glibc arena.

    THE LIMIT, measured: the map is read when the setting is asked for, and it lists a library loaded AFTER the
    process started (a ``ctypes`` or ``dlopen`` load) as well, which does not take malloc over. A stand-in named
    like mimalloc and loaded through ``ctypes`` moved the same process from ``capped at 2`` to ``replaced, no
    effect``. Nothing in this application loads such a library, and the error is on the modest side (it says a cap
    had no effect that did), but a reading taken later than the start can say it."""
    try:
        lines = Path("/proc/self/maps").read_bytes().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return None
    found: dict[str, None] = {}
    for line in lines:
        fields = line.split(None, 5)  # address, permissions, offset, device, inode, pathname
        if len(fields) == 6 and fields[5].startswith("/"):
            found[fields[5].removesuffix(" (deleted)").rsplit("/", 1)[-1]] = None
    return list(found)


def _malloc_replacement(names: Iterable[str]) -> str | None:
    """The first of ``names`` (base names of files) that is a known malloc replacement, or None."""
    for base in names:
        if any(known in base.lower() for known in _MALLOC_REPLACEMENTS):
            return base
    return None


def _tunes_arena_max(tunables: str | None) -> bool:
    """Whether ``GLIBC_TUNABLES`` names ``glibc.malloc.arena_max``, which glibc lets take
    precedence over ``MALLOC_ARENA_MAX`` in whichever order the two were set (measured). Tunables
    are separated by ``:`` and nothing else: a ``;`` makes the value glibc reads for the tunable
    before it invalid, so it ignores that one and the variable applies (measured), and an entry
    after a ``;`` is not one glibc ever reads."""
    return any(part.strip().startswith("glibc.malloc.arena_max=") for part in (tunables or "").split(":"))


def _glibc_version() -> str | None:
    """``glibc 2.39`` on glibc, None on anything else (musl, macOS, Windows). Asked of the
    C library itself: ``platform.libc_ver`` scans the interpreter's binary when that
    fails, which a diagnostic read at every boot has no business doing."""
    try:
        got = os.confstr("CS_GNU_LIBC_VERSION")
    except (AttributeError, ValueError, OSError):
        return None
    return got.strip() if got and got.strip().startswith("glibc") else None


def allocator_setting() -> dict[str, Any]:
    """Which C allocator this process runs on and whether its malloc arenas are capped
    (R114). Every session's record carries it, so a report can tell the instances that run
    with the cap from those that do not, and the sessions either side of an update.

    ``effective`` is the answer to "does this process run with the cap". True only on glibc
    started with ``MALLOC_ARENA_MAX`` set to a plain positive whole number (``arena_cap`` is
    then that number, and None otherwise: it names a cap the process runs with, never one the
    environment merely says). False where the variable is not set, where the allocator is not
    glibc, and where a malloc replacement is LOADED (read from the process's own memory map, not
    from the name an ``LD_PRELOAD`` entry gives: one that did not load is no replacement, and one
    that loaded under another name is), because the variable does nothing there. None where it
    cannot be told: a value glibc may have ignored or read differently (not a plain positive whole
    number), ``GLIBC_TUNABLES`` naming ``glibc.malloc.arena_max``, which outranks the variable and
    is not interpreted here, or an ``LD_PRELOAD`` naming a replacement while the loaded files
    cannot be read. The variables are the process's STARTING environment (``source`` says where
    they were read), never a later ``os.environ``."""
    try:
        env, source = _starting_values(_ARENA_VAR, _TUNABLES_VAR, _PRELOAD_VAR)
        raw = env[_ARENA_VAR]
        libc = _glibc_version()
        loaded = _loaded_files()
        replacement = _malloc_replacement(loaded or ())
        # Only used where the map cannot be read: what the environment NAMES stands in, as a doubt.
        named = _malloc_replacement(
            entry.rsplit("/", 1)[-1] for entry in (env[_PRELOAD_VAR] or "").replace(":", " ").split()
        )
        cap = _plain_count(raw)
        out: dict[str, Any] = {
            "allocator": libc or f"not glibc ({sys.platform})",
            "arena_cap": None,
            "effective": False,
            "source": source,
        }
        was_set = f" (it was set to {raw!r})" if raw is not None else ""
        if libc is None:
            out["note"] = "MALLOC_ARENA_MAX has no effect here" + was_set
        elif replacement is not None:
            out["note"] = (
                f"malloc is replaced by {replacement} (loaded into this process), which has no glibc "
                "arenas: MALLOC_ARENA_MAX has no effect on it" + was_set
            )
        elif loaded is None and named is not None:
            out["effective"] = None
            out["note"] = (
                f"LD_PRELOAD names {named}, and the files this process loaded could not be read: "
                "whether malloc is replaced, and so whether MALLOC_ARENA_MAX applies, is not known" + was_set
            )
        elif _tunes_arena_max(env[_TUNABLES_VAR]):
            out["effective"] = None
            out["note"] = (
                "GLIBC_TUNABLES sets glibc.malloc.arena_max, which outranks MALLOC_ARENA_MAX "
                "and is not read here: whether the arenas are capped is not known"
            )
        elif raw is None:
            out["note"] = (
                "MALLOC_ARENA_MAX was not set: up to 8 malloc arenas per online CPU, glibc's default "
                "on a 64-bit machine"
            )
        elif cap is None:
            out["effective"] = None
            out["note"] = (
                f"MALLOC_ARENA_MAX was set to {raw!r}, which is not a plain positive whole "
                "number: whether glibc applied it is not known"
            )
        else:
            out["effective"] = True
            out["arena_cap"] = cap
            out["note"] = f"malloc arenas capped at {cap} by MALLOC_ARENA_MAX"
        return out
    except Exception as exc:  # noqa: BLE001 - an optional reading, never a second failure
        return {
            "allocator": None,
            "arena_cap": None,
            "effective": None,
            "note": f"the allocator setting could not be read ({type(exc).__name__}): unmeasured",
        }


def _session_header() -> dict[str, Any]:
    """What identifies this session in its own record, written once at its start: the
    process, when it began, and the allocator setting it began with."""
    return {"pid": os.getpid(), "started_at": _now(), "allocator": allocator_setting()}


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


def _linux_thread_clock(tid: int) -> int:
    """The kernel's CPU-time clock id of the thread with kernel id ``tid`` (the scheduler-time flavour,
    ``MAKE_THREAD_CPUCLOCK(tid, CPUCLOCK_SCHED)`` of ``linux/posix-timers.h``: the same number
    ``pthread_getcpuclockid`` returns on glibc and musl, and a stable part of the kernel's interface)."""
    return ((~tid) << 3) | 6


def _thread_cpu(tids: list[int]) -> dict[int, float]:
    """CPU seconds (user + system) of the given kernel thread ids; a thread whose time
    cannot be read is absent.

    Only the threads asked for. On Linux by the thread's own kernel CPU clock
    (:func:`_linux_thread_clock` and ``clock_gettime``): one system call that never releases the GIL,
    measured 0.01-0.12 ms for four to twenty busy threads, where every ``/proc`` read waits for the GIL
    and under a thread that holds it (the very burst being recorded) each one waits a switch
    interval -- eight reads took 1.2-1.7 s with eight busy threads, psutil's scan of all forty-odd
    0.5-0.7 s. The id used is the KERNEL's thread id (``native_id``), never a ``pthread_t``:
    ``pthread_getcpuclockid`` dereferences the thread's own record, which another thread's ``join`` can free
    between the lookup and the call (a segfault, and a recycled record read as ANOTHER thread's clock,
    both reproduced at a 1 microsecond switch interval), where a kernel id that no longer names a thread
    is only an error, ``EINVAL``, and a tid of another process is one too. A thread the clock refuses
    falls back to one ``/proc`` read; on other platforms psutil, whose thread list there is one native call
    (on macOS its ids are not the ones ``threading`` reports, so nothing matches and the time is absent)."""
    out: dict[int, float] = {}
    if not tids:
        return out
    rest = list(tids)
    if sys.platform.startswith("linux") and hasattr(time, "clock_gettime"):
        rest = []
        for tid in tids:
            try:
                out[tid] = round(time.clock_gettime(_linux_thread_clock(tid)), 2)
            except (OSError, OverflowError, ValueError, AttributeError):
                rest.append(tid)
        if not rest:
            return out
    if sys.platform.startswith("linux"):
        try:
            tick = float(os.sysconf("SC_CLK_TCK"))
        except (ValueError, OSError):
            return out
        for tid in rest:
            try:
                raw = Path(f"/proc/self/task/{tid}/stat").read_bytes()
                # fields after the ")" that closes the name: utime and stime are the
                # 12th and 13th (fields 14 and 15 of proc(5)), in clock ticks
                fields = raw.rsplit(b")", 1)[1].split()
                out[tid] = round((int(fields[11]) + int(fields[12])) / tick, 2)
            except (OSError, IndexError, ValueError):
                continue
        return out
    try:
        import psutil

        want = set(rest)
        for t in psutil.Process().threads():
            if int(t.id) in want:
                out[int(t.id)] = round(float(t.user_time) + float(t.system_time), 2)
    except Exception:  # noqa: BLE001 - CPU time is an optional reading
        return out
    return out


def _is_waiting(innermost: str) -> bool:
    return innermost.split(":", 1)[0] in _WAITING_IN


def _stack_of(frame: types.FrameType) -> list[str]:
    """The innermost frame, then up to ``_STACK_APP_FRAMES`` of the app's own frames above it
    (innermost first); with no app frame at all, the thread's own entry point."""
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
    return stack


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
        stack = _stack_of(frame)
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


def _light_path() -> Path:
    return _path().with_name(_LIGHT_FILE)


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
    light = _read(_light_path())
    if (
        light
        and light.get("pid") == got.get("pid")
        and light.get("started_at") == got.get("started_at")
        and isinstance(light.get("snapshots"), list)
    ):
        got["pressure_light"] = light["snapshots"]
        got["pressure_light_taken"] = light.get("taken")
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


def _guard_view() -> dict[str, Any] | None:
    """The memory guard's state in four fields, or None when it is off or unreadable.

    One short lock hold inside the guard and no I/O. Imported here, not at the top: the guard
    is the scheduler's, and a forensic sidecar must import without it."""
    try:
        from src.scheduler import memguard

        st = memguard.memory_guard.state()
    except Exception:  # noqa: BLE001 - the guard is optional context, never a failure
        return None
    if not st.get("enabled"):
        return None
    return {
        "engaged": bool(st.get("engaged")),
        "since": st.get("since"),
        "reason": st.get("reason"),
        "engagements": st.get("engagements"),
    }


def _guard_rose(guard: dict[str, Any] | None) -> bool:
    """True when the memory guard has engaged since the previous liveness reading.

    Evaluated on EVERY reading, whichever trigger claims the snapshot, so its baseline is
    never stale and an engagement is not reported twice."""
    global _GUARD_WAS_ENGAGED
    engaged = bool(guard and guard.get("engaged"))
    with _LOCK:
        was, _GUARD_WAS_ENGAGED = _GUARD_WAS_ENGAGED, engaged
    return engaged and not was


def _held_due(
    readings: dict[str, float], guard: dict[str, Any] | None, rose: bool, now: float
) -> str | None:
    """Why a machine that is ALREADY short earns a snapshot, or None; CLAIMED under the lock.

    ``"memory guard engaged"`` at the moment the guard engages (``rose``), and ``"memory still
    short"`` every ``_PLATEAU_INTERVAL_S`` after the previous snapshot while memory is below the
    line or the guard stays engaged. The moment of engaging respects ``_PRESSURE_MIN_INTERVAL_S``
    like every other trigger, so a guard that flaps cannot make a snapshot a second."""
    global _LAST_PRESSURE
    avail = readings.get("avail_mb")
    total = readings.get("total_mb")
    below = bool(avail is not None and total and avail <= _pressure_line_mb(total))
    held = bool(guard and guard.get("engaged")) or below
    with _LOCK:
        since = now - _LAST_PRESSURE
        if rose and since >= _PRESSURE_MIN_INTERVAL_S:
            _LAST_PRESSURE = now
            return "memory guard engaged"
        if held and since >= _PLATEAU_INTERVAL_S:
            _LAST_PRESSURE = now
            return "memory still short"
    return None


def _burst_due(now: float) -> dict[str, Any] | None:
    """``{"blocks_gained": n, "over_s": t}`` when the Python heap grew by a burst since
    the previous call, CLAIMED under the lock; else None. Called by the liveness thread
    alone, so "since the previous call" is its own 5 s cadence."""
    global _LAST_BLOCKS, _LAST_BURST
    counter = getattr(sys, "getallocatedblocks", None)  # CPython only
    if counter is None:
        return None
    blocks = counter()
    with _LOCK:
        before, _LAST_BLOCKS = _LAST_BLOCKS, (now, blocks)
        if before is None or blocks - before[1] < _BURST_BLOCKS:
            return None
        if (now - _LAST_BURST) < _BURST_MIN_INTERVAL_S:
            return None
        _LAST_BURST = now
    return {"blocks_gained": blocks - before[1], "over_s": round(now - before[0], 1)}


def _pressure_snapshot(
    readings: dict[str, float], why: str, guard: dict[str, Any] | None = None
) -> dict[str, Any]:
    """What every thread was doing, with the memory readings it was taken at and WHY it
    was taken: ``memory short`` (below the line), ``allocation burst``, ``memory guard
    engaged`` or ``memory still short`` (a plateau). ``guard`` is the memory guard's state
    at that moment; it is kept when the guard was engaged, so a snapshot says whether the
    pause was already in force while it was being taken."""
    snap: dict[str, Any] = {"at": _now(), "why": why}
    if guard and guard.get("engaged"):
        snap["guard"] = guard
    for key in ("avail_mb", "total_mb", "rss_mb", "swap_used_mb"):
        if readings.get(key) is not None:
            snap[key] = readings[key]
    if readings.get("total_mb"):
        snap["line_mb"] = round(_pressure_line_mb(readings["total_mb"]), 1)
    # The kernel's counters only: the heap walk is exactly what a short machine must
    # not do (see _HEAP_WALK_MIN_AVAIL_SHARE).
    snap["memory"] = composition(walk_heap=False)
    snap["threads"] = thread_snapshot()
    return snap


def _guard_line() -> tuple[float | None, float | None]:
    """The memory guard's own line as (available-memory floor in MB, RSS share of RAM in percent),
    each ``None`` when it cannot be read. Plain attributes, no lock: read even when the guard is
    switched off, because the line is still where memory becomes dangerous."""
    try:
        from src.scheduler import memguard

        g = memguard.memory_guard
        floor, pct = getattr(g, "avail_floor_mb", None), getattr(g, "rss_pct", None)
        return (
            float(floor) if isinstance(floor, int | float) and floor > 0 else None,
            float(pct) if isinstance(pct, int | float) and pct > 0 else None,
        )
    except Exception:  # noqa: BLE001 - the guard is optional context, never a failure
        return None, None


def _light_near(readings: dict[str, float], guard: dict[str, Any] | None) -> str | None:
    """Why the machine is NEAR the memory guard's line (see ``_LIGHT_NEAR_FACTOR``), or None."""
    if guard and guard.get("engaged"):
        return "memory guard engaged"
    floor, pct = _guard_line()
    avail, total, rss = readings.get("avail_mb"), readings.get("total_mb"), readings.get("rss_mb")
    if avail is not None and floor is not None and avail <= floor * _LIGHT_NEAR_FACTOR:
        return "available memory near the guard's floor"
    if rss is not None and total and pct is not None and 100.0 * rss / total >= pct / _LIGHT_NEAR_FACTOR:
        return "process memory near the guard's share"
    return None


def _light_due(readings: dict[str, float], guard: dict[str, Any] | None, now: float) -> str | None:
    """Why this reading earns a LIGHT snapshot, or None; CLAIMED under the lock."""
    global _LAST_LIGHT
    why = _light_near(readings, guard)
    if why is None:
        return None
    with _LOCK:
        if (now - _LAST_LIGHT) < _LIGHT_INTERVAL_S:
            return None
        _LAST_LIGHT = now
    return why


def _busiest_threads(
    previous_cpu: dict[int, float],
) -> tuple[list[dict[str, Any]], dict[int, float], int, int]:
    """The ``_LIGHT_THREADS`` working threads that spent the most CPU since ``previous_cpu``, with
    their stacks; the CPU reading of every candidate (the next call's baseline); how many threads
    were working; and for how many of them the CPU was ASKED for (the first ``_LIGHT_CPU_CANDIDATES``
    found, not the busiest: which are busiest is what the read decides; the readings returned say how many
    of those it got). Only the threads whose innermost frame is not a wait are read at all, and only the
    busiest get a stack. A thread the previous reading did not see has no delta (absent, never its
    lifetime total presented as recent), and ranks after those that have one."""
    frames = sys._current_frames()
    by_ident = {t.ident: t for t in threading.enumerate()}
    me = threading.get_ident()
    working: list[tuple[Any, types.FrameType, int]] = []
    for ident, frame in frames.items():
        if ident == me or _is_waiting(_frame_line(frame)):
            continue
        thread = by_ident.get(ident)
        native = getattr(thread, "native_id", None) if thread else None
        if native is not None:
            working.append((thread, frame, native))
    candidates = working[:_LIGHT_CPU_CANDIDATES]
    cpu = _thread_cpu([native for _t, _f, native in candidates])
    ranked: list[tuple[float | None, float, Any, types.FrameType, int]] = []
    for thread, frame, native in candidates:
        c = cpu.get(native)
        delta = round(c - previous_cpu[native], 1) if c is not None and native in previous_cpu else None
        ranked.append((delta, c if c is not None else 0.0, thread, frame, native))
    ranked.sort(key=lambda r: (r[0] is None, -(r[0] or 0.0), -r[1]))
    out: list[dict[str, Any]] = []
    for delta, _c, thread, frame, native in ranked[:_LIGHT_THREADS]:
        entry: dict[str, Any] = {"name": thread.name, "tid": native, "stack": _stack_of(frame)}
        if native in cpu:
            entry["cpu_s"] = cpu[native]
        if delta is not None:
            entry["cpu_delta_s"] = delta
        out.append(entry)
    del frames
    return out, cpu, len(working), len(candidates)


def _light_snapshot(readings: dict[str, float], why: str, guard: dict[str, Any] | None) -> dict[str, Any]:
    """One LIGHT snapshot (see ``_LIGHT_NEAR_FACTOR``). Called by the liveness thread alone; the
    baseline it measures against is the previous light snapshot's. It says how long it took
    (``took_ms``: the readings and the choice of threads, not the write of the file, which
    ``observe`` does after it): an instrument that runs on the machine it watches shows its own
    cost."""
    global _LIGHT_BASELINE
    t0 = time.perf_counter()
    mono = time.monotonic()
    snap: dict[str, Any] = {"at": _now(), "why": why}
    if guard and guard.get("engaged"):
        snap["guard"] = guard
    for key in ("avail_mb", "total_mb", "rss_mb", "swap_used_mb"):
        if readings.get(key) is not None:
            snap[key] = readings[key]
    snap["memory"] = composition(walk_heap=False)
    with _LOCK:
        before = _LIGHT_BASELINE
    threads, cpu, working, asked_for = _busiest_threads(before["cpu"] if before else {})
    blocks = snap["memory"].get("py_alloc_blocks")
    if before is not None:
        # The time the deltas are over, beside the threads' CPU as well as the blocks: the first
        # snapshot of a new episode measures against the last one of the previous, hours earlier.
        snap["over_s"] = round(mono - before["mono"], 1)
        if isinstance(blocks, int) and isinstance(before.get("blocks"), int):
            snap["blocks_gained"] = blocks - before["blocks"]
    snap["working_threads"] = working
    # The threads the CPU was asked for and the ones it was READ for are not the same number: on a platform
    # that cannot read a thread's CPU (macOS without a matching id, a host without psutil) nothing is read,
    # and the threads below are then the first found, not the busiest -- said, never left to be assumed.
    snap["cpu_asked_for"] = asked_for
    snap["cpu_read_for"] = len(cpu)
    if asked_for and not cpu:
        snap["thread_cpu"] = "unavailable on this platform: the threads below are not ranked by CPU"
    snap["threads"] = threads
    with _LOCK:
        _LIGHT_BASELINE = {"mono": mono, "blocks": blocks, "cpu": cpu}
    snap["took_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return snap


def _reset_snapshots() -> None:
    """This session's snapshot state, emptied. Caller holds ``_LOCK``."""
    global _PRESSURE, _PRESSURE_TAKEN, _EPISODE_LOW, _LAST_PRESSURE, _LAST_BLOCKS, _LAST_BURST
    global _GUARD_WAS_ENGAGED, _LIGHT, _LIGHT_TAKEN, _LAST_LIGHT, _LIGHT_BASELINE, _LIGHT_FAILED
    _PRESSURE, _PRESSURE_TAKEN, _EPISODE_LOW, _LAST_PRESSURE = [], 0, None, _NEVER
    _LAST_BLOCKS, _LAST_BURST, _GUARD_WAS_ENGAGED = None, _NEVER, False
    _LIGHT, _LIGHT_TAKEN, _LAST_LIGHT, _LIGHT_BASELINE = [], 0, _NEVER, None
    _LIGHT_FAILED = 0


def capture_previous() -> dict[str, Any] | None:
    """Read the PREVIOUS session's marks and start this session's record.

    Call once at boot, before anything can observe. Returns the previous marks (or
    None when there are none — a first boot, or a removed file)."""
    global _PREV, _PREV_LOADED, _MARKS, _LAST_WRITE
    with _LOCK:
        if not _PREV_LOADED:
            _PREV = _read_record()
            _PREV_LOADED = True
        _MARKS = _session_header()
        _LAST_WRITE = _NEVER
        _reset_snapshots()
        _write(dict(_MARKS))
        for stale in (_pressure_path(), _light_path()):
            try:
                stale.unlink(missing_ok=True)
            except OSError:
                _LOG.debug("could not reset %s", stale.name, exc_info=True)
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
    global _LAST_WRITE, _LAST_COMPOSITION, _PRESSURE_TAKEN, _LIGHT_TAKEN, _LIGHT_FAILED
    try:
        readings = _readings()
        now = time.monotonic()
        pressure = None
        light = None
        light_failure: str | None = None
        if may_snapshot_threads:
            # The burst reading is taken on every call, so its baseline is always the
            # previous 5 s reading, even when this call is a memory-short snapshot.
            burst = _burst_due(now)
            guard = _guard_view()
            rose = _guard_rose(guard)
            if _pressure_due(readings, now):
                pressure = _pressure_snapshot(readings, "memory short", guard)
            elif (held := _held_due(readings, guard, rose, now)) is not None:
                pressure = _pressure_snapshot(readings, held, guard)
            elif burst is not None:
                pressure = _pressure_snapshot(readings, "allocation burst", guard)
            if pressure is not None and burst is not None:
                pressure.update(burst)
            if pressure is None and (near := _light_due(readings, guard, now)) is not None:
                try:
                    light = _light_snapshot(readings, near, guard)
                except Exception as exc:  # noqa: BLE001 - its own failure must not skip the marks below
                    # (retried at the next 15 s claim, which ``_light_due`` already made). Never silent: the
                    # first failure of a session is a WARNING and every one is counted in the marks, because
                    # "no light snapshot" must not read the same as "never near the line".
                    _LOG.debug("light pressure snapshot failed", exc_info=True)
                    first = str(exc).splitlines()[0][:160] if str(exc) else ""
                    light_failure = f"{type(exc).__name__}: {first}"
        # At a new RSS peak, what the memory is made of (2026-09-26). Read OUTSIDE the
        # lock -- the heap walk is the slow part -- and at most once per interval.
        at_peak = None
        rss = readings.get("rss_mb")
        if rss is not None and (now - _LAST_COMPOSITION) >= _MIN_COMPOSITION_INTERVAL_S:
            with _LOCK:
                peak_so_far = _MARKS.get("rss_max_mb")
            if peak_so_far is None or rss > peak_so_far:
                _LAST_COMPOSITION = now
                walk = _heap_walk_is_safe(readings)
                at_peak = composition(walk_heap=walk)
                if not walk:
                    at_peak["heap_skipped"] = (
                        "memory was already short"
                        if readings.get("avail_mb") is not None and readings.get("total_mb")
                        else "available memory could not be read"
                    )
                elif at_peak.get("heap_in_use_mb") is None:
                    at_peak["heap_skipped"] = "no glibc 2.33+ heap report on this system"
                at_peak["rss_mb"] = rss
                at_peak["at"] = _now()
        with _LOCK:
            if not _MARKS:
                _MARKS.update(_session_header())
            if at_peak is not None:
                _MARKS["at_peak"] = at_peak
                # A peak taken with memory already short skips the heap walk, and the
                # last peak before an out-of-memory death usually is one of those. So the
                # newest peak that DID read the heap is kept beside it, or no crash
                # export could say what glibc held (2026-09-28: a 1M-article import died
                # at 5.6 GB and its export read "C heap not read").
                if at_peak.get("heap_in_use_mb") is not None:
                    _MARKS["heap_at_peak"] = at_peak
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
            first_light_failure = False
            if light_failure is not None:
                _LIGHT_FAILED += 1
                first_light_failure = _LIGHT_FAILED == 1
                _MARKS["pressure_light_failed"] = _LIGHT_FAILED
                _MARKS["pressure_light_last_failure"] = light_failure
            light_doc: dict[str, Any] = {}
            if light is not None:
                _LIGHT.append(light)
                del _LIGHT[:-_LIGHT_KEEP]
                _LIGHT_TAKEN += 1
                _MARKS["pressure_light_taken"] = _LIGHT_TAKEN
                light_doc = {
                    "pid": _MARKS.get("pid"),
                    "started_at": _MARKS.get("started_at"),
                    "taken": _LIGHT_TAKEN,
                    "kept": _LIGHT_KEEP,
                    "method": _LIGHT_METHOD,
                    "snapshots": list(_LIGHT),
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
        if first_light_failure:
            _LOG.warning(
                "a light pressure snapshot failed (%s); the count is in the session marks as pressure_light_failed",
                light_failure,
            )
        if light_doc:
            _write(light_doc, _light_path())
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
        if _LIGHT:
            out["pressure_light"] = list(_LIGHT)
        return out


def _fit_newest(items: list[Any], budget: int) -> tuple[list[Any], int]:
    """The newest of ``items`` (oldest first) whose JSON fits ``budget`` bytes, and how many older
    ones were dropped. The size is measured on what would be written, never estimated."""
    kept = list(items)
    while kept and len(json.dumps(kept, separators=(",", ":"), default=str)) > budget:
        kept.pop(0)
    return kept, len(items) - len(kept)


def diagnostics_member(max_bytes: int) -> dict[str, Any]:
    """The pressure TAIL as one diagnostics-bundle member (the slot contract planned for the single
    Diagnostics zip of R119: ``(max_bytes) -> dict``, never raises, keeps the newest, names the cut).
    It is not called at this head: the slot table is built with the button (PR D of the
    diagnostics-redesign plan), which says which member carries what.

    It carries the minutes before a kill and nothing else about memory: the LIGHT snapshots of this
    session and of the previous one (the previous session's tail is the one an unclean end is read
    from), each ring cut oldest-first to its half of what the member's fixed part leaves, with the
    count dropped. A budget that cannot hold the fixed part gets a short note saying so (a member
    larger than the budget only when the budget is smaller than that note itself, about 85 bytes), never
    a truncated snapshot. The previous session's light ring is also copied into
    ``session-forensics.json`` (``previous_session_peaks.pressure_light``), so the two files carry the same
    snapshots until the slot table decides which one keeps them. Counts, times, sizes and stack
    locations only."""
    try:
        budget = int(max_bytes)
        prev = previous() or {}
        now = current()
        out: dict[str, Any] = {
            "method": _LIGHT_METHOD,
            "interval_s": _LIGHT_INTERVAL_S,
            "kept_per_session": _LIGHT_KEEP,
            "this_session": {
                "taken": now.get("pressure_light_taken"),
                "snapshots": [],
                "dropped_oldest_to_fit": 0,
            },
            "previous_session": {
                "taken": prev.get("pressure_light_taken"),
                "snapshots": [],
                "dropped_oldest_to_fit": 0,
                "started_at": prev.get("started_at"),
                "found": bool(prev),
            },
        }
        fixed = len(json.dumps(out, separators=(",", ":"), default=str))
        room = budget - fixed - _MEMBER_SLACK
        if room < 0:
            return {
                "omitted": "max_bytes is below the member's fixed part",
                "needs_at_least_bytes": fixed + _MEMBER_SLACK,
            }
        half = room // 2
        for key, source in (("this_session", now), ("previous_session", prev)):
            ring, cut = _fit_newest(list(source.get("pressure_light") or []), half)
            out[key]["snapshots"], out[key]["dropped_oldest_to_fit"] = ring, cut
        return out
    except Exception as exc:  # noqa: BLE001 - a bundle member must never raise
        return {"error": f"{type(exc).__name__}: {str(exc).splitlines()[0][:160] if str(exc) else ''}"}


def reset_for_tests() -> None:
    """Clear the module state. Test-only; the suite shares one process."""
    global _PREV, _PREV_LOADED, _MARKS, _LAST_WRITE, _LAST_COMPOSITION
    with _LOCK:
        _PREV = None
        _PREV_LOADED = False
        _MARKS = {}
        _LAST_WRITE = _NEVER
        _LAST_COMPOSITION = _NEVER
        _reset_snapshots()
