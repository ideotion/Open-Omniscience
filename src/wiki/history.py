"""The Wikipedia lane's own hourly history: what it did, kept by itself and exposed whole.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. The 17 operator bundles of 2026-10-06 could not say where the walk's time went
(it ran at 37 % of what its own answer time allows), which replies Wikipedia gave (the walk kept
only its LAST error), how long a drain held the corpus's writer, or why two lanes went quiet for
days: the counters lived in memory and a bundle read after a restart saw none of them. A
72-hour run that is meant to show the lane's limits has to leave its own record, so the lane
keeps one: an hourly aggregate per kind of event in ``wiki.db`` (``wiki_lane_hourly``), which
survives a restart and an update exactly as the run clock does.

WHAT IS RECORDED (``metric`` / ``kind``):

* ``walk`` / ``ok`` or a refusal token, per edition: requests, answer time, bytes, pages, the
  longest ``Retry-After`` seen and the latest detail (the walk's bookmark on ``ok``, the
  exception TYPE and HTTP status on a refusal, never a URL or a message);
* ``drain`` / ``ok`` or ``failed``: drains, their duration, revisions stored; ``drain_stage`` /
  ``hot-sets`` or ``feeds``: how long each stage took, and ``feeds`` is the time the corpus
  connection is held;
* ``tick`` / ``index``, ``warm``, ``walk``, ``pageviews``, ``sleep``: where the idle time of a
  tick went, which is the question the walk's pace raised;
* ``stream`` / a counter name, per edition for the kept events: what the stream delivered,
  reconnected, timed out on and failed, as per-tick differences of its own counters.

WHAT IT IS NOT. No rate, no score and no verdict: counts and milliseconds with the method
beside them. A row is an aggregate of the events that reached THIS process in that hour, so an
hour with a restart in it holds the part before and the part after added together.

BOUNDED, AND THE BOUND SAYS WHAT IT PROTECTS. Rows older than :data:`RETENTION_DAYS` are
pruned (once an hour, at the flush), because the table is read whole into a diagnostics
bundle with a size limit and seven days is the soak window's own window: a longer history
would be a second window nobody reads. The buffer is flushed in ONE lane transaction per drain
tick, never per event, so recording adds one small write every thirty seconds and nothing to
the stream's hot path.

NEVER RAISES INTO THE LANE. A history that cannot be written is counted and dropped (the
caller wraps the flush); the lane's job is the pages, not this.
"""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

_LOG = logging.getLogger("wiki.history")

#: How long an hourly row is kept. The soak window's own read window is seven days
#: (``src/monitoring/soak_window.py``); this keeps exactly what a bundle reads and the
#: diagnostics zip's size limit allows, and nothing it never opens.
RETENTION_DAYS: int = 7

#: The longest ``Retry-After`` the history will record, in seconds. A header can say anything;
#: a day is more than any wait this lane would honour, and a larger figure is a server
#: mis-speaking, not a measurement.
RETRY_AFTER_MAX_S: int = 86_400

#: The stream counters recorded as per-tick differences. All are counts the stream measured.
STREAM_DELTA_KEYS: tuple[str, ...] = (
    "events_seen",
    "events_kept",
    "events_malformed",
    "events_redirect",
    "connections",
    "read_timeouts",
    "transport_errors",
)

_DETAIL_MAX = 160


def hour_of(at: datetime) -> datetime:
    """The start of the UTC hour containing ``at``."""
    at = at.astimezone(UTC) if at.tzinfo else at.replace(tzinfo=UTC)
    return at.replace(minute=0, second=0, microsecond=0)


