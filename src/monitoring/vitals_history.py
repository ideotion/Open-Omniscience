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

SCHEMA = "oo-vitals-1"
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
#: tails: a crash loop restarts every few minutes, and the tail that matters is the first one, the
#: session that ran long enough to say how it died, which one short session after another would
#: otherwise push out.
PREVIOUS_TAIL_KEEP = 30
PREVIOUS_SESSIONS_KEEP = 3
#: Session starts kept (a month of daily restarts, or a crash loop's last half hour), gaps listed
#: (the member lists where rows stop; the newest fifty are the ones an investigation reads) and
#: clock steps recorded: each is one short row, bounded so a clock that keeps stepping cannot
#: grow the file.
SESSIONS_KEEP = 30
GAPS_KEEP = 50
CLOCK_STEPS_KEEP = 20
#: A clock that steps back by up to this much (two five-minute buckets, the same line the gaps
#: use, and more than a network time correction ever steps) is held in the open bucket; a bigger step closes everything that is open and starts again,
#: so a step never piles an hour of ticks into one row.
CLOCK_HOLD_S = 2 * FINE_S
#: After a failed write the next try is this soon, not on every five-second tick.
FLUSH_RETRY_S = 60.0
#: What the member may weigh, raw JSON. It protects the one zip, not the user's upload: the full
#: retention with 25 busy loggers measures about 166 KB raw (about 36 KB zipped) against the 4 MB
#: a part may weigh, and a smaller number would cut the 48 hours the member exists to show.
MEMBER_BUDGET_BYTES = 200_000

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
# RE-ENTRANT ON PURPOSE (Opus read of the first version, B1): CPython runs the cyclic collector
# and Python-level signal handlers between any two bytecodes, so a finalizer that logs (SQLAlchemy's
# pool does, and asyncio's "Task exception was never retrieved") or a SIGHUP handler that logs can
# re-enter ``emit`` on the thread that is inside it. A plain lock would make that thread wait for
# itself while holding the handler's own lock, and every later thread that logs would wait behind
# it. The critical section is dictionary updates that are consistent at every bytecode boundary,
# so the nested call just counts one more line.
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
_CLOCK_STEPS: list[dict[str, Any]] = []
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
_COST: dict[str, float] = {}
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
    compared = 0
    for entry in snap:
        tid, cpu = entry.get("tid"), entry.get("cpu_s")
        if tid is None:
            continue
        alive.add(tid)
        if cpu is None:
            continue
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
        return None, "no thread had an earlier reading to take a difference from (the first minute, or the first after memory was short)"
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


def _rebase_clock(wall: float) -> tuple[int, _Acc] | None:
    """The clock is further behind the open buckets than a hold can bound (a file written while
    the clock was ahead, a manual step back, a machine that woke with a wrong time): close
    everything that is open as it stands, start again at the clock's time, and record the step.
    Rows stay in the order they were written, so a reader meets the step where it happened and
    ``clock_steps`` says how far back it went. Called under ``_LOCK``; returns the minute it
    closed, for the caller to turn into a row after the lock is released."""
    global _FINE_ACC, _FINE_T, _COARSE_ACC, _COARSE_T, _MIN_ACC, _MIN_T, _HOUR_LOGS_T, _CLOCK_BACK
    was = _FINE_T
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
    _CLOCK_BACK += 1
    _CLOCK_STEPS.append({"at": _iso(wall), "was": _iso(was), "back_s": int(was - wall)})
    _trim(_CLOCK_STEPS, CLOCK_STEPS_KEEP)
    return finished


