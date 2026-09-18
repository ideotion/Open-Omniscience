"""
World-law API: tracked legal documents, change feed, and on-demand tracking.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Read endpoints list tracked documents (coverage by jurisdiction) and the flagged-change
feed; ``track`` fetches watched documents now through the ethical fetcher. A research
mirror, never legal advice — every record links back to its official source.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.catalog.countries import country_payload_iso3, country_query_forms
from src.database.models import LawDocument, LawRevision, LawRevisionSummary
from src.database.session import get_db

router = APIRouter(prefix="/api/law", tags=["law"])

_CAVEAT = (
    "A research mirror, not the authoritative source and not legal advice. Every "
    "document links back to its official gazette; changes are surfaced, never judged."
)


def _verdict_of(last_status: str | None) -> str:
    """Classify the free-text ``last_status`` track.py already writes into a
    small, honest, named set the UI can badge/colour -- never a NEW guess, just
    a label over the real message (which stays visible verbatim on hover).
    Order matters: check the more specific substrings before the generic ones.
    """
    if not last_status:
        return "never_checked"
    s = last_status.lower()
    if "robots" in s:
        return "robots_blocked"
    if s.startswith("fetch error") or s.startswith("error:"):
        return "error"
    if "no usable text" in s or "too short" in s or s.startswith("empty") or "scanned" in s:
        return "empty"
    if s.startswith("re-read with"):
        # The strip stage re-read this document's own baseline: the extractor changed,
        # the law did not. Without this it fell through to "other" -- so the one outcome
        # that means ruling 35 SUCCEEDED read as the one that means we do not know what
        # happened, on exactly the surface built to show whether it had.
        return "re_extracted"
    if s.startswith("changed ("):
        return "changed"
    if "reverted" in s:
        return "reverted"
    if "baseline" in s:
        return "baselined"
    if s == "unchanged":
        return "unchanged"
    return "other"


def _latest_summaries_by_revision(
    db: Session, revision_ids: list[int]
) -> dict[int, LawRevisionSummary]:
    """The MOST RECENT AI change-summary per revision id, batched (never N+1 across
    a list of revisions). A revision may be re-summarized (a later, better prompt)
    -- the highest id per revision is the latest; history isn't lost, just not the
    default view (mirrors ArticleAnalysis's "latest wins" convention)."""
    if not revision_ids:
        return {}
    rows = (
        db.query(LawRevisionSummary)
        .filter(LawRevisionSummary.revision_id.in_(revision_ids))
        .order_by(LawRevisionSummary.revision_id, LawRevisionSummary.id.desc())
        .all()
    )
    out: dict[int, LawRevisionSummary] = {}
    for row in rows:
        out.setdefault(row.revision_id, row)  # first hit per id, at desc order = latest
    return out


def _summary_dict(row: LawRevisionSummary | None) -> dict | None:
    """None when no summary exists yet -- never a fabricated placeholder. Rendered
    "AI-derived · unreliable" by the caller (the established third class)."""
    if row is None:
        return None
    return {
        "summary": row.summary,
        "model": row.model,
        "prompt_version": row.prompt_version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _doc_dict(doc: LawDocument, *, revisions: int = 0, flagged: int = 0) -> dict:
    return {
        "id": doc.id,
        "jurisdiction": doc.jurisdiction,
        "title": doc.title,
        "url": doc.url,
        "official_url": doc.official_url,
        "category": doc.category,
        "consolidated": bool(doc.consolidated),
        "watched": bool(doc.watched),
        # S4b (the Cambodia fix): the catalog's own asserted language/country, when
        # stated -- never guessed. Absent for most pre-S4b rows (honestly None).
        "language": doc.language,
        "country": doc.country,
        # Both alpha-3 forms, because a law row carries TWO country-shaped facts and
        # they are not the same claim: `jurisdiction` is the legal system the document
        # belongs to (`uk`, `eu`, `int`), `country` is the catalogue's own assertion
        # about where it comes from. Q303 names GBR for the `uk` jurisdiction, which is
        # why the two can legitimately differ on one row.
        "country_iso3": country_payload_iso3(doc.country),
        "jurisdiction_iso3": country_payload_iso3(doc.jurisdiction),
        "has_baseline": doc.baseline_text is not None,
        "last_checked_at": doc.last_checked_at.isoformat() if doc.last_checked_at else None,
        "last_status": doc.last_status,
        "verdict": _verdict_of(doc.last_status),
        "revisions": revisions,
        "flagged": flagged,
    }


@router.get("/status")
def law_status(db: Session = Depends(get_db)) -> dict:
    """Coverage overview: documents per jurisdiction + change/flag totals."""
    by_jur: dict[str, int] = {
        jur: n
        for jur, n in db.query(LawDocument.jurisdiction, func.count(LawDocument.id))
        .group_by(LawDocument.jurisdiction)
        .all()
    }
    last_checked = db.query(func.max(LawDocument.last_checked_at)).scalar()
    return {
        "documents": db.query(func.count(LawDocument.id)).scalar() or 0,
        "jurisdictions": {k: int(v) for k, v in sorted(by_jur.items())},
        "tracked": db.query(func.count(LawDocument.id))
        .filter(LawDocument.baseline_text.isnot(None))
        .scalar()
        or 0,
        "changes": db.query(func.count(LawRevision.id))
        .filter(LawRevision.delta_bytes != 0)
        .scalar()
        or 0,
        "flagged": db.query(func.count(LawRevision.id)).filter_by(flagged=True).scalar() or 0,
        # Field report 2026-07-17 (the law-vertical brief, S2): a working tracker with
        # no *flagged* amendments yet renders a bare "no changes" that reads identically
        # to a tracker that never ran. Surface the last pass so the two are distinguishable.
        "last_checked_at": last_checked.isoformat() if last_checked else None,
        "caveat": _CAVEAT,
    }


@router.get("/documents")
def law_documents(
    jurisdiction: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """List tracked legal documents (optionally by jurisdiction)."""
    q = db.query(LawDocument)
    if jurisdiction:
        # BOTH forms, and this is the case that makes the widening necessary rather
        # than tidy: Q303 displays `GBR` for a row stored as `uk`, so an operator can
        # read the code off the screen, paste it here, and must not get an empty list.
        q = q.filter(LawDocument.jurisdiction.in_(country_query_forms(jurisdiction)))
    docs = q.order_by(LawDocument.jurisdiction, LawDocument.id).all()
    rev_counts: dict[int, int] = {
        doc_id: n
        for doc_id, n in db.query(LawRevision.document_id, func.count(LawRevision.id))
        .group_by(LawRevision.document_id)
        .all()
    }
    flag_counts: dict[int, int] = {
        doc_id: n
        for doc_id, n in db.query(LawRevision.document_id, func.count(LawRevision.id))
        .filter_by(flagged=True)
        .group_by(LawRevision.document_id)
        .all()
    }
    return {
        "caveat": _CAVEAT,
        "documents": [
            _doc_dict(d, revisions=rev_counts.get(d.id, 0), flagged=flag_counts.get(d.id, 0))
            for d in docs
        ],
    }


@router.get("/changes")
def law_changes(
    flagged_only: bool = False,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    """Recent tracked legal changes (ALL real changes by default, newest first).

    Field report 2026-07-17 (the law-vertical brief, S2): consolidated statutes
    rarely trip the flagging heuristics, so a perfectly-working tracker with
    real (unflagged) byte-level changes rendered "no changes yet" forever under
    the old flagged_only=True default. Flagging stays available as an opt-IN
    toggle (``flagged_only=true``), never the default.
    """
    q = db.query(LawRevision, LawDocument).join(
        LawDocument, LawDocument.id == LawRevision.document_id
    )
    q = q.filter(LawRevision.delta_bytes != 0)
    if flagged_only:
        q = q.filter(LawRevision.flagged.is_(True))
    rows = q.order_by(LawRevision.observed_at.desc(), LawRevision.id.desc()).limit(limit).all()
    by_rev = _latest_summaries_by_revision(db, [rev.id for rev, _doc in rows])
    return {
        "caveat": _CAVEAT,
        "changes": [
            {
                "id": rev.id,
                "document_id": doc.id,
                "jurisdiction": doc.jurisdiction,
                "title": doc.title,
                "official_url": doc.official_url or doc.url,
                "category": doc.category,
                "observed_at": rev.observed_at.isoformat() if rev.observed_at else None,
                "delta_bytes": rev.delta_bytes,
                "flagged": bool(rev.flagged),
                "flag_reasons": (rev.flag_reasons or "").split(",") if rev.flag_reasons else [],
                "diff": rev.diff or "",
                # AI-derived, unreliable (S3, ruled): auto-populated for UI-language
                # jurisdictions, else null until the on-demand button is clicked.
                "ai_summary": _summary_dict(by_rev.get(rev.id)),
            }
            for rev, doc in rows
        ],
    }


@router.post("/track")
def law_track(
    limit: int = Query(25, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    """Fetch all watched legal documents now (through the ethical fetcher)."""
    from src.law.track import track_watched
    from src.safety.fetcher import make_fetcher

    fetcher = make_fetcher()
    return track_watched(db, fetcher, limit_documents=limit)


@router.post("/seed")
def law_seed(db: Session = Depends(get_db)) -> dict:
    """(Re)seed the worldwide legal catalog + register trackable documents (idempotent)."""
    from src.law.catalog import register_documents, seed_legal_sources

    sources = seed_legal_sources(db)
    documents = register_documents(db)
    return {"sources": sources, "documents": documents}


class _AddDocumentBody(BaseModel):
    """S3 of the law-vertical brief (2026-07-17): add-a-document-by-URL — the
    missing workflow (editing configs/legal_sources.yml + re-seeding was the only
    way before this)."""

    jurisdiction: str = Field(..., min_length=1, max_length=8)
    title: str = Field(..., min_length=1, max_length=512)
    url: str = Field(..., min_length=1, max_length=1000)
    official_url: str | None = Field(default=None, max_length=1000)
    category: str = Field(default="legislation", max_length=40)
    language: str | None = Field(default=None, max_length=8)
    country: str | None = Field(default=None, max_length=8)

    @field_validator("url", "official_url")
    @classmethod
    def _must_be_http(cls, v: str | None) -> str | None:
        if v and not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("must be an http(s) URL")
        return v


@router.post("/documents")
def add_law_document(body: _AddDocumentBody, db: Session = Depends(get_db)) -> dict:
    """Track a new document by pasting its URL (S3): deduped on
    ``(jurisdiction, url)`` — a 409 on a duplicate, never a silent second row.
    Fetched through the ethical fetcher immediately (the SAME path ``/track``
    uses) so the maintainer sees a real verdict right away; a robots-blocked or
    unreachable URL is still STORED (so it can be retried later) but its honest
    ``last_status`` is returned — never silently dropped, never fabricated."""
    jurisdiction = body.jurisdiction.strip().lower()
    dup = (
        db.query(LawDocument)
        .filter_by(jurisdiction=jurisdiction, url=body.url)
        .first()
    )
    if dup is not None:
        if dup.watched:
            raise HTTPException(status_code=409, detail="This document is already tracked.")
        # Previously unwatched (via DELETE below) -- re-adding the same URL
        # reactivates it rather than erroring or creating a second row.
        dup.watched = True
        db.commit()
        doc = dup
    else:
        doc = LawDocument(
            jurisdiction=jurisdiction,
            title=body.title.strip(),
            url=body.url,
            official_url=body.official_url,
            category=body.category,
            consolidated=False,
            watched=True,
            language=body.language,
            country=body.country,
        )
        db.add(doc)
        db.commit()

    from src.law.track import track_document
    from src.safety.fetcher import make_fetcher

    result = track_document(db, make_fetcher(), doc)
    return {**_doc_dict(doc), "track_result": result, "caveat": _CAVEAT}


@router.delete("/documents/{document_id}")
def remove_law_document(document_id: int, db: Session = Depends(get_db)) -> dict:
    """Stop tracking a document (S3's DELETE/unwatch). NEVER deletes the corpus
    Article or the already-captured revisions — what was already learned stays
    searchable; only FUTURE tracking passes skip it. Re-adding the same URL
    re-activates it (watched=True) rather than a fresh duplicate row."""
    doc = db.query(LawDocument).filter_by(id=document_id).first()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    doc.watched = False
    db.commit()
    return {"id": doc.id, "watched": False}


@router.get("/documents/{document_id}")
def law_document(document_id: int, db: Session = Depends(get_db)) -> dict:
    """One document with its change history (diffs)."""
    doc = db.query(LawDocument).filter_by(id=document_id).first()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    revs = (
        db.query(LawRevision)
        .filter_by(document_id=doc.id)
        .order_by(LawRevision.observed_at.desc())
        .all()
    )
    by_rev = _latest_summaries_by_revision(db, [r.id for r in revs])
    return {
        **_doc_dict(doc, revisions=len(revs)),
        "caveat": _CAVEAT,
        "revisions": [
            {
                "id": r.id,
                "observed_at": r.observed_at.isoformat() if r.observed_at else None,
                "delta_bytes": r.delta_bytes,
                "flagged": bool(r.flagged),
                "flag_reasons": (r.flag_reasons or "").split(",") if r.flag_reasons else [],
                "diff": r.diff or "",
                "ai_summary": _summary_dict(by_rev.get(r.id)),
            }
            for r in revs
        ],
    }


@router.post("/revisions/{revision_id}/summarize")
def summarize_law_revision(revision_id: int, db: Session = Depends(get_db)) -> dict:
    """On-demand AI change summary (S3, ruled). The AUTO ride-along only fires for
    documents whose asserted language is a UI language; this endpoint covers every
    OTHER jurisdiction (or lets a user re-request one sooner). Loopback local
    inference through the active Ollama backend — airplane-safe since the §7 gate
    split, so no network-consent gate here; a down/unavailable model degrades
    honestly (``status="unavailable"``), never a fabricated summary. A revision
    with no recorded diff (a baseline, not a change) is a 422 — there is nothing
    to summarize."""
    rev = db.query(LawRevision).filter_by(id=revision_id).first()
    if rev is None:
        raise HTTPException(status_code=404, detail="Revision not found.")
    doc = db.query(LawDocument).filter_by(id=rev.document_id).first()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    from src.law.summarize import summarize_revision

    result = summarize_revision(db, doc, rev)
    if result.get("status") == "no_diff":
        raise HTTPException(status_code=422, detail=result.get("detail"))
    ai_summary = None
    if result.get("status") == "ok":
        row = db.query(LawRevisionSummary).filter_by(id=result["summary_id"]).first()
        ai_summary = _summary_dict(row)
    return {"status": result.get("status"), "detail": result.get("detail"), "ai_summary": ai_summary}


def _diff_to_html(diff: str | None, _esc) -> str:
    """Colourise a stored unified diff (+ added / - removed) for the reader."""
    rows = []
    for ln in (diff or "").splitlines():
        cls = "add" if ln[:1] == "+" else ("del" if ln[:1] == "-" else "ctx")
        rows.append(f"<div class='dl {cls}'>{_esc(ln)}</div>")
    return "".join(rows) or "<div class='muted'>(no textual diff recorded)</div>"


#: How each stored ``diff_basis`` reads to a human. The NULL case is deliberately not
#: "baseline": a row recorded before the basis was tracked happens to be baseline-anchored,
#: and saying so as though somebody had decided it would turn an absence into a claim.
_LOG = logging.getLogger(__name__)

_BASIS_WORDS = {
    "first": "the first captured snapshot — there is nothing earlier to measure it against",
    "previous": "measured against the previous version",
    "previous-text": "measured against the text this document held before the change",
    "baseline": "measured against the first captured snapshot",
}
_BASIS_UNRECORDED = "recorded before the comparison's anchor was stored — the figures are against the first captured snapshot"


def _selected_version(doc, revs, version: int | None) -> tuple[object | None, str | None, str | None]:
    """The revision to display, its text, and an honest note when there is no text.

    Returns ``(revision_or_None, text_or_None, note_or_None)``. ``revision`` is ``None``
    for the document's current text, which is the default and is what ``latest_text``
    holds. A requested version that does not exist is a 404 — silently showing the
    current text under a URL that names another version is the wrong-version-under-the-
    right-date defect the endpoint docstring describes.
    """
    if version is not None:
        rev = next((r for r in revs if r.id == version), None)
        if rev is None:
            raise HTTPException(status_code=404, detail="Version not found for this document.")
        if rev.full_text is not None:
            return rev, rev.full_text, None
        # A revision from before per-version text was stored. Refuse BY NAME: the diff for
        # this version is still shown below, so the reader loses the full text and keeps
        # the evidence, rather than being handed a neighbouring version's words.
        return rev, None, (
            "This version was recorded before the full text of each version was stored, so "
            "its text is not held locally. Its change is still shown in the amendment "
            "history below."
        )
    text = doc.latest_text if doc.latest_text is not None else doc.baseline_text
    if text is None:
        return None, None, "No text captured yet — track this document to store a snapshot."
    return None, text, None


#: How Q905's dating label reads on screen. Q905 = a's second clause: an observed
#: snapshot without official dating becomes a version dated by observation "and labelled
#: so". The label is the whole point -- a date shown without it is a capture date wearing
#: a consolidation date's clothes -- so an UNLABELLED row says that too, rather than
#: silently borrowing the official wording.
_DATING_WORDS = {
    "official": "as the document states it",
    "observed": "dated by observation — this instance saw the text on this day; the "
    "source stated no date of its own",
}
#: Q927's redistribution states, in words. THREE, never a boolean: "we did not record
#: the terms" and "the terms forbid it" are different facts, and a bool would have to
#: fold one into the other -- folding to permitted redistributes terms nobody read.
_REDISTRIBUTION_WORDS = {
    "permitted": "This licence permits redistribution",
    "forbidden": "This licence forbids redistribution — the text is not exported",
    "unknown": "The terms are not recorded; this app makes no claim about redistribution",
}

_DATING_UNRECORDED = "recorded before this app tracked how the date was determined"


@dataclass(frozen=True, slots=True)
class _LaneMeta:
    """What ``law.db`` knows about the document on screen, read once, never raising.

    A frozen record rather than a dict so the template cannot ask for a key that was
    never set and render an empty string where a fact belongs.
    """

    licence_name: str
    licence_url: str | None
    redistribution: str
    provenance: str
    provenance_body: str | None
    identity: str
    #: ``(language, title, url)`` per OTHER tracked language version of the same law.
    siblings: tuple[tuple[str, str, str], ...]


def _lane_meta(doc) -> _LaneMeta | None:
    """Read the law's identity group, licence and provenance from ``law.db``.

    Returns ``None`` when there is nothing to show — no lane key, no lane file, no row,
    or a lane that will not open. The reader then renders the rows it has, which is the
    honest outcome: this metadata is an ADDITION to the document, and a page that 500s
    because a second database is absent would make the text unreachable over a fact
    about its licence.
    """
    lane_key = getattr(doc, "lane_key", None)
    if not lane_key:
        return None
    try:
        from src.law.lane_models import LawDocumentMeta
        from src.law.model import identity_group, licence_of, provenance_of, redistribution_state
        from src.versioned.store import lane_session

        with lane_session("law") as session:
            meta = session.query(LawDocumentMeta).filter_by(lane_key=lane_key).first()
            if meta is None:
                return None
            licence = licence_of(meta)
            phrase, body = provenance_of(meta)
            group = identity_group(session, meta.identity_id)
            siblings: list[tuple[str, str, str]] = []
            identity = ""
            if group is not None:
                identity = (
                    f"{group.identity.identity_scheme}:{group.identity.jurisdiction_alpha3}:"
                    f"{group.identity.document_identity}"
                )
                siblings = [
                    (m.language, m.title or "", m.source_url or "")
                    for m in group.members
                    if m.lane_key != lane_key
                ]
            return _LaneMeta(
                licence_name=licence.name,
                licence_url=licence.url,
                redistribution=redistribution_state(meta),
                provenance=phrase,
                provenance_body=body,
                identity=identity,
                siblings=tuple(siblings),
            )
    except Exception:  # noqa: BLE001 - the lane is an addition; the text is the document
        _LOG.debug("law reader: lane metadata unavailable for document %s", doc.id, exc_info=True)
        return None


def _valid_on(shown, revs) -> str | None:
    """The point in time the version ON SCREEN represents, or ``None``.

    For the current text that is the newest revision's ``valid_on`` — the same row
    ``latest_text`` came from — because the date belongs to the version, not to the
    document. ``None`` where the document never stated one: there is no fallback to the
    capture date, which is the collapse the adapter's date discipline exists to prevent.
    """
    rev = shown if shown is not None else (revs[0] if revs else None)
    return getattr(rev, "valid_on", None) if rev is not None else None


def _valid_on_dating(shown, revs) -> str | None:
    """How the date ``_valid_on`` returned was determined (Q905). Never inferred.

    Read from the SAME revision, so the date and its method cannot come from two
    different versions. ``None`` where the row predates the label.
    """
    rev = shown if shown is not None else (revs[0] if revs else None)
    return getattr(rev, "valid_on_dating", None) if rev is not None else None


def _in_force_cell(shown, revs, _esc) -> str | None:
    """The version's point in time, with Q905's dating label BESIDE it.

    Three outcomes, and the middle one is the ruling:

    * the source stated a date -> the date, plainly;
    * the source stated none   -> the day this instance OBSERVED the text, carrying the
      "dated by observation" label in its own element, because Q905 = a says such a
      version is "dated by observation and labelled so" and a date without that label is
      a capture date being read as a consolidation date;
    * neither, or a row recorded before the label existed -> no row at all, rather than
      a date with an unexplained provenance.

    The label is a SEPARATE element from the date, which is what lets the i18n walker
    translate it: a text node containing both would match no key in any locale.
    """
    rev = shown if shown is not None else (revs[0] if revs else None)
    if rev is None:
        return None
    dating = getattr(rev, "valid_on_dating", None)
    stated = getattr(rev, "valid_on", None)
    if stated:
        cell = f"<span>{_esc(stated)}</span>"
        if dating and dating != "official":
            cell += f" <span class='muted'>{_esc(_DATING_WORDS.get(dating, _DATING_UNRECORDED))}</span>"
        return cell
    if dating == "observed":
        observed = getattr(rev, "observed_at", None)
        if observed is None:
            return None
        return (
            f"<span>{_esc(observed.strftime('%Y-%m-%d'))}</span> "
            f"<span class='muted'>{_esc(_DATING_WORDS['observed'])}</span>"
        )
    return None


def _retrieved_on(doc, shown, revs) -> str | None:
    """When THIS instance captured the version on screen — the adapter's third date.

    It gets no column of its own. ``LawRevision.observed_at`` and the ``retrieved_on``
    handed to the parser are set from the same ``now`` inside one call of
    ``track_document``, so a second column would be two records of one fact, which is the
    shape that produced the S04-13 per-host-stamp defect. For the current text the answer
    is the newest revision's ``observed_at``; ``None`` where no revision carries one,
    because a date we cannot read is absent, never today's.
    """
    rev = shown if shown is not None else (revs[0] if revs else None)
    if rev is None or rev.observed_at is None:
        return None
    return rev.observed_at.strftime("%Y-%m-%d")


def _version_label(doc, rev) -> tuple[str, str]:
    """One version, as ``(phrase, data)`` — never one welded string.

    The i18n DOM walker matches a text node EXACTLY, so "2026-01-02 14:00 — +42 bytes"
    can never be a key: the numbers vary and no locale file can hold every corpus. The
    PHRASE is fixed and keyable; the DATA (a timestamp, a signed byte count) is data and
    renders the same in every language. The caller puts them in separate elements, which
    is the only arrangement the walker can translate half of.
    """
    if rev is None:
        return "Current text (as last captured)", ""
    when = rev.observed_at.strftime("%Y-%m-%d %H:%M") if rev.observed_at else ""
    if not rev.diff and not (rev.delta_bytes or 0):
        return "first captured snapshot", when
    delta = rev.delta_bytes or 0
    return "an amendment", f"{when} · {delta:+d} bytes"


def _shown_cell(doc, shown, _esc) -> str:
    """The "Showing" row's value: the same phrase/data split the picker uses.

    Two elements, because the i18n DOM walker matches a text node exactly — a phrase
    welded to a timestamp is a string no locale file can hold.
    """
    phrase, data = _version_label(doc, shown)
    out = f"<span class='vp'>{_esc(phrase)}</span>"
    return out + (f" <span class='vd'>{_esc(data)}</span>" if data else "")


def _version_picker(doc, revs, shown, _esc) -> str:
    """The version selector. A plain ``<form>`` of links, so it needs no JavaScript.

    The reader page is served standalone (its own document, not the SPA), and a control
    that needs script to work is a control that does not work when script is blocked — on
    a page whose whole job is to show a legal text. Each entry is a link carrying
    ``?version=``; the current text is the link with no parameter.

    A version with no stored text is still LISTED and still selectable, marked as such:
    hiding it would make the amendment history and the selector disagree about how many
    versions exist, and the entry's own page says why its text is missing.
    """
    if not revs:
        return ""
    items = []
    here = f"/api/law/documents/{doc.id}/view"

    def _entry(href: str, rev, selected: bool) -> str:
        phrase, data = _version_label(doc, rev)
        # Two elements, always: the walker translates the phrase and leaves the data
        # alone. One element carrying both could never match a key.
        body = f"<span class='vp'>{_esc(phrase)}</span>"
        if data:
            body += f" <span class='vd'>{_esc(data)}</span>"
        missing = (
            ""
            if rev is None or rev.full_text is not None
            else " <span class='muted'>text not stored</span>"
        )
        tag = " <span class='now'>shown</span>" if selected else ""
        return (
            f"<li><a class='vsel{' on' if selected else ''}' href='{_esc(href)}'>{body}</a>"
            f"{missing}{tag}</li>"
        )

    items.append(_entry(here, None, shown is None))
    for r in revs:
        items.append(_entry(f"{here}?version={r.id}", r, shown is not None and r.id == shown.id))
    return (
        "<nav class='versions'><h2>Versions</h2><ol>"
        + "".join(items)
        + "</ol><p class='muted vnote'>Every version this instance captured. The current "
        "text is the newest capture, not a live consolidation.</p></nav>"
    )


@router.get("/documents/{document_id}/provision-timeline")
def law_provision_timeline(document_id: int, db: Session = Depends(get_db)) -> dict:
    """Analytic 1 (Q914 = a): which PROVISIONS of this document changed, and when.

    READ-ONLY and LOCAL: it opens no network path and creates nothing — a document whose
    lane row does not exist gets an honest refusal rather than a lane brought into being
    by a GET.

    The version ORDER is supplied from ``corpus.db``, oldest first, because the lane holds
    no ordering of its own: ordering by the lane's own row timestamps would order by when
    this app wrote the rows, which is not when the versions happened.
    """
    doc = db.query(LawDocument).filter_by(id=document_id).first()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    lane_key = getattr(doc, "lane_key", None)
    if not lane_key:
        return {
            "available": False,
            "reason": (
                "this document has no law-model row yet; it is recorded on the next "
                "tracking pass, and until then there are no provisions to compare"
            ),
        }
    order = [
        key
        for (key,) in db.query(LawRevision.lane_key)
        .filter(LawRevision.document_id == doc.id, LawRevision.lane_key.isnot(None))
        .order_by(LawRevision.observed_at.asc(), LawRevision.id.asc())
        .all()
    ]
    try:
        from src.law.analytics import provision_timeline
        from src.versioned.store import lane_session

        with lane_session("law") as lane:
            payload = provision_timeline(lane, lane_key, revision_order=order)
    except Exception:  # noqa: BLE001 - the lane is an addition; a GET must not 500 on it
        _LOG.debug("law provision timeline unavailable for %s", document_id, exc_info=True)
        return {"available": False, "reason": "the law lane could not be read on this install"}
    payload["available"] = True
    return payload


@router.get("/amendment-velocity")
def law_amendment_velocity(
    period: Annotated[str, Query(pattern="^(month|year)$")] = "month",
    db: Session = Depends(get_db),
) -> dict:
    """Analytic 2 (Q914 = a): captured versions per jurisdiction per period.

    NOT a legislative rate, and the payload says so: the caveat travels with the numbers
    and ``tracked_documents`` is returned per jurisdiction as the denominator a reader
    would need — which this endpoint deliberately does not divide by.
    """
    from src.law.analytics import amendment_velocity

    return amendment_velocity(db, period=period)


@router.get("/documents/{document_id}/view", response_class=HTMLResponse)
def view_law_document(
    document_id: int,
    version: Annotated[int | None, Query(description="A LawRevision id to display instead of the current text.")] = None,
    db: Session = Depends(get_db),
):
    """Render the locally-stored copy of a tracked law as a clean reading page.

    Shows the CURRENT text with a version selector, plus the full amendment timeline
    (each change as a coloured diff), and links back to the official gazette as an
    explicit, confirmed external action. A research mirror, never the authoritative
    source — nothing here is legal advice, and the text is whatever we captured, not a
    live consolidation unless ``consolidated`` says so.

    L0 DEFECT 1 (Q917), AND WHY IT WAS WORTH A RULING. This page rendered
    ``doc.baseline_text`` — the FIRST snapshot ever taken — under a heading carrying the
    document's title, with every later amendment shown only as a diff underneath. So a
    reader of a much-amended Act was shown the superseded text as *the law*, and the
    materialised current text (``latest_text``, written by the tracker since the
    versioned-sources ruling) was read by nothing. The failure direction is the bad one:
    an out-of-date statute is plausible, complete and wrong, where an empty page would at
    least have announced itself.

    ``?version=<revision id>`` shows one stored past version instead. A revision that
    carries no stored text REFUSES by name rather than falling through to another
    version's text — showing the wrong version's words under the right version's date is
    the same defect this endpoint is being fixed for, one level down.
    """
    import html as _html

    from src.utils.security import safe_href

    doc = db.query(LawDocument).filter_by(id=document_id).first()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    revs = (
        db.query(LawRevision)
        .filter_by(document_id=doc.id)
        .order_by(LawRevision.observed_at.desc(), LawRevision.id.desc())
        .all()
    )

    shown, text, shown_note = _selected_version(doc, revs, version)
    paras = (
        "".join(f"<p>{_html.escape(line)}</p>" for line in (text or "").split("\n") if line.strip())
        or f"<p class='muted'>{_html.escape(shown_note or 'No text captured yet — track this document to store a snapshot.')}</p>"
    )
    # Read ONCE, before anything that renders it: two reads could return two answers
    # if a concurrent pass rewrote the row between them, and a page showing one
    # document's licence beside another's language group is the failure this whole
    # model is shaped to avoid.
    lane = _lane_meta(doc)
    version_picker = _version_picker(doc, revs, shown, _html.escape)
    rev_items = []
    for r in revs:
        when = r.observed_at.strftime("%Y-%m-%d %H:%M") if r.observed_at else "—"
        # The first capture is the BASELINE, not an amendment: a 0-byte row
        # labelled as a change confused the live test — say what it is.
        if not r.diff and not (r.delta_bytes or 0):
            rev_items.append(
                f"<details class='rev'><summary>{when} · <span>baseline captured "
                f"(the reference text — amendments are measured against it)</span></summary>"
                f"<div class='basis'>{_html.escape(_BASIS_WORDS.get(r.diff_basis or '', _BASIS_UNRECORDED))}</div>"
                f"<div class='diff'><div class='muted'>No change: this is the first "
                f"snapshot.</div></div></details>"
            )
            continue
        delta = f"{'+' if (r.delta_bytes or 0) > 0 else ''}{r.delta_bytes or 0} bytes"
        flags = (
            f" · <span class='flag'>{_html.escape(r.flag_reasons or 'flagged')}</span>"
            if r.flagged
            else ""
        )
        # The anchor the byte figure and the diff were measured against. A history that
        # mixes baseline-anchored rows (recorded before Q917) with previous-anchored ones
        # is showing two quantities under one heading, so every row says which it is.
        basis = _BASIS_WORDS.get(r.diff_basis or "", _BASIS_UNRECORDED)
        rev_items.append(
            f"<details class='rev'><summary>{when} · {delta}{flags}</summary>"
            f"<div class='basis'>{_html.escape(basis)}</div>"
            f"<div class='diff'>{_diff_to_html(r.diff, _html.escape)}</div></details>"
        )
    # Q908 = a: one document identity, N language versions "aligned by identity". This is
    # the LINK half of it. The reader's language SWITCH is 0.5 (S05-07), so this lists the
    # other versions and says what they are rather than pretending to be a switcher.
    #
    # Each entry is three separate elements -- the language tag, the title, the kind --
    # because the walker translates a text node only when it matches a key exactly, and a
    # line reading "fr · Loi … · official translation" matches nothing in any locale.
    siblings_html = ""
    if lane is not None and lane.siblings:
        items = "".join(
            f"<li><span class='lang'>{_html.escape(language)}</span> "
            + (
                f"<a href='{_html.escape(safe_href(url) or '')}' class='ext'>{_html.escape(title or url)}</a>"
                if url
                else f"<span>{_html.escape(title)}</span>"
            )
            + "</li>"
            for language, title, url in lane.siblings
        )
        siblings_html = (
            "<section class='versions langs'><h2>Other language versions</h2>"
            f"<ul>{items}</ul>"
            "<p class='muted'>Each language version is tracked as its own document, with "
            "its own history. They are the same law, aligned by identity.</p></section>"
        )

    revs_html = (
        ("<section class='history'><h2>Amendment history</h2>" + "".join(rev_items) + "</section>")
        if rev_items
        else ""
    )

    def _row(label: str, value: str | None) -> str:
        return f"<div class='mrow'><span>{label}</span><b>{value}</b></div>" if value else ""

    official = safe_href(doc.official_url or doc.url)
    meta_rows = "".join(
        [
            _row("Jurisdiction", _html.escape((doc.jurisdiction or "").upper())),
            _row("Category", _html.escape(doc.category or "")),
            # The Chromium click-through of this block (2026-09-18, en/fr/de/ar) caught
            # three of its labels rendering in English under every locale. Two were simply
            # unkeyed; this one ALSO could not safely become a key, because the i18n walker
            # matches a text node EXACTLY and a bare "Text" would then translate every
            # element anywhere in the app whose whole content is that word. The label is
            # renamed to what the row actually says -- which KIND of text is stored -- so it
            # is both unambiguous to a reader and safe as a key. Its two values are phrases
            # this page itself emits (not stored data), so they are keyed as well; `_row`
            # puts label and value in separate elements, which is what lets each translate.
            _row(
                "Text kind",
                "point-in-time consolidation" if doc.consolidated else "raw captured fetch",
            ),
            _row(
                "Last checked",
                _html.escape(doc.last_checked_at.strftime("%Y-%m-%d %H:%M"))
                if doc.last_checked_at
                else None,
            ),
            _row("Last status", _html.escape(doc.last_status) if doc.last_status else None),
            _row("Changes recorded", str(len(revs)) if revs else None),
            # L0 defect 3 (Q917): the adapter's three dates, each shown only where it is
            # known, and each labelled with what it MEANS. "Published 2026-07-31" for a
            # 2018 Act was the maintainer's original complaint, and it came from one field
            # standing in for three. `retrieved_on` is composed from the revision's own
            # `observed_at` rather than stored twice — the label says so.
            _row("Enacted", _html.escape(doc.enacted_on) if doc.enacted_on else None),
            _row("This text is in force from", _in_force_cell(shown, revs, _html.escape)),
            _row(
                "Captured by this instance",
                _html.escape(_retrieved_on(doc, shown, revs) or "") or None,
            ),
            _row("Showing", _shown_cell(doc, shown, _html.escape)),
            # The law model's block (Q927's licence, Q901's provenance, Q908's identity).
            # Absent rather than empty when `law.db` has nothing for this document: a row
            # reading "Licence: —" states that we looked and found none, which is a
            # different fact from never having recorded one.
            _row(
                "Licence",
                (
                    f"<a class='ext' href='{_html.escape(lane.licence_url)}' "
                    f"rel='noopener noreferrer'>{_html.escape(lane.licence_name)}</a>"
                    if (lane is not None and lane.licence_url)
                    else (_html.escape(lane.licence_name) if lane is not None else None)
                ),
            ),
            _row(
                "Redistribution",
                _html.escape(_REDISTRIBUTION_WORDS.get(lane.redistribution, lane.redistribution))
                if lane is not None
                else None,
            ),
            # The phrase and the body are SEPARATE elements: the walker translates a text
            # node only when it matches a key exactly, so a body name inside the sentence
            # would freeze the whole line in English.
            _row(
                "Provenance",
                (
                    f"<span>{_html.escape(lane.provenance)}</span>"
                    + (f" <span class='muted'>({_html.escape(lane.provenance_body)})</span>"
                       if lane.provenance_body else "")
                )
                if lane is not None
                else None,
            ),
            _row("Identity", _html.escape(lane.identity) if (lane and lane.identity) else None),
        ]
    )
    # The footer used to read "Captured snapshot — it does not change if the official text
    # is later amended", which was true of the baseline this page used to show and became
    # FALSE the moment it started showing the current text. A sentence about what the
    # reader is looking at has to be derived from what is on screen, or it is a fabricated
    # caveat pointing the wrong way.
    footer_line = (
        "This is the newest text this instance captured — not a live consolidation. It "
        "moves when a later capture finds the official text amended (each change is shown "
        "above)."
        if shown is None
        else "A stored past version. The current captured text is the first entry in the "
        "version list above."
    )
    title = _html.escape(doc.title or "(untitled)")
    official_html = (
        f"<a class='ext src-link' href='{_html.escape(official)}' rel='noopener noreferrer'>Open the official gazette ↗</a>"
        if official
        else "<span class='muted'>No official (http/https) URL recorded.</span>"
    )

    doc_html = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><style>
  :root {{ color-scheme: light dark; --paper:#0e1116; --fg:#e7e9ee; --mut:#8b93a1; --line:#222833;
    --accent:#5ea0ff; --card:#141923; --add:#2ea043; --del:#f85149; --warn:#f0a23a; }}
  @media (prefers-color-scheme: light) {{ :root {{ --paper:#faf8f4; --fg:#1a1d22; --mut:#6b7280;
    --line:#e4e0d8; --card:#fff; --accent:#2b6cd4; }} }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--paper); color:var(--fg); font:17px/1.7 Georgia,'Times New Roman',serif; }}
  .wrap {{ max-width:820px; margin:0 auto; padding:28px 22px 80px; }}
  .crumb {{ font:12px/1.4 system-ui,sans-serif; color:var(--mut); margin-bottom:16px; }}
  h1 {{ font-size:27px; line-height:1.25; margin:0 0 14px; }}
  .meta {{ font:13px/1.6 system-ui,sans-serif; background:var(--card); border:1px solid var(--line);
    border-radius:10px; padding:10px 14px; margin:0 0 22px; }}
  .mrow {{ display:flex; justify-content:space-between; gap:14px; padding:3px 0; border-top:1px solid var(--line); }}
  .mrow:first-child {{ border-top:0; }} .mrow span {{ color:var(--mut); }} .mrow b {{ font-weight:600; text-align:right; }}
  article p {{ margin:0 0 1.05em; }} .muted {{ color:var(--mut); }}
  .history, .versions {{ margin-top:30px; }}
  .versions ol {{ list-style:none; margin:0; padding:0; font:13px/1.9 system-ui,sans-serif; }}
  .versions li {{ border-top:1px solid var(--line); padding:4px 0; }}
  .versions li:first-child {{ border-top:0; }}
  a.vsel.on {{ font-weight:700; }}
  .now {{ font:11px system-ui,sans-serif; color:var(--mut); }}
  .vnote {{ font:12px/1.6 system-ui,sans-serif; margin:8px 0 0; }}
  .basis {{ font:12px/1.5 system-ui,sans-serif; color:var(--mut); padding:2px 12px 6px; }}
  .history h2, .versions h2, .src-h {{ font:600 14px system-ui,sans-serif; color:var(--mut); text-transform:uppercase;
    letter-spacing:.04em; margin:0 0 10px; }}
  details.rev {{ border:1px solid var(--line); border-radius:8px; margin-bottom:7px; background:var(--card); }}
  details.rev summary {{ cursor:pointer; padding:8px 12px; font:13px system-ui,sans-serif; }}
  .flag {{ color:var(--warn); font-weight:600; }}
  .diff {{ font:12px/1.5 ui-monospace,Menlo,Consolas,monospace; padding:6px 0; border-top:1px solid var(--line); overflow:auto; }}
  .dl {{ padding:0 12px; white-space:pre-wrap; }}
  .dl.add {{ background:color-mix(in srgb,var(--add) 16%,transparent); }}
  .dl.del {{ background:color-mix(in srgb,var(--del) 16%,transparent); }}
  .dl.ctx {{ color:var(--mut); }}
  a {{ color:var(--accent); }}
  footer {{ margin-top:34px; padding-top:18px; border-top:1px solid var(--line);
    font:13px/1.6 system-ui,sans-serif; color:var(--mut); }}
  .src-link {{ display:inline-block; margin-top:6px; font-weight:600; }}
  .vp {{ }} .vd {{ color:var(--mut); font-variant-numeric:tabular-nums; }}
</style>
<!-- The i18n engine, as the ARTICLE reader already loads it. This page is served
     standalone (its own browser tab, not the SPA), and until 2026-09-18 it loaded
     nothing, so every word on it was English whatever the operator's UI language —
     on a surface whose whole job is a legal text. The walker matches a text node
     EXACTLY, which is why every phrase this page emits is in its own element with
     the dates and byte counts beside it as data. -->
<script src="/static/i18n.js" defer></script>
</head><body>
<div class="wrap">
  <div class="crumb">Open Omniscience · World law · offline stored copy — a research mirror, not legal advice</div>
  <article><h1>{title}</h1><div class="meta">{meta_rows}</div>{paras}</article>
  {version_picker}
  {siblings_html}
  {revs_html}
  <footer>
    {footer_line}
    <div style="margin-top:8px">{official_html}</div>
    <div style="font-size:12px">Opening the gazette makes a live request from your machine; you'll be asked to confirm.</div>
  </footer>
</div>
<script>
  document.addEventListener('click', function(e){{
    var a = e.target.closest && e.target.closest('a.ext');
    if(!a) return; e.preventDefault();
    var t = (window.OOI18N && OOI18N.t) ? OOI18N.t : function(x){{ return x; }};
    if(window.confirm(t("Open the official source on the public web?") + "\\n\\n" + a.href +
      "\\n\\n" + t("This leaves your local copy and makes a live request from your machine — the site may see your visit. Continue?")))
      window.open(a.href, '_blank', 'noopener');
  }});
</script>
</body></html>"""
    return HTMLResponse(content=doc_html)
