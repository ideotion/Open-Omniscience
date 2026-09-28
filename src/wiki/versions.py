"""A watched Wikipedia page's revisions, in the one version reader's shape (Q918's note).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The same payload ``src/law/versions.py`` fills for a law, filled from ``wiki_revisions``:
so the version selector, the side-by-side comparison, the part navigation (a law's
provisions, a page's ``== sections ==``), the permalink, the licence line and the dating
label are drawn by ONE component for both, and a disclosure that exists for one kind
exists for the other or is absent from both for a stated reason.

A WIKIPEDIA REVISION IS DATED BY ITS EDIT. The source records when each edit was saved,
so every row carries dating ``edit`` — the source's own timestamp, never this instance's
capture time. Only revisions whose FULL text is stored can be compared; the others are
listed (hiding them would make the selector and the tracked history disagree about how
many versions exist) and refuse a comparison by name.
"""

from __future__ import annotations

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


def reader_payload(db: Session, page: WikiPage) -> dict:
    """The shared version reader's payload for one watched page (newest first)."""
    base = db.query(WikiRevision).filter(WikiRevision.page_id == page.id)
    total = base.count()
    rows = (
        base.with_entities(
            WikiRevision.id,
            WikiRevision.revid,
            WikiRevision.timestamp,
            WikiRevision.delta_bytes,
            WikiRevision.parent_revid,
            (WikiRevision.full_text.isnot(None)).label("has_text"),
        )
        .order_by(WikiRevision.timestamp.desc(), WikiRevision.id.desc())
        .limit(MAX_LISTED)
        .all()
    )
    versions = []
    newer: str | None = None
    for r in rows:
        when = r.timestamp.strftime("%Y-%m-%d %H:%M") if r.timestamp else None
        versions.append(
            {
                "id": r.id,
                "label": "a revision",
                "observed_at": r.timestamp.isoformat() if r.timestamp else None,
                "valid_from": when,
                "valid_to": newer,
                "partial": False,
                "dating": "edit",
                "has_text": bool(r.has_text),
                "delta_bytes": r.delta_bytes,
                "local_url": None,
                "external_url": revision_url(page.wiki, r.revid),
                "summary": None,
            }
        )
        newer = when
    return {
        "kind": "wiki",
        "id": page.id,
        "title": page.title,
        "language": page.wiki,
        "jurisdiction": None,
        "versions": versions,
        "total": total,
        "permalink": None,
        "history_url": history_url(page.wiki, page.title),
        "identifier": None,
        "licence": {"name": LICENCE_NAME, "url": LICENCE_URL, "id": "cc-by-sa-4.0"},
        "provenance": None,
        # One edition per watched page: Wikipedia's language editions are separate
        # articles, not translations of one text, so there is no switch to offer.
        "languages": [],
        "parts_name": "sections",
        "method": (
            "The revisions this machine stored for this page, dated by each edit's own "
            "timestamp. Two revisions are compared line by line on this machine from "
            "their stored texts; only revisions whose full text is stored can be compared."
        ),
        "caveat": (
            "The tracked slice of edits, not necessarily every historical revision. "
            "'Until' is the next revision this machine holds. Sections are read from "
            "'== heading ==' lines; templates are not expanded."
        ),
    }


def compare_payload(
    db: Session, page: WikiPage, from_id: int, to_id: int, *, part: str | None = None
) -> dict:
    """Two stored revisions side by side, with the section navigation between them."""
    revs = {
        r.id: r
        for r in db.query(WikiRevision)
        .filter(WikiRevision.page_id == page.id, WikiRevision.id.in_([from_id, to_id]))
        .all()
    }
    if from_id not in revs or to_id not in revs:
        raise LookupError("version not found for this page")
    a, b = revs[from_id], revs[to_id]
    base = {"kind": "wiki", "id": page.id, "from": from_id, "to": to_id, "part": part}
    missing = [r.id for r in (a, b) if r.full_text is None]
    if missing:
        return base | {
            "method": "text-not-held",
            "missing": missing,
            "rows": [],
            "parts": None,
            "parts_reason": None,
        }
    before, after = _section_parts(a.full_text), _section_parts(b.full_text)
    parts = compare_parts(before, after)
    if part:
        diff = side_by_side(part_text(before, part), part_text(after, part))
    else:
        diff = side_by_side(a.full_text, b.full_text)
    return base | diff | {"parts": parts, "parts_reason": None}
