"""A watched Wikipedia page's revisions, in the one version reader's shape (Q918's note).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The same payload ``src/law/versions.py`` fills for a law, filled from the page's stored revisions:
so the version selector, the side-by-side comparison, the part navigation (a law's
provisions, a page's ``== sections ==``), the permalink, the licence line and the dating
label are drawn by ONE component for both, and a disclosure that exists for one kind
exists for the other or is absent from both for a stated reason.

A WIKIPEDIA REVISION IS DATED BY ITS EDIT. The source records when each edit was saved,
so a row carries dating ``edit`` — the source's own timestamp, never this instance's
capture time — and a lane capture the source did not date says ``observed`` instead. Only revisions whose FULL text is stored can be compared; the others are
listed (hiding them would make the selector and the tracked history disagree about how
many versions exist) and refuse a comparison by name.

A PAGE'S VERSIONS LIVE IN TWO STORES, AND THE READER LISTS BOTH. The old tracker writes
``wiki_revisions`` in ``corpus.db`` (a "Track now" press, a page check); since Q1020 moved
Wikipedia to the lane, the scheduler's captures go to ``wiki.db`` instead — the page's
baseline and its ``versioned_revisions``, joined on ``external_id_for(wiki, title)``. A
reader that read only the first would show a lane-running instance nothing but what the
old tracker happened to catch. So each version's id NAMES its store (``t`` tracker, ``b``
the lane's baseline, ``l`` a lane revision), and one edit held in both is listed once,
preferring the copy whose text is stored.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from src.database.models import WikiPage, WikiRevision
from src.versioned.compare import Part, compare_parts, part_text, side_by_side
from src.wiki.attribution import LICENCE_NAME, LICENCE_URL, history_url, revision_url
from src.wiki.sections import LEAD, split_sections

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

#: Newest revisions listed at most; ``total`` says how many exist.
MAX_LISTED = 200


def _section_parts(text: str | None) -> list[Part] | None:
    """A revision's sections as navigable parts; a second section of the same title is
    addressed ``title #2`` so the two cannot be compared as one."""
    if text is None:
        return None
    seen: dict[str, int] = {}
    parts = []
    for s in split_sections(text):
        title = "(lead)" if s.title == LEAD else s.title
        n = seen.get(title, 0) + 1
        seen[title] = n
        address = title if n == 1 else f"{title} #{n}"
        # The newline before the next heading belongs to the layout, not the section:
        # without the strip, a page's last section reads "changed" the moment a new
        # section is appended after it.
        parts.append(Part(address=address, label=address, text=s.body.strip("\n")))
    return parts


def _lane_rows(page: WikiPage) -> list[dict]:
    """The page's versions held in the Wikipedia lane, text included; ``[]`` when the lane
    is absent or does not follow this page. Read inside the session (a detached row cannot
    reload its compressed text)."""
    from sqlalchemy import select
    from sqlalchemy.exc import SQLAlchemyError

    from src.versioned.adapters.wiki import external_id_for
    from src.versioned.models import VersionedBaseline, VersionedEntity, VersionedRevision
    from src.versioned.store import LaneAbsentError, lane_exists, lane_session

    if not lane_exists("wiki"):
        return []
    out: list[dict] = []
    try:
        with lane_session("wiki") as lane:
            ent = lane.execute(
                select(VersionedEntity.id).where(
                    VersionedEntity.external_id == external_id_for(page.wiki, page.title)
                )
            ).scalar_one_or_none()
            if ent is None:
                return []
            for b in lane.execute(
                select(VersionedBaseline).where(VersionedBaseline.entity_id == ent)
            ).scalars():
                out.append(
                    {
                        "key": f"b{b.id}",
                        "revid": b.revision_ref,
                        "when": b.revised_at,
                        "observed": b.captured_at,
                        "text": b.content,
                        "delta": None,
                        "store": "lane",
                    }
                )
            for r in lane.execute(
                select(VersionedRevision).where(VersionedRevision.entity_id == ent)
            ).scalars():
                out.append(
                    {
                        "key": f"l{r.id}",
                        "revid": r.revision_ref,
                        "when": r.revised_at,
                        "observed": r.observed_at,
                        "text": r.content,
                        "delta": r.diff_byte_delta,
                        "store": "lane",
                    }
                )
    except (LaneAbsentError, SQLAlchemyError):
        # An unreadable lane is not "no versions": the tracker's rows still list, and the
        # method line says which store the list came from.
        return []
    return out


