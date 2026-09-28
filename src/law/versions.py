"""A law's versions, read the way every change-tracking reader reads them (Q905, Q908, Q918).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q918's note makes the law reader's controls a SHARED grammar: "the UI should be homogenous
with other parts of the app's ability to track change, such as wikipedia articles". So
this module does not build a law widget. It fills the payload the one version reader
(``src/static/ooversions.js``, served by ``src/api/versions.py``) draws for every kind —
the same keys ``src/wiki/versions.py`` fills for a watched Wikipedia page — and the
reader draws the same controls and the same disclosures for both.

THE ONE DATING RULE (Q905 = a). A version is placed in time by the date its SOURCE stated
(``valid_on``, dating ``official``); a version whose source stated none is placed on the
day this instance observed it and is labelled ``observed`` everywhere it appears; a row
recorded before the label existed is placed the same way and labelled ``unrecorded`` —
never promoted to either of the other two. ``effective_versions`` is the only function
that applies that rule, and both the reader and the point-in-time search read it, so the
version a search says was in force on a date is the version the reader shows for it.

"UNTIL" IS THE NEXT VERSION THIS INSTANCE HOLDS, NOT A REPEAL DATE. A version's
``valid_to`` is the effective date of the next version held here. A version skipped
between two polls is invisible to this rule, and the payload's caveat says so.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from src.database.models import LawDocument, LawRevision, LawRevisionSummary
from src.versioned.compare import Part, compare_parts, part_text, side_by_side

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

_LOG = logging.getLogger(__name__)

#: The dating vocabulary every version row carries. Closed; the reader keys its words on
#: it and a value outside it renders as ``unrecorded``, never as a stated date.
DATINGS: tuple[str, ...] = ("official", "observed", "unrecorded", "edit")

#: A source date is kept exactly as stated; for ORDERING only it is padded to a full day.
#: ``partial`` travels with the version so no surface prints "2019-01-01" for a document
#: that said only "2019".
_DATE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?")

#: The external permalink for the identifier schemes that have one by rule (Q918 names
#: "an ELI / CELEX permalink"). Built from the identifier alone — never looked up, and
#: never asked of a model (Q920). ``act-number`` and ``local`` have no resolver, so they
#: get none and the reader says so.
_CELEX_URL = "https://eur-lex.europa.eu/legal-content/AUTO/?uri=CELEX:{value}"

AI_LABEL = "≈ AI-derived · unreliable"


def _day(value: str | None) -> tuple[str | None, bool]:
    """``(sortable YYYY-MM-DD, partial)`` for a stated date, or ``(None, False)``."""
    m = _DATE.match((value or "").strip())
    if not m:
        return None, False
    year, month, day = m.group(1), m.group(2), m.group(3)
    return f"{year}-{month or '01'}-{day or '01'}", not (month and day)


@dataclass(frozen=True, slots=True)
class VersionRow:
    """One held version of one document, placed in time by the ONE dating rule."""

    revision_id: int
    lane_key: str | None
    #: The day the version starts, as the reader prints it: the source's own string for
    #: an ``official`` date (possibly partial), the observation day otherwise.
    valid_from: str | None
    #: ``valid_from`` padded to a full day, for ordering and for the in-force test only.
    sort_day: str | None
    partial: bool
    dating: str
    observed_at: datetime | None
    #: The next held version's ``valid_from``; ``None`` for the newest.
    valid_to: str | None = None
    valid_to_sort: str | None = None


def _dating_of(rev) -> str:
    dating = getattr(rev, "valid_on_dating", None)
    if dating in ("official", "observed"):
        return dating
    return "unrecorded"


def effective_versions(rows) -> list[VersionRow]:
    """Every held version, OLDEST first, each with its ``valid_from`` / ``valid_to``.

    ``rows`` are ``LawRevision``-shaped (id, lane_key, valid_on, valid_on_dating,
    observed_at). A stated date is used only when the row's dating says the source
    stated it; a ``valid_on`` on a row whose dating is not ``official`` is a legacy
    value this app cannot vouch for and orders nothing.
    """
    placed: list[VersionRow] = []
    for rev in rows:
        dating = _dating_of(rev)
        observed = getattr(rev, "observed_at", None)
        if dating == "official" and getattr(rev, "valid_on", None):
            shown = rev.valid_on
            sort_day, partial = _day(rev.valid_on)
        else:
            if dating == "official":
                dating = "unrecorded"  # labelled official with no date: not a date
            shown = observed.strftime("%Y-%m-%d") if observed else None
            sort_day, partial = shown, False
        placed.append(
            VersionRow(
                revision_id=rev.id,
                lane_key=getattr(rev, "lane_key", None),
                valid_from=shown,
                sort_day=sort_day,
                partial=partial,
                dating=dating,
                observed_at=observed,
            )
        )
    placed.sort(key=lambda v: (v.sort_day or "", v.observed_at or datetime.min, v.revision_id))
    out: list[VersionRow] = []
    for i, v in enumerate(placed):
        nxt = placed[i + 1] if i + 1 < len(placed) else None
        out.append(
            VersionRow(
                revision_id=v.revision_id,
                lane_key=v.lane_key,
                valid_from=v.valid_from,
                sort_day=v.sort_day,
                partial=v.partial,
                dating=v.dating,
                observed_at=v.observed_at,
                valid_to=nxt.valid_from if nxt else None,
                valid_to_sort=nxt.sort_day if nxt else None,
            )
        )
    return out


def in_force_on(versions: list[VersionRow], day: str) -> VersionRow | None:
    """The held version in force on ``day`` (``YYYY-MM-DD``), or ``None``.

    ``None`` when the day precedes the earliest held version: this instance holds no
    text for that date, and the answer is "not held", never the oldest text it has.
    """
    current = None
    for v in versions:
        if v.sort_day is not None and v.sort_day <= day:
            current = v
        elif v.sort_day is not None and v.sort_day > day:
            break
    return current


def _revision_rows(db: Session, document_id: int):
    """The version facts without the texts: the texts are loaded only when compared."""
    return (
        db.query(LawRevision)
        .with_entities(
            LawRevision.id,
            LawRevision.lane_key,
            LawRevision.valid_on,
            LawRevision.valid_on_dating,
            LawRevision.observed_at,
            LawRevision.delta_bytes,
            LawRevision.diff_basis,
            (LawRevision.full_text.isnot(None)).label("has_text"),
        )
        .filter(LawRevision.document_id == document_id)
        .all()
    )


def external_permalink(scheme: str | None, value: str | None) -> str | None:
    """The ELI or CELEX permalink the identifier itself names, or ``None``."""
    if not scheme or not value:
        return None
    if scheme == "eli" and value.startswith(("http://", "https://")):
        return value
    if scheme == "celex" and re.fullmatch(r"[0-9a-z()]+", value):
        return _CELEX_URL.format(value=value.upper())
    return None


def _latest_summaries(db: Session, revision_ids: list[int]) -> dict[int, LawRevisionSummary]:
    if not revision_ids:
        return {}
    rows = (
        db.query(LawRevisionSummary)
        .filter(LawRevisionSummary.revision_id.in_(revision_ids))
        .order_by(LawRevisionSummary.created_at.asc(), LawRevisionSummary.id.asc())
        .all()
    )
    return {r.revision_id: r for r in rows}  # the newest wins: append-only, never overwritten


def _lane_facts(db: Session, doc: LawDocument) -> dict:
    """Identity, licence, provenance and the language versions — read once, never raising."""
    out: dict = {"identifier": None, "licence": None, "provenance": None, "languages": []}
    lane_key = getattr(doc, "lane_key", None)
    if not lane_key:
        return out
    try:
        from src.law.lane_models import LawDocumentMeta
        from src.law.model import identity_group, licence_of, provenance_of
        from src.versioned.store import lane_exists, lane_session

        if not lane_exists("law"):
            return out
        with lane_session("law") as lane:
            meta = lane.query(LawDocumentMeta).filter_by(lane_key=lane_key).first()
            if meta is None:
                return out
            licence = licence_of(meta)
            out["licence"] = {"name": licence.name, "url": licence.url, "id": licence.licence_id}
            phrase, body = provenance_of(meta)
            out["provenance"] = {"phrase": phrase, "body": body}
            group = identity_group(lane, meta.identity_id)
            if group is None:
                return out
            ident = group.identity
            out["identifier"] = {
                "scheme": ident.identity_scheme,
                "value": ident.document_identity,
                "jurisdiction": ident.jurisdiction_alpha3,
                "url": external_permalink(ident.identity_scheme, ident.document_identity),
            }
            keys = {m.lane_key: (m.language, m.title, m.translation_kind) for m in group.members}
        # The switch links LOCAL readers: a language version is reachable only if this
        # instance tracks it, and a sibling with no corpus row is listed as not held.
        docs = {
            d.lane_key: d
            for d in db.query(LawDocument).filter(LawDocument.lane_key.in_(list(keys))).all()
        }
        out["languages"] = [
            {
                "language": language,
                "title": title or (docs[k].title if k in docs else ""),
                "id": docs[k].id if k in docs else None,
                "current": k == lane_key,
                "kind": kind,
            }
            for k, (language, title, kind) in keys.items()
        ]
    except Exception:  # noqa: BLE001 - the lane is an addition; the text is the document
        _LOG.debug("law versions: lane facts unavailable for %s", doc.id, exc_info=True)
    return out


def reader_payload(db: Session, doc: LawDocument) -> dict:
    """The shared version reader's payload for one law document (newest version first)."""
    rows = _revision_rows(db, doc.id)
    placed = effective_versions(rows)
    by_id = {r.id: r for r in rows}
    summaries = _latest_summaries(db, [v.revision_id for v in placed])
    versions = []
    for idx, v in enumerate(reversed(placed)):
        r = by_id[v.revision_id]
        # The FIRST CAPTURE is a fact about when this instance started, not about the
        # dating order: its row says so ("first"); a row older than that column is the
        # oldest one held.
        first = r.diff_basis == "first" or (r.diff_basis is None and idx == len(placed) - 1)
        s =summaries.get(v.revision_id)
        versions.append(
            {
                "id": v.revision_id,
                "label": "first captured snapshot" if first else "an amendment",
                "observed_at": v.observed_at.isoformat() if v.observed_at else None,
                "valid_from": v.valid_from,
                "valid_to": v.valid_to,
                "partial": v.partial,
                "dating": v.dating,
                "has_text": bool(r.has_text),
                "delta_bytes": None if first else r.delta_bytes,
                "local_url": f"/api/law/documents/{doc.id}/view?version={v.revision_id}",
                "external_url": None,
                "summary": (
                    {"text": s.summary, "model": s.model, "label": AI_LABEL} if s is not None else None
                ),
            }
        )
    facts = _lane_facts(db, doc)
    return {
        "kind": "law",
        "id": doc.id,
        "title": doc.title,
        "language": doc.language,
        "jurisdiction": doc.jurisdiction,
        "versions": versions,
        "total": len(versions),
        "permalink": f"/api/law/documents/{doc.id}/view",
        "identifier": facts["identifier"],
        "licence": facts["licence"],
        "provenance": facts["provenance"],
        "languages": facts["languages"],
        "parts_name": "provisions",
        "method": (
            "Every version this instance captured, placed in time by the date its source "
            "states; a version whose source states none is placed on the day it was "
            "observed and labelled so. Two versions are compared line by line on this "
            "machine from their stored texts."
        ),
        "caveat": (
            "A research mirror, not legal advice. 'Until' is the next version this "
            "instance holds, not a repeal date: a version published between two captures "
            "is not held and is not shown."
        ),
    }


