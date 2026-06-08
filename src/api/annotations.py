"""
Annotations API: author, sign/export, import, web-of-trust, transparent aggregation.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

All local — no server, no accounts. Export produces a signed, portable bundle; import
verifies a bundle before storing it (an invalid one is refused, loudly); aggregation
returns *who asserted what* for a source, never a consensus number.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.annotations import store

router = APIRouter(prefix="/api/annotations", tags=["annotations"])


class NewAnnotation(BaseModel):
    target: str
    kind: str
    value: str
    note: str = ""


class AuthorName(BaseModel):
    name: str


class TrustUpdate(BaseModel):
    author_id: str
    trusted: bool = True


class ImportBody(BaseModel):
    bundle: dict
    trusted: bool = True


@router.get("/mine")
def get_mine() -> dict:
    """Your authored annotations."""
    return store.load_mine()


@router.post("/mine")
def add_mine(body: NewAnnotation) -> dict:
    """Add one annotation to your authored set."""
    try:
        return store.add_annotation(body.target, body.kind, body.value, body.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/mine/{index}")
def remove_mine(index: int) -> dict:
    """Remove one of your annotations by index."""
    return store.remove_annotation(index)


@router.put("/mine/author")
def set_author(body: AuthorName) -> dict:
    """Set the author name that ships in your exported bundles."""
    return store.set_author_name(body.name)


@router.get("/export")
def export() -> dict:
    """A signed, portable bundle of your authored annotations."""
    return store.export_bundle()


@router.post("/import")
def import_bundle(body: ImportBody) -> dict:
    """Verify and store an imported bundle (refused if the signature fails)."""
    try:
        return store.import_bundle(body.bundle, trusted=body.trusted)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/authors")
def authors() -> dict:
    """Imported authors and their trust flags (the web-of-trust)."""
    return {"authors": store.list_authors()}


@router.put("/authors/trust")
def trust(body: TrustUpdate) -> dict:
    """Trust or untrust an imported author."""
    if not store.set_trusted(body.author_id, body.trusted):
        raise HTTPException(status_code=404, detail="author not found")
    return {"author_id": body.author_id, "trusted": body.trusted}


@router.delete("/authors/{author_id}")
def remove_author(author_id: str) -> dict:
    """Remove an imported author and all their annotations."""
    if not store.remove_author(author_id):
        raise HTTPException(status_code=404, detail="author not found")
    return {"removed": author_id}


@router.get("/for")
def for_target(target: str) -> dict:
    """Transparent aggregation of annotations about a source (who asserted what)."""
    return store.aggregate_for_target(target)