def retry_after_of(exc: BaseException) -> int | None:
    """The ``Retry-After`` seconds an HTTP refusal carried, or ``None``.

    Read by SHAPE (``exc.response.headers``), without importing an HTTP library: the walk module
    opens no socket and must not join the socket-importer allowlist for this. A date-form header
    is not parsed (it would need the clock and a locale); it is recorded as absent, not guessed.
    """
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        raw = headers.get("Retry-After")
    except Exception:  # noqa: BLE001 - an odd headers object is an absent header
        return None
    if raw is None:
        return None
    text = str(raw).strip()
    # ``isdigit`` alone accepts superscripts and other Unicode digits that ``int`` rejects.
    if not (text.isascii() and text.isdigit()):
        return None
    return min(int(text), RETRY_AFTER_MAX_S)


@dataclass(slots=True)
class Agg:
    """One key's events inside one hour, before they are written."""

    n: int = 0
    sum_ms: int = 0
    max_ms: int = 0
    sum_bytes: int = 0
    sum_pages: int = 0
    max_retry_after_s: int | None = None
    detail: str | None = None
    at: datetime | None = None

    def add(
        self,
        *,
        n: int = 1,
        ms: int = 0,
        bytes_: int = 0,
        pages: int = 0,
        retry_after_s: int | None = None,
        detail: str | None = None,
        at: datetime | None = None,
    ) -> None:
        self.n += int(n)
        ms = max(0, int(ms))
        self.sum_ms += ms
        self.max_ms = max(self.max_ms, ms)
        self.sum_bytes += max(0, int(bytes_))
        self.sum_pages += max(0, int(pages))
        if retry_after_s is not None:
            self.max_retry_after_s = max(self.max_retry_after_s or 0, int(retry_after_s))
        if detail is not None:
            self.detail = str(detail)[:_DETAIL_MAX]
            self.at = at

    def merge(self, other: Agg) -> None:
        self.n += other.n
        self.sum_ms += other.sum_ms
        self.max_ms = max(self.max_ms, other.max_ms)
        self.sum_bytes += other.sum_bytes
        self.sum_pages += other.sum_pages
        if other.max_retry_after_s is not None:
            self.max_retry_after_s = max(self.max_retry_after_s or 0, other.max_retry_after_s)
        if other.detail is not None and (self.at is None or (other.at or self.at) >= self.at):
            self.detail, self.at = other.detail, other.at


Key = tuple[datetime, str, str, str]


def write_agg(lane: Any, key: Key, agg: Agg) -> None:
    """Add one aggregate to its hourly row in an OPEN lane session (created if absent)."""
    from src.wiki.lane_models import WikiLaneHour

    hour, metric, edition, kind = key
    row = lane.execute(
        select(WikiLaneHour).where(
            WikiLaneHour.hour_start == hour,
            WikiLaneHour.metric == metric,
            WikiLaneHour.edition == edition,
            WikiLaneHour.kind == kind,
        )
    ).scalar_one_or_none()
    if row is None:
        row = WikiLaneHour(
            hour_start=hour, metric=metric, edition=edition, kind=kind,
            n=0, sum_ms=0, max_ms=0, sum_bytes=0, sum_pages=0,
        )
        lane.add(row)
    row.n = int(row.n or 0) + agg.n
    row.sum_ms = int(row.sum_ms or 0) + agg.sum_ms
    row.max_ms = max(int(row.max_ms or 0), agg.max_ms)
    row.sum_bytes = int(row.sum_bytes or 0) + agg.sum_bytes
    row.sum_pages = int(row.sum_pages or 0) + agg.sum_pages
    if agg.max_retry_after_s is not None:
        row.max_retry_after_s = max(int(row.max_retry_after_s or 0), agg.max_retry_after_s)
    if agg.detail is not None:
        row.last_detail = agg.detail
        row.last_at = agg.at


