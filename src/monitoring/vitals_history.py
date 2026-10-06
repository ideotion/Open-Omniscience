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
  peak of swap in use, of the thread count and of Python's allocated blocks, the lowest free
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
import re
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
#: shortest.
FINE_S = 300
FINE_KEEP = 576
COARSE_S = 3600
COARSE_KEEP = 336
MINUTE_S = 60
MINUTE_KEEP = 60
LOG_KEEP = 168
#: Loggers named per hour; the rest of that hour's lines are summed under ``other``.
LOG_LOGGERS_PER_HOUR = 8
#: Distinct logger names counted in one hour before the rest fall into ``other`` (a logger
#: created per request would otherwise grow the table without bound).
_LOG_NAMES_CAP = 64
#: Written to disk this often, and at a clean end.
FLUSH_S = 300.0
#: The slow readings (stat calls, the thread sample) are taken this often.
SLOW_S = 60.0
#: Threads named per minute.
BUSIEST_THREADS = 3
#: Rows of the previous session's tail kept (the minutes before it stopped).
PREVIOUS_TAIL_KEEP = 30
SESSIONS_KEEP = 30
GAPS_KEEP = 50
#: What the member may weigh, raw JSON. It protects the one zip, not the user's upload: the full
#: retention with 25 busy loggers measures about 150 KB raw (about 40 KB zipped) against the 4 MB
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
# takes this one, for a dictionary update, and nothing else is ever done while holding it.
_LOG_LOCK = threading.Lock()
_STARTED = False
_FINE: list[list[Any]] = []
_COARSE: list[list[Any]] = []
_LOGS: list[dict[str, Any]] = []
_MINUTES: list[dict[str, Any]] = []
_SESSIONS: list[dict[str, Any]] = []
_PREVIOUS: dict[str, Any] | None = None
_CLOCK_BACK = 0
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
_LAST_CPU: dict[int, float] = {}
_PROC: Any = None
_HANDLER: _CountHandler | None = None
_COST: dict[str, float] = {}


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
                if key not in _HOUR_LOGS and len(_HOUR_LOG_NAMES) >= _LOG_NAMES_CAP and record.name not in _HOUR_LOG_NAMES:
                    key = ("other", key[1])
                _HOUR_LOG_NAMES.add(key[0])
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
    for (name, letter), n in counts.items():
        per.setdefault(name, {})[letter] = per.get(name, {}).get(letter, 0) + n
    ranked = sorted(
        per.items(),
        key=lambda kv: (-kv[1].get("c", 0) - kv[1].get("e", 0), -kv[1].get("w", 0), -sum(kv[1].values()), kv[0]),
    )
    rest: dict[str, int] = {}
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
    return row


def _stat_mb(path: Path) -> float | None:
    try:
        return os.stat(path).st_size / (1024 * 1024)
    except OSError:
        return None


def _slow_readings(now: float) -> dict[str, float]:
    """The readings that cost a system call each: the data drive's free space and the sizes of
    the database, its write-ahead log and the columnar file. Taken every ``SLOW_S``; between
    two readings the last one is repeated, which is correct for a size and honest for a
    minimum (it can only miss a dip shorter than the interval)."""
    global _LAST_SLOW, _SLOW
    if now - _LAST_SLOW < SLOW_S:
        return _SLOW
    _LAST_SLOW = now
    out: dict[str, float] = {}
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
    _SLOW = out
    return out


def _fast_readings() -> dict[str, float]:
    """RSS, available memory, swap in use, thread count and Python's allocated blocks. A
    reading that cannot be taken is absent. psutil is an optional extra: without it the
    history holds only the readings that need none."""
    global _PROC
    out: dict[str, float] = {}
    counter = getattr(sys, "getallocatedblocks", None)
    if counter is not None:
        out["blocks"] = counter() / 1000.0
    try:
        import psutil
    except Exception:  # noqa: BLE001
        out["threads"] = float(threading.active_count())
        return out
    try:
        if _PROC is None:
            _PROC = psutil.Process()
        out["rss"] = _PROC.memory_info().rss / (1024 * 1024)
        out["threads"] = float(_PROC.num_threads())
    except Exception:  # noqa: BLE001
        out.setdefault("threads", float(threading.active_count()))
    with contextlib.suppress(Exception):  # an optional reading: absent when it fails
        out["avail"] = psutil.virtual_memory().available / (1024 * 1024)
    with contextlib.suppress(Exception):
        out["swap"] = psutil.swap_memory().used / (1024 * 1024)
    return out


