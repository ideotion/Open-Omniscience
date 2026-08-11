"""
The Bulletin API — generate, list, read and remove persisted editions.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Design record §2 (this namespace), §9 (the edition is the record), §13 (draft →
published; automation reaches a DRAFT, never a publication — the operator is the
byline).

LOCAL by construction: generating an edition reads the corpus and writes one JSON
file under data_dir. No network, so no consent gate. Layer A involves no model at
all; the narration layer, when it lands, runs on loopback.

Every route is gated on the same hardware predicate as the rest of the feature
(§3) — the gate reports its own reason and the standing override reveals it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.database.session import get_db

router = APIRouter(prefix="/api/bulletin", tags=["bulletin"])


def _require_gate() -> dict:
    """The hardware gate, as a 403 with its reason rather than a bare refusal."""
    from src.bulletin.gate import bulletin_available

    gate = bulletin_available()
    if not gate["available"]:
        raise HTTPException(status_code=403, detail=gate)
    return gate


@router.get("/availability")
def availability() -> dict:
    """Whether the Bulletin is available on this machine, and why.

    Deliberately NOT gated — a surface asking "should I draw this?" must get an
    answer, and the answer is the refusal itself. This is the one route that
    reports the gate instead of enforcing it.
    """
    from src.bulletin.gate import bulletin_available

    return bulletin_available()


@router.post("/generate")
def generate(
    cadence: str = Query("weekly", description="daily | weekly | monthly | trimester | semester | yearly"),
    persist: bool = Query(True, description="write the edition to disk"),
    narrate: bool = Query(False, description="add the removable narration layer"),
    db: Session = Depends(get_db),
) -> dict:
    """Build one edition over a closed period and (by default) persist it.

    The result is a DRAFT. Automation reaches a draft and stops: the operator is
    the byline, so nothing here publishes anything.

    Narration is OFF by default. With it off the edition is Layer A exactly —
    deterministic counts with their methods. With it on the same document gains a
    story block and a narration block, and nothing already there changes: that
    asymmetry is what makes the layer removable in practice rather than in a
    docstring.

    The document is regenerated FROM the persisted record rather than edited,
    which is what makes re-rendering or toggling a producer unable to change a
    number.
    """
    from src.bulletin.edition import build_edition
    from src.bulletin.period import resolve_period
    from src.bulletin.store import persist_edition

    gate = _require_gate()
    try:
        period = resolve_period(cadence)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    edition = build_edition(db, period, narrate=narrate)
    edition["gate"] = gate
    if persist:
        try:
            path = persist_edition(edition, period)
            edition["filename"] = path.name
            edition["persisted"] = True
        except OSError as exc:
            # A generated edition that could not be written is still a real answer:
            # return it with the failure stated rather than losing the work to a 500.
            edition["persisted"] = False
            edition["persist_error"] = f"{type(exc).__name__}: {exc}"
    else:
        edition["persisted"] = False
    return edition


@router.get("/editions")
def editions() -> dict:
    """Every persisted edition, newest covered period first."""
    from src.bulletin.store import list_editions

    _require_gate()
    rows = list_editions()
    return {
        "editions": rows,
        "count": len(rows),
        "method": "one JSON file per edition under data_dir()/bulletin/editions",
        "caveat": (
            "Editions ride the encrypted backup and are restored additively — an "
            "existing local edition is never overwritten by an imported one."
        ),
    }


@router.get("/editions/{filename}")
def edition(filename: str) -> dict:
    """One persisted edition, by its exact filename."""
    from src.bulletin.store import read_edition

    _require_gate()
    try:
        return read_edition(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="no such edition") from exc
    except ValueError as exc:  # malformed JSON on disk — say so, never return {}
        raise HTTPException(status_code=500, detail=f"edition unreadable: {exc}") from exc


@router.get("/editions/{filename}/review")
def review(filename: str) -> dict:
    """The edition as a set of decisions, with the evidence for each.

    Per §13 this shows, per sentence, whether it passed validation or fell back
    to a template — a sentence the operator can SEE was checked is a different
    thing from a paragraph labelled "validated".

    Read-only. Deciding happens by re-rendering with exclusions, never by editing
    the record.
    """
    from src.bulletin.review import review_view
    from src.bulletin.store import read_edition

    _require_gate()
    try:
        return review_view(read_edition(filename))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="no such edition") from exc


def _selection(exclude_sections: str, exclude_stories: str) -> dict:
    """Parse the operator's exclusions from two comma-separated query params."""
    return {
        "exclude_sections": [s for s in (exclude_sections or "").split(",") if s.strip()],
        "exclude_stories": [s for s in (exclude_stories or "").split(",") if s.strip()],
    }


