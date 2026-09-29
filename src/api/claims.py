"""The Claim Workspace's one read (gate row K, brief ``S05-11`` S1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``GET /api/claims/workspace?claim=…`` walks the workspace over the local corpus
(:func:`src.analytics.claim_workspace.build_workspace`) and returns the trail: the related
articles, the paths they group into and what joined each one, the trail in publication
order, the corroboration offers (each naming the host it would ask; nothing is fetched
here), and what the corpus holds that the trail is silent on. A trail, never a verdict:
nothing in the payload scores, rates or grades the claim.

``POST /api/claims/trail-bundle`` (step ⑥) walks the SAME trail again on the server and
returns it as a ZIP signed with the custody key (:mod:`src.analytics.claim_bundle`). It
never signs a trail a caller posts: what the signature vouches for is what this install
computed. ``POST /api/claims/trail-bundle/verify`` checks a bundle, offline.

Loopback, no network. Plain ``def`` handlers, so the codec-bound content reads run on the
threadpool, never on the event loop.
"""

from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.analytics.claim_workspace import DEFAULT_TRAIL, MAX_CLAIM_CHARS, MAX_TRAIL, build_workspace
from src.database.session import get_db

router = APIRouter(prefix="/api/claims", tags=["claims"])


@router.get("/workspace")
def claim_workspace(
    claim: str = Query(..., min_length=1, max_length=MAX_CLAIM_CHARS),
    query: str | None = Query(None, max_length=2000),
    limit: int = Query(DEFAULT_TRAIL, ge=1, le=MAX_TRAIL),
    expand: bool = True,
    ui_lang: str | None = Query(None, max_length=10),
    db: Session = Depends(get_db),
) -> dict:
    """The claim's evidence trail: ① related articles (the Search tab's index and grammar;
    a query derived from the claim's words when ``query`` is blank, and the payload says
    which), ② the independence paths with the join that made each, ③ who said what, when,
    ④ the corroboration offers, ⑤ what is missing."""
    try:
        return build_workspace(db, claim, query=query, limit=limit, expand=expand, ui_lang=ui_lang)
    except ValueError as exc:  # an empty claim, or a query the grammar rejects
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class TrailBundleRequest(BaseModel):
    claim: str = Field(..., min_length=1, max_length=MAX_CLAIM_CHARS)
    query: str | None = Field(None, max_length=2000)
    limit: int = Field(DEFAULT_TRAIL, ge=1, le=MAX_TRAIL)
    expand: bool = True
    ui_lang: str | None = Field(None, max_length=10)
    #: Carry each article's stored text (on by default: a recipient can then check the
    #: SHA-256 against the words). Off, each article file carries metadata and the hash.
    full_text: bool = True


#: The largest bundle the verify endpoint reads (bytes). A trail is bounded to MAX_TRAIL
#: articles; this is far above any honest one and keeps a stray upload from filling memory.
MAX_VERIFY_BYTES = 256 * 1024 * 1024


@router.post("/trail-bundle")
def claim_trail_bundle(req: TrailBundleRequest, db: Session = Depends(get_db)) -> dict:
    """Step ⑥: the trail as a signed ZIP (base64 in ``zip_base64``) and what it holds.

    An OSM-derived row rides with OpenStreetMap's credit and the ODbL line (Q823 = a);
    the 409 that refused such a bundle before the ruling is gone."""
    from src.analytics.claim_bundle import build_trail_bundle

    try:
        ws = build_workspace(db, req.claim, query=req.query, limit=req.limit,
                             expand=req.expand, ui_lang=req.ui_lang)
        data, report = build_trail_bundle(db, ws, full_text=req.full_text)
    except ValueError as exc:  # an empty claim or trail, or a query the grammar rejects
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**report, "zip_base64": base64.b64encode(data).decode("ascii")}


@router.post("/trail-bundle/verify")
async def verify_claim_trail_bundle(request: Request) -> dict:
    """Check a trail bundle posted as the raw ZIP body. Needs no database; the signature is
    checked against the key the bundle carries (``key_checked`` says so)."""
    from starlette.concurrency import run_in_threadpool

    from src.analytics.claim_bundle import verify_trail_bundle

    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="no file was sent")
    if len(data) > MAX_VERIFY_BYTES:
        raise HTTPException(status_code=413, detail="the file is larger than any trail bundle")
    return await run_in_threadpool(verify_trail_bundle, data)
