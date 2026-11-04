"""The per-edition coverage report (v0.6 row D, S06-03 S1 + S3; Q723, Q108): what the lane holds of each edition, and since when.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q723 = a asks, per edition: pages seen over the edition's total (its own ``siteinfo`` statistics), the full-text share, the time of the
last event and the gap history. Every figure is READ from rows the lane already wrote, through the readers the counters artifact and
Living sources already share (``walk_coverage``, ``warm_coverage``), so the Living sources view, the soak bundle and the release run cannot
disagree about a number. There is no second counter, and nothing here is accumulated: the report survives a restart.

WHAT IT REFUSES TO DO.
* A share is a ratio of two counts, shown with both counts. It is never a verdict or a bar (V1-6 / Q1017: measured first). It can pass 100%,
  because the edition counts its articles its own way (``WikiWalkCursor``'s caveat).
* A lane that has never run reports ``measured: false`` and why, and a number it does not have is ``None`` with a reason beside it, never 0.
* The denominator of an edition whose ``siteinfo`` read failed is the LAST stored total with its date, and the failure is named.
* The full-text share carries two bounds, because a page WARM promoted to HOT keeps its WARM row and may be counted by both tiers: the
  lower bound is the larger tier alone, the upper bound the two tiers summed. Neither is "the" share.
* A gap is a named stretch the lane did not see (Q727). The report lists the newest ones per edition with the reason, and the count per
  reason; it never turns them into a percentage, because a lane cannot know how much it missed.

S3, THE LOCATED-SHARE COUNTERS. "Addresses found / located / outside your OSM countries" per edition and per press lane need the address
extractor (S2) and the local OSM address index (S05-04), neither of which is in this build. The block says so in a ``reason``; it carries
no number, because a zero would read as "none were found" where the truth is "nothing looked". It exists so the bundle member has the
place K8's located share will fill, and so a reader is told why it is empty.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import exists, func, select

from src.monitoring.secret_scrub import log_failure
from src.wiki.languages import UI_LOCALE_CODES

_LOG = logging.getLogger("wiki.coverage")

#: The twelve editions, in a fixed order (alphabetical by code, so the report does not reorder as the counts move). Any other edition the
#: lane holds rows for follows them, so a thirteenth edition is shown rather than left out.
TWELVE: tuple[str, ...] = tuple(sorted(UI_LOCALE_CODES))

#: How many of an edition's newest gaps the report lists. The count per reason is over ALL of its gaps; the list is the newest few, so the
#: member's size is bounded by editions and not by how long the lane has run.
GAPS_LISTED_PER_EDITION: int = 5

#: The two feed names an edition's changes and gaps carry (``src.wiki.lane.feed_name`` and the adapter's fallback).
_FEED_PREFIXES: tuple[str, ...] = ("stream:", "recentchanges:")

_LOCATED_REASON = "address-extractor-not-built"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _iso(value: Any) -> str | None:
    at = _aware(value)
    return at.isoformat() if at is not None else None


def _edition_of_feed(feed: str) -> str:
    for prefix in _FEED_PREFIXES:
        if feed.startswith(prefix):
            return feed[len(prefix) :]
    return feed


def _ratio(numerator: int | None, denominator: int | None) -> float | None:
    if numerator is None or not denominator:
        return None
    return round(numerator / denominator, 4)


def _hot_pages_with_text(lane: Any) -> dict[str, int]:
    """HOT's pages that hold a text, per edition: entities with at least one revision whose content was stored.

    ``language`` is the edition code the lane wrote at birth (``src.wiki.lane``). The EXISTS probes the revision index by entity, so the
    cost follows the number of followed pages, which the HOT budget bounds, and not the number of revisions.
    """
    from src.versioned.models import VersionedEntity, VersionedRevision

    holds_text = exists().where(
        VersionedRevision.entity_id == VersionedEntity.id, VersionedRevision.content.is_not(None)
    )
    rows = lane.execute(
        select(VersionedEntity.language, func.count(VersionedEntity.id))
        .where(VersionedEntity.language.is_not(None), holds_text)
        .group_by(VersionedEntity.language)
    ).all()
    return {str(language): int(n) for language, n in rows}


def _last_events(lane: Any, editions: list[str]) -> dict[str, dict[str, Any]]:
    """The newest change this app recorded per edition, and where each feed's cursor stands.

    One indexed read per feed (``ix_versioned_change_feed_time``): the newest ``recorded_at`` first. ``recorded_at`` is when THIS app
    stored the change and ``occurred_at`` when the source says it happened; both are given, apart, because a resumed stream replays
    yesterday's edits and the two differ by exactly that.
    """
    from src.versioned.models import VersionedChange, VersionedCursor

    out: dict[str, dict[str, Any]] = {}
    for edition in editions:
        best: dict[str, Any] | None = None
        for prefix in _FEED_PREFIXES:
            feed = f"{prefix}{edition}"
            row = lane.execute(
                select(
                    VersionedChange.recorded_at, VersionedChange.occurred_at, VersionedChange.feed
                )
                .where(VersionedChange.feed == feed)
                .order_by(VersionedChange.recorded_at.desc())
                .limit(1)
            ).first()
            if row is None:
                continue
            recorded = _aware(row[0])
            prior = _aware(best["recorded_at"]) if best else None
            if best is None or (recorded is not None and (prior is None or recorded > prior)):
                best = {"recorded_at": recorded, "occurred_at": _aware(row[1]), "feed": feed}
        cursor = None
        for prefix in _FEED_PREFIXES:
            cursor = lane.execute(
                select(VersionedCursor.updated_at, VersionedCursor.contiguous_through).where(
                    VersionedCursor.feed == f"{prefix}{edition}"
                )
            ).first()
            if cursor is not None:
                break
        out[edition] = {
            "last_event_recorded_at": _iso(best["recorded_at"]) if best else None,
            "last_event_occurred_at": _iso(best["occurred_at"]) if best else None,
            "last_event_feed": best["feed"] if best else None,
            "cursor_updated_at": _iso(cursor[0]) if cursor else None,
            "contiguous_through": _iso(cursor[1]) if cursor else None,
        }
    return out


def _gaps(lane: Any, *, newest: bool = True) -> dict[str, dict[str, Any]]:
    """Every published gap, per edition: the count by reason (all of them) and the newest few, with their reason and bounds."""
    from src.versioned.models import VersionedGap

    by_edition: dict[str, dict[str, Any]] = {}
    counts = lane.execute(
        select(VersionedGap.feed, VersionedGap.reason, func.count(VersionedGap.id)).group_by(
            VersionedGap.feed, VersionedGap.reason
        )
    ).all()
    for feed, reason, n in counts:
        block = by_edition.setdefault(
            _edition_of_feed(str(feed)), {"total": 0, "by_reason": {}, "newest": []}
        )
        block["total"] += int(n)
        block["by_reason"][str(reason)] = block["by_reason"].get(str(reason), 0) + int(n)
    for edition, block in by_edition.items():
        if not newest:
            del block["newest"]  # R413: the bundle member carries counts by reason only
            continue
        feeds = [f"{prefix}{edition}" for prefix in _FEED_PREFIXES]
        rows = (
            lane.execute(
                select(VersionedGap)
                .where(VersionedGap.feed.in_(feeds))
                .order_by(VersionedGap.detected_at.desc())
                .limit(GAPS_LISTED_PER_EDITION)
            )
            .scalars()
            .all()
        )
        block["newest"] = [
            {
                "reason": row.reason,
                "detected_at": _iso(row.detected_at),
                "from_time": _iso(row.from_time),
                "to_time": _iso(row.to_time),
                "closed": row.closed_at is not None,
            }
            for row in rows
        ]
    return by_edition


def _located_block() -> dict[str, Any]:
    """S3's counters, absent with the reason: no extractor and no address index exist in this build, so there is nothing to count."""
    return {
        "measured": False,
        "reason": _LOCATED_REASON,
        "fields": ["addresses_found", "addresses_located", "addresses_outside_your_osm_countries"],
        "per_edition": None,
        "per_press_lane": None,
        "method": (
            "Not measured. Counting addresses found, located and outside the user's OSM countries needs the address extractor (S06-03 S2) and the "
            "local OSM address index (S05-04); until both exist the report has no number to give, and a zero would read as 'none found'."
        ),
        "caveat": (
            "No bar is set and none is implied (K8's located share is pending ruling V1-6): a resolver ships before any bar (Q1017). "
            "Addresses outside your OSM countries are not located, and never sent to an external geocoder (Q820)."
        ),
    }


