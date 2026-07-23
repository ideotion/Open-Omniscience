"""Hourly Library-counter snapshots (2026-07-23 field-feedback S2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The Library tab showed a handful of counters (sources, keywords, Wikipedia
pages/revisions tracked, law documents/revisions tracked) as bare LIVE numbers
with no history. The maintainer asked for small evolution graphs instead
(2026-07-23 field feedback, item 3/5) with INFINITE retention ("I would prefer
infinite retention"). Most of these counters have no history anywhere else in
the store — unlike ``Article.created_at``, which already lets an articles/hour
graph be derived retroactively for free (see :func:`hourly_article_counts`
below) — so this module RECORDS one, honestly, starting from the moment
recording begins. Nothing here ever fabricates a value earlier than the first
real snapshot; the serving side must say "recording began at X" for any window
that predates it.

Each tracked metric is a cheap ``COUNT(*)`` over a small/indexed table — never
the SQLCipher codec column-order perf trap (a join dragging whole content rows
through the codec for one small field). ``StatSnapshot`` is append-only and its
own (metric, hour) unique constraint is the freshness gate — no separate marker
file, unlike the JSON-marker convention the heavier keyword-cleanup / incremental-
vacuum maintenance steps use (this is orders of magnitude cheaper per hour, so
the table itself is the driftproof source of truth for "already snapped this
hour").
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.database.models import StatSnapshot as StatSnapshotRow
from src.database.session import engine

_LOG = logging.getLogger("database.snapshots")

# Table name -> metric name. Each is a real COUNT(*) over a small/indexed table
# (never a full-content decrypt scan). Kept intentionally small: these are the
# Library-tab "Downloaded"/"Database" counters that had no history anywhere.
_SNAPSHOT_TABLES: dict[str, str] = {
    "articles": "articles",
    "sources": "sources",
    "keywords": "keywords",
    "wiki_pages": "wiki_pages",
    "wiki_revisions": "wiki_revisions",
    "law_documents": "law_documents",
    "law_revisions": "law_revisions",
}

ALL_METRICS = tuple(_SNAPSHOT_TABLES) + ("articles_per_hour",)


def _hour_bucket(now: datetime) -> datetime:
    """Truncate to the top of the hour, naive UTC (matches how other DateTime
    columns in this schema are stored — see ``Article.created_at`` etc.)."""
    if now.tzinfo is not None:
        now = now.astimezone(UTC).replace(tzinfo=None)
    return now.replace(minute=0, second=0, microsecond=0)


def _count(session: Session, table_name: str) -> int:
    from sqlalchemy import table as sa_table

    return int(session.execute(select(func.count()).select_from(sa_table(table_name))).scalar() or 0)


def maybe_snapshot_library_stats(session: Session, *, now: datetime | None = None) -> dict:
    """Record one hourly snapshot of the tracked counters, if this hour has none yet.

    Freshness gate: the (metric, hour) unique constraint IS the marker — if a row
    for ``metric="articles"`` (an always-present table) already exists for this
    hour bucket, the snapshot is skipped as fresh. Only tables PRESENT in this
    build are counted (a core-only install with no law/wiki tables gets an
    honestly smaller set, never a crash). Never raises: a write failure rolls
    back and is reported, it must not break the caller's other maintenance steps.
    """
    now = now or datetime.now(UTC)
    bucket = _hour_bucket(now)
    present = set(inspect(engine).get_table_names())
    # Pick the first tracked metric whose backing table actually exists in this
    # build (never just the first dict key regardless of presence — a stripped
    # build without, say, "articles" must still gate correctly on whatever it does have).
    anchor = next((m for m, tbl in _SNAPSHOT_TABLES.items() if tbl in present), None)
    if anchor is None:
        return {"skipped": "no-tables"}
    already = (
        session.query(StatSnapshotRow)
        .filter(StatSnapshotRow.metric == anchor, StatSnapshotRow.taken_at == bucket)
        .first()
    )
    if already is not None:
        return {"skipped": "fresh", "hour": bucket.isoformat()}

    recorded: dict[str, int] = {}
    for metric, table_name in _SNAPSHOT_TABLES.items():
        if table_name not in present:
            continue
        try:
            value = _count(session, table_name)
        except Exception:  # noqa: BLE001 - one bad count must not lose the rest
            _LOG.warning("snapshot count failed for %s", metric, exc_info=True)
            continue
        try:
            # A SAVEPOINT (not the whole transaction) around each insert: a
            # rollback on IntegrityError must discard only THIS row, never the
            # metrics already flushed earlier in this same loop (the project's
            # own documented lesson about a bare ``session.rollback()`` mid-batch
            # silently discarding every prior uncommitted insert).
            with session.begin_nested():
                session.add(StatSnapshotRow(metric=metric, taken_at=bucket, value=value))
        except IntegrityError:
            # A concurrent writer beat us to this (metric, hour) — fine, it is
            # recorded either way; never a duplicate, never a crash.
            continue
        recorded[metric] = value
    if not recorded:
        return {"skipped": "no-metrics"}
    return {"hour": bucket.isoformat(), "recorded": recorded}


def hourly_article_counts(session: Session, *, days: int, now: datetime | None = None) -> list[dict]:
    """The articles/hour series over the past ``days`` — DERIVED live from
    ``Article.created_at`` (real history that already exists since the article was
    first stored; no snapshot table needed, and no gap before "recording began").
    Bounded to ``days`` (validated by the caller); returns ``[{"t": iso, "n": int}]``
    for every hour that has at least one article, oldest first."""
    from src.database.models import Article

    now = now or datetime.now(UTC)
    since = _hour_bucket(now) - timedelta(days=days)
    if engine.url.get_backend_name() == "sqlite":
        bucket_expr = func.strftime("%Y-%m-%dT%H:00:00", Article.created_at)
    else:
        bucket_expr = func.date_trunc("hour", Article.created_at)
    rows = (
        session.query(bucket_expr.label("bucket"), func.count().label("n"))
        .filter(Article.created_at >= since)
        .group_by("bucket")
        .order_by("bucket")
        .all()
    )
    out = []
    for bucket, n in rows:
        iso = bucket if isinstance(bucket, str) else (bucket.isoformat() if bucket else None)
        out.append({"t": iso, "n": int(n or 0)})
    return out


def metric_history(session: Session, *, metric: str, days: int) -> dict:
    """Bounded read of one recorded metric's snapshot series.

    Storage retention is infinite; the RESPONSE is bounded to ``days`` (the
    caller validates the range). Returns the series plus ``recording_began_at``
    (the timestamp of the metric's very first snapshot ever, regardless of the
    window) so the UI can state honestly "recording began at X" instead of
    implying a gap is a real absence of activity."""
    if metric not in _SNAPSHOT_TABLES:
        return {"metric": metric, "series": [], "recording_began_at": None, "error": "unknown metric"}
    now = datetime.now(UTC)
    since = _hour_bucket(now) - timedelta(days=days)
    first = (
        session.query(func.min(StatSnapshotRow.taken_at))
        .filter(StatSnapshotRow.metric == metric)
        .scalar()
    )
    rows = (
        session.query(StatSnapshotRow.taken_at, StatSnapshotRow.value)
        .filter(StatSnapshotRow.metric == metric, StatSnapshotRow.taken_at >= since)
        .order_by(StatSnapshotRow.taken_at)
        .all()
    )
    series = [{"t": t.isoformat(), "n": int(v)} for t, v in rows]
    return {
        "metric": metric,
        "series": series,
        "recording_began_at": first.isoformat() if first else None,
    }

