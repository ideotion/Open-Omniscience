"""The install's vitals, kept as a history: memory, drive, database and log counts over days.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS (2026-10-06, R119). Nothing in the app held the SHAPE of a memory climb. The
only per-tick series is ``collect_perf``: 200 ticks that span five to six minutes in the debug
bundle, taken from a file that keeps two hours and only while a pass runs. The 17 bundles read
on 2026-10-06 could say where memory stood at the end of a pass and never how it got there, so
a machine that died at 02:30 after a slow day-long climb and one that died in a 45-second burst
looked the same in every bundle. The same gap hid the drive filling, the write-ahead log
growing to 1.19 GB and a logger that went from nothing to hundreds of warnings an hour.

WHAT IT KEEPS (all of it counts, sizes and times; no article, no address, no term):

- ``fine``: 5-minute buckets for 48 hours; ``coarse``: hourly buckets for 14 days. Each bucket
  is one row of numbers (``COLUMNS`` names them): how many 5-second ticks it holds, then the
  min / mean / max of the process's resident memory and of the machine's available memory, the
  peak of Python's allocated blocks, of swap in use and of the thread count (these two are read
  once a minute, the memory readings every five seconds), the lowest free
  space on the data drive and the largest size of the database, its write-ahead log and the
  columnar file.
- ``minutes``: the last 60 minutes, one row a minute, with the three busiest threads of that
  minute (their CPU seconds in it and their innermost two frames).
- ``logs``: per hour for 7 days, the log lines that reached the root logger by logger and level
  (``w12e1`` = 12 warnings and 1 error), the eight busiest loggers named and the rest summed.
- ``session_starts`` and ``gaps``: where the process started and where the rows stop, so a gap
  reads as a gap.

HONESTY RULES BAKED IN

- A reading that cannot be taken is ``null`` in its place, never 0. A bucket's tick count
  ``n`` is how many ticks it holds, so a bucket with far fewer than the 60 a five-minute bucket
  can hold says the process was young, stopped or the machine was asleep. Nothing is
  interpolated across a gap.
- THE MINUTES BEFORE A KILL ARE NOT CLAIMED HERE. The history is written to disk every five
  minutes and at a clean end, so a kill loses up to five minutes of it. The member says when it
  was last written (``last_flush_at``) and names the record that carries the tail
  (``tail_in``).
- The log counts are of the records that REACHED the root logger, which depends on the levels
  the app configured; ``log_level`` says what the root logger was set to. It is a count, not a
  log, and the 2,000-record error log stays the place to read a message.
- Every call is best-effort and bounded. This rides the 5-second liveness tick the session
  ledger already has (no thread of its own), takes the cheap kernel counters only, writes one
  small file every five minutes, atomically and without fsync, and never raises into its
  caller: an instrument on a periodic path must not become a load source on the machine it
  watches.
"""

from __future__ import annotations

import atexit
import contextlib
import json
import logging
import os
import shutil
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.paths import data_dir

_LOG = logging.getLogger(__name__)

#: The layout of the file and of the member. 2: the open log hour is stored as raw (logger, level,
#: count) triples and the previous sessions' tails and the clock steps are stored (an older file
#: of this build's development is read as no history, never half-trusted).
SCHEMA = "oo-vitals-2"
_FILE = "vitals_history.json"

#: Five-minute buckets for 48 hours; hourly buckets for 14 days; one row a minute for the last
#: 60 minutes; hourly log counts for 7 days. Each number protects one thing: 48 h of five-minute
#: rows is what a 72 h soak needs to show the shape of the last two days and still be a few
#: dozen kilobytes; 14 days of hourly rows is what an update-and-restart cycle can be read
#: against; the log table is the one that grows with the number of loggers, so it is the
#: shortest. FINE_S protects the per-minute extremes: five minutes is the coarsest bucket in
#: which a burst of hundreds of megabytes in seconds (bundle 091717's RSS rose at up to 64 MB/s)
#: still shows in the bucket's min and max. MINUTE_S x MINUTE_KEEP is the last hour at the
#: resolution of one thread sample a minute: finer would put the thread walk (0.3-0.6 s under a
#: GIL-holding burst) on the tick more often than the load it is meant to explain.
FINE_S = 300
FINE_KEEP = 576
COARSE_S = 3600
COARSE_KEEP = 336
MINUTE_S = 60
MINUTE_KEEP = 60
LOG_KEEP = 168
#: Loggers named per hour; the rest of that hour's lines are summed under ``other``.
LOG_LOGGERS_PER_HOUR = 8
#: Distinct logger names counted in one hour before the rest fall into one overflow bucket (a
#: logger created per request would otherwise grow the table without bound). Its name is not a
#: logger's, so it can never be mistaken for one called "other".
_LOG_NAMES_CAP = 64
_OVERFLOW = "(past the name cap)"
#: Written to disk this often, and at a clean end. It bounds what a kill loses (up to this much of
#: the history) against the cost of writing the whole document (about 2 ms of CPU at full
#: retention): more often is more CPU for minutes the 15-second pressure snapshot records better.
FLUSH_S = 300.0
#: The slow readings (stat calls, the thread count, the swap) are taken this often: none of them
#: moves in seconds, and each is a system call that waits a GIL hand-off under busy threads.
SLOW_S = 60.0
#: Threads named per minute: enough to tell one runaway thread from a pool, few enough that a
#: minute row stays a few hundred bytes (60 of them are in the member).
BUSIEST_THREADS = 3
#: Rows of a previous session's tail kept (the minutes before it stopped), and how many sessions'
#: tails: a crash loop restarts every few minutes, and the tail that matters is the one of the
#: session that ran long enough to say how it died, which one short session after another would
#: otherwise push out. A tail of fewer than ``PREVIOUS_TAIL_MIN`` minutes is the short kind: the
#: file is written at the session's first tick and then every ``FLUSH_S`` (five minutes), so a
#: session that dies before its second write leaves no minute at all (and inherits the tails it
#: found), and one that lives a little longer leaves four or fewer, which says too little to push
#: out one that ran for five or more. A short tail is the first to be evicted, never the last
#: written.
PREVIOUS_TAIL_KEEP = 30
PREVIOUS_SESSIONS_KEEP = 3
PREVIOUS_TAIL_MIN = 5
#: Session starts kept (a month of daily restarts, or a crash loop's last half hour), gaps listed
#: (the member lists where rows stop; the newest fifty are the ones an investigation reads) and
#: clock steps recorded: each is one short row, bounded so a clock that keeps stepping cannot
#: grow the file.
SESSIONS_KEEP = 30
GAPS_KEEP = 50
CLOCK_STEPS_KEEP = 20
#: A clock whose time is behind the open five-minute bucket's START by up to this much (two
#: buckets, the line the gaps use, and more than a network time correction ever steps) is held:
#: its ticks stay in the open bucket and nothing is reordered. A bigger step closes everything
#: that is open and starts again, so one step never piles hours of ticks into one row. The edge
#: is exact from the bucket's start, which is bucket-aligned, and it does not depend on which
#: second of the bucket the last tick fell in; measured from the LAST TICK it is a step of 600 to
#: 895 s (the last tick may be up to 295 s into its bucket), and ``back_s`` says the real size.
#: What it protects: the open bucket holds at most (CLOCK_HOLD_S + 2 * FINE_S) / 5 = 240 ticks
#: (a full bucket is 60), and a minute row that spans a hold up to about 190.
CLOCK_HOLD_S = 2 * FINE_S
#: A clock that keeps stepping (a broken time source flapping, a machine that wakes wrong again and
#: again) would close the open buckets on every tick that follows a step and push the 48 hours the
#: member exists to show out of the table within a couple of hours. So a big step starts a new
#: history at most this often (the monotonic clock, which a step cannot move); a bigger step that
#: comes sooner is held like a small one, marked ``kept_open`` in ``clock_steps``, and starts its
#: new history at the first tick after the interval. One bucket holds at most this many extra
#: seconds of ticks for that.
REBASE_MIN_GAP_S = FINE_S
#: After a failed write the next try is this soon, not on every five-second tick.
FLUSH_RETRY_S = 60.0
#: What the member may weigh, raw JSON. Measured on the test's fixture
#: (``test_the_heaviest_member_fits_its_budget...``: 25 loggers, readings of four or five digits,
#: frames of about 40 characters): 140 KB for the full retention, 189 KB with the three previous
#: sessions' tails, 246 KB with 58-character logger names (the longer names a deep package gives);
#: 260 KB is 6 per cent above that. It is sized above the fixture and is not a maximum: a logger
#: name has no length ceiling and a real row is heavier than the fixture's, and a member that does
#: pass it drops the oldest log hours first and says so (``dropped_oldest_rows``). A smaller number
#: cuts the 48 hours or the tails the member exists to show. What the number protects is the room
#: the other members need in the zip (the plan's new-member budgets add to 1,324 KB raw, PLAN 4), not
#: the 4 MB part (R119):
#: at 4,000,000 bytes a part holds fifteen of these members raw and about seventy zipped (at the
#: first measure's ratio, 4.6 to 1: 36 KB zipped for 166 KB raw; the test's constant rows zip 25 to
#: 1 and say nothing), so one history, growing with the number of loggers, cannot crowd them out.
MEMBER_BUDGET_BYTES = 260_000