@router.get("/editions/{filename}/ai-plan")
def ai_plan(
    filename: str,
    target_lang: str = Query("", description="also plan translating the named articles into this"),
    per_call_s: float = Query(
        0.0, description="seconds per model call MEASURED on this machine; 0 = unknown"
    ),
    concurrency: int = Query(1, ge=1, le=16, description="lanes the backend would run"),
) -> dict:
    """Phase 2, as a plan: what a local model would be asked to do for this edition.

    The maintainer's two-phase design puts this AFTER phase 1 exists — "an option
    appearing after phase 1 has been produced" — so it is computed from the
    persisted record rather than offered before there is anything to enhance. It is
    a read: pure arithmetic over the edition dict, no model, no DB, nothing started.

    ``per_call_s`` must be MEASURED on this machine (Settings → Advanced →
    Diagnostics → the LLM latency bench). Without it the plan reports the exact
    call count and refuses a duration, which is the honest answer on hardware
    nothing has timed.
    """
    from src.bulletin.store import read_edition
    from src.bulletin.worklist import ai_worklist

    _require_gate()
    try:
        edition = read_edition(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="no such edition") from exc
    return ai_worklist(
        edition,
        target_lang=target_lang or None,
        per_call_s=per_call_s or None,
        concurrency=concurrency,
    )


@router.get("/editions/{filename}/render")
def render_edition(
    filename: str,
    fmt: str = Query("html", description="html | markdown"),
    exclude_sections: str = Query("", description="comma-separated section keys to leave out"),
    exclude_stories: str = Query("", description="comma-separated story keys to leave out"),
    include_plan: bool = Query(False, description="append the phase-2 plan to the document"),
    target_lang: str = Query("", description="with include_plan: also plan translations"),
    lang: str = Query("en", description="the language to WRITE the document in"),
):
    """Render a persisted edition as a self-contained page or as Markdown.

    EVERY FIGURE COMES FROM THE RECORD, so re-rendering cannot change one. That is
    what makes toggling a producer a re-render rather than a re-computation, and it is
    why exclusions are applied HERE rather than written back — output is never
    hand-edited. The one thing rendering adds is the reference numbering, stamped onto
    the in-memory copy read from disk; it is deterministic and goes nowhere near the
    file.

    An exclusion is stated in the rendered document. The operator chooses what to
    publish, but a reader of a document that silently omits three of its seven
    sections has no way to know they are reading a selection.

    Published output carries EXTERNAL identity only — a local article id resolves
    to a different article on a recipient's install, so it never leaves here.

    ``include_plan`` appends phase 2 as a PLAN, clearly labelled as one. It takes no
    ``per_call_s``, deliberately: a duration is a measurement of THIS machine, and a
    rendered document travels — a recipient reading "about twelve minutes" would read
    it as a property of the work rather than of somebody else's hardware. The call
    count is exact and hardware-independent, so that is what the document states. The
    JSON route above is where a measured duration belongs, because it answers to the
    operator sitting in front of the machine it was measured on.
    """
    from fastapi.responses import HTMLResponse, PlainTextResponse

    from src.bulletin.i18n import Translator
    from src.bulletin.render import render
    from src.bulletin.review import apply_selection
    from src.bulletin.store import read_edition

    _require_gate()
    try:
        edition = read_edition(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="no such edition") from exc

    edition = apply_selection(edition, **_selection(exclude_sections, exclude_stories))

    if include_plan:
        # AFTER the selection, never before: the plan describes the work for the
        # document as it will be published, so a section the operator excluded must
        # not appear in it as work to do. In memory only — the plan is derived FROM
        # the record and never becomes part of it.
        from src.bulletin.worklist import ai_worklist

        edition["ai_worklist"] = ai_worklist(edition, target_lang=target_lang or None)

    # ONE translator for the whole document, so its report describes exactly this
    # render. A locale with no catalog is not an error: the document comes out in
    # English and says at the top that it did, which is a better answer than refusing
    # to produce a bulletin over a missing translation.
    tr = Translator(lang)
    try:
        text = render(edition, fmt, tr=tr)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # The DOWNLOADED name is the report's own, not the record's: the record is
    # `20260810-OOS-weekly-<id>.json` and the document an operator keeps is
    # `20260811_OOS_Bulletin_Weekly.md` — the day the bulletin was created, matching
    # the annexes ZIP beside it.
    stem = _bundle_stem(edition, filename)
    # The language and its coverage travel as headers too, so a caller learns what it
    # got without parsing the prose — and so a UI can say "written in French, 142 of
    # 180 sentences" rather than leaving the operator to notice the English.
    rep = tr.report()
    lang_headers = {
        "X-OO-Language": rep["language"],
        "X-OO-Language-Translated": str(rep["translated"]),
        "X-OO-Language-Strings": str(rep["strings_seen"]),
    }
    if (fmt or "").strip().lower() == "html":
        return HTMLResponse(
            text,
            headers={"Content-Disposition": f'inline; filename="{stem}.html"', **lang_headers},
        )
    return PlainTextResponse(
        text,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{stem}.md"', **lang_headers},
    )


