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


@router.get("/editions/{filename}/render")
def render_edition(
    filename: str,
    fmt: str = Query("html", description="html | markdown"),
    exclude_sections: str = Query("", description="comma-separated section keys to leave out"),
    exclude_stories: str = Query("", description="comma-separated story keys to leave out"),
):
    """Render a persisted edition as a self-contained page or as Markdown.

    Rendering is PURE: the numbers come from the record, so re-rendering cannot
    change one. That is what makes toggling a producer a re-render rather than a
    re-computation, and it is why exclusions are applied HERE rather than written
    back — output is never hand-edited.

    An exclusion is stated in the rendered document. The operator chooses what to
    publish, but a reader of a document that silently omits three of its seven
    sections has no way to know they are reading a selection.

    Published output carries EXTERNAL identity only — a local article id resolves
    to a different article on a recipient's install, so it never leaves here.
    """
    from fastapi.responses import HTMLResponse, PlainTextResponse

    from src.bulletin.render import render
    from src.bulletin.review import apply_selection
    from src.bulletin.store import read_edition

    _require_gate()
    try:
        edition = read_edition(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="no such edition") from exc

    edition = apply_selection(edition, **_selection(exclude_sections, exclude_stories))

    try:
        text = render(edition, fmt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    stem = filename.rsplit(".", 1)[0]
    if (fmt or "").strip().lower() == "html":
        return HTMLResponse(
            text, headers={"Content-Disposition": f'inline; filename="{stem}.html"'}
        )
    return PlainTextResponse(
        text,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{stem}.md"'},
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