def record(
    lane: Any,
    metric: str,
    *,
    edition: str = "",
    kind: str = "",
    ms: int = 0,
    bytes_: int = 0,
    pages: int = 0,
    retry_after_s: int | None = None,
    detail: str | None = None,
    at: datetime | None = None,
) -> None:
    """Write ONE event straight into an open lane session, inside the caller's transaction.

    For the walk, which already writes its own page rows in a transaction per request: the
    history row rides that commit instead of costing a second one. A failure here
    is the caller's to handle; the table exists whenever the walk can write (the lane schema
    is ensured before the first walk step), and the row is two statements on a unique key.
    """
    at = at or datetime.now(UTC)
    agg = Agg()
    agg.add(ms=ms, bytes_=bytes_, pages=pages, retry_after_s=retry_after_s, detail=detail, at=at)
    write_agg(lane, (hour_of(at), metric, edition, kind), agg)


class HistoryBuffer:
    """In-memory hourly aggregates, flushed in one lane transaction per drain tick."""

    def __init__(self, *, now: Any = None) -> None:
        self._now = now or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()
        self._rows: dict[Key, Agg] = {}
        self._last_prune_hour: datetime | None = None
        #: Flushes that failed (their rows were kept for the next one), for a status surface.
        self.flush_failures = 0
        self.last_flush_error: str | None = None

    def note(
        self,
        metric: str,
        *,
        edition: str = "",
        kind: str = "",
        n: int = 1,
        ms: int = 0,
        bytes_: int = 0,
        pages: int = 0,
        retry_after_s: int | None = None,
        detail: str | None = None,
    ) -> None:
        at = self._now()
        key = (hour_of(at), metric, edition[:16], kind[:64])
        with self._lock:
            agg = self._rows.get(key)
            if agg is None:
                agg = self._rows[key] = Agg()
            agg.add(n=n, ms=ms, bytes_=bytes_, pages=pages, retry_after_s=retry_after_s,
                    detail=detail, at=at)

    def pending(self) -> int:
        with self._lock:
            return len(self._rows)

    def flush(self, lane: Any) -> int:
        """Write everything noted so far into an open lane session. Returns the rows written.

        The aggregates are taken out of the buffer FIRST and put back (merged) when the write
        fails, so a failed flush loses nothing and a concurrent ``note`` is never blocked behind
        the database. The lane's sessions do not autoflush, so the statements only reach the
        database at ``flush()`` and ``commit()``: both run INSIDE the guard, because a failure
        there is exactly the failure this has to survive.
        """
        with self._lock:
            taken, self._rows = self._rows, {}
        if not taken:
            return 0
        try:
            for key, agg in taken.items():
                write_agg(lane, key, agg)
            pruned_at = self._prune(lane)
            lane.flush()
            lane.commit()
            if pruned_at is not None:
                self._last_prune_hour = pruned_at
        except Exception as exc:  # noqa: BLE001 - kept for the next flush
            with self._lock:
                for key, agg in taken.items():
                    mine = self._rows.get(key)
                    if mine is None:
                        self._rows[key] = agg
                    else:
                        mine.merge(agg)
            self.flush_failures += 1
            self.last_flush_error = f"{type(exc).__name__}: {exc}"[:200]
            raise
        return len(taken)

    def _prune(self, lane: Any) -> datetime | None:
        """Delete rows past the retention window, at most once an hour.

        Returns the hour to remember AFTER the commit succeeds (``None`` when nothing was done),
        so a rolled-back prune is tried again at the next flush rather than skipped for an hour.
        """
        from sqlalchemy import delete

        from src.wiki.lane_models import WikiLaneHour

        hour = hour_of(self._now())
        if self._last_prune_hour == hour:
            return None
        cutoff = hour - timedelta(days=RETENTION_DAYS)
        lane.execute(delete(WikiLaneHour).where(WikiLaneHour.hour_start < cutoff))
        return hour