def edition_coverage(
    lane: Any, *, now: datetime | None = None, newest_gaps: bool = True
) -> dict[str, Any]:
    """The report: one row per edition (the twelve first), a totals row, and the located block. Never raises on a missing table.

    ``measured`` is False, with a ``reason``, for a lane that has never run (the walk, WARM and the stream have written nothing); the twelve
    rows are still listed with their fields ``None`` so a surface can draw twelve honest "no run yet" lines.
    """
    from src.wiki.walk import walk_coverage
    from src.wiki.warm import warm_coverage

    at = now or _utcnow()
    try:
        walk = walk_coverage(lane, now=at)
        warm = warm_coverage(lane)
        hot = _hot_pages_with_text(lane)
        gaps = _gaps(lane, newest=newest_gaps)
    except Exception as exc:  # noqa: BLE001 - a report that cannot read says so; it never blanks the artifact it rides
        log_failure(
            _LOG, "the edition coverage report could not read the lane", exc, level=logging.WARNING
        )
        return {
            "measured": False,
            "reason": "unreadable",
            "editions": [],
            "located": _located_block(),
        }

    walk_by = (
        {row["edition"]: row for row in walk.get("editions", [])} if walk.get("measured") else {}
    )
    warm_by = (
        {row["edition"]: row for row in warm.get("editions", [])} if warm.get("measured") else {}
    )
    names = list(TWELVE) + sorted(
        (set(walk_by) | set(warm_by) | set(hot) | set(gaps)) - set(TWELVE)
    )
    try:
        events = _last_events(lane, names)
    except Exception as exc:  # noqa: BLE001
        log_failure(
            _LOG,
            "the edition coverage report could not read the stream's last events",
            exc,
            level=logging.WARNING,
        )
        events = {
            n: dict.fromkeys(("last_event_recorded_at", "last_event_occurred_at", "last_event_feed", "cursor_updated_at", "contiguous_through"))
            | {"last_event_unreadable": True}
            for n in names
        }

    rows: list[dict[str, Any]] = []
    for name in names:
        w, m = walk_by.get(name), warm_by.get(name)
        pages_seen = int(w["pages_seen"]) if w else None
        total = w.get("edition_articles") if w else None
        hot_n = int(hot.get(name, 0))
        warm_n = int(m["pages_with_text"]) if m else None  # WARM never ran for this edition: unknown, not 0
        gap = gaps.get(name) or (
            {"total": 0, "by_reason": {}, "newest": []}
            if newest_gaps
            else {"total": 0, "by_reason": {}}
        )
        # walk.py stores ONE last_error for every refusal (a batch 503 as much as a siteinfo failure) and clears it
        # never, so it cannot say the TOTAL's read failed. It is given as what it is: the walk's last refusal.
        total_note = {
            "last_refusal": w.get("last_error") if w else None,
            "last_refusal_at": w.get("last_error_at") if w else None,
        }
        ran = bool(
            w
            or m
            or hot_n
            or gap["total"]
            or (name in events and events[name].get("last_event_recorded_at"))
        )
        rows.append(
            {
                "edition": name,
                "has_run": ran,
                "reason": None if ran else "no-run-yet",
                "pages_seen": pages_seen,
                "pass_no": int(w["pass_no"]) if w else None,
                "walk_complete": bool(w and w.get("completed_at")),
                "walk_requests": w.get("requests") if w else None,
                "walk_response_bytes": w.get("response_bytes") if w else None,
                "walk_consecutive_failures": w.get("consecutive_failures") if w else None,
                "walk_updated_at": w.get("updated_at") if w else None,
                "edition_articles": total,
                "edition_articles_read_at": w.get("edition_articles_read_at") if w else None,
                "edition_articles_read": total_note,
                "pages_seen_share": _ratio(pages_seen, total),
                "full_text": {
                    "hot_pages_with_text": hot_n,
                    "warm_pages_with_text": warm_n,
                    "warm_promoted": int(m["promoted"]) if m else None,
                    "share_lower_bound": _ratio(max(hot_n, warm_n or 0), pages_seen),
                    "share_upper_bound": _ratio(hot_n + warm_n, pages_seen) if warm_n is not None else None,
                },
                **events.get(name, {}),
                "gaps": gap,
            }
        )
    totals = {
        "pages_seen": sum(r["pages_seen"] or 0 for r in rows),
        "edition_articles": sum(int(r["edition_articles"] or 0) for r in rows),
        # An edition whose total was never read adds nothing to the sum above; the count says how many.
        "editions_without_total": sum(1 for r in rows if r["edition_articles"] is None),
        "editions_with_a_run": sum(1 for r in rows if r["has_run"]),
        "gaps": sum(r["gaps"]["total"] for r in rows),
    }
    measured = totals["editions_with_a_run"] > 0
    if not newest_gaps:
        # The bundle member (R413, net-zero): an edition that never ran is its name and the reason, not a dozen nulls.
        rows = [r if r["has_run"] else {k: r[k] for k in ("edition", "has_run", "reason")} for r in rows]
    return {
        "measured": measured,
        "reason": None if measured else "lane-never-run",
        "read_at": at.isoformat(),
        "editions": rows,
        "totals": totals,
        "located": (
            {k: v for k, v in _located_block().items() if k in ("measured", "reason", "fields")}
            if not newest_gaps
            else _located_block()
        ),
        "method": (
            "Read, not accumulated, from rows the lane wrote: pages seen and the edition's article count from the walk's bookmark rows (walk_coverage), "
            "pages holding a text from HOT's revisions and WARM's counts, the last event from the newest versioned_changes row of the edition's "
            "feed, and the gaps from versioned_gaps. The same readers as the counters artifact and Living sources."
        ),
        "caveat": (
            "A share is two counts, not a score, and no bar is set. The edition counts its articles its own way, so pages seen can pass 100%. A "
            "page promoted from WARM to HOT may be counted by both tiers, so the full-text share is given as a lower and an upper bound. A gap is "
            "a stretch the lane did not see, listed with its reason; the lane cannot know how much it missed."
        ),
    }