#: Which record carries the minutes before a kill. Set once the owner of that record has
#: confirmed it; until then the member says the 5-minute history is the only record.
TAIL_IN: dict[str, str] | None = None

#: The row layout. Memory, drive free and sizes in whole MB (a megabyte is below the noise on a
#: machine whose memory is counted in gigabytes), blocks in thousands.
COLUMNS = (
    "t", "n",
    "rss_min", "rss_mean", "rss_max",
    "avail_min", "avail_mean", "avail_max",
    "swap_max", "threads_max", "blocks_k_max",
    "drive_free_min", "db_max", "wal_max", "columnar_max",
)
# metric -> (the column offsets it fills in order: min / mean / max, or a single extreme)
_SPEC = (
    ("rss", ("min", "mean", "max")),
    ("avail", ("min", "mean", "max")),
    ("swap", ("max",)),
    ("threads", ("max",)),
    ("blocks", ("max",)),
    ("drive_free", ("min",)),
    ("db", ("max",)),
    ("wal", ("max",)),
    ("columnar", ("max",)),
)

_LOCK = threading.RLock()
# A LEAF lock for the log counts. ``logging`` calls ``emit`` with the handler's own lock held, and
# the history's main lock is held while rows are folded, so emit must never wait on that one: it
# takes this one, for a dictionary update, and nothing else is ever done while holding it. The
# order, where both are needed, is ``_LOCK`` then ``_LOG_LOCK``, never the other way.
#
# RE-ENTRANT ON PURPOSE (independent read of the first version, B1): CPython runs the cyclic collector
# and Python-level signal handlers between any two bytecodes, so a finalizer that logs (SQLAlchemy's
# pool does, and asyncio's "Task exception was never retrieved") or a SIGHUP handler that logs can
# re-enter ``emit`` on the thread that is inside it. A plain lock would make that thread wait for
# itself while holding the handler's own lock, and every later thread that logs would wait behind
# it. The critical section is dictionary updates, each consistent at every bytecode boundary, so
# the nested call is counted. (A nested line of the SAME logger and level can cost one count: the
# collector runs between the read and the store of ``_HOUR_LOGS[key] = _HOUR_LOGS.get(key, 0) + 1``,
# which takes an asyncio error inside an asyncio error; one line lost per such event is the
# price of never waiting for itself.)
_LOG_LOCK = threading.RLock()
_STARTED = False
_FINE: list[list[Any]] = []
_COARSE: list[list[Any]] = []
_LOGS: list[dict[str, Any]] = []
_MINUTES: list[dict[str, Any]] = []
_SESSIONS: list[dict[str, Any]] = []
_PREVIOUS: list[dict[str, Any]] = []
_CLOCK_BACK = 0
_CLOCK_HOLD = False
#: The step the running hold recorded: a later rebase that is only that hold ending says when the
#: new history began on this record, instead of recording the same step a second time.
_HOLD_STEP: dict[str, Any] | None = None
_CLOCK_STEPS: list[dict[str, Any]] = []
_LAST_REBASE = float("-inf")  # monotonic time of the last big step that started a new history
_LAST_WALL: float | None = None  # the wall clock at the last tick: what a step back is measured from
_LAST_FLUSH = float("-inf")
_LAST_FLUSH_AT: str | None = None

_FINE_ACC: _Acc | None = None
_FINE_T = 0
_COARSE_ACC: _Acc | None = None
_COARSE_T = 0
_MIN_ACC: _Acc | None = None
_MIN_T = 0
_HOUR_LOGS: dict[tuple[str, str], int] = {}
_HOUR_LOG_NAMES: set[str] = set()
_HOUR_LOGS_T = 0
_SLOW: dict[str, Any] = {}
_LAST_SLOW = float("-inf")
#: tid -> (CPU seconds at the last reading, when). A baseline older than ``_BASELINE_MAX_AGE_S`` is
#: not used: a thread that went unread for longer would make "the minute's CPU" the CPU of several.
_LAST_CPU: dict[int, tuple[float, float]] = {}
_BASELINE_MAX_AGE_S = 2 * MINUTE_S + 30
_PROC: Any = None
_HANDLER: _CountHandler | None = None
_COST: dict[str, float | None] = {}
#: Failures of the recorder's own work this session, counted and named by type, so a failing disk
#: shows in the vitals themselves and not only in a debug log nobody reads. Messages carry no path.
_ERRORS: dict[str, Any] = {}


class _Acc:
    """One bucket under construction: per metric the lowest, highest, sum and count."""

    __slots__ = ("n", "lo", "hi", "total", "cnt")

    def __init__(self) -> None:
        self.n = 0
        self.lo: dict[str, float] = {}
        self.hi: dict[str, float] = {}
        self.total: dict[str, float] = {}
        self.cnt: dict[str, int] = {}

    def add(self, sample: dict[str, float]) -> None:
        self.n += 1
        for key, value in sample.items():
            if key in self.lo:
                if value < self.lo[key]:
                    self.lo[key] = value
                if value > self.hi[key]:
                    self.hi[key] = value
                self.total[key] += value
                self.cnt[key] += 1
            else:
                self.lo[key] = self.hi[key] = self.total[key] = value
                self.cnt[key] = 1

    def merge(self, other: _Acc) -> None:
        """Fold a finished (finer) bucket into this one, weighting the mean by its counts."""
        self.n += other.n
        for key in other.lo:
            if key in self.lo:
                self.lo[key] = min(self.lo[key], other.lo[key])
                self.hi[key] = max(self.hi[key], other.hi[key])
                self.total[key] += other.total[key]
                self.cnt[key] += other.cnt[key]
            else:
                self.lo[key], self.hi[key] = other.lo[key], other.hi[key]
                self.total[key], self.cnt[key] = other.total[key], other.cnt[key]

    def row(self, t: int) -> list[Any]:
        out: list[Any] = [t, self.n]
        for name, kinds in _SPEC:
            for kind in kinds:
                if name not in self.lo:
                    out.append(None)
                elif kind == "min":
                    out.append(round(self.lo[name]))
                elif kind == "max":
                    out.append(round(self.hi[name]))
                else:
                    out.append(round(self.total[name] / self.cnt[name]))
        return out