def _ordinal(edition: dict, filename: str) -> int:
    """Which bulletin of its creation day this is.

    ``list_editions()`` reads the filename for the cadence but the creation date lives
    INSIDE each record, so the siblings' ``generated_at`` has to be read. Only the
    same-cadence editions are opened: nothing else can share a stem, so nothing else
    can affect the position. That keeps a click-time read bounded to the editions that
    could actually collide rather than to the whole directory.
    """
    from src.bulletin.annexes import edition_ordinal
    from src.bulletin.store import list_editions, read_edition

    mine = str((edition.get("period") or {}).get("cadence") or "").strip().lower()
    siblings: list[dict] = []
    for row in list_editions():
        name = row.get("filename")
        if not name or str(row.get("cadence") or "").lower() != mine:
            continue
        try:
            rec = edition if name == filename else read_edition(name)
        except (FileNotFoundError, ValueError):
            # An unreadable sibling cannot be named either, so it cannot occupy a
            # position. Skipped rather than guessed at.
            continue
        siblings.append(
            {
                "filename": name,
                "cadence": mine,
                "generated_at": rec.get("generated_at"),
            }
        )
    return edition_ordinal(filename, siblings)


def _bundle_stem(edition: dict, filename: str) -> str:
    from src.bulletin.annexes import bundle_stem

    return bundle_stem(edition, ordinal=_ordinal(edition, filename))


@router.get("/editions/{filename}/annexes")
def annexes(
    filename: str,
    full_text: bool = Query(True, description="carry each article's whole stored text"),
    exclude_sections: str = Query("", description="the same selection the report was rendered with"),
    exclude_stories: str = Query(""),
    lang: str = Query("en", description="the language the REPORT was written in"),
    db: Session = Depends(get_db),
):
    """The report's annexes as a ZIP: one Markdown file per cited article, plus a
    contents page.

    THE SELECTION MUST MATCH THE REPORT. The reference numbers are assigned over the
    document as it will be published, so a bundle built without the operator's
    exclusions would number a different set — `[0007]` in the report would open the
    wrong article, which is worse than no annexes at all. The same two query params
    the render route takes are therefore taken here, and the frontend sends both to
    both.

    This is NOT the evidence archive. That one writes every article in the period to
    a directory on this machine so the counts can be recomputed, and is measured in
    gigabytes. This is the citation set of one document, small enough to download.
    """
    from fastapi.responses import Response

    from src.bulletin.annexes import build_annexes
    from src.bulletin.review import apply_selection
    from src.bulletin.store import read_edition

    _require_gate()
    try:
        edition = read_edition(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="no such edition") from exc

    ordinal = _ordinal(edition, filename)
    edition = apply_selection(edition, **_selection(exclude_sections, exclude_stories))
    # ``lang`` is the language the REPORT was written in. The annexes are English, so
    # passing it through is not a translation — it is what lets the contents page SAY
    # the two differ instead of leaving a reader to wonder whether something broke.
    out = build_annexes(
        db, edition, ordinal=ordinal, full_text=bool(full_text), report_lang=lang
    )
    return Response(
        content=out["data"],
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{out["filename"]}"',
            # The counts a caller cannot read out of a binary body, so a UI can say
            # what it just handed the operator instead of only that it finished.
            "X-OO-Annex-Articles": str(out["articles"]),
            "X-OO-Annex-Files": str(out["files"]),
        },
    )


