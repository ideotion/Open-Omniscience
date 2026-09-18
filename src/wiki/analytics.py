"""Q712's analytics 1-3, as COUNTS over the lane's own rows. No verdicts, no blends.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q712 = a confirms five analytics and their order: edit velocity · contested pages ·
newly created pages · divergence · attention. The first three are 0.4's; the last two
are 0.5's (S05-06) and are not here, not stubbed, and not named as "coming soon" on
any surface.

EVERY NUMBER IS A COUNT THIS MODULE MADE ITSELF, and every block carries its method,
its caveat and its ``n``. Nothing is normalised, weighted, ranked against a baseline or
folded with anything else — the non-negotiable against composite scores applies to
other people's edits at least as strongly as to our own sources.

THE HONEST NAME FOR ANALYTIC 2, WHICH IS NOT THE RULING'S NAME. Q712 calls it
"contested pages". What this lane STORES is every change's byte delta, its kind and
when it arrived — and NOT who made it: ``FeedChange`` carries no editor, by design,
since the stream's author field is a person's name or IP and keeping one per edit for
twelve editions is a surveillance database this project will not build. So a page
cannot be shown here to be CONTESTED — one person editing a page ten times and ten
people disagreeing are the same rows. What IS measurable is edit CONCENTRATION and
back-and-forth SIZE REVERSALS, and those are what the block reports and what it is
named for. The gap between the ruling's word and the measurement is stated on the
block itself, where the operator reads it, not only here.

READS THE LANE, TOUCHES NO NETWORK, AND SURVIVES A RESTART because it computes from
stored rows rather than from a process counter.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

#: Invariant #16's app-wide sparse rule, mirrored so a caller can label a series
#: without importing the chart toolkit: fewer than this many points renders as BARS,
#: not as a line interpolated through them.
SPARSE_BAR_MAX: int = 10

#: How many pages one leaderboard names. A bound, not a ranking depth: past this the
#: list stops being readable and the count is what carries the information.
TOP_N: int = 20

#: The default window. Seven days, so a ≥ 72 h operator run sits inside it.
DEFAULT_WINDOW_DAYS: int = 7


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _window(window_days: int, now: datetime) -> tuple[datetime, list[str]]:
    start = (now - timedelta(days=window_days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    labels = [
        (start + timedelta(days=i)).date().isoformat()
        for i in range((now.date() - start.date()).days + 1)
    ]
    return start, labels


def _edition_of(feed: str) -> str:
    """``stream:en`` -> ``en``. The feed name is the lane's, not the source's."""
    return feed.split(":", 1)[1] if ":" in feed else feed


def edit_velocity(
    lane: Any, *, window_days: int = DEFAULT_WINDOW_DAYS, now: datetime | None = None
) -> dict[str, Any]:
    """Analytic 1: changes per day, overall and per edition.

    Counted by when THIS APP recorded them, for the reason ``counters.py`` gives: a
    resumed stream replays yesterday's edits, and counting by the edit's own timestamp
    would report a quiet day this app in fact spent working.
    """
    from src.versioned.models import VersionedChange

    at = now or _utcnow()
    start, labels = _window(window_days, at)
    rows = lane.execute(
        select(
            func.date(VersionedChange.recorded_at),
            VersionedChange.feed,
            func.count(VersionedChange.id),
        )
        .where(VersionedChange.recorded_at >= start)
        .group_by(func.date(VersionedChange.recorded_at), VersionedChange.feed)
    ).all()

    overall: dict[str, int] = dict.fromkeys(labels, 0)
    per_edition: dict[str, dict[str, int]] = {}
    for day, feed, n in rows:
        if not day:
            continue
        key = str(day)
        overall[key] = overall.get(key, 0) + int(n)
        edition = _edition_of(feed or "")
        per_edition.setdefault(edition, dict.fromkeys(labels, 0))[key] = int(n)

    series: list[dict[str, Any]] = [{"day": d, "changes": overall.get(d, 0)} for d in labels]
    total = sum(int(p["changes"]) for p in series)
    return {
        "measured": total > 0,
        "series": series,
        "per_edition": {
            edition: [{"day": d, "changes": days.get(d, 0)} for d in labels]
            for edition, days in sorted(per_edition.items())
        },
        "total": total,
        "n": len(series),
        "sparse": len(series) < SPARSE_BAR_MAX,
        "method": (
            "versioned_changes rows per day, counted by the day this app RECORDED them "
            "(a resumed stream replays yesterday's edits)"
        ),
        "caveat": (
            "The count is of changes this app was handed. A stretch it was not handed "
            "is a published gap, not a quiet day -- read the gaps beside this."
        ),
    }


def edit_concentration(
    lane: Any,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    now: datetime | None = None,
    top_n: int = TOP_N,
) -> dict[str, Any]:
    """Analytic 2, named for what it measures rather than for what it suggests.

    Q712 calls this "contested pages". This lane stores no editor, so one person
    editing ten times and ten people disagreeing produce identical rows — the word
    "contested" would be a claim about people from data about bytes. What is measured:
    how many changes each page got, over how many distinct days, and how many times its
    SIZE reversed direction. A reversal is the shape an undo leaves; it is evidence,
    not proof, and the block says so.
    """
    from src.versioned.models import VersionedChange

    at = now or _utcnow()
    start, _ = _window(window_days, at)
    rows = lane.execute(
        select(
            VersionedChange.external_id,
            VersionedChange.feed,
            VersionedChange.recorded_at,
            VersionedChange.byte_delta,
        )
        .where(VersionedChange.recorded_at >= start)
        .where(VersionedChange.external_id.is_not(None))
        .order_by(VersionedChange.external_id, VersionedChange.recorded_at)
    ).all()

    by_page: dict[str, dict[str, Any]] = {}
    for external_id, feed, recorded_at, delta in rows:
        page = by_page.setdefault(
            str(external_id),
            {
                "external_id": str(external_id),
                "edition": _edition_of(feed or ""),
                "changes": 0,
                "days": set(),
                "reversals": 0,
                "_last_sign": 0,
                "bytes_added": 0,
                "bytes_removed": 0,
            },
        )
        page["changes"] += 1
        if isinstance(recorded_at, datetime):
            page["days"].add(recorded_at.date().isoformat())
        if delta:
            sign = 1 if delta > 0 else -1
            # A REVERSAL is a sign flip between consecutive changes. The first change
            # cannot be one -- there is nothing before it to reverse -- and a delta of
            # zero is not a direction, so it neither counts nor resets.
            if page["_last_sign"] and sign != page["_last_sign"]:
                page["reversals"] += 1
            page["_last_sign"] = sign
            if delta > 0:
                page["bytes_added"] += int(delta)
            else:
                page["bytes_removed"] += int(-delta)

    ranked = sorted(
        by_page.values(), key=lambda p: (-p["changes"], -p["reversals"], p["external_id"])
    )
    pages = [
        {
            "external_id": p["external_id"],
            "edition": p["edition"],
            "changes": p["changes"],
            "distinct_days": len(p["days"]),
            "reversals": p["reversals"],
            "bytes_added": p["bytes_added"],
            "bytes_removed": p["bytes_removed"],
        }
        for p in ranked[:top_n]
    ]
    return {
        "measured": bool(by_page),
        "pages": pages,
        "n": len(by_page),
        "truncated": len(by_page) > top_n,
        "window_days": window_days,
        "method": (
            "changes per page in the window, the distinct days they fell on, and the "
            "number of times the page's SIZE reversed direction between consecutive "
            "changes. Ordered by change count; no value is normalised or combined."
        ),
        "caveat": (
            "This lane does not store who made an edit, so it cannot show that a page "
            "is contested: one person editing ten times and ten people disagreeing "
            "look the same here. A size reversal is the shape an undo leaves -- "
            "evidence, not proof."
        ),
    }


def newly_created(
    lane: Any,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    now: datetime | None = None,
    top_n: int = TOP_N,
) -> dict[str, Any]:
    """Analytic 3: pages the stream reported as CREATED in the window.

    Reads the change KIND the adapter recorded, which comes from the source's own
    event. A page created before this lane started following its edition is not here
    and must not be: the lane knows only what it was told.
    """
    from src.versioned.models import VersionedChange

    at = now or _utcnow()
    start, labels = _window(window_days, at)
    rows = lane.execute(
        select(
            func.date(VersionedChange.recorded_at),
            VersionedChange.feed,
            VersionedChange.external_id,
        )
        .where(VersionedChange.recorded_at >= start)
        .where(VersionedChange.change_kind == "create")
        .order_by(VersionedChange.recorded_at.desc())
    ).all()

    per_day: dict[str, int] = dict.fromkeys(labels, 0)
    per_edition: dict[str, int] = {}
    recent: list[dict[str, Any]] = []
    for day, feed, external_id in rows:
        if day:
            per_day[str(day)] = per_day.get(str(day), 0) + 1
        edition = _edition_of(feed or "")
        per_edition[edition] = per_edition.get(edition, 0) + 1
        if len(recent) < top_n and external_id:
            recent.append({"external_id": str(external_id), "edition": edition, "day": str(day)})

    series: list[dict[str, Any]] = [{"day": d, "created": per_day.get(d, 0)} for d in labels]
    total = sum(int(p["created"]) for p in series)
    return {
        "measured": total > 0,
        "series": series,
        "per_edition": dict(sorted(per_edition.items())),
        "recent": recent,
        "total": total,
        "n": len(series),
        "sparse": len(series) < SPARSE_BAR_MAX,
        "method": "versioned_changes rows whose kind the source reported as 'create'",
        "caveat": (
            "Only creations this lane was told about. A page created before you "
            "started following its edition is not here, and a creation that arrived "
            "during a published gap is not here either."
        ),
    }


def analytics(
    lane: Any, *, window_days: int = DEFAULT_WINDOW_DAYS, now: datetime | None = None
) -> dict[str, Any]:
    """Q712's first three, composed without a verdict.

    The two 0.5 analytics (divergence, attention) are ABSENT — not stubbed, not listed
    as pending. A surface that named them would be advertising a feature; a session
    that stubbed them would be building one in 0.4 that the ruling puts in 0.5.
    """
    at = now or _utcnow()
    blocks = {
        "edit_velocity": edit_velocity(lane, window_days=window_days, now=at),
        "edit_concentration": edit_concentration(lane, window_days=window_days, now=at),
        "newly_created": newly_created(lane, window_days=window_days, now=at),
    }
    return {
        "window_days": window_days,
        "read_at": at.isoformat(),
        **blocks,
        "unmeasured": sorted(k for k, v in blocks.items() if not v.get("measured")),
        "method": (
            "Counts over the lane's own change rows. Nothing is normalised, weighted "
            "or combined, and no block is a verdict about a page or an editor."
        ),
    }