def _from_row(row: list[Any]) -> _Acc:
    """The accumulator a stored row describes, so a bucket that was open at the last flush
    can be folded into the hour it belongs to. The mean is weighted by the tick count."""
    acc = _Acc()
    acc.n = int(row[1] or 0)
    i = 2
    for name, kinds in _SPEC:
        vals = dict(zip(kinds, row[i:i + len(kinds)], strict=True))
        i += len(kinds)
        lo = vals.get("min", vals.get("mean", vals.get("max")))
        hi = vals.get("max", vals.get("mean", vals.get("min")))
        if lo is None or hi is None:
            continue
        acc.lo[name], acc.hi[name] = float(lo), float(hi)
        mean = vals.get("mean")
        acc.cnt[name] = max(acc.n, 1)
        acc.total[name] = float(mean if mean is not None else hi) * acc.cnt[name]
    return acc


def _level_letter(levelno: int) -> str:
    if levelno >= logging.CRITICAL:
        return "c"
    if levelno >= logging.ERROR:
        return "e"
    if levelno >= logging.WARNING:
        return "w"
    if levelno >= logging.INFO:
        return "i"
    return "d"


class _CountHandler(logging.Handler):
    """Counts the records that reach the root logger by logger and level; keeps nothing else."""

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        try:
            key = (record.name, _level_letter(record.levelno))
            with _LOG_LOCK:
                if record.name not in _HOUR_LOG_NAMES:
                    if len(_HOUR_LOG_NAMES) >= _LOG_NAMES_CAP:
                        key = (_OVERFLOW, key[1])
                    else:
                        _HOUR_LOG_NAMES.add(record.name)
                _HOUR_LOGS[key] = _HOUR_LOGS.get(key, 0) + 1
        except Exception:  # noqa: BLE001 - counting must never break logging
            return


def _path() -> Path:
    return data_dir() / "diagnostics" / _FILE


def _iso(epoch: float | int) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _trim(seq: list[Any], keep: int) -> None:
    if len(seq) > keep:
        del seq[:-keep]


def _logs_row(t: int, counts: dict[tuple[str, str], int]) -> dict[str, Any]:
    """One hour of log counts: the busiest loggers by name (errors first, then warnings, then
    everything), the rest summed. ``by`` maps a logger to its counts, ``other`` is the sum."""
    per: dict[str, dict[str, int]] = {}
    overflow: dict[str, int] = {}
    for (name, letter), n in counts.items():
        if name == _OVERFLOW:
            overflow[letter] = overflow.get(letter, 0) + n
            continue
        per.setdefault(name, {})[letter] = per.get(name, {}).get(letter, 0) + n
    ranked = sorted(
        per.items(),
        key=lambda kv: (-kv[1].get("c", 0) - kv[1].get("e", 0), -kv[1].get("w", 0), -sum(kv[1].values()), kv[0]),
    )
    rest: dict[str, int] = dict(overflow)
    for _name, letters in ranked[LOG_LOGGERS_PER_HOUR:]:
        for letter, n in letters.items():
            rest[letter] = rest.get(letter, 0) + n

    def text(letters: dict[str, int]) -> str:
        return "".join(f"{k}{letters[k]}" for k in "cewid" if letters.get(k))

    row: dict[str, Any] = {
        "t": t,
        "lines": sum(counts.values()),
        "by": {name: text(letters) for name, letters in ranked[:LOG_LOGGERS_PER_HOUR]},
    }
    if rest:
        row["other"] = text(rest)
        row["other_loggers"] = max(len(ranked) - LOG_LOGGERS_PER_HOUR, 0)
        if overflow:
            row["past_name_cap"] = sum(overflow.values())  # lines of loggers that came after the cap
    return row


def _stat_mb(path: Path) -> float | None:
    try:
        return os.stat(path).st_size / (1024 * 1024)
    except OSError:
        return None


def _process() -> Any:
    """The psutil handle of this process, made once; ``None`` where psutil is not installed."""
    global _PROC
    if _PROC is None:
        import psutil

        _PROC = psutil.Process()
    return _PROC


def _count_readings() -> dict[str, float]:
    """The thread count and the swap in use. Each is a read of the kernel's own files, and
    under a busy interpreter each read costs a GIL hand-off (measured: 0.5 and 0.9 ms of the
    thread's CPU, of a 3.2 ms tick, with three busy threads; 0.012 and 0.043 ms idle). Neither
    moves in five seconds the way memory does, and ``session_hwm`` already reads swap every five
    seconds into its own marks, so they are read with the slow group, once a minute."""
    out: dict[str, float] = {}
    try:
        out["threads"] = float(_process().num_threads())
    except Exception:  # noqa: BLE001 - no psutil, or the read failed: Python's own count
        out["threads"] = float(threading.active_count())
    with contextlib.suppress(Exception):  # an optional reading: absent when it fails
        import psutil

        out["swap"] = psutil.swap_memory().used / (1024 * 1024)
    return out


def _slow_readings(now: float) -> dict[str, float]:
    """The readings that cost a system call each and that move slowly: the data drive's free
    space, the sizes of the database, its write-ahead log and the columnar file, the thread count
    and the swap in use. Taken every ``SLOW_S``; between two readings the last one is repeated,
    which is correct for a size and honest for a minimum (it can only miss a dip shorter than
    the interval).

    What could not be read is ABSENT from the result, and the result replaces the last one
    whole: when the data drive is unplugged ``data_dir()`` raises, and a reading kept from before
    would be repeated as current for as long as the drive stayed away (a vanished drive reading
    as 19 GB free). The counts are still taken, because they do not need the drive."""
    global _LAST_SLOW, _SLOW
    if now - _LAST_SLOW < SLOW_S:
        return _SLOW
    _LAST_SLOW = now  # set first: a failure is retried in a minute, not on every tick
    out: dict[str, float] = _count_readings()
    try:
        base = data_dir()
        with contextlib.suppress(OSError):
            out["drive_free"] = shutil.disk_usage(base).free / (1024 * 1024)
        for key, name in (
            ("db", "open_omniscience.db"),
            ("wal", "open_omniscience.db-wal"),
            ("columnar", "analytics.duckdb"),
        ):
            size = _stat_mb(base / name)
            if size is not None:
                out[key] = size
    except Exception:  # noqa: BLE001 - the data folder is not there (DataVolumeMissing): no drive readings
        _LOG.debug("vitals history: the data folder could not be read", exc_info=True)
    _SLOW = out
    return out


def _fast_readings() -> dict[str, float]:
    """RSS, available memory and Python's allocated blocks: what moves in seconds. A reading
    that cannot be taken is absent. psutil is an optional extra: without it the history holds
    only the readings that need none."""
    out: dict[str, float] = {}
    counter = getattr(sys, "getallocatedblocks", None)
    if counter is not None:
        out["blocks"] = counter() / 1000.0
    try:
        import psutil
    except Exception:  # noqa: BLE001 - psutil is an optional extra; the reading above stays
        return out
    with contextlib.suppress(Exception):  # each reading on its own: one failing leaves the other
        out["rss"] = _process().memory_info().rss / (1024 * 1024)
    with contextlib.suppress(Exception):
        out["avail"] = psutil.virtual_memory().available / (1024 * 1024)
    return out


