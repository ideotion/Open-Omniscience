"""
World-law API: tracked legal documents, change feed, and on-demand tracking.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Read endpoints list tracked documents (coverage by jurisdiction) and the flagged-change
feed; ``track`` fetches watched documents now through the ethical fetcher. A research
mirror, never legal advice — every record links back to its official source.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

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
    by_jur = dict(
        db.query(LawDocument.jurisdiction, func.count(LawDocument.id))
        .group_by(LawDocument.jurisdiction)
        .all()
    )
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
        q = q.filter(LawDocument.jurisdiction == jurisdiction)
    docs = q.order_by(LawDocument.jurisdiction, LawDocument.id).all()
    rev_counts = dict(
        db.query(LawRevision.document_id, func.count(LawRevision.id))
        .group_by(LawRevision.document_id)
        .all()
    )
    flag_counts = dict(
        db.query(LawRevision.document_id, func.count(LawRevision.id))
        .filter_by(flagged=True)
        .group_by(LawRevision.document_id)
        .all()
    )
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


def _diff_to_html(diff: str, _esc) -> str:
    """Colourise a stored unified diff (+ added / - removed) for the reader."""
    rows = []
    for ln in (diff or "").splitlines():
        cls = "add" if ln[:1] == "+" else ("del" if ln[:1] == "-" else "ctx")
        rows.append(f"<div class='dl {cls}'>{_esc(ln)}</div>")
    return "".join(rows) or "<div class='muted'>(no textual diff recorded)</div>"


@router.get("/documents/{document_id}/view", response_class=HTMLResponse)
def view_law_document(document_id: int, db: Session = Depends(get_db)):
    """Render the locally-stored copy of a tracked law as a clean reading page.

    Shows the captured baseline text plus the full amendment timeline (each change
    as a coloured diff), and links back to the official gazette as an explicit,
    confirmed external action. A research mirror, never the authoritative source —
    nothing here is legal advice, and the text is whatever we captured, not a live
    consolidation unless ``consolidated`` says so.
    """
    import html as _html

    from src.utils.security import safe_href

    doc = db.query(LawDocument).filter_by(id=document_id).first()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    text = doc.baseline_text or ""
    paras = (
        "".join(f"<p>{_html.escape(line)}</p>" for line in text.split("\n") if line.strip())
        or "<p class='muted'>No baseline text captured yet — track this document to store a snapshot.</p>"
    )

    revs = (
        db.query(LawRevision)
        .filter_by(document_id=doc.id)
        .order_by(LawRevision.observed_at.desc())
        .all()
    )
    rev_items = []
    for r in revs:
        when = r.observed_at.strftime("%Y-%m-%d %H:%M") if r.observed_at else "—"
        # The first capture is the BASELINE, not an amendment: a 0-byte row
        # labelled as a change confused the live test — say what it is.
        if not r.diff and not (r.delta_bytes or 0):
            rev_items.append(
                f"<details class='rev'><summary>{when} · baseline captured "
                f"(the reference text — amendments are measured against it)</summary>"
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
        rev_items.append(
            f"<details class='rev'><summary>{when} · {delta}{flags}</summary>"
            f"<div class='diff'>{_diff_to_html(r.diff, _html.escape)}</div></details>"
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
            _row(
                "Text", "point-in-time consolidation" if doc.consolidated else "raw captured fetch"
            ),
            _row(
                "Last checked",
                _html.escape(doc.last_checked_at.strftime("%Y-%m-%d %H:%M"))
                if doc.last_checked_at
                else None,
            ),
            _row("Last status", _html.escape(doc.last_status) if doc.last_status else None),
            _row("Changes recorded", str(len(revs)) if revs else None),
        ]
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
  .history {{ margin-top:30px; }}
  .history h2, .src-h {{ font:600 14px system-ui,sans-serif; color:var(--mut); text-transform:uppercase;
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
</style></head><body>
<div class="wrap">
  <div class="crumb">Open Omniscience · World law · offline stored copy — a research mirror, not legal advice</div>
  <article><h1>{title}</h1><div class="meta">{meta_rows}</div>{paras}</article>
  {revs_html}
  <footer>
    Captured snapshot — it does not change if the official text is later amended (amendments show above).
    <div style="margin-top:8px">{official_html}</div>
    <div style="font-size:12px">Opening the gazette makes a live request from your machine; you'll be asked to confirm.</div>
  </footer>
</div>
<script>
  document.addEventListener('click', function(e){{
    var a = e.target.closest && e.target.closest('a.ext');
    if(!a) return; e.preventDefault();
    if(window.confirm("Open the official source on the public web?\\n\\n" + a.href +
      "\\n\\nThis leaves your local copy and makes a live request from your machine — the site may see your visit. Continue?"))
      window.open(a.href, '_blank', 'noopener');
  }});
</script>
</body></html>"""
    return HTMLResponse(content=doc_html)
