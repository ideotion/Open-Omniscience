"""The Living sources view's one overview read: coverage, freshness and storage per source.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q1016 (a), gate row O's S6: one view for Wikipedia, law and maps -- a timeline of changes,
the diff, coverage, freshness and budget. The timelines and diffs are read from the routes
that already hold them (``/api/wiki/lane/changes``, ``/api/wiki/pages/{id}/revisions``,
``/api/law/changes``); this module answers the one question none of them does, the state
of each source at a glance, so the three can be read side by side.

COUNTS AND DATES, NEVER A VERDICT. Freshness is the newest and the oldest check, never a
threshold: "stale" would need a number nobody ruled, and a page checked a week ago is
stale for a breaking story and fresh for a statute. Coverage is what is followed and what
was only counted, side by side -- a lane under a budget ingests a fraction of what it is
told about, and the fraction is the honest figure, not the numerator alone.

EVERY PART DEGRADES ON ITS OWN. A lane that never ran, a main database table that is
empty, a map manager that cannot be read: each becomes a named absence in its own block,
and the other blocks still answer. One source's trouble must not blank the view of the
other two.

NOTHING HERE TOUCHES THE NETWORK, AND NOTHING HERE WRITES. The Wikipedia lane is opened
without ``create``, so a read never makes the file a drain would have made.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.database.session import get_db

_LOG = logging.getLogger("api.living")

router = APIRouter(prefix="/api/living", tags=["living"])

#: The window every "recent" count uses. One number for the whole view, so two figures
#: on the same page cannot silently be counted over different spans.
WINDOW_DAYS = 30


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        # The main database stores naive UTC; say so on the wire rather than let a
        # browser read it as the operator's local time.
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _unreadable(what: str) -> dict[str, Any]:
    return {"measured": False, "reason": "unreadable", "detail": f"{what} could not be read"}


def _wiki_stream(since: datetime) -> dict[str, Any]:
    """The live stream's own lane file: pages followed, changes reported, text stored."""
    from src.versioned.models import (
        VersionedChange,
        VersionedCursor,
        VersionedEntity,
        VersionedGap,
    )
    from src.versioned.store import LaneAbsentError, lane_path, lane_session

    if not lane_path("wiki").is_file():
        return {"measured": False, "reason": "lane-never-run"}
    try:
        with lane_session("wiki") as lane:
            pages = lane.execute(select(func.count(VersionedEntity.id))).scalar_one()
            recent = VersionedChange.recorded_at >= since
            followed = lane.execute(
                select(func.count(VersionedChange.id)).where(
                    recent, VersionedChange.entity_id.isnot(None)
                )
            ).scalar_one()
            with_text = lane.execute(
                select(func.count(VersionedChange.id)).where(
                    recent,
                    VersionedChange.entity_id.isnot(None),
                    VersionedChange.ingested_revision_id.isnot(None),
                )
            ).scalar_one()
            not_followed = lane.execute(
                select(func.count(VersionedChange.id)).where(
                    recent, VersionedChange.entity_id.is_(None)
                )
            ).scalar_one()
            last_change = lane.execute(select(func.max(VersionedChange.recorded_at))).scalar_one()
            cursors = lane.execute(
                select(VersionedCursor.updated_at, VersionedCursor.contiguous_through)
            ).all()
            open_gaps = lane.execute(
                select(func.count(VersionedGap.id)).where(VersionedGap.closed_at.is_(None))
            ).scalar_one()
    except LaneAbsentError:
        return {"measured": False, "reason": "lane-never-run"}
    except SQLAlchemyError:
        # A file with no schema (the S5 walk's empty wiki.db) is repaired by the next
        # drain; until then it is named, never a 500 that blanks the other sources.
        _LOG.warning("living overview: the Wikipedia lane could not be read", exc_info=True)
        return _unreadable("the Wikipedia lane file")
    through = [c.contiguous_through for c in cursors if c.contiguous_through is not None]
    return {
        "measured": True,
        "pages": int(pages),
        "changes": int(followed),
        "changes_with_text": int(with_text),
        "changes_not_followed": int(not_followed),
        "last_change_at": _iso(last_change),
        # The EARLIEST point every feed has been read without a break through: with two
        # feeds, one current and one behind, the honest "complete through" is the one
        # behind. None when no feed has declared one.
        "contiguous_through": _iso(min(through)) if through else None,
        "cursor_read_at": _iso(max((c.updated_at for c in cursors), default=None)),
        "open_gaps": int(open_gaps),
    }


def _wiki_tracked(db: Session, since: datetime) -> dict[str, Any]:
    """The pages the operator follows by hand (Settings -> Wikipedia), in the main database."""
    from src.database.models import WikiPage, WikiRevision

    # Counted by when THIS machine stored the revision, not by the edit's own time: the
    # stream and the law tracker count by when they recorded, and three windows on one
    # page must mean the same thing. A page added today with a year of history is not
    # a year of changes this week.
    try:
        watched = WikiPage.watched.is_(True)
        pages = db.query(func.count(WikiPage.id)).filter(watched).scalar() or 0
        never = (
            db.query(func.count(WikiPage.id))
            .filter(watched, WikiPage.last_checked_at.is_(None))
            .scalar()
            or 0
        )
        newest, oldest = (
            db.query(func.max(WikiPage.last_checked_at), func.min(WikiPage.last_checked_at))
            .filter(watched)
            .one()
        )
        revisions = (
            db.query(func.count(WikiRevision.id)).filter(WikiRevision.created_at >= since).scalar()
            or 0
        )
        flagged = (
            db.query(func.count(WikiRevision.id))
            .filter(WikiRevision.created_at >= since, WikiRevision.flagged.is_(True))
            .scalar()
            or 0
        )
    except SQLAlchemyError:
        _LOG.warning("living overview: tracked Wikipedia pages could not be read", exc_info=True)
        return _unreadable("the tracked Wikipedia pages")
    return {
        "measured": True,
        "pages": int(pages),
        "never_checked": int(never),
        "newest_check_at": _iso(newest),
        "oldest_check_at": _iso(oldest),
        "changes": int(revisions),
        "flagged": int(flagged),
    }


