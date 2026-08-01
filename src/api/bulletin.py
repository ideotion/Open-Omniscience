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
    db: Session = Depends(get_db),
) -> dict:
    """Build one edition over a closed period and (by default) persist it.

    The result is a DRAFT. Automation reaches a draft and stops: the operator is
    the byline, so nothing here publishes anything.

    Layer A only for now — deterministic counts with their methods. The document
    is regenerated FROM the persisted record rather than edited, which is what
    makes re-rendering or toggling a producer unable to change a number.
    """
    from src.bulletin.facts import layer_a
    from src.bulletin.period import resolve_period
    from src.bulletin.store import persist_edition

    gate = _require_gate()
    try:
        period = resolve_period(cadence)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    edition = layer_a(db, period)
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