def _all_rows(db: Session, page: WikiPage) -> list[dict]:
    """Every held version of the page from both stores, one per edit, newest first."""
    rows = [
        {
            "key": f"t{r.id}",
            "revid": str(r.revid),
            "when": r.timestamp,
            "observed": r.timestamp,
            "text": r.full_text,
            "delta": r.delta_bytes,
            "store": "tracker",
        }
        for r in db.query(WikiRevision).filter(WikiRevision.page_id == page.id).all()
    ]
    by_revid: dict[str, dict] = {}
    for r in rows + _lane_rows(page):
        held = by_revid.get(r["revid"])
        if held is None or (held["text"] is None and r["text"] is not None):
            by_revid[r["revid"]] = r

    def _key(r: dict):
        t = r["when"] or r["observed"]
        return (t.replace(tzinfo=None) if t is not None else None) or datetime.min

    return sorted(by_revid.values(), key=lambda r: (_key(r), r["key"]), reverse=True)


def reader_payload(db: Session, page: WikiPage) -> dict:
    """The shared version reader's payload for one watched page (newest first)."""
    held = _all_rows(db, page)
    versions = []
    newer: str | None = None
    for r in held[:MAX_LISTED]:
        edited = r["when"]
        when = (
            (edited or r["observed"]).strftime("%Y-%m-%d %H:%M")
            if (edited or r["observed"])
            else None
        )
        versions.append(
            {
                "id": r["key"],
                "label": "a revision",
                "observed_at": r["observed"].isoformat() if r["observed"] else None,
                "valid_from": when,
                "valid_to": newer,
                "partial": False,
                # The edit's own timestamp where the source gave one; a lane capture
                # without it is dated by observation and says so.
                "dating": "edit" if edited is not None else "observed",
                "has_text": r["text"] is not None,
                "delta_bytes": r["delta"],
                "local_url": None,
                "external_url": revision_url(page.wiki, r["revid"])
                if str(r["revid"]).isdigit()
                else None,
                "summary": None,
            }
        )
        newer = when
    stores = sorted({r["store"] for r in held})
    return {
        "kind": "wiki",
        "id": page.id,
        "title": page.title,
        "language": page.wiki,
        "jurisdiction": None,
        "versions": versions,
        "total": len(held),
        "permalink": None,
        "history_url": history_url(page.wiki, page.title),
        "identifier": None,
        "licence": {"name": LICENCE_NAME, "url": LICENCE_URL, "id": "cc-by-sa-4.0"},
        "provenance": None,
        # One edition per watched page: Wikipedia's language editions are separate
        # articles, not translations of one text, so there is no switch to offer.
        "languages": [],
        "parts_name": "sections",
        "stores": stores,
        "method": (
            "The revisions this machine stored for this page, from the Wikipedia lane and "
            "from the page tracker, one row per edit, dated by each edit's own timestamp. "
            "Two revisions are compared line by line on this machine from their stored "
            "texts; only revisions whose full text is stored can be compared."
        ),
        "caveat": (
            "The tracked slice of edits, not necessarily every historical revision. "
            "'Until' is the next revision this machine holds. Sections are read from "
            "'== heading ==' lines; templates are not expanded."
        ),
    }


def compare_payload(
    db: Session, page: WikiPage, from_id: str, to_id: str, *, part: str | None = None
) -> dict:
    """Two stored revisions side by side, with the section navigation between them."""
    held = {r["key"]: r for r in _all_rows(db, page)}
    from_id, to_id = str(from_id), str(to_id)
    if from_id not in held or to_id not in held:
        raise LookupError("version not found for this page")
    a, b = held[from_id], held[to_id]
    base = {"kind": "wiki", "id": page.id, "from": from_id, "to": to_id, "part": part}
    missing = [k for k, r in ((from_id, a), (to_id, b)) if r["text"] is None]
    if missing:
        return base | {
            "method": "text-not-held",
            "missing": missing,
            "rows": [],
            "parts": None,
            "parts_reason": None,
        }
    before, after = _section_parts(a["text"]), _section_parts(b["text"])
    parts = compare_parts(before, after)
    if part:
        diff = side_by_side(part_text(before, part), part_text(after, part))
    else:
        diff = side_by_side(a["text"], b["text"])
    return base | diff | {"parts": parts, "parts_reason": None}