def _provision_parts(revision_lane_key: str | None) -> list[Part] | None:
    """One version's provisions as navigable parts, or ``None`` when it has none."""
    if not revision_lane_key:
        return None
    try:
        from src.law.model import provisions_for
        from src.versioned.store import lane_exists, lane_session

        if not lane_exists("law"):
            return None
        with lane_session("law") as lane:
            rows = provisions_for(lane, revision_lane_key)
            parts = [
                Part(
                    address=p.address,
                    label=" ".join(x for x in ((p.num or "").strip(), (p.heading or "").strip()) if x)
                    or p.address,
                    text=p.text or "",
                )
                for p in rows
            ]
    except Exception:  # noqa: BLE001 - a navigation aid, never a reason to refuse the diff
        _LOG.debug("law versions: provisions unavailable for %s", revision_lane_key, exc_info=True)
        return None
    return parts or None


def compare_payload(
    db: Session, doc: LawDocument, from_id: int, to_id: int, *, part: str | None = None
) -> dict:
    """Two held versions side by side, with the provision navigation between them.

    Raises ``LookupError`` for a version that is not this document's, and returns an
    honest refusal (``method = "text-not-held"``) for a version whose text was never
    stored — never the neighbouring version's words under the asked-for one's date.
    """
    revs = {
        r.id: r
        for r in db.query(LawRevision)
        .filter(LawRevision.document_id == doc.id, LawRevision.id.in_([from_id, to_id]))
        .all()
    }
    if from_id not in revs or to_id not in revs:
        raise LookupError("version not found for this document")
    a, b = revs[from_id], revs[to_id]
    missing = [r.id for r in (a, b) if r.full_text is None]
    base = {"kind": "law", "id": doc.id, "from": from_id, "to": to_id, "part": part}
    if missing:
        return base | {
            "method": "text-not-held",
            "missing": missing,
            "rows": [],
            "parts": None,
            "parts_reason": None,
        }
    before_parts, after_parts = _provision_parts(a.lane_key), _provision_parts(b.lane_key)
    if before_parts is None or after_parts is None:
        parts = None
        reason = (
            "No provisions were parsed for one of these versions (its text did not arrive "
            "in a structured format), so it can only be compared as a whole."
        )
    else:
        parts, reason = compare_parts(before_parts, after_parts), None
    if part:
        if parts is None:
            raise LookupError("this comparison has no provisions to scope to")
        diff = side_by_side(part_text(before_parts, part), part_text(after_parts, part))
    else:
        diff = side_by_side(a.full_text, b.full_text)
    return base | diff | {"parts": parts, "parts_reason": reason}