def _busiest(avail_mb: float | None) -> list[dict[str, Any]] | None:
    """The busiest threads of the minute that just ended: CPU seconds spent BETWEEN two
    snapshots, with the innermost two frames. ``None`` when memory is short, because
    ``session_pressure.json`` is already recording what every thread does then and a
    second walk of the stacks would only add to the load."""
    global _LAST_CPU
    try:
        from src.monitoring import session_hwm

        if avail_mb is not None:
            try:
                import psutil

                total = psutil.virtual_memory().total / (1024 * 1024)
                if avail_mb <= session_hwm._pressure_line_mb(total):
                    return None
            except Exception:  # noqa: BLE001
                pass
        snap = session_hwm.thread_snapshot()
    except Exception:  # noqa: BLE001
        return None
    now_cpu: dict[int, float] = {}
    scored: list[tuple[float, dict[str, Any]]] = []
    for entry in snap:
        tid, cpu = entry.get("tid"), entry.get("cpu_s")
        if tid is None or cpu is None:
            continue
        now_cpu[tid] = cpu
        spent = cpu - _LAST_CPU.get(tid, cpu)
        if spent > 0:
            scored.append((spent, entry))
    _LAST_CPU = now_cpu
    scored.sort(key=lambda s: -s[0])
    return [
        {"thread": e.get("name"), "cpu_s": round(spent, 1), "frames": list(e.get("stack", []))[:2]}
        for spent, e in scored[:BUSIEST_THREADS]
    ]


def _close_fine() -> None:
    """Finish the open five-minute bucket and fold it into its hour."""
    global _FINE_ACC, _FINE_T, _COARSE_ACC, _COARSE_T
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
    why the caller does not hold the history's lock."""
    row: dict[str, Any] = {"t": t, "n": acc.n}
    for key, label, which in (
        ("rss", "rss_max", "hi"),
        ("avail", "avail_min", "lo"),
        ("swap", "swap_max", "hi"),
        ("threads", "threads_max", "hi"),
    ):
        if key in acc.lo:
            row[label] = round((acc.hi if which == "hi" else acc.lo)[key])
    busiest = _busiest(avail_mb)
    if busiest is not None:
        row["busiest"] = busiest
    return row