def snapshot(lane: Any, *, days: int = RETENTION_DAYS) -> dict:
    """The hourly rows of the last ``days`` days, whole, for a diagnostics bundle."""
    from sqlalchemy import inspect as sa_inspect

    from src.wiki.lane_models import WikiLaneHour

    method = (
        "wiki_lane_hourly: one row per hour per metric/kind/edition, aggregated by this process "
        "as events happened and flushed once per drain tick; walk rows carry requests, answer "
        "milliseconds, bytes, pages, the longest Retry-After and the latest detail (the bookmark, "
        "or a refusal's exception type and HTTP status); tick rows say where each tick's seconds "
        "went; stream rows are per-tick differences of the stream's own counters."
    )
    caveat = (
        f"Rows older than {RETENTION_DAYS} days are pruned. An hour with a restart in it holds the "
        "part before and the part after added together; an hour with no row had no such event "
        "reach this process, which is not the same as the wiki having been quiet."
    )
    out: dict = {"retention_days": RETENTION_DAYS, "method": method, "caveat": caveat, "rows": []}
    if not sa_inspect(lane.connection()).has_table(WikiLaneHour.__tablename__):
        out["reason"] = "the lane file has no history table yet (it is created when this build first opens it)"
        return out
    since = hour_of(datetime.now(UTC)) - timedelta(days=int(days))
    rows = lane.execute(
        select(WikiLaneHour)
        .where(WikiLaneHour.hour_start >= since)
        .order_by(WikiLaneHour.hour_start, WikiLaneHour.metric, WikiLaneHour.edition, WikiLaneHour.kind)
    ).scalars()
    out["rows"] = [_row_dict(r) for r in rows]
    out["rows_total"] = len(out["rows"])
    return out


def _row_dict(r: Any) -> dict:
    d: dict = {
        "hour": r.hour_start.isoformat() if r.hour_start else None,
        "metric": r.metric,
        "kind": r.kind,
        "n": int(r.n),
    }
    if r.edition:
        d["edition"] = r.edition
    if r.sum_ms:
        d["sum_ms"] = int(r.sum_ms)
        d["max_ms"] = int(r.max_ms)
    if r.sum_bytes:
        d["sum_bytes"] = int(r.sum_bytes)
    if r.sum_pages:
        d["sum_pages"] = int(r.sum_pages)
    if r.max_retry_after_s is not None:
        d["max_retry_after_s"] = int(r.max_retry_after_s)
    if r.last_detail:
        d["last_detail"] = r.last_detail
        d["last_at"] = r.last_at.isoformat() if r.last_at else None
    return d


def stream_deltas(
    before: dict[str, int] | None, counters: dict[str, Any] | None
) -> tuple[dict[str, int], dict[str, int]]:
    """``(deltas, new_baseline)`` for the stream's counters since the last tick.

    A counter that went DOWN (a rebuilt runner restarts them at zero) is read as a restart: the
    new value is the delta, never a negative one.
    """
    new: dict[str, int] = {}
    deltas: dict[str, int] = {}
    if not counters:
        return deltas, dict(before or {})
    for key in STREAM_DELTA_KEYS:
        value = counters.get(key)
        if not isinstance(value, int):
            continue
        new[key] = value
        prev = (before or {}).get(key, 0)
        diff = value - prev if value >= prev else value
        if diff:
            deltas[key] = diff
    return deltas, new


def per_edition_deltas(
    before: dict[str, int] | None, per_edition: dict[str, Any] | None
) -> tuple[dict[str, int], dict[str, int]]:
    """Like :func:`stream_deltas`, for the stream's per-edition kept counts."""
    new: dict[str, int] = {}
    deltas: dict[str, int] = {}
    for edition, value in (per_edition or {}).items():
        if not isinstance(value, int):
            continue
        new[edition] = value
        prev = (before or {}).get(edition, 0)
        diff = value - prev if value >= prev else value
        if diff:
            deltas[edition] = diff
    return deltas, new


def percentile(values: Iterable[float], q: float) -> float | None:
    """The ``q`` quantile (0 to 1) of ``values`` by nearest rank; ``None`` for no values."""
    data = sorted(values)
    if not data:
        return None
    rank = max(1, min(len(data), math.ceil(q * len(data))))
    return data[rank - 1]