def _law(db: Session, since: datetime) -> dict[str, Any]:
    """The legal documents the law tracker follows, in the main database."""
    from src.database.models import LawDocument, LawRevision

    try:
        documents = db.query(func.count(LawDocument.id)).scalar() or 0
        jurisdictions = db.query(func.count(func.distinct(LawDocument.jurisdiction))).scalar() or 0
        never = (
            db.query(func.count(LawDocument.id))
            .filter(LawDocument.last_checked_at.is_(None))
            .scalar()
            or 0
        )
        newest, oldest = db.query(
            func.max(LawDocument.last_checked_at), func.min(LawDocument.last_checked_at)
        ).one()
        # The same rule /api/law/changes lists by: a revision with no byte change is a
        # re-check, not a change, so the count and the list below it agree.
        real = LawRevision.delta_bytes != 0
        changes = (
            db.query(func.count(LawRevision.id))
            .filter(real, LawRevision.observed_at >= since)
            .scalar()
            or 0
        )
        flagged = (
            db.query(func.count(LawRevision.id))
            .filter(real, LawRevision.observed_at >= since, LawRevision.flagged.is_(True))
            .scalar()
            or 0
        )
    except SQLAlchemyError:
        _LOG.warning("living overview: the law tracker could not be read", exc_info=True)
        return _unreadable("the law tracker")
    return {
        "measured": True,
        "documents": int(documents),
        "jurisdictions": int(jurisdictions),
        "never_checked": int(never),
        "newest_check_at": _iso(newest),
        "oldest_check_at": _iso(oldest),
        "changes": int(changes),
        "flagged": int(flagged),
    }


#: The map manager's own status words (``OsmDownloadEntry.status``), in the order the
#: view lists them. The manager says ``error`` where the task manager says "failed";
#: counting under a word it never writes would read every failure as zero.
_MAP_STATES = ("done", "downloading", "queued", "paused", "error")


def _maps() -> dict[str, Any]:
    """The OpenStreetMap regions the download manager holds, and the bytes on disk."""
    try:
        from src.geo.osm_downloads import get_manager

        entries = get_manager().list()
    except Exception:  # noqa: BLE001 - a named absence, never a 500 over the other sources
        _LOG.warning("living overview: the map downloads could not be read", exc_info=True)
        return _unreadable("the map downloads")
    by_state = dict.fromkeys(_MAP_STATES, 0)
    other = 0
    on_disk = 0
    for e in entries:
        status = e.get("status")
        if status in by_state:
            by_state[status] += 1
        else:
            other += 1
        on_disk += int(e.get("downloaded_bytes") or 0)
    return {
        "measured": True,
        "regions": len(entries),
        "by_state": by_state,
        "other_state": other,
        "bytes_on_disk": on_disk,
        # A downloaded extract carries the date of the data it holds inside its own
        # header, which nothing here reads yet; the file's own time says when THIS
        # machine wrote it, which is not the same fact. So: not recorded, by name.
        "freshness": {"measured": False, "reason": "not-recorded"},
    }


def _storage(db: Session) -> dict[str, Any]:
    """Settings -> Storage's own rows, by kind, so the two surfaces cannot disagree."""
    from src.versioned.budget import storage_report

    try:
        report = storage_report(db)
    except Exception:  # noqa: BLE001 - the counts above still answer without it
        _LOG.warning("living overview: the storage report could not be read", exc_info=True)
        return {}
    return {row["kind"]: row for row in report.get("lanes", [])}


@router.get("/overview")
def living_overview(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Each living source's coverage, freshness, recent changes and storage, measured now."""
    now = datetime.now(UTC)
    since = now - timedelta(days=WINDOW_DAYS)
    storage = _storage(db)
    return {
        "read_at": now.isoformat(),
        "window_days": WINDOW_DAYS,
        "since": since.isoformat(),
        "sources": [
            {
                "kind": "wiki",
                "stream": _wiki_stream(since),
                "tracked": _wiki_tracked(db, since.replace(tzinfo=None)),
                "storage": storage.get("wiki"),
            },
            {
                "kind": "law",
                "tracker": _law(db, since.replace(tzinfo=None)),
                "storage": storage.get("law"),
            },
            {
                "kind": "osm",
                "maps": _maps(),
                "storage": storage.get("osm"),
            },
        ],
        "method": (
            f"Counts of what this machine recorded in the last {WINDOW_DAYS} days, read now. Wikipedia "
            "stream: the lane file's own rows -- pages followed, changes the stream reported "
            "for them, how many had their text stored, and changes it reported for pages you "
            "do not follow. Complete through: the earliest point every feed was read without "
            "a break. Tracked pages, law: the main database's rows, with the newest and oldest "
            "check. Maps: the download manager's regions and the bytes on disk. Storage: the "
            "same rows as Settings -> Storage. Nothing is sent anywhere."
        ),
        "caveat": (
            "Freshness is shown as dates, never judged: how recent is recent enough depends "
            "on the story. A change counted is not a change read: under a budget the stream "
            "stores the text of some changes and counts the rest."
        ),
    }
