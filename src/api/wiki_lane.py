"""The Wikipedia lane's read-only surfaces: counts, analytics, and one page's sections.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q714 (separate lane counts everywhere, and the Home strip's own figure), Q712
(analytics 1-3) and Q711 (the section-aware diff) reach the UI through here.

EVERY ROUTE IS A READ AND EVERY ROUTE DEGRADES. A lane that has never run has no file,
and that is the ordinary state of a fresh install — so each route answers with a
NAMED absence rather than a 404 or a row of zeros. "This lane has not run" and "this
lane ran and found nothing" are different facts about an operator's machine and the
difference is the whole reason these counts are worth showing.

NOTHING HERE TOUCHES THE NETWORK. The lane's collecting is the runner's; these routes
read what it stored.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from src.versioned.store import LaneAbsentError, lane_path, lane_session

_LOG = logging.getLogger("api.wiki.lane")

router = APIRouter(prefix="/api/wiki/lane", tags=["wikipedia"])

#: The absence every route returns when there is no lane file. A SHARED shape, so two
#: surfaces cannot come to disagree about what "not run yet" looks like.
_ABSENT = {
    "measured": False,
    # A TOKEN the UI translates, beside the English reason a log or an API client reads.
    "reason": "lane-never-run",
    "detail": "the Wikipedia lane has no database file yet -- it has never run",
}


def _absent() -> dict:
    return dict(_ABSENT)


@router.get("/status")
def lane_status() -> dict:
    """Q714's own figure: pages followed and changes recorded today.

    "Today" is the LOCAL machine's day, not UTC, and that is deliberate for this one
    number: it sits on the Home strip beside other figures the operator reads as
    "today", and a UTC day would make the strip disagree with itself for anyone not on
    UTC. Every other count in this lane is UTC, and each says which it uses.
    """
    from datetime import datetime

    from sqlalchemy import func, select

    from src.versioned.models import VersionedChange, VersionedEntity

    if not lane_path("wiki").is_file():
        return _absent()
    # AWARE, because the lane's own timestamp type refuses a naive one by name — and
    # it is right to: a naive boundary compared against stored UTC would silently
    # shift the count by the operator's offset. ``astimezone()`` attaches the machine's
    # CURRENT offset, so the boundary is local midnight expressed in a form the lane
    # can compare. Across a DST change within the same day the offset that applied at
    # midnight may differ from the one now; the window is then off by the shift, which
    # is an hour twice a year and is named rather than pretended away.
    midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        with lane_session("wiki") as lane:
            pages = lane.execute(select(func.count(VersionedEntity.id))).scalar_one()
            changes_today = lane.execute(
                select(func.count(VersionedChange.id)).where(
                    VersionedChange.recorded_at >= midnight
                )
            ).scalar_one()
            changes_total = lane.execute(select(func.count(VersionedChange.id))).scalar_one()
    except LaneAbsentError:
        return _absent()
    return {
        "measured": True,
        "pages": int(pages),
        "changes_today": int(changes_today),
        "changes_total": int(changes_total),
        # Present so a caller never has to infer it from the two above -- an inferred
        # denominator is the one that goes wrong silently.
        "counted_since": midnight.isoformat(),
        "day": "local",
        "method": (
            "versioned_entities rows for pages; versioned_changes rows recorded since "
            "local midnight for today's changes"
        ),
        "caveat": (
            "These are the lane's OWN counts and they are separate from the corpus's "
            "article count on purpose -- a Wikipedia page followed here is not an "
            "article in your press corpus unless its text was stored. 'Today' runs "
            "from this machine's local midnight; on the two days a year the clocks "
            "change, the window is off by the shift."
        ),
    }


@router.get("/analytics")
def lane_analytics(window_days: int = Query(7, ge=1, le=90)) -> dict:
    """Q712's analytics 1-3. The other two are 0.5's and are not here."""
    from src.wiki.analytics import analytics

    if not lane_path("wiki").is_file():
        return _absent()
    try:
        with lane_session("wiki") as lane:
            return {"measured": True, **analytics(lane, window_days=window_days)}
    except LaneAbsentError:
        return _absent()


@router.get("/counters")
def lane_counters_route(window_days: int = Query(7, ge=1, le=90)) -> dict:
    """The operator's ≥ 72 h run, read from the lane's own rows.

    The SAME figures the soak bundle carries — this route is the one a person opens,
    that one is the one a bundle collects, and both call the same function so they
    cannot drift.
    """
    from src.versioned.store import lane_file_bytes
    from src.wiki.counters import lane_counters

    if not lane_path("wiki").is_file():
        return _absent()
    try:
        with lane_session("wiki") as lane:
            return {
                "measured": True,
                **lane_counters(
                    lane, window_days=window_days, file_bytes=lane_file_bytes("wiki")
                ),
            }
    except LaneAbsentError:
        return _absent()


@router.get("/places")
def lane_places(limit: int = Query(2000, ge=1, le=20000)) -> dict:
    """Q819 STEP 1: the lane's pages that carry coordinates, as points for the map.

    THE COORDINATES ARE THE WIKI'S OWN, from ``prop=coordinates`` (Q705's field), and
    they are stored as a FACT row — so a page the wiki gives no coordinate for has no
    row and appears nowhere here, rather than appearing at ``0, 0``. Null Island is the
    canonical way a map layer lies, and the absence is what prevents it.

    THE QID TRAVELS WITH EACH POINT, which is the whole reason step 1 is worth doing
    before step 2: Q819's step 2 joins OSM objects tagged ``wikidata`` to the SAME
    place in 0.5, and it can only do that if the wiki side already carries the
    identifier. A point with no QID is still drawn — it is a real place with a real
    coordinate — and it is marked as unjoinable rather than dropped.

    NO CLUSTERING, NO BINNING AND NO SAMPLING HERE. The renderer owns how a crowded
    map is drawn; a server that thinned the set would be deciding for it, and the
    detailed-curves rule ("no arbitrary downsampling anywhere") applies to points on a
    map exactly as it does to a series on a chart. What this route DOES do is bound the
    answer and SAY when it did: a truncated set that did not say so would be a silent
    downsample by another name.
    """
    from sqlalchemy import select

    from src.versioned.models import VersionedEntity, VersionedEntityFact
    from src.wiki.identity import parse_external_id
    from src.wiki.pagefacts import decode

    if not lane_path("wiki").is_file():
        return _absent()
    points: list[dict] = []
    total = 0
    try:
        with lane_session("wiki") as lane:
            rows = lane.execute(
                select(VersionedEntityFact, VersionedEntity)
                .join(VersionedEntity, VersionedEntity.id == VersionedEntityFact.entity_id)
                .where(VersionedEntityFact.name == "coordinates")
                .order_by(VersionedEntity.id)
            ).all()
            total = len(rows)
            for fact, entity in rows[:limit]:
                try:
                    value = decode(fact.value_json)
                except Exception:  # noqa: BLE001 - one unreadable row is not a failed map
                    _LOG.debug("unreadable coordinates fact on %s", entity.external_id)
                    continue
                lat, lon = value.get("lat"), value.get("lon")
                if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                    continue
                # OUT-OF-RANGE IS DROPPED, NOT CLAMPED. A clamped coordinate is a point
                # drawn at the edge of the world as though it had been measured there.
                if not (-90.0 <= float(lat) <= 90.0 and -180.0 <= float(lon) <= 180.0):
                    continue
                edition: str | None
                try:
                    edition = parse_external_id(entity.external_id).wiki
                except ValueError:
                    edition = None
                points.append(
                    {
                        "external_id": entity.external_id,
                        "title": entity.title,
                        "edition": edition,
                        "lat": float(lat),
                        "lon": float(lon),
                        "qid": entity.qid,
                        # Named on the point rather than inferred from a null by the
                        # renderer: step 2's join is the reason this field exists.
                        "joinable": entity.qid is not None,
                    }
                )
    except LaneAbsentError:
        return _absent()
    return {
        "measured": True,
        "points": points,
        "n": len(points),
        "total_with_coordinates": total,
        "truncated": total > len(points),
        "with_qid": sum(1 for p in points if p["joinable"]),
        "method": (
            "coordinates the wiki itself reports for a page (prop=coordinates), stored "
            "as a fact row. A page the wiki gives no coordinate for is absent here, "
            "never placed at 0,0."
        ),
        "caveat": (
            "Only pages this lane follows AND whose text has been read. A page whose "
            "changes are recorded but whose text was not stored has no facts yet, so "
            "it has no point -- that is a gap in what has been read, not in the world."
        ),
    }


@router.get("/sections")
def lane_sections(external_id: str = Query(..., min_length=3, max_length=512)) -> dict:
    """Q711: which SECTIONS changed between this page's newest stored version and the
    one before it.

    "The one before it" is the previous INGESTED version, which ``revisions.py``
    already keeps and already warns is not necessarily the version in force — a budget
    may have skipped one. That caveat is carried here rather than restated, so the two
    surfaces cannot come to word it differently.
    """
    from sqlalchemy import select

    from src.versioned.models import VersionedBaseline, VersionedEntity, VersionedRevision
    from src.wiki.sections import section_diff

    if not lane_path("wiki").is_file():
        return _absent()
    try:
        with lane_session("wiki") as lane:
            entity = lane.execute(
                select(VersionedEntity).where(VersionedEntity.external_id == external_id)
            ).scalar_one_or_none()
            if entity is None:
                raise HTTPException(
                    status_code=404, detail=f"this lane does not follow {external_id!r}"
                )
            revisions = lane.execute(
                select(VersionedRevision)
                .where(VersionedRevision.entity_id == entity.id)
                .order_by(VersionedRevision.observed_at.desc())
                .limit(2)
            ).scalars().all()
            if not revisions:
                return {
                    "measured": False,
                    "reason": "no-stored-text",
                    "detail": (
                        "this page's changes are recorded but its text was not stored "
                        "-- it is not in the HOT tier, or the storage budget was spent"
                    ),
                }
            newest = revisions[0]
            # Both are OPTIONAL: a page whose only stored text is its baseline has no
            # previous revision, and one with neither has no previous anything. The
            # annotation says so rather than letting the first branch's non-null type
            # win and the second branch look like a bug.
            previous: str | None
            previous_ref: str | None
            if len(revisions) > 1:
                previous, previous_ref = revisions[1].content, revisions[1].revision_ref
            else:
                baseline = lane.execute(
                    select(VersionedBaseline).where(VersionedBaseline.entity_id == entity.id)
                ).scalar_one_or_none()
                previous = baseline.content if baseline else None
                previous_ref = baseline.revision_ref if baseline else None
            diff = section_diff(previous, newest.content or "")
            return {
                "measured": True,
                "external_id": external_id,
                "title": entity.title,
                "revision_ref": newest.revision_ref,
                "compared_with": previous_ref,
                **diff.as_dict(),
            }
    except HTTPException:
        raise
    except LaneAbsentError:
        return _absent()


#: The most diff text one answer carries. A stored diff is bounded when it is made
#: (``compute_diff`` refuses past 40,000 lines or 4 MiB), which is still more than a
#: panel can draw; the answer says when it was cut and by how much.
_DIFF_TEXT_CAP = 200_000


@router.get("/changes")
def lane_changes(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=1_000_000),
) -> dict:
    """The stream's timeline for the pages the lane follows, newest first (Q1016).

    EVERY change the stream reported for a followed page is a row, stored text or not:
    ``text_stored`` says which, so a change that was only counted reads as counted
    rather than as a change nobody made. The diff counts are the ones stored when the
    revision was ingested; the text itself is one more request away
    (``/revisions/{id}``), because a timeline of fifty diffs would be megabytes.
    """
    from sqlalchemy import func, select
    from sqlalchemy.exc import SQLAlchemyError

    from src.versioned.models import VersionedChange, VersionedEntity, VersionedRevision

    if not lane_path("wiki").is_file():
        return _absent()
    try:
        with lane_session("wiki") as lane:
            total = lane.execute(
                select(func.count(VersionedChange.id)).where(VersionedChange.entity_id.isnot(None))
            ).scalar_one()
            rows = lane.execute(
                select(
                    VersionedChange.id,
                    VersionedChange.change_kind,
                    VersionedChange.occurred_at,
                    VersionedChange.recorded_at,
                    VersionedChange.byte_delta,
                    VersionedEntity.title,
                    VersionedEntity.language,
                    VersionedEntity.external_id,
                    VersionedRevision.id.label("revision_id"),
                    VersionedRevision.diff_method,
                    VersionedRevision.diff_added,
                    VersionedRevision.diff_removed,
                )
                .join(VersionedEntity, VersionedChange.entity_id == VersionedEntity.id)
                .outerjoin(
                    VersionedRevision, VersionedChange.ingested_revision_id == VersionedRevision.id
                )
                .order_by(VersionedChange.recorded_at.desc(), VersionedChange.id.desc())
                .limit(limit)
                .offset(offset)
            ).all()
    except LaneAbsentError:
        return _absent()
    except SQLAlchemyError:
        _LOG.warning("lane changes: the Wikipedia lane could not be read", exc_info=True)
        return {
            "measured": False,
            "reason": "lane-unreadable",
            "detail": "the Wikipedia lane file could not be read; the next drain repairs a file with no tables",
        }
    changes = []
    for r in rows:
        m = r._mapping
        changes.append(
            {
                "id": m["id"],
                # Stored verbatim, including a kind outside edit/create/delete/move: the
                # view shows what the source said rather than the nearest known word.
                "change_kind": m["change_kind"],
                "occurred_at": m["occurred_at"].isoformat() if m["occurred_at"] else None,
                "recorded_at": m["recorded_at"].isoformat() if m["recorded_at"] else None,
                "byte_delta": m["byte_delta"],
                "title": m["title"],
                "language": m["language"],
                "external_id": m["external_id"],
                "text_stored": m["revision_id"] is not None,
                "revision_id": m["revision_id"],
                "diff_method": m["diff_method"],
                "diff_added": m["diff_added"],
                "diff_removed": m["diff_removed"],
            }
        )
    return {
        "measured": True,
        "count": len(changes),
        "total": int(total),
        "offset": offset,
        "changes": changes,
        "method": (
            "versioned_changes rows for the pages this lane follows, newest recorded first, "
            "each joined to the revision it ingested when its text was stored"
        ),
    }


@router.get("/revisions/{revision_id}")
def lane_revision_diff(revision_id: int) -> dict:
    """One ingested revision's stored diff, as it was computed when it arrived.

    Never a live re-diff: the text compared against was the lane's previous stored
    version, which is not necessarily the source's previous revision (a revision the
    stream only counted has no text to compare with). ``diff_from_ref`` names what it
    was compared with, and a revision with no diff says why (``diff_method``).
    """
    from sqlalchemy import select
    from sqlalchemy.exc import SQLAlchemyError

    from src.versioned.models import VersionedEntity, VersionedRevision

    if not lane_path("wiki").is_file():
        return _absent()
    try:
        with lane_session("wiki") as lane:
            row = lane.execute(
                select(VersionedRevision, VersionedEntity.title, VersionedEntity.language)
                .join(VersionedEntity, VersionedRevision.entity_id == VersionedEntity.id)
                .where(VersionedRevision.id == revision_id)
            ).first()
            if row is None:
                raise HTTPException(status_code=404, detail="no such revision in the Wikipedia lane")
            rev, title, language = row
            # Read INSIDE the session: leaving it commits, which expires the row, and a
            # detached row cannot reload what the payload below still needs.
            text = rev.diff_text
            full = len(text) if text is not None else 0
            return {
                "measured": True,
                "id": rev.id,
                "title": title,
                "language": language,
                "revision_ref": rev.revision_ref,
                "diff_from_ref": rev.diff_from_ref,
                "observed_at": rev.observed_at.isoformat() if rev.observed_at else None,
                "revised_at": rev.revised_at.isoformat() if rev.revised_at else None,
                "diff_method": rev.diff_method,
                "diff_added": rev.diff_added,
                "diff_removed": rev.diff_removed,
                "diff_byte_delta": rev.diff_byte_delta,
                "diff_text": text[:_DIFF_TEXT_CAP] if text is not None else None,
                "diff_chars": full,
                "truncated": full > _DIFF_TEXT_CAP,
            }
    except HTTPException:
        raise
    except LaneAbsentError:
        return _absent()
    except SQLAlchemyError:
        _LOG.warning("lane revision: the Wikipedia lane could not be read", exc_info=True)
        return {
            "measured": False,
            "reason": "lane-unreadable",
            "detail": "the Wikipedia lane file could not be read; the next drain repairs a file with no tables",
        }