@router.post("/editions/{filename}/publish")
def publish(
    filename: str,
    exclude_sections: str = Query(""),
    exclude_stories: str = Query(""),
) -> dict:
    """Mark an edition published, recording the operator's selection with it.

    §13: automation reaches a DRAFT and stops. This route is the operator's act —
    it is what makes them the byline rather than the machine.

    The stamp APPENDS to the edition's state history rather than overwriting it,
    so an edition published, revised and republished can still say what happened
    and when. The selection is recorded alongside, because "what was published" is
    not answerable from a document showing only what survived it.
    """
    from src.bulletin.review import apply_selection
    from src.bulletin.store import mark_published, read_edition

    _require_gate()
    sel = _selection(exclude_sections, exclude_stories)
    try:
        edition = read_edition(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="no such edition") from exc

    recorded = (apply_selection(edition, **sel)).get("selection") or {}
    recorded.update(sel)
    try:
        out = mark_published(filename, selection=recorded)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="no such edition") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"could not stamp the edition: {exc}") from exc
    return {
        "filename": filename,
        "state": out.get("state"),
        "published_at": out.get("published_at"),
        "state_history": out.get("state_history") or [],
        "selection": recorded,
    }


@router.post("/evidence/plan")
def evidence_plan_route(
    cadence: str = Query("weekly"),
    dest: str = Query("", description="destination directory on THIS machine"),
    db: Session = Depends(get_db),
) -> dict:
    """What an evidence archive for this period would contain — before writing it.

    The article count is exact; the size is an estimate and says so. This step
    exists because the archive holds the period's articles in full, which can be
    large, and because it is PLAINTEXT leaving an encrypted store — a decision the
    operator makes with the real numbers in front of them, not after the fact.
    """
    from src.bulletin.evidence import evidence_plan
    from src.bulletin.period import resolve_period

    _require_gate()
    try:
        period = resolve_period(cadence)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return evidence_plan(db, period, dest=dest or None)


@router.post("/evidence/build")
def evidence_build_route(
    cadence: str = Query("weekly"),
    dest: str = Query(..., description="destination directory on THIS machine"),
    edition_file: str = Query("", description="an existing edition; omit to build a fresh one"),
    db: Session = Depends(get_db),
) -> dict:
    """Write the evidence archive to a directory on this machine.

    Server-side destination, never a browser download: the archive can be the size
    of a period of the corpus, which is not something to push through a tab. Same
    shape as the large-data folder backup, for the same reason.
    """
    from src.bulletin.evidence import build_evidence_archive
    from src.bulletin.facts import layer_a
    from src.bulletin.period import resolve_period
    from src.bulletin.store import read_edition

    _require_gate()
    try:
        period = resolve_period(cadence)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if edition_file:
        try:
            edition = read_edition(edition_file)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="no such edition") from exc
    else:
        edition = layer_a(db, period)

    try:
        return build_evidence_archive(db, edition, period, dest)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"could not write the archive: {exc}") from exc


@router.delete("/editions/{filename}")
def remove_edition(filename: str) -> dict:
    """Delete one persisted edition.

    An edition is a record, so removing one is the operator's call and nothing
    else's — no retention policy prunes them behind your back.
    """
    from src.bulletin.store import delete_edition

    _require_gate()
    if not delete_edition(filename):
        raise HTTPException(status_code=404, detail="no such edition")
    return {"deleted": filename}
