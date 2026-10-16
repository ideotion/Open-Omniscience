"""
Slow-query + EXPLAIN QUERY PLAN log — the "which query scans the whole corpus?" log.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Recursive-augmentation log #3 (maintainer 2026-07-02): the scaling pain (trending /
top_terms / associations freezing at ~10M mentions) is a QUERY problem — a scan of the
mentions table where an index or a rollup should serve it. A passive listener records
every statement slower than a threshold (bounded ring buffer, normalised so a poll loop
doesn't flood it), and an on-demand ``EXPLAIN QUERY PLAN`` over the real encrypted store
tells me EXACTLY which query scans vs uses an index — far more actionable than a
benchmark alone. It is the key to "where do I add a covering index or a rollup?".

Honesty + safety: local-only, network-free, timings + SQL shape only (bound values are
NOT recorded — no corpus content leaks). The listener never raises (a broken log must
not break the app). EXPLAIN is read-only and deadline-guarded.

It sees SINGLE statements: a read that totals minutes as thousands of short statements (the chunked
trending and corpus-keyword reads, ``database/query.py``) no longer shows up here as one slow query.

WALL TIME ALONE CANNOT SAY WHY A STATEMENT WAS SLOW. The 16 Oct 2026 bundles show a ``SAVEPOINT`` (no table, index, FTS
or WAL work) averaging 36.5 s against 35.0 s for an ``INSERT INTO articles``, so most of the interval was not the
statement's own work, and the record could not say what it was. Each record therefore also carries what the EXECUTING
THREAD did over the same interval, taken from the OS at the two listeners (about one microsecond a statement):

* ``cpu_ms``: the thread's CPU time (user and system) over the interval. CPU close to the wall time means the statement
  worked; far below it means the thread waited.
* ``nvcsw``: voluntary context switches, the thread giving the CPU up to wait (a lock, a sleep, a read, the GIL). A
  large count with ``cpu_ms`` far below the wall time is a wait. It CANNOT tell a SQLite busy-handler sleep from a wait
  for the GIL: both are voluntary, so a wait is named a wait and its owner is not guessed.
* ``nivcsw``: involuntary switches, the scheduler taking the CPU away: CPU starvation (50 workers on 2 cores).
* ``majflt`` and ``inblock``: major page faults and blocks read from disk during the interval: memory pushed out to swap,
  or cold pages, as against a lock.

The numbers are ABSENT, never 0, where the OS cannot give them (``RUSAGE_THREAD`` is Linux only; ``time.thread_time``
may be unavailable): a 0 would read as "the thread did not wait". They are counts and seconds: no statement text, no
bound value. The interval is the one between this module's two listeners, which is the DBAPI call to within the listeners
registered before it (the stale-library check and the statement-kind note both run first, and no other
``after_cursor_execute`` listener exists), so it is the same interval the wall time was always taken over.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any

try:  # POSIX only: Windows has no resource module, and the numbers it gives are then absent, not 0
    import resource as _resource
except ImportError:  # pragma: no cover - platform
    _resource = None  # type: ignore[assignment]

from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.monitoring.secret_scrub import record_text

_CAP = 200  # newest slow-query records kept
_LOCK = threading.Lock()
_RING: deque[dict[str, Any]] = deque(maxlen=_CAP)
_AGG: dict[str, dict[str, Any]] = {}  # normalised SQL -> {count, total_ms, max_ms, sample}
_installed = False

# Per-connection start time is stashed on the DBAPI cursor's context via info dict.
_START_KEY = "_oo_slowq_start"

_NUM_RE = re.compile(r"\b\d+\b")
_STR_RE = re.compile(r"'[^']*'")
_WS_RE = re.compile(r"\s+")


def _threshold_ms() -> float:
    """Slow-query threshold in ms (OO_SLOW_QUERY_MS; default 500)."""
    try:
        return float(os.environ.get("OO_SLOW_QUERY_MS", "500"))
    except ValueError:
        return 500.0


def _normalise(sql: str) -> str:
    """Collapse a statement to its SHAPE — bound values stripped so nothing from the
    corpus is recorded and identical queries aggregate together."""
    s = _WS_RE.sub(" ", sql).strip()
    s = _STR_RE.sub("'?'", s)
    s = _NUM_RE.sub("?", s)
    return s[:600]


#: What the executing thread did, as the fields a record carries: the name, and where the OS gives it. ``cpu_ms`` is a float
#: (milliseconds); the rest are counts the kernel keeps per thread.
_THREAD_COUNTS = ("nvcsw", "nivcsw", "majflt", "inblock")
_RUSAGE_THREAD = getattr(_resource, "RUSAGE_THREAD", None)


def _thread_sample() -> tuple[float | None, tuple[int, int, int, int] | None]:
    """The calling thread's CPU seconds and its (nvcsw, nivcsw, majflt, inblock) counters now, each ``None`` where the OS cannot say.

    Never raises: it runs before EVERY statement the engine sends, on every thread, so an unsupported clock is "no number", not an error."""
    cpu: float | None
    try:
        cpu = time.thread_time()
    except (OSError, ValueError, AttributeError):
        cpu = None
    counts: tuple[int, int, int, int] | None = None
    if _resource is not None and _RUSAGE_THREAD is not None:
        try:
            r = _resource.getrusage(_RUSAGE_THREAD)
            counts = (int(r.ru_nvcsw), int(r.ru_nivcsw), int(r.ru_majflt), int(r.ru_inblock))
        except (OSError, ValueError):
            counts = None
    return cpu, counts


def _thread_fields(
    before: tuple[float | None, tuple[int, int, int, int] | None],
) -> dict[str, float | int]:
    """What the thread did since ``before`` (a :func:`_thread_sample`), as record fields; a field the OS could not give is left out."""
    cpu0, counts0 = before
    cpu1, counts1 = _thread_sample()
    out: dict[str, float | int] = {}
    if cpu0 is not None and cpu1 is not None:
        out["cpu_ms"] = round(max(0.0, cpu1 - cpu0) * 1000.0, 1)
    if counts0 is not None and counts1 is not None:
        for name, a, b in zip(_THREAD_COUNTS, counts0, counts1, strict=True):
            out[name] = max(0, b - a)
    return out


def _record(sql: str, duration_ms: float, thread: dict[str, float | int] | None = None) -> None:
    try:
        norm = _normalise(sql)
        at = datetime.now(UTC).isoformat(timespec="seconds")
        extra = thread or {}
        with _LOCK:
            _RING.append({"at": at, "duration_ms": round(duration_ms, 1), "sql": norm, **extra})
            agg = _AGG.get(norm)
            if agg is None:
                agg = {"count": 0, "total_ms": 0.0, "max_ms": 0.0, "sql": norm}
                # Bound the aggregate keyspace so a pathological query generator can't
                # grow it without limit (distinct shapes are few in practice).
                if len(_AGG) < 512:
                    _AGG[norm] = agg
            agg["count"] += 1
            agg["total_ms"] += duration_ms
            agg["max_ms"] = max(agg["max_ms"], duration_ms)
            # The thread's own figures, summed over the calls that HAD them (``measured``), so a figure missing on some calls is
            # not averaged as a 0 over all of them.
            if extra:
                agg["measured"] = agg.get("measured", 0) + 1
                agg["measured_ms"] = agg.get("measured_ms", 0.0) + duration_ms
                for name, value in extra.items():
                    agg[name] = agg.get(name, 0) + value
    except Exception:  # noqa: BLE001 - the log must never break the app
        return


def install(engine: Engine) -> None:
    """Attach the timing listeners to the engine (idempotent). SQLite-focused but
    harmless on any backend — it only times statements. Never raises."""
    global _installed
    if _installed:
        return
    try:

        @event.listens_for(engine, "before_cursor_execute")
        def _before(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
            # The thread's sample first, the clock last: what is measured as the statement's time must not include taking it.
            sample = _thread_sample()
            conn.info[_START_KEY] = (time.perf_counter(), sample)

        @event.listens_for(engine, "after_cursor_execute")
        def _after(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
            started = conn.info.pop(_START_KEY, None)
            if started is None:
                return
            t0, sample = started
            dur_ms = (time.perf_counter() - t0) * 1000.0
            if dur_ms >= _threshold_ms():
                _record(statement, dur_ms, _thread_fields(sample))

        _installed = True
    except Exception:  # noqa: BLE001 - instrumentation must never break boot
        return


def recent(limit: int = 100) -> list[dict[str, Any]]:
    with _LOCK:
        return list(_RING)[-limit:]


def _agg_row(a: dict[str, Any]) -> dict[str, Any]:
    """One shape's row. The thread's figures are TOTALS over the calls that had them, beside ``measured`` (how many) and
    ``measured_ms`` (their wall time), so ``cpu_ms / measured_ms`` is the share of the wall time the thread spent working."""
    row: dict[str, Any] = {
        "sql": a["sql"],
        "count": a["count"],
        "total_ms": round(a["total_ms"], 1),
        "avg_ms": round(a["total_ms"] / a["count"], 1) if a["count"] else 0.0,
        "max_ms": round(a["max_ms"], 1),
    }
    if a.get("measured"):
        row["measured"] = a["measured"]
        row["measured_ms"] = round(a["measured_ms"], 1)
        for name in ("cpu_ms", *_THREAD_COUNTS):
            if name in a:
                row[name] = round(a[name], 1) if name == "cpu_ms" else int(a[name])
    return row


def _by_total() -> list[dict[str, Any]]:
    with _LOCK:
        rows = [_agg_row(a) for a in _AGG.values()]
    rows.sort(key=lambda r: r["total_ms"], reverse=True)
    return rows


# The heavy analytics whose plans I most want to see on the real corpus. Static SQL
# (no bound corpus values), so EXPLAIN is safe to expose. Kept small + representative.
_PROBE_QUERIES: list[tuple[str, str]] = [
    (
        "top_terms_corpuswide",
        "SELECT keyword_id, SUM(count) FROM keyword_mentions GROUP BY keyword_id "
        "ORDER BY 2 DESC LIMIT 50",
    ),
    (
        "trending_window",
        "SELECT keyword_id, COUNT(*) FROM keyword_mentions "
        "WHERE observed_on >= date('now','-7 day') GROUP BY keyword_id ORDER BY 2 DESC LIMIT 50",
    ),
    (
        "mentions_by_source",
        "SELECT source_id, COUNT(*) FROM keyword_mentions GROUP BY source_id",
    ),
    (
        "article_by_created",
        "SELECT id FROM articles ORDER BY created_at DESC LIMIT 50",
    ),
]


def explain_probes(session: Session) -> list[dict[str, Any]]:
    """Run EXPLAIN QUERY PLAN over the representative heavy queries and report the plan.

    A plan step containing 'SCAN' over ``keyword_mentions`` (without an index) is the
    scaling smell; 'SEARCH … USING INDEX' is the healthy shape. Read-only,
    deadline-guarded, SQLite-only."""
    bind = session.get_bind()
    if getattr(getattr(bind, "dialect", None), "name", "") != "sqlite":
        return []
    out: list[dict[str, Any]] = []
    for name, sql in _PROBE_QUERIES:
        try:
            with statement_deadline_safe(session):
                rows = session.execute(text("EXPLAIN QUERY PLAN " + sql)).fetchall()
            plan = [str(r[-1]) for r in rows]
            # SQLite marks BOTH a bare table scan and an index-only scan with "SCAN".
            # A "SCAN <table> USING [COVERING] INDEX ..." is HEALTHY (index-only); the
            # scaling smell is a bare "SCAN <table>" with no index. Flag only the latter.
            bare_scans = [
                p for p in plan if p.upper().startswith("SCAN") and "USING" not in p.upper()
            ]
            out.append(
                {
                    "name": name,
                    "plan": plan,
                    "full_scan": bool(bare_scans),
                    "scans": bare_scans,
                }
            )
        except Exception as exc:  # noqa: BLE001 - one probe failing must not abort the rest
            out.append({"name": name, "error": record_text(exc, limit=200, typed=False)})
    return out


def statement_deadline_safe(session: Session):
    """Local wrapper so this module has no hard import cycle at module load."""
    from src.database.maintenance import statement_deadline

    return statement_deadline(session, 15.0)


def summary(session: Session | None = None) -> dict[str, Any]:
    """The slow-query log: the passive ring buffer + aggregate, plus (when a session is
    given) the on-demand EXPLAIN of the heavy analytics on the live store."""
    report: dict[str, Any] = {
        "threshold_ms": _threshold_ms(),
        "installed": _installed,
        "captured": len(_RING),
        "by_total_time": _by_total()[:25],
        "recent": recent(50),
        "method": (
            "A passive listener records every statement slower than the threshold "
            "(SQL shape only — bound values stripped, no corpus content). EXPLAIN QUERY "
            "PLAN over the heavy analytics shows scan-vs-index on the real store. "
            "Read-only; no score."
        ),
    }
    if session is not None:
        report["explain"] = explain_probes(session)
    return report
