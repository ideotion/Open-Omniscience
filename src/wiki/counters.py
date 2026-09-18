"""The lane's OWN counters, for the operator's ≥ 72 h run — read, never accumulated.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

S04-09's operator step 1: "Run the lane ≥ 72 h on the reference VM inside its budget
with all twelve editions; read its OWN counters from ONE artifact (rows / day, bytes /
day, gap history), written where the soak bundle reads."

THERE IS NO COUNTERS FILE, AND THAT IS THE DESIGN. Every figure below is COMPUTED
from rows the lane already wrote: changes per day from ``versioned_changes``, gaps
from ``versioned_gaps``, bytes over time from ``versioned_size_samples``. A separate
counters file would be a second source of truth about the same facts, and the two
would eventually disagree — which is the failure the observatory's own invariant #31
is written against ("a lens, never a second source of truth"). It also means the
counters SURVIVE A RESTART, which a process-cumulative counter cannot, and a 72-hour
run that the app was restarted during is exactly the run this exists to read.

THE TWO BYTE FIGURES STAY APART, HERE AS EVERYWHERE. ``text_bytes`` is the
UNCOMPRESSED length of the text this lane stored, summed from the rows. ``file_bytes``
is the lane FILE on disk, sidecars included, sampled. On a compressed lane the first
is a multiple of the second, and presenting either as the other would misstate the
operator's remaining room. Both are labelled with their method; neither is derived
from the other.

WHAT AN ABSENCE MEANS. A block with no reading says ``measured: false`` and WHY. A
lane that has never run reports absent, not zero; a window with no growth samples
reports absent, not "0 bytes/day". The distinction is the whole reason this is worth
writing rather than summing.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

_LOG = logging.getLogger("wiki.counters")

#: The window the operator's run is read over. 7 days, so a ≥ 72 h run fits inside
#: it with room for the day boundaries at each end rather than being clipped by them.
DEFAULT_WINDOW_DAYS: int = 7

#: How often the runner records the lane file's size. Matches the app's existing
#: at-most-hourly ``wal_bytes`` snapshot cadence, so the growth series has the same
#: resolution as the one the soak window already reads beside it.
SAMPLE_INTERVAL_S: float = 3600.0


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _iso(value: Any) -> str | None:
    """``_aware`` then ISO, in ONE call. Written because the inline form called
    ``_aware`` twice -- once to test and once to format -- which is both a second
    decision on the same value and something no reader can see is equivalent."""
    aware = _aware(value)
    return aware.isoformat() if aware is not None else None


def record_size_sample(lane: Any, file_bytes: int | None, *, now: datetime | None = None) -> bool:
    """Record one lane-file size reading, at most once per :data:`SAMPLE_INTERVAL_S`.

    ``False`` when nothing was recorded — because the file could not be measured
    (``None``) or because the newest sample is still fresh. Returning the fact rather
    than logging it lets the caller's own report say how many it took.

    ``None`` is NOT stored as ``0``. A lane whose file cannot be stat'ed has no
    reading, and a zero in the series would show up later as a lane that shrank to
    nothing and grew back.
    """
    if file_bytes is None:
        return False
    from src.versioned.models import VersionedSizeSample

    at = now or _utcnow()
    newest = lane.execute(
        select(func.max(VersionedSizeSample.measured_at))
    ).scalar_one_or_none()
    newest_aware = _aware(newest)
    if newest_aware is not None and (at - newest_aware).total_seconds() < SAMPLE_INTERVAL_S:
        return False
    lane.add(VersionedSizeSample(measured_at=at, file_bytes=file_bytes, method="stat+wal"))
    lane.flush()
    return True


def _days(window_days: int, now: datetime) -> tuple[datetime, list[str]]:
    start = (now - timedelta(days=window_days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    labels = [
        (start + timedelta(days=i)).date().isoformat() for i in range((now.date() - start.date()).days + 1)
    ]
    return start, labels


def changes_per_day(lane: Any, *, window_days: int, now: datetime) -> dict[str, Any]:
    """Rows per day, counted by when THIS APP recorded them.

    ``recorded_at``, not the source's ``occurred_at``, and the difference matters for
    exactly the reading this exists for: a resumed stream replays hours of edits whose
    ``occurred_at`` is yesterday, and counting by that would report a quiet day this
    app in fact spent working. The operator is measuring their own machine's
    throughput, so the machine's own clock is the honest axis.
    """
    from src.versioned.models import VersionedChange

    start, labels = _days(window_days, now)
    rows = lane.execute(
        select(
            func.date(VersionedChange.recorded_at),
            func.count(VersionedChange.id),
        )
        .where(VersionedChange.recorded_at >= start)
        .group_by(func.date(VersionedChange.recorded_at))
    ).all()
    by_day = {str(day): int(n) for day, n in rows if day}
    series: list[dict[str, Any]] = [{"day": d, "changes": by_day.get(d, 0)} for d in labels]
    total = sum(int(p["changes"]) for p in series)
    return {
        "measured": bool(by_day),
        "series": series,
        "total": total,
        "n": len(series),
        "method": (
            "versioned_changes rows, grouped by the day THIS APP recorded them "
            "(not the day the edit happened -- a resumed stream replays yesterday)"
        ),
        "caveat": (
            "A day inside the window with no rows is a real zero for that day; the "
            "block reports measured:false only when the whole window is empty."
        ),
    }


def bytes_per_day(lane: Any, *, window_days: int, now: datetime) -> dict[str, Any]:
    """Growth, from the lane file's OWN measured size at two or more times.

    ABSENT WITH A REASON when fewer than two samples fall in the window, because a
    rate needs two readings and one reading is not a small rate — it is no rate. The
    brief's S4 wording for the storage panel is the rule here too.
    """
    from src.versioned.models import VersionedSizeSample

    start, _labels = _days(window_days, now)
    rows = lane.execute(
        select(VersionedSizeSample.measured_at, VersionedSizeSample.file_bytes)
        .where(VersionedSizeSample.measured_at >= start)
        .order_by(VersionedSizeSample.measured_at)
    ).all()
    samples = [(a, int(b)) for a, b in ((_aware(t), v) for t, v in rows) if a is not None]
    out: dict[str, Any] = {
        "samples": len(samples),
        "method": "the lane file on disk (stat + -wal/-shm), sampled at most hourly",
    }
    if len(samples) < 2:
        out["measured"] = False
        out["reason"] = (
            "a growth rate needs two readings of the file's size; this window has "
            f"{len(samples)}. This is not a rate of zero."
        )
        return out
    first_at, first_bytes = samples[0]
    last_at, last_bytes = samples[-1]
    seconds = (last_at - first_at).total_seconds()
    if seconds <= 0:
        out["measured"] = False
        out["reason"] = "the first and last samples share a timestamp; no interval to divide by"
        return out
    out["measured"] = True
    out["first_at"] = first_at.isoformat()
    out["last_at"] = last_at.isoformat()
    out["first_bytes"] = first_bytes
    out["last_bytes"] = last_bytes
    out["span_seconds"] = seconds
    out["bytes_per_day"] = (last_bytes - first_bytes) * 86400.0 / seconds
    out["caveat"] = (
        "Measured between the first and last samples in this window only. A lane "
        "that was stopped for part of it grew for less time than the span suggests, "
        "and this figure does not know that."
    )
    return out


def gap_history(lane: Any, *, window_days: int, now: datetime, limit: int = 50) -> dict[str, Any]:
    """Every gap this lane PUBLISHED in the window, newest first, with its reason.

    Q727's record, read back. Reported as rows and never as a coverage percentage: a
    lane cannot know how much it missed, only that it missed a named stretch.
    """
    from src.versioned.models import VersionedGap

    start, _ = _days(window_days, now)
    rows = lane.execute(
        select(VersionedGap)
        .where(VersionedGap.detected_at >= start)
        .order_by(VersionedGap.detected_at.desc())
        .limit(limit + 1)
    ).scalars().all()
    truncated = len(rows) > limit
    by_reason: dict[str, int] = {}
    entries = []
    for row in rows[:limit]:
        by_reason[row.reason] = by_reason.get(row.reason, 0) + 1
        entries.append(
            {
                "feed": row.feed,
                "reason": row.reason,
                "detected_at": (_aware(row.detected_at) or _utcnow()).isoformat(),
                "from_time": _iso(row.from_time),
                "to_time": _iso(row.to_time),
                "closed": row.closed_at is not None,
            }
        )
    return {
        "measured": True,
        "gaps": entries,
        "by_reason": by_reason,
        "n": len(entries),
        "truncated": truncated,
        "method": "versioned_gaps rows the lane wrote itself, newest first",
        "caveat": (
            "A gap says a stretch of the change log was not handed to this app. It is "
            "never a percentage: a lane cannot know how much it missed, only that it "
            "missed a named stretch."
        ),
    }


def entity_counts(lane: Any) -> dict[str, Any]:
    """How many pages the lane follows, and which rule brought each one in."""
    from src.versioned.models import VersionedEntity

    rows = lane.execute(
        select(VersionedEntity.admitted_reason, func.count(VersionedEntity.id)).group_by(
            VersionedEntity.admitted_reason
        )
    ).all()
    by_reason = {(r or "unrecorded"): int(n) for r, n in rows}
    deleted = lane.execute(
        select(func.count(VersionedEntity.id)).where(VersionedEntity.deleted_at.is_not(None))
    ).scalar_one()
    return {
        "measured": True,
        "followed": sum(by_reason.values()),
        "by_admitted_reason": by_reason,
        "marked_deleted_upstream": int(deleted),
        "method": "versioned_entities rows, grouped by the reason each was admitted",
        "caveat": (
            "'unrecorded' means the row predates the column, not that no rule applied."
        ),
    }


def lane_counters(
    lane: Any,
    *,
    kind: str = "wiki",
    window_days: int = DEFAULT_WINDOW_DAYS,
    now: datetime | None = None,
    file_bytes: int | None = None,
) -> dict[str, Any]:
    """The whole reading: rows/day, bytes/day, gap history, entity counts.

    Each block carries its own ``measured`` and its own method, exactly as the soak
    window's blocks do, and this function composes them without a verdict. What the
    numbers MEAN is the maintainer's call; a composite would be a score.
    """
    at = now or _utcnow()
    blocks = {
        "rows_per_day": changes_per_day(lane, window_days=window_days, now=at),
        "bytes_per_day": bytes_per_day(lane, window_days=window_days, now=at),
        "gaps": gap_history(lane, window_days=window_days, now=at),
        "entities": entity_counts(lane),
    }
    unmeasured = sorted(k for k, v in blocks.items() if not v.get("measured"))
    return {
        "kind": kind,
        "window_days": window_days,
        "read_at": at.isoformat(),
        "file_bytes": file_bytes,
        **blocks,
        "unmeasured": unmeasured,
        "method": (
            "Composed from rows the lane already wrote -- there is no counters file. "
            "Every block survives a restart, because nothing here is a "
            "process-cumulative counter."
        ),
    }