def tick(now: float | None = None) -> None:
    """Fold one reading into the history. Called by the session ledger's liveness thread every
    5 seconds, after the high-water marks. Best-effort: never raises, and flushes to disk at
    most every ``FLUSH_S``. Nothing slow runs under the history's lock: the readings are taken
    before it and the minute's thread sample after it."""
    global _FINE_ACC, _FINE_T, _MIN_ACC, _MIN_T, _HOUR_LOGS_T, _CLOCK_BACK
    try:
        if not _STARTED:
            return
        started = time.perf_counter()
        wall = time.time() if now is None else now
        sample = _fast_readings()
        sample.update(_slow_readings(time.monotonic()))
        finished: tuple[int, _Acc] | None = None
        with _LOCK:
            fine_t = int(wall // FINE_S) * FINE_S
            if _FINE_ACC is not None and fine_t < _FINE_T:
                fine_t = _FINE_T  # the clock stepped back: stay in the open bucket, never reorder
                _CLOCK_BACK += 1
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
        _COST["tick_ms_last"] = round((time.perf_counter() - started) * 1000, 2)
        _COST["tick_ms_max"] = max(_COST.get("tick_ms_max", 0.0), _COST["tick_ms_last"])
        if time.monotonic() - _LAST_FLUSH >= FLUSH_S:
            flush()
    except Exception:  # noqa: BLE001 - a recorder never raises into its caller
        _LOG.debug("vitals history tick failed", exc_info=True)


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
    twice (the open hour holds only the five-minute buckets that are already closed)."""
    with _LOG_LOCK:
        open_counts = dict(_HOUR_LOGS)
    with _LOCK:
        return {
            "fine": [list(r) for r in _FINE],
            "open_fine": _FINE_ACC.row(_FINE_T) if _FINE_ACC is not None else None,
            "coarse": [list(r) for r in _COARSE],
            "open_coarse": _COARSE_ACC.row(_COARSE_T) if _COARSE_ACC is not None else None,
            "logs": [dict(r) for r in _LOGS],
            "open_logs": _logs_row(_HOUR_LOGS_T, open_counts) if open_counts else None,
            "minutes": [dict(r) for r in _MINUTES],
            "session_starts": [dict(s) for s in _SESSIONS],
            "clock_stepped_back": _CLOCK_BACK,
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
    if doc.get("open_logs"):
        logs.append({**doc["open_logs"], "open": True})
    return {"fine": fine, "coarse": coarse, "logs": logs, "minutes": list(doc.get("minutes") or [])}


def flush() -> None:
    """Write the history now (atomic, no fsync). Called every ``FLUSH_S`` by ``tick`` and at a
    clean end; best-effort."""
    global _LAST_FLUSH, _LAST_FLUSH_AT
    try:
        if not _STARTED:
            return
        started = time.perf_counter()
        doc = _state_doc()
        doc.update({"schema": SCHEMA, "saved_at": _iso(time.time())})
        target = _path()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, target)
        with _LOCK:
            _LAST_FLUSH = time.monotonic()
            _LAST_FLUSH_AT = doc["saved_at"]
        _COST["flush_ms_last"] = round((time.perf_counter() - started) * 1000, 2)
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


def _counts_from_row(row: dict[str, Any]) -> dict[tuple[str, str], int]:
    """The log counts an hour's row describes, so an hour that was open at the last flush
    carries on counting in the new session instead of leaving two rows for one hour."""
    out: dict[tuple[str, str], int] = {}
    named = dict(row.get("by") or {})
    if row.get("other"):
        named["other"] = row["other"]
    for name, text in named.items():
        for letter, n in re.findall(r"([cewid])(\d+)", str(text)):
            out[(str(name), letter)] = out.get((str(name), letter), 0) + int(n)
    return out


def start() -> None:
    """Read the previous session's history from disk and begin this session's. Idempotent; the
    session ledger calls it where it starts its liveness thread. What the previous session
    last wrote becomes ``previous_session`` (its last minutes), its closed rows stay in the
    history and its open buckets resume, so a restart leaves a gap and not a hole."""
    global _STARTED, _FINE, _COARSE, _LOGS, _MINUTES, _SESSIONS, _PREVIOUS, _LAST_FLUSH_AT
    global _FINE_ACC, _FINE_T, _COARSE_ACC, _COARSE_T, _HOUR_LOGS, _HOUR_LOGS_T, _CLOCK_BACK
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
                open_fine = _rows([prev.get("open_fine")])
                if open_fine:
                    _FINE_ACC, _FINE_T = _from_row(open_fine[0]), int(open_fine[0][0])
                open_coarse = _rows([prev.get("open_coarse")])
                if open_coarse:
                    _COARSE_ACC, _COARSE_T = _from_row(open_coarse[0]), int(open_coarse[0][0])
                open_logs = prev.get("open_logs")
                if isinstance(open_logs, dict) and open_logs.get("t"):
                    restored = _counts_from_row(open_logs)
                    with _LOG_LOCK:
                        _HOUR_LOGS = restored
                        _HOUR_LOG_NAMES.update(name for name, _ in restored)
                    _HOUR_LOGS_T = int(open_logs["t"])
                minutes = [m for m in prev.get("minutes", []) if isinstance(m, dict)]
                _PREVIOUS = {
                    "last_flush_at": prev.get("saved_at"),
                    "minutes": minutes[-PREVIOUS_TAIL_KEEP:],
                }
                _LAST_FLUSH_AT = prev.get("saved_at")
        except Exception:  # noqa: BLE001 - a damaged file starts a fresh history
            _LOG.debug("vitals history: could not read the previous file", exc_info=True)
            _FINE, _COARSE, _LOGS, _SESSIONS, _PREVIOUS = [], [], [], [], None
            _FINE_ACC = _COARSE_ACC = None
            _FINE_T = _COARSE_T = _HOUR_LOGS_T = 0
            with _LOG_LOCK:
                _HOUR_LOGS = {}
                _HOUR_LOG_NAMES.clear()
        _MINUTES = []
        _SESSIONS.append({"t": int(time.time()), "pid": os.getpid()})
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
                previous = dict(_PREVIOUS) if _PREVIOUS else None
                cost = dict(_COST)
        else:
            doc = _load() or {}
            last_flush_at = doc.get("saved_at")
            previous = None
            cost = {}
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
                f"{list(COLUMNS)} with memory and sizes in whole MB and blocks in thousands; `null` is a "
                "reading that could not be taken, never zero; `n` is the ticks a bucket holds "
                f"(a full 5-minute bucket holds {FINE_S // 5}); `minutes` is the last hour, one row a "
                "minute, with the three busiest threads of that minute (CPU seconds spent in it, "
                "innermost two frames; left out while memory is short, because "
                "session_pressure.json records the threads then); `logs` counts the lines that "
                "reached the root logger per hour by logger and level (c critical, e error, "
                "w warning, i info, d debug)."
            ),
            "caveat": (
                "A kill loses the ticks since the last flush (up to five minutes), so the minutes "
                "before a kill are not claimed here: `tail_in` names the record that carries them. "
                "Log counts are of the records that reached the root logger at the level the app "
                "set (`log_level`), not of every line. Nothing is interpolated across a gap."
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
            "cost": cost,
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
            member["previous_session"] = previous
        return _fit(member, max_bytes)
    except Exception as exc:  # noqa: BLE001 - a member that fails says so
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"[:300]}


def _fit(member: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    """Drop the OLDEST rows, from the largest table first, until the member fits, and say what
    was dropped. The newest rows are the ones an investigation needs."""
    dropped: dict[str, int] = {}
    tables = ("fine", "coarse", "logs", "minutes")

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
    return member


def reset_for_tests() -> None:
    """Forget the in-memory state and detach the log counter. Test-only."""
    global _STARTED, _FINE, _COARSE, _LOGS, _MINUTES, _SESSIONS, _PREVIOUS, _CLOCK_BACK
    global _LAST_FLUSH, _LAST_FLUSH_AT, _FINE_ACC, _FINE_T, _COARSE_ACC, _COARSE_T
    global _MIN_ACC, _MIN_T, _HOUR_LOGS, _HOUR_LOGS_T, _SLOW, _LAST_SLOW, _LAST_CPU, _HANDLER
    global _PROC, _COST, TAIL_IN
    with _LOCK:
        if _HANDLER is not None:
            logging.getLogger().removeHandler(_HANDLER)
        _STARTED = False
        _FINE, _COARSE, _LOGS, _MINUTES, _SESSIONS = [], [], [], [], []
        _PREVIOUS = None
        _CLOCK_BACK = 0
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
        TAIL_IN = None