def _busiest(avail_mb: float | None, now: float | None = None) -> tuple[list[dict[str, Any]] | None, str | None]:
    """The busiest threads of the minute that just ended: (rows, why). Each row is the CPU a
    thread spent BETWEEN two of its own readings (``over_s`` says how many seconds apart they
    were, normally 60) with its innermost two frames.

    ``rows`` is ``None``, with the reason, when the sample was not taken (memory is short:
    ``session_pressure.json`` is already recording what every thread does then, and a second
    walk of the stacks would only add to the load) or when no thread has an earlier reading to
    take a difference from (the first minute of a session, or the first after memory was short).
    An empty list is the other fact: threads were compared and none of them burned CPU.

    A thread's CPU is read only while it is not waiting (see ``session_hwm.thread_snapshot``), so
    a thread that was waiting at the previous sample has no baseline and goes unnamed for that
    minute: a pool worker parked in its queue at the sample instant can be missed. A baseline is
    carried forward for a thread that is still alive but unread, and dropped after
    ``_BASELINE_MAX_AGE_S``. ``now`` is the monotonic clock, injected by the tests."""
    global _LAST_CPU
    try:
        from src.monitoring import session_hwm

        if avail_mb is not None:
            try:
                import psutil

                total = psutil.virtual_memory().total / (1024 * 1024)
                if avail_mb <= session_hwm._pressure_line_mb(total):
                    return None, (
                        "memory was short: session_pressure.json records what every thread does then"
                    )
            except Exception:  # noqa: BLE001
                pass
        snap = session_hwm.thread_snapshot()
    except Exception as exc:  # noqa: BLE001
        return None, f"the threads could not be sampled ({type(exc).__name__})"
    if now is None:
        now = time.monotonic()
    before = _LAST_CPU
    after: dict[int, tuple[float, float]] = {}
    alive: set[int] = set()
    scored: list[tuple[float, float, dict[str, Any]]] = []
    compared = figures = working = 0
    for entry in snap:
        tid, cpu = entry.get("tid"), entry.get("cpu_s")
        if tid is None:
            continue
        alive.add(tid)
        if not entry.get("waiting") and not entry.get("sampler"):
            working += 1  # a thread ``thread_snapshot`` meant to read a CPU figure for
        if cpu is None:
            continue
        figures += 1
        after[tid] = (cpu, now)
        was = before.get(tid)
        if was is None or now - was[1] > _BASELINE_MAX_AGE_S:
            continue
        compared += 1
        spent = cpu - was[0]
        if spent > 0:
            scored.append((spent, now - was[1], entry))
    for tid, was in before.items():
        if tid in alive and tid not in after and now - was[1] <= _BASELINE_MAX_AGE_S:
            after[tid] = was  # still there, only not read this time
    _LAST_CPU = after
    if not compared:
        # four different facts, each with its own reason: a reader of an idle night must not be told
        # that memory was short
        if not figures:
            if working:
                # a platform that cannot read a thread's CPU time (macOS: psutil's thread ids are not
                # the ones ``threading`` reports) gives no figure to a busy thread either; calling it
                # "idle" would say, every minute of a busy session, a cause that did not happen
                return None, (
                    f"the platform gave no per-thread CPU figure for the {working} thread(s) that were "
                    "not waiting, so no thread can be named"
                )
            return None, "every thread was waiting at this reading, so none had a CPU figure to compare (an idle process)"
        if not before:
            return None, "the first reading of this session: there is nothing yet to take a difference from"
        if any(now - was[1] > _BASELINE_MAX_AGE_S for was in before.values()):
            return None, (
                f"the earlier readings were more than {_BASELINE_MAX_AGE_S} s old (memory was short, "
                "or the minute stayed open while the clock stood still)"
            )
        return None, "no thread with a CPU figure had one at the earlier reading too (each was new or waiting then)"
    scored.sort(key=lambda s: -s[0])
    return [
        {
            "thread": e.get("name"), "cpu_s": round(spent, 1), "over_s": round(span),
            "frames": list(e.get("stack", []))[:2],
        }
        for spent, span, e in scored[:BUSIEST_THREADS]
    ], None


def _close_fine() -> None:
    """Finish the open five-minute bucket and fold it into its hour."""
    global _FINE_ACC, _COARSE_ACC, _COARSE_T
    acc, t = _FINE_ACC, _FINE_T
    if acc is None:
        return
    _FINE.append(acc.row(t))
    _trim(_FINE, FINE_KEEP)
    hour = t - t % COARSE_S
    if _COARSE_ACC is not None and hour != _COARSE_T:
        _COARSE.append(_COARSE_ACC.row(_COARSE_T))
        _trim(_COARSE, COARSE_KEEP)
        _COARSE_ACC = None
    if _COARSE_ACC is None:
        _COARSE_ACC, _COARSE_T = _Acc(), hour
    _COARSE_ACC.merge(acc)
    _FINE_ACC = None


def _close_hour_logs() -> None:
    """Finish the hour's log counts. The counts are swapped out under the leaf lock and the row
    is built after it is released."""
    global _HOUR_LOGS
    with _LOG_LOCK:
        counts, _HOUR_LOGS = _HOUR_LOGS, {}
        _HOUR_LOG_NAMES.clear()
    if counts:
        _LOGS.append(_logs_row(_HOUR_LOGS_T, counts))
        _trim(_LOGS, LOG_KEEP)


def _minute_row(t: int, acc: _Acc, avail_mb: float | None) -> dict[str, Any]:
    """One finished minute as a row. The slow part, the thread sample, is taken here, which is
    why the caller does not hold the history's lock. ``busiest`` is ``null`` with ``busiest_why``
    when the threads could not be compared, never an empty list standing for "none was busy"."""
    row: dict[str, Any] = {"t": t, "n": acc.n}
    for key, label, which in (
        ("rss", "rss_max", "hi"),
        ("avail", "avail_min", "lo"),
        ("swap", "swap_max", "hi"),
        ("threads", "threads_max", "hi"),
    ):
        if key in acc.lo:
            row[label] = round((acc.hi if which == "hi" else acc.lo)[key])
    busiest, why = _busiest(avail_mb)
    row["busiest"] = busiest
    if busiest is None:
        row["busiest_why"] = why
    return row


def _rebase_clock(wall: float, last_wall: float) -> tuple[int, _Acc] | None:
    """The clock is further behind the open buckets than a hold can bound (a file written while
    the clock was ahead, a manual step back, a machine that woke with a wrong time): close
    everything that is open as it stands, start again at the clock's time, and record the step.
    Rows stay in the order they were written, so a reader meets the step where it happened and
    ``clock_steps`` says how far back it went (from the clock's last reading, ``last_wall``).
    A rebase that follows a hold (the step was too soon after the last rebase to start a history,
    so it was recorded and held open) is that hold ending, not a second step: the clock has gone on
    from where it stepped, so it is not behind its own last reading, and the record the hold made
    says when the new history began (``new_history_at``) instead of a second record with a size
    of nothing. Called under ``_LOCK``; returns the minute it closed, for the caller to turn into
    a row after the lock is released."""
    global _FINE_T, _COARSE_ACC, _COARSE_T, _MIN_ACC, _MIN_T, _HOUR_LOGS_T, _CLOCK_BACK, _CLOCK_HOLD
    global _HOLD_STEP
    _close_fine()
    if _COARSE_ACC is not None:
        _COARSE.append(_COARSE_ACC.row(_COARSE_T))
        _trim(_COARSE, COARSE_KEEP)
        _COARSE_ACC = None
    finished = (_MIN_T, _MIN_ACC) if _MIN_ACC is not None else None
    _MIN_ACC = None
    if _HOUR_LOGS_T:
        _close_hour_logs()
    _FINE_T = _COARSE_T = _MIN_T = _HOUR_LOGS_T = 0
    if last_wall > wall:
        _CLOCK_BACK += 1
        _CLOCK_STEPS.append({"at": _iso(wall), "was": _iso(last_wall), "back_s": int(last_wall - wall)})
        _trim(_CLOCK_STEPS, CLOCK_STEPS_KEEP)
    elif _HOLD_STEP is not None:
        _HOLD_STEP["new_history_at"] = _iso(wall)
    _CLOCK_HOLD = False  # a hold that was running ended here; a small step right after is a new one
    _HOLD_STEP = None
    return finished


