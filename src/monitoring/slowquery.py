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
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

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


def _record(sql: str, duration_ms: float) -> None:
    try:
        norm = _normalise(sql)
        at = datetime.now(UTC).isoformat(timespec="seconds")
        with _LOCK:
            _RING.append({"at": at, "duration_ms": round(duration_ms, 1), "sql": norm})
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
            conn.info[_START_KEY] = time.perf_counter()

        @event.listens_for(engine, "after_cursor_execute")
        def _after(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
            started = conn.info.pop(_START_KEY, None)
            if started is None:
                return
            dur_ms = (time.perf_counter() - started) * 1000.0
            if dur_ms >= _threshold_ms():
                _record(statement, dur_ms)

        _installed = True
    except Exception:  # noqa: BLE001 - instrumentation must never break boot
        return


def recent(limit: int = 100) -> list[dict[str, Any]]:
    with _LOCK:
        return list(_RING)[-limit:]


def _by_total() -> list[dict[str, Any]]:
    with _LOCK:
        rows = [
            {
                "sql": a["sql"],
                "count": a["count"],
                "total_ms": round(a["total_ms"], 1),
                "avg_ms": round(a["total_ms"] / a["count"], 1) if a["count"] else 0.0,
                "max_ms": round(a["max_ms"], 1),
            }
            for a in _AGG.values()
        ]
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
            out.append({"name": name, "error": str(exc)[:200]})
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