def tick(now: float | None = None) -> None:
    """Fold one reading into the history. Called by the session ledger's liveness thread every
    5 seconds, after the high-water marks. Best-effort: never raises, and flushes to disk at
    most every ``FLUSH_S``. Nothing slow runs under the history's lock: the readings are taken
    before it and the minute's thread sample after it."""
    global _FINE_ACC, _FINE_T, _MIN_ACC, _MIN_T, _HOUR_LOGS_T, _CLOCK_BACK, _CLOCK_HOLD
    try:
        if not _STARTED:
            return
        started_wall, started_cpu = time.perf_counter(), time.thread_time()
        wall = time.time() if now is None else now
        sample = _fast_readings()
        sample.update(_slow_readings(time.monotonic()))
        finished: tuple[int, _Acc] | None = None
        with _LOCK:
            fine_t = int(wall // FINE_S) * FINE_S
            if _FINE_ACC is not None and fine_t < _FINE_T:
                if _FINE_T - fine_t > CLOCK_HOLD_S:
                    finished = _rebase_clock(wall)
                else:
                    # a small step back: stay in the open bucket, never reorder; one step, however
                    # many ticks it lasts
                    if not _CLOCK_HOLD:
                        _CLOCK_HOLD = True
                        _CLOCK_BACK += 1
                        _CLOCK_STEPS.append({"at": _iso(wall), "was": _iso(_FINE_T), "back_s": int(_FINE_T - wall)})
                        _trim(_CLOCK_STEPS, CLOCK_STEPS_KEEP)
                    fine_t = _FINE_T
            else:
                _CLOCK_HOLD = False
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
        if time.monotonic() - _LAST_FLUSH >= FLUSH_S:
            flush()
    except Exception as exc:  # noqa: BLE001 - a recorder never raises into its caller
        _note_error("tick", exc)
        _LOG.debug("vitals history tick failed", exc_info=True)


def _note_error(what: str, exc: BaseException) -> None:
    """Count a failure of the recorder's own work and keep the last one's type and, for an
    operating-system error, its reason (never its message, which names a path)."""
    with contextlib.suppress(Exception):
        reason = type(exc).__name__
        if isinstance(exc, OSError) and exc.strerror:
            reason += f": {exc.strerror}"
        _ERRORS[f"{what}_failures"] = _ERRORS.get(f"{what}_failures", 0) + 1
        _ERRORS[f"last_{what}_error"] = {"at": _iso(time.time()), "error": reason[:120]}


def _note_cost(what: str, started_wall: float, started_cpu: float) -> None:
    """What a tick or a flush cost: this thread's CPU time and the wall time, kept apart because
    under busy Python threads the wall time is mostly waiting for the interpreter lock (measured:
    a tick is about 1 ms of CPU and about 50 ms of wall with three busy threads), and a reader
    taking the wall figure for work would blame the recorder for the machine's load."""
    cpu = round((time.thread_time() - started_cpu) * 1000, 2)
    wall = round((time.perf_counter() - started_wall) * 1000, 2)
    _COST[f"{what}_cpu_ms_last"], _COST[f"{what}_wall_ms_last"] = cpu, wall
    _COST[f"{what}_cpu_ms_max"] = max(_COST.get(f"{what}_cpu_ms_max", 0.0), cpu)
    _COST[f"{what}_wall_ms_max"] = max(_COST.get(f"{what}_wall_ms_max", 0.0), wall)


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
            open_counts = sorted([name, letter, n] for (name, letter), n in _HOUR_LOGS.items())
        return {
            "fine": [list(r) for r in _FINE],
            "open_fine": _FINE_ACC.row(_FINE_T) if _FINE_ACC is not None else None,
            "coarse": [list(r) for r in _COARSE],
            "open_coarse": _COARSE_ACC.row(_COARSE_T) if _COARSE_ACC is not None else None,
            "logs": [dict(r) for r in _LOGS],
            "open_logs_t": _HOUR_LOGS_T if open_counts else 0,
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
    fine = list(doc.get("fine") or [])
    open_fine = doc.get("open_fine")
    if open_fine:
        fine.append(open_fine)
    coarse = list(doc.get("coarse") or [])
    pending: dict[int, _Acc] = {}
    if doc.get("open_coarse"):
        pending[int(doc["open_coarse"][0])] = _from_row(doc["open_coarse"])
    if open_fine:
        hour = int(open_fine[0]) - int(open_fine[0]) % COARSE_S
        pending.setdefault(hour, _Acc()).merge(_from_row(open_fine))
    for hour in sorted(pending):
        coarse.append(pending[hour].row(hour))
    logs = list(doc.get("logs") or [])
    open_counts = _counts_from_triples(doc.get("open_logs_counts"))
    if open_counts and doc.get("open_logs_t"):
        logs.append({**_logs_row(int(doc["open_logs_t"]), open_counts), "open": True})
    return {"fine": fine, "coarse": coarse, "logs": logs, "minutes": list(doc.get("minutes") or [])}


def flush() -> None:
    """Write the history now (atomic, no fsync). Called every ``FLUSH_S`` by ``tick`` and at a
    clean end; best-effort. A write that fails (the drive is full or read-only) is tried again
    in ``FLUSH_RETRY_S``, not on every tick, and is counted in ``cost``."""
    global _LAST_FLUSH, _LAST_FLUSH_AT
    try:
        if not _STARTED:
            return
        started_wall, started_cpu = time.perf_counter(), time.thread_time()
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


def _rows(raw: Any) -> list[list[Any]]:
    """The stored rows that have the layout this build writes; anything else is dropped."""
    return [r for r in (raw or []) if isinstance(r, list) and len(r) == len(COLUMNS)]


def _counts_from_triples(raw: Any) -> dict[tuple[str, str], int]:
    """The (logger, level) -> count table a stored list of [logger, level, count] describes;
    anything that is not that shape is dropped."""
    out: dict[tuple[str, str], int] = {}
    for item in raw or []:
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
    global _CLOCK_STEPS
    wall = time.time() if now is None else now
    with _LOCK:
        if _STARTED:
            return
        try:
            prev = _load()
            if prev is not None:
                _FINE, _COARSE = _rows(prev.get("fine")), _rows(prev.get("coarse"))
                _LOGS = [r for r in prev.get("logs", []) if isinstance(r, dict)]
                _SESSIONS = [s for s in prev.get("session_starts", []) if isinstance(s, dict)]
                _CLOCK_BACK = int(prev.get("clock_stepped_back") or 0)
                _CLOCK_STEPS = [c for c in prev.get("clock_steps", []) if isinstance(c, dict)][-CLOCK_STEPS_KEEP:]
                open_fine = _rows([prev.get("open_fine")])
                if open_fine:
                    _FINE_ACC, _FINE_T = _from_row(open_fine[0]), int(open_fine[0][0])
                open_coarse = _rows([prev.get("open_coarse")])
                if open_coarse:
                    _COARSE_ACC, _COARSE_T = _from_row(open_coarse[0]), int(open_coarse[0][0])
                restored = _counts_from_triples(prev.get("open_logs_counts"))
                if restored and prev.get("open_logs_t"):
                    with _LOG_LOCK:
                        _HOUR_LOGS = restored
                        _HOUR_LOG_NAMES.update(name for name, _ in restored if name != _OVERFLOW)
                    _HOUR_LOGS_T = int(prev["open_logs_t"])
                    if int(wall // COARSE_S) * COARSE_S != _HOUR_LOGS_T:
                        _close_hour_logs()
                        _HOUR_LOGS_T = 0
                minutes = [m for m in prev.get("minutes", []) if isinstance(m, dict)]
                carried = [
                    {"last_flush_at": p.get("last_flush_at"), "minutes": [m for m in p.get("minutes", []) if isinstance(m, dict)]}
                    for p in prev.get("previous_sessions", []) if isinstance(p, dict)
                ]
                if minutes:
                    # a session that wrote no minute of its own (it was killed within its first
                    # minute) leaves the tails it inherited as they were, so a crash loop does not
                    # push out the tail of the session that ran long enough to say how it died
                    carried.append({"last_flush_at": prev.get("saved_at"), "minutes": minutes[-PREVIOUS_TAIL_KEEP:]})
                _PREVIOUS = carried[-PREVIOUS_SESSIONS_KEEP:]
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
        _SESSIONS.append({"t": int(wall), "pid": os.getpid()})
        _trim(_SESSIONS, SESSIONS_KEEP)
        _STARTED = True
    _ensure_handler()
    atexit.unregister(flush)
    atexit.register(flush)


def _gaps(fine: list[list[Any]]) -> list[dict[str, Any]]:
    """Where the five-minute rows stop for longer than two buckets: the process was down, the
    machine asleep, or the file was written by an older build. Newest ``GAPS_KEEP``."""
    out: list[dict[str, Any]] = []
    times = [int(r[0]) for r in fine]
    for before, after in zip(times, times[1:], strict=False):
        if after - before > 2 * FINE_S:
            out.append({"from": _iso(before + FINE_S), "to": _iso(after), "seconds": after - before - FINE_S})
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
        previous = [p for p in doc.get("previous_sessions") or [] if isinstance(p, dict) and p.get("minutes")]
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
                "`busiest_why` when the threads could not be compared: memory was short, because "
                "session_pressure.json records the threads then, or it is the first minute); "
                "`logs` counts the lines that reached the root logger per hour by logger and level "
                "(c critical, e error, w warning, i info, d debug), the loggers past the eight "
                "busiest summed in `other`; rows are in the order they were written and "
                "`clock_steps` says where the clock stepped back; `previous_sessions` holds the last "
                "minutes of the sessions before this one (newest last)."
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
                "load, not the recorder's work. `errors` counts this session's failed ticks and failed "
                "writes of the recorder itself, with the last one's type (no message, which can name a path)."
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
            "clock_stepped_back": int(doc.get("clock_stepped_back") or 0),
            "clock_steps": [c for c in doc.get("clock_steps") or [] if isinstance(c, dict)],
            "cost": cost,
            "errors": errors,
            "fine": view["fine"],
            "coarse": view["coarse"],
            "logs": view["logs"],
            "minutes": view["minutes"],
            "session_starts": [
                {"at": _iso(s["t"]), "pid": s.get("pid")}
                for s in (doc.get("session_starts") or [])
                if isinstance(s, dict) and isinstance(s.get("t"), int | float)
            ],
            "gaps": _gaps(view["fine"]),
        }
        if previous:
            member["previous_sessions"] = previous
        return _fit(member, max_bytes)
    except Exception as exc:  # noqa: BLE001 - a member that fails says so
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"[:300]}


def _fit(member: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    """Drop the OLDEST rows, from the largest table first, until the member fits, and say what
    was dropped. The newest rows are the ones an investigation needs. A budget too small for one
    row of every table cannot be met, and the member says so instead of claiming it was."""
    dropped: dict[str, int] = {}
    tables = ("fine", "coarse", "logs", "minutes", "previous_sessions")

    def encoded(value: Any) -> int:
        return len(json.dumps(value, separators=(",", ":")).encode("utf-8"))

    total = encoded(member)
    while total > max_bytes:
        sizes = {k: encoded(member.get(k) or []) for k in tables if len(member.get(k) or []) > 1}
        if not sizes:
            break
        name = max(sizes, key=lambda k: sizes[k])
        rows = member[name]
        cut = max(1, len(rows) // 10)
        member[name] = rows[cut:]
        dropped[name] = dropped.get(name, 0) + cut
        total = encoded(member)
    if dropped:
        member["dropped_oldest_rows"] = dropped
        member["dropped_why"] = f"the member is held to {max_bytes} bytes; the newest rows are kept"
    if total > max_bytes:
        member["over_budget_bytes"] = total
        member["dropped_why"] = (
            f"the member could not be held to {max_bytes} bytes: every table is down to its newest row"
        )
    return member


def reset_for_tests() -> None:
    """Forget the in-memory state and detach the log counter. Test-only."""
    global _STARTED, _FINE, _COARSE, _LOGS, _MINUTES, _SESSIONS, _PREVIOUS, _CLOCK_BACK
    global _CLOCK_HOLD, _CLOCK_STEPS
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
        _CLOCK_STEPS = []
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