def tick(now: float | None = None, mono: float | None = None) -> None:
    """Fold one reading into the history. Called by the session ledger's liveness thread every
    5 seconds, after the high-water marks. Best-effort: never raises, and flushes to disk at
    most every ``FLUSH_S``. Nothing slow runs under the history's lock: the readings are taken
    before it and the minute's thread sample after it. ``now`` is the wall clock and ``mono`` the
    monotonic one, both injected by the tests."""
    global _FINE_ACC, _FINE_T, _MIN_ACC, _MIN_T, _HOUR_LOGS_T, _CLOCK_BACK, _CLOCK_HOLD, _LAST_REBASE
    global _LAST_WALL, _HOLD_STEP
    try:
        if not _STARTED:
            return
        started_wall, started_cpu = time.perf_counter(), _thread_cpu()
        wall = time.time() if now is None else now
        mono = time.monotonic() if mono is None else mono
        sample = _fast_readings()
        sample.update(_slow_readings(mono))
        finished: tuple[int, _Acc] | None = None
        with _LOCK:
            fine_t = int(wall // FINE_S) * FINE_S
            last_wall = float(_FINE_T) if _LAST_WALL is None else _LAST_WALL  # the bucket's start, before this session's first tick
            if _FINE_ACC is not None and fine_t < _FINE_T:
                big = _FINE_T - fine_t > CLOCK_HOLD_S
                if big and mono - _LAST_REBASE >= REBASE_MIN_GAP_S:
                    _LAST_REBASE = mono
                    finished = _rebase_clock(wall, last_wall)
                else:
                    # a small step back (or a big one that follows another too soon): stay in the
                    # open bucket, never reorder; one step, however many ticks it lasts
                    if not _CLOCK_HOLD:
                        _CLOCK_HOLD = True
                        _CLOCK_BACK += 1
                        step = {"at": _iso(wall), "was": _iso(last_wall), "back_s": int(last_wall - wall)}
                        if big:
                            step["kept_open"] = True
                        _CLOCK_STEPS.append(step)
                        _trim(_CLOCK_STEPS, CLOCK_STEPS_KEEP)
                        _HOLD_STEP = step
                    fine_t = _FINE_T
            else:
                _CLOCK_HOLD = False
                _HOLD_STEP = None
            if _FINE_ACC is not None and fine_t != _FINE_T:
                _close_fine()
            if _FINE_ACC is None:
                _FINE_ACC, _FINE_T = _Acc(), fine_t
            _FINE_ACC.add(sample)
            minute_t = int(wall // MINUTE_S) * MINUTE_S
            if _MIN_ACC is not None and minute_t > _MIN_T:
                finished = (_MIN_T, _MIN_ACC)
                _MIN_ACC = None
            if _MIN_ACC is None:
                _MIN_ACC, _MIN_T = _Acc(), max(minute_t, _MIN_T)
            _MIN_ACC.add(sample)
            _LAST_WALL = wall
            hour_t = int(wall // COARSE_S) * COARSE_S
            if _HOUR_LOGS_T and hour_t > _HOUR_LOGS_T:
                _close_hour_logs()
            if hour_t > _HOUR_LOGS_T:
                _HOUR_LOGS_T = hour_t
        if finished is not None:
            row = _minute_row(finished[0], finished[1], sample.get("avail"))
            with _LOCK:
                _MINUTES.append(row)
                _trim(_MINUTES, MINUTE_KEEP)
        _ensure_handler()
        _note_cost("tick", started_wall, started_cpu)
        if mono - _LAST_FLUSH >= FLUSH_S:
            flush()
    except Exception as exc:  # noqa: BLE001 - a recorder never raises into its caller
        _note_error("tick", exc)
        _LOG.debug("vitals history tick failed", exc_info=True)


def _thread_cpu() -> float | None:
    """This thread's CPU seconds, or ``None`` where the platform has no per-thread clock
    (``time.thread_time`` raises there): the cost then reports its wall time only, and the
    recorder keeps recording instead of failing every tick on a clock it only wanted for its
    own cost."""
    try:
        return time.thread_time()
    except Exception:  # noqa: BLE001 - OSError or AttributeError, by platform
        return None


def _reason(exc: BaseException) -> str:
    """What a failure may leave in the zip: its type and, for an operating-system error, the
    system's own reason ("No space left on device"), cut to 120 characters. Never its message,
    which can name a path or carry text a user typed."""
    reason = type(exc).__name__
    if isinstance(exc, OSError) and exc.strerror:
        reason += f": {exc.strerror}"
    return reason[:120]


def _note_error(what: str, exc: BaseException) -> None:
    """Count a failure of the recorder's own work and keep the last one's reason (``_reason``)."""
    with contextlib.suppress(Exception):
        _ERRORS[f"{what}_failures"] = _ERRORS.get(f"{what}_failures", 0) + 1
        _ERRORS[f"last_{what}_error"] = {"at": _iso(time.time()), "error": _reason(exc)}


def _note_cost(what: str, started_wall: float, started_cpu: float | None) -> None:
    """What a tick or a flush cost: this thread's CPU time and the wall time, kept apart because
    under busy Python threads the wall time is mostly waiting for the interpreter lock (measured:
    a tick is about 1 ms of CPU and about 50 ms of wall with three busy threads), and a reader
    taking the wall figure for work would blame the recorder for the machine's load."""
    ended_cpu = _thread_cpu()
    cpu = None if started_cpu is None or ended_cpu is None else round((ended_cpu - started_cpu) * 1000, 2)
    wall = round((time.perf_counter() - started_wall) * 1000, 2)
    _COST[f"{what}_cpu_ms_last"], _COST[f"{what}_wall_ms_last"] = cpu, wall  # cpu: null, never 0, when unread
    if cpu is not None:
        _COST[f"{what}_cpu_ms_max"] = max(_COST.get(f"{what}_cpu_ms_max") or 0.0, cpu)
    _COST[f"{what}_wall_ms_max"] = max(_COST.get(f"{what}_wall_ms_max") or 0.0, wall)


def _ensure_handler() -> None:
    """The log counter on the root logger, re-attached when something removed it."""
    global _HANDLER
    root = logging.getLogger()
    if _HANDLER is None:
        _HANDLER = _CountHandler(level=logging.NOTSET)
    if _HANDLER not in root.handlers:
        root.addHandler(_HANDLER)


def _state_doc() -> dict[str, Any]:
    """The state as the document the file holds: the closed rows, and the OPEN accumulators as
    rows kept apart from them, so a restart resumes the open bucket without counting a tick
    twice (the open hour holds only the five-minute buckets that are already closed). The open
    hour's log counts are kept as the raw (logger, level, count) triples, not as the display row
    that sums the quiet loggers, so a second restart in the same hour loses nothing. Lock order
    is ``_LOCK`` then ``_LOG_LOCK``, as in ``tick``: one hold, so a tick that closes the hour
    cannot make the same counts appear twice."""
    with _LOCK:
        with _LOG_LOCK:
            counts = dict(_HOUR_LOGS)  # a C-level copy: no bytecode runs inside it, so nothing can re-enter ``emit``
        # walked outside the leaf lock: a finalizer that logs while this runs adds a key to the live
        # dictionary, never to the copy (iterating the live one under the re-entrant lock raised
        # "dictionary changed size" and failed the flush or the member)
        open_counts = sorted([name, letter, n] for (name, letter), n in counts.items())
        return {
            "fine": [list(r) for r in _FINE],
            "open_fine": _FINE_ACC.row(_FINE_T) if _FINE_ACC is not None else None,
            "coarse": [list(r) for r in _COARSE],
            "open_coarse": _COARSE_ACC.row(_COARSE_T) if _COARSE_ACC is not None else None,
            "logs": [dict(r) for r in _LOGS],
            # dated when written, never 0 for counts that exist: a session that ends before its first
            # tick still has the lines of its boot, and a 0 here made the next start drop them
            "open_logs_t": (_HOUR_LOGS_T or int(time.time() // COARSE_S) * COARSE_S) if open_counts else 0,
            "open_logs_counts": open_counts,
            "minutes": [dict(r) for r in _MINUTES],
            "previous_sessions": [dict(p) for p in _PREVIOUS],
            "session_starts": [dict(s) for s in _SESSIONS],
            "clock_stepped_back": _CLOCK_BACK,
            "clock_steps": [dict(c) for c in _CLOCK_STEPS],
        }


def _view_from_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """The tables a reader sees: each open bucket appended to its table, and the open hour's row
    made of the closed five-minute buckets plus the open one."""
    fine = _rows(doc.get("fine"))
    open_fine = _row(doc.get("open_fine"))
    if open_fine:
        fine.append(open_fine)
    coarse = _rows(doc.get("coarse"))
    pending: dict[int, _Acc] = {}
    open_coarse = _row(doc.get("open_coarse"))
    if open_coarse:
        pending[int(open_coarse[0])] = _from_row(open_coarse)
    if open_fine:
        hour = int(open_fine[0]) - int(open_fine[0]) % COARSE_S
        pending.setdefault(hour, _Acc()).merge(_from_row(open_fine))
    for hour in sorted(pending):
        coarse.append(pending[hour].row(hour))
    logs = _dicts(doc.get("logs"))
    open_counts = _counts_from_triples(doc.get("open_logs_counts"))
    open_t = _whole(doc.get("open_logs_t"))
    if open_counts and open_t:
        logs.append({**_logs_row(open_t, open_counts), "open": True})
    return {"fine": fine, "coarse": coarse, "logs": logs, "minutes": _dicts(doc.get("minutes"))}


def flush() -> None:
    """Write the history now (atomic, no fsync). Called every ``FLUSH_S`` by ``tick`` and at a
    clean end; best-effort. A write that fails (the drive is full or read-only) is tried again
    in ``FLUSH_RETRY_S``, not on every tick, and is counted in ``cost``."""
    global _LAST_FLUSH, _LAST_FLUSH_AT
    try:
        if not _STARTED:
            return
        started_wall, started_cpu = time.perf_counter(), _thread_cpu()
        try:
            doc = _state_doc()
            doc.update({"schema": SCHEMA, "saved_at": _iso(time.time())})
            target = _path()
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
            os.replace(tmp, target)
        except Exception as exc:
            with _LOCK:
                _LAST_FLUSH = time.monotonic() - FLUSH_S + FLUSH_RETRY_S
            _note_error("flush", exc)
            raise
        with _LOCK:
            _LAST_FLUSH = time.monotonic()
            _LAST_FLUSH_AT = doc["saved_at"]
        _note_cost("flush", started_wall, started_cpu)
        _COST["flush_bytes_last"] = float(target.stat().st_size)
    except Exception:  # noqa: BLE001
        _LOG.debug("vitals history flush failed", exc_info=True)


def _load() -> dict[str, Any] | None:
    try:
        got = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(got, dict) or got.get("schema") != SCHEMA:
        return None
    return got


def _list(raw: Any) -> list[Any]:
    """``raw`` if it is a list, else an empty one: a field of the wrong type in an otherwise valid
    file (hand-edited, or written by another build) costs that field, never the whole history."""
    return raw if isinstance(raw, list) else []


def _dicts(raw: Any) -> list[dict[str, Any]]:
    return [x for x in _list(raw) if isinstance(x, dict)]


def _whole(raw: Any) -> int:
    """An integer field of the file, or 0."""
    if isinstance(raw, bool):
        return 0
    try:
        return int(raw or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


#: What a stored value may be before the row that carries it is dropped. What they protect: a hand-edited
#: file or another build is a valid JSON document whose numbers can be absurd (an integer of 309 digits,
#: a time in the year 10**8), and ``_iso`` or a float conversion raises on those, which would empty the
#: history at start or turn the member off until 576 newer rows push the row out (48 hours). A time
#: ends in 2100 (4,102,444,800 s), a row counts at most a billion ticks, a reading stays under 10**15
#: (a byte count of a petabyte); NaN and infinity fail the comparison without an import.
_MAX_EPOCH = 4_102_444_800
_MAX_TICKS = 10**9
_MAX_CELL = 1e15


def _whole_in(raw: Any, limit: int) -> bool:
    return isinstance(raw, int) and not isinstance(raw, bool) and 0 <= raw < limit


def _number(raw: Any) -> bool:
    return isinstance(raw, int | float) and not isinstance(raw, bool) and abs(raw) < _MAX_CELL


def _row(raw: Any) -> list[Any] | None:
    """One stored row of this build's layout, or ``None``: the right length, a whole ``t`` (a time
    before 2100) and a whole ``n``, every other cell a number under 10**15 or null. A cell of another
    type or size (a hand-edited file, another build) would end in ``int(...)`` at start or in
    ``_gaps`` and take the history with it, so the row that carries it is dropped alone."""
    if not isinstance(raw, list) or len(raw) != len(COLUMNS):
        return None
    if not (_whole_in(raw[0], _MAX_EPOCH) and _whole_in(raw[1], _MAX_TICKS)):
        return None
    return raw if all(x is None or _number(x) for x in raw[2:]) else None


def _rows(raw: Any) -> list[list[Any]]:
    """The stored rows that have the layout this build writes; anything else is dropped."""
    return [r for r in map(_row, _list(raw)) if r is not None]


def _counts_from_triples(raw: Any) -> dict[tuple[str, str], int]:
    """The (logger, level) -> count table a stored list of [logger, level, count] describes;
    anything that is not that shape is dropped."""
    out: dict[tuple[str, str], int] = {}
    for item in _list(raw):
        if (
            isinstance(item, list) and len(item) == 3 and isinstance(item[0], str)
            and item[1] in ("c", "e", "w", "i", "d") and isinstance(item[2], int) and item[2] > 0
        ):
            out[(item[0], item[1])] = out.get((item[0], item[1]), 0) + item[2]
    return out


def start(now: float | None = None) -> None:
    """Read the previous session's history from disk and begin this session's. Idempotent; the
    session ledger calls it where it starts its liveness thread. What the previous session
    last wrote becomes one of ``previous_sessions`` (its last minutes), its closed rows stay in
    the history and its open buckets resume, so a restart leaves a gap and not a hole. The log
    hour that was open is resumed only when it is still the current hour; otherwise it is
    closed here, before the counter is attached, so this session's first lines are never dated
    into an hour that ended while the process was down. ``now`` is the wall clock, injected by
    the tests."""
    global _STARTED, _FINE, _COARSE, _LOGS, _MINUTES, _SESSIONS, _PREVIOUS, _LAST_FLUSH_AT
    global _FINE_ACC, _FINE_T, _COARSE_ACC, _COARSE_T, _HOUR_LOGS, _HOUR_LOGS_T, _CLOCK_BACK
    global _CLOCK_STEPS, _LAST_WALL
    wall = time.time() if now is None else now
    with _LOCK:
        if _STARTED:
            return
        try:
            prev = _load()
            if prev is not None:
                _FINE, _COARSE = _rows(prev.get("fine")), _rows(prev.get("coarse"))
                _LOGS = _dicts(prev.get("logs"))
                _SESSIONS = _dicts(prev.get("session_starts"))
                _CLOCK_BACK = _whole(prev.get("clock_stepped_back"))
                _CLOCK_STEPS = _dicts(prev.get("clock_steps"))[-CLOCK_STEPS_KEEP:]
                open_fine = _rows([prev.get("open_fine")])
                if open_fine:
                    _FINE_ACC, _FINE_T = _from_row(open_fine[0]), int(open_fine[0][0])
                open_coarse = _rows([prev.get("open_coarse")])
                if open_coarse:
                    _COARSE_ACC, _COARSE_T = _from_row(open_coarse[0]), int(open_coarse[0][0])
                restored = _counts_from_triples(prev.get("open_logs_counts"))
                if restored and _whole(prev.get("open_logs_t")):
                    with _LOG_LOCK:
                        _HOUR_LOGS = restored
                        _HOUR_LOG_NAMES.update(name for name, _ in restored if name != _OVERFLOW)
                    _HOUR_LOGS_T = _whole(prev.get("open_logs_t"))
                    if int(wall // COARSE_S) * COARSE_S != _HOUR_LOGS_T:
                        _close_hour_logs()
                        _HOUR_LOGS_T = 0
                minutes = _dicts(prev.get("minutes"))
                carried: list[dict[str, Any]] = [
                    {"last_flush_at": p.get("last_flush_at"), "minutes": _dicts(p.get("minutes"))}
                    for p in _dicts(prev.get("previous_sessions"))
                ]
                if minutes:
                    # a session that wrote no minute of its own (it died before its second write,
                    # five minutes in) leaves the tails it inherited as they were; one that wrote a
                    # few adds its tail, and a SHORT tail is the first to go when there are more
                    # than ``PREVIOUS_SESSIONS_KEEP``, so a crash loop does not push out the tail
                    # of the session that ran long enough to say how it died
                    carried.append({"last_flush_at": prev.get("saved_at"), "minutes": minutes[-PREVIOUS_TAIL_KEEP:]})
                while len(carried) > PREVIOUS_SESSIONS_KEEP:
                    short = [i for i, p in enumerate(carried) if len(p["minutes"]) < PREVIOUS_TAIL_MIN]
                    del carried[short[0] if short else 0]
                _PREVIOUS = carried
                _LAST_FLUSH_AT = prev.get("saved_at")
        except Exception:  # noqa: BLE001 - a damaged file starts a fresh history
            _LOG.debug("vitals history: could not read the previous file", exc_info=True)
            _FINE, _COARSE, _LOGS, _SESSIONS, _PREVIOUS, _CLOCK_STEPS = [], [], [], [], [], []
            _FINE_ACC = _COARSE_ACC = None
            _FINE_T = _COARSE_T = _HOUR_LOGS_T = 0
            _CLOCK_BACK = 0
            with _LOG_LOCK:
                _HOUR_LOGS = {}
                _HOUR_LOG_NAMES.clear()
        _MINUTES = []
        _LAST_WALL = None
        _SESSIONS.append({"t": int(wall), "pid": os.getpid()})
        _trim(_SESSIONS, SESSIONS_KEEP)
        _STARTED = True
    _ensure_handler()
    atexit.unregister(flush)
    atexit.register(flush)


def _gaps(fine: list[list[Any]], steps: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Where the five-minute rows stop for longer than two buckets: the process was down, the
    machine asleep, or the file was written by an older build. Newest ``GAPS_KEEP``. A gap that
    has a recorded clock step inside it or at its edge says so (``clock_step``): it may be the
    clock's correction forward and not time the process was down (a forward step is not recorded,
    so a gap without the mark can still be one)."""
    out: list[dict[str, Any]] = []
    times = [int(r[0]) for r in fine]
    stamps = [str(x) for st in steps or [] for x in (st.get("at"), st.get("was")) if x]
    for before, after in zip(times, times[1:], strict=False):
        if after - before > 2 * FINE_S:
            gap = {"from": _iso(before + FINE_S), "to": _iso(after), "seconds": after - before - FINE_S}
            if any(_iso(before) <= stamp <= _iso(after + FINE_S) for stamp in stamps):
                gap["clock_step"] = True
            out.append(gap)
    return out[-GAPS_KEEP:]


def diagnostics_member(max_bytes: int = MEMBER_BUDGET_BYTES) -> dict[str, Any]:
    """The history as a bundle member (the R119 slot contract: never raises, keeps the newest
    rows, says what it dropped to stay inside ``max_bytes``). In a process that is not
    recording (the liveness thread is switched off) it reports what the file holds and says
    that nothing is being added."""
    try:
        recording = _STARTED
        if recording:
            doc = _state_doc()
            with _LOCK:
                last_flush_at = _LAST_FLUSH_AT
                cost = dict(_COST)
            errors = dict(_ERRORS)
        else:
            doc = _load() or {}
            last_flush_at = doc.get("saved_at")
            cost = {}
            errors = {}
        previous = [p for p in _dicts(doc.get("previous_sessions")) if p.get("minutes")]
        view = _view_from_doc(doc)
        flush_age: int | None = None
        if last_flush_at:
            try:
                stamp = datetime.fromisoformat(str(last_flush_at).replace("Z", "+00:00")).timestamp()
                flush_age = round(time.time() - stamp)
            except ValueError:
                flush_age = None
        member: dict[str, Any] = {
            "available": bool(view["fine"]) or recording,
            "recording": recording,
            "schema": SCHEMA,
            "method": (
                "Counts and sizes read from the kernel's own counters on the 5-second liveness tick, "
                "folded into buckets; written to disk every five minutes and at a clean end. "
                "`fine` rows are 5-minute buckets (48 h), `coarse` rows hourly (14 d); a row is "
                f"{list(COLUMNS)} with memory and sizes in whole MiB and blocks in thousands; `null` is a "
                "reading that could not be taken, never zero; `n` is the ticks a bucket holds "
                f"(a full 5-minute bucket holds up to {FINE_S // 5}: about 55 to 59 on a busy machine, "
                "where each tick waits for the interpreter, and more after a held clock step; a bucket "
                "with far fewer says the process was young or stopped, or the machine was asleep); "
                "swap and the thread count are read once a minute, the memory readings every tick; "
                "`minutes` is the last hour, one row a minute, with the three busiest threads of that "
                "minute (`cpu_s` is the CPU a thread spent between two of its own readings, `over_s` "
                "apart, with its innermost two frames; a thread that was waiting at the previous "
                "reading has no earlier figure and is not named that minute; `busiest` is `null` with "
                "`busiest_why` when the threads could not be compared, and the reason says which: "
                "memory was short (session_pressure.json records the threads then), every thread was "
                "waiting at the reading (an idle process), the platform gave no per-thread CPU figure "
                "to the threads that were working, the earlier reading was too old, or it is the "
                "first reading of the session); "
                "`logs` counts the lines that reached the root logger per hour by logger and level "
                "(c critical, e error, w warning, i info, d debug), the loggers past the eight "
                "busiest summed in `other`; rows are in the order they were written and "
                "`clock_steps` says where the clock stepped back and by how much from its own last reading "
                "(`kept_open`: a step too soon after the last one to start a new history, held in the open "
                "bucket until the interval passes, when `new_history_at` says where the new history "
                "began; a hold is one record at the size it began with, so a deeper step inside the "
                "rate-limit window lands in no record; a held step also lengthens one minute row, "
                "whose `n` says by how much); a gap "
                "marked `clock_step` is next to a recorded step and may be the clock's correction forward "
                "(forward steps are not recorded) and not down time; `previous_sessions` holds the last "
                "minutes of the sessions before this one (newest last); `open` on a log hour marks the "
                "hour that was open at the last write."
            ),
            "caveat": (
                "A kill loses the ticks since the last flush (up to five minutes), so the minutes "
                "before a kill are not claimed here: `tail_in` names the record that carries them. "
                "Log counts are of the records that reached the root logger: each logger's own level "
                "decides that, so a logger the app set to INFO is counted at INFO while `log_level`, "
                "the root's own, may say WARNING. Nothing is interpolated across a gap."
            ),
            "cost_note": (
                "`cpu` is the CPU time of the thread that took the reading; `wall` includes waiting "
                "for the interpreter, which under busy threads is most of it and is the machine's "
                "load, not the recorder's work (`null` where the platform has no per-thread clock). `errors` counts this session's failed ticks and failed "
                "writes of the recorder itself, counted over the whole session and never reset, with the "
                "last one's type and, for an operating-system error, the system's reason (no message, "
                "which can name a path)."
            ),
            "columns": list(COLUMNS),
            "bucket_s": {"fine": FINE_S, "coarse": COARSE_S, "minutes": MINUTE_S},
            "retention": {
                "fine_h": FINE_KEEP * FINE_S // 3600,
                "coarse_d": COARSE_KEEP * COARSE_S // 86400,
                "minutes": MINUTE_KEEP,
                "logs_d": LOG_KEEP // 24,
            },
            "log_level": logging.getLevelName(logging.getLogger().getEffectiveLevel()),
            "last_flush_at": last_flush_at,
            "last_flush_age_s": flush_age,
            "tail_in": TAIL_IN
            if TAIL_IN is not None
            else {
                "member": None,
                "why": "no finer record of the minutes before a kill is built yet; this history is the only record",
            },
            "now": _iso(time.time()),
            "clock_stepped_back": _whole(doc.get("clock_stepped_back")),
            "clock_steps": _dicts(doc.get("clock_steps")),
            "cost": cost,
            "errors": errors,
            "fine": view["fine"],
            "coarse": view["coarse"],
            "logs": view["logs"],
            "minutes": view["minutes"],
            "session_starts": [
                {"at": _iso(s["t"]), "pid": s.get("pid")}
                for s in _dicts(doc.get("session_starts"))
                if _number(s.get("t")) and 0 <= s["t"] < _MAX_EPOCH
            ],
            "gaps": _gaps(view["fine"], _dicts(doc.get("clock_steps"))),
        }
        if previous:
            member["previous_sessions"] = previous
        return _fit(member, max_bytes)
    except Exception as exc:  # noqa: BLE001 - a member that fails says so
        return {"available": False, "error": _reason(exc)}


def _fit(member: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    """Drop the OLDEST rows, from the largest table first, until the member fits, and say what
    was dropped. The newest rows are the ones an investigation needs. A budget too small for one
    row of every table cannot be met, and the member says so instead of claiming it was."""
    dropped: dict[str, int] = {}
    tables = ("fine", "coarse", "logs", "minutes")

    def encoded(value: Any) -> int:
        return len(json.dumps(value, separators=(",", ":")).encode("utf-8"))

    def say() -> None:
        member["dropped_oldest_rows"] = dict(dropped)
        member["dropped_why"] = (
            f"the member is held to {max_bytes} bytes; the newest rows are kept"
            + ("; of the earlier sessions' tails the shortest went first" if "previous_sessions" in dropped else "")
        )

    total = encoded(member)
    while total > max_bytes:
        sizes = {k: encoded(member.get(k) or []) for k in tables if len(member.get(k) or []) > 1}
        if sizes:
            name = max(sizes, key=lambda k: sizes[k])
            rows = member[name]
            cut = max(1, len(rows) // 10)
            member[name] = rows[cut:]
        elif len(member.get("previous_sessions") or []) > 1:
            # the earlier sessions' tails are what says how the last crash happened and they are
            # small: they are cut only when every other table is down to its newest row, and then
            # the shortest tail goes first (the one that says the least)
            name, cut = "previous_sessions", 1
            tails = member[name]
            shortest = min(range(len(tails)), key=lambda i: (len(tails[i].get("minutes") or []), i))
            member[name] = tails[:shortest] + tails[shortest + 1:]
        else:
            break
        dropped[name] = dropped.get(name, 0) + cut
        say()  # the notes weigh something too: measured with them in, not added after the check
        total = encoded(member)
    if total > max_bytes:
        member["over_budget_bytes"] = 0
        member["dropped_why"] = (
            f"the member could not be held to {max_bytes} bytes: every table is down to its newest row"
        )
        member["over_budget_bytes"] = encoded(member)
    return member


def reset_for_tests() -> None:
    """Forget the in-memory state and detach the log counter. Test-only."""
    global _STARTED, _FINE, _COARSE, _LOGS, _MINUTES, _SESSIONS, _PREVIOUS, _CLOCK_BACK
    global _CLOCK_HOLD, _CLOCK_STEPS, _LAST_REBASE, _LAST_WALL, _HOLD_STEP
    global _LAST_FLUSH, _LAST_FLUSH_AT, _FINE_ACC, _FINE_T, _COARSE_ACC, _COARSE_T
    global _MIN_ACC, _MIN_T, _HOUR_LOGS, _HOUR_LOGS_T, _SLOW, _LAST_SLOW, _LAST_CPU, _HANDLER
    global _PROC, _COST, TAIL_IN
    with _LOCK:
        if _HANDLER is not None:
            logging.getLogger().removeHandler(_HANDLER)
        _STARTED = False
        _FINE, _COARSE, _LOGS, _MINUTES, _SESSIONS = [], [], [], [], []
        _PREVIOUS = []
        _CLOCK_BACK = 0
        _CLOCK_HOLD = False
        _HOLD_STEP = None
        _CLOCK_STEPS = []
        _LAST_REBASE = float("-inf")
        _LAST_WALL = None
        _LAST_FLUSH, _LAST_FLUSH_AT = float("-inf"), None
        _FINE_ACC = _COARSE_ACC = _MIN_ACC = None
        _FINE_T = _COARSE_T = _MIN_T = _HOUR_LOGS_T = 0
        with _LOG_LOCK:
            _HOUR_LOGS = {}
            _HOUR_LOG_NAMES.clear()
        _SLOW, _LAST_SLOW, _LAST_CPU = {}, float("-inf"), {}
        _HANDLER = None
        _PROC = None
        _COST = {}
        _ERRORS.clear()
        TAIL_IN = None
