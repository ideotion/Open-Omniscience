"""Legal consent endpoints (first-launch acceptance of the legal document set).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Loopback-only, single-user. Records the local Utilisateur's explicit acceptance
of the documents under ``docs/legal/`` (or, on DECLINE, uninstalls the app per the
maintainer's first-launch policy). NOT telemetry -- the consent record stays on
the machine (see ``src.legal.consent``). These endpoints are reachable while the
store is still locked/fresh (the first-launch flow runs before the DB exists), so
``/api/legal/`` is on the locked-state allowlist in ``src.api.unlock``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from src.legal.consent import (
    CONSENT_DOC_VERSION,
    consent_status,
    record_consent,
)
from src.legal.documents import (
    DECLINE_CONFIRM_WORD,
    build_download_zip,
    documents_payload,
    perform_decline_uninstall,
)

router = APIRouter(prefix="/api/legal", tags=["legal"])


class AcceptBody(BaseModel):
    """Body for POST /api/legal/consent: the document-set version being accepted."""

    version: str = CONSENT_DOC_VERSION


class DeclineBody(BaseModel):
    """Body for POST /api/legal/decline: an explicit, typed confirmation."""

    confirm: bool = False
    word: str = ""


@router.get("/consent")
def get_consent() -> dict:
    """Whether acceptance is still required, plus the documents and any prior record."""
    return consent_status()


@router.post("/consent")
def post_consent(body: AcceptBody) -> dict:
    """Record explicit acceptance of the current document-set version.

    Refuses (400) a version that does not match the version the app currently
    ships, so a stale acceptance can never be recorded as current.
    """
    if body.version != CONSENT_DOC_VERSION:
        raise HTTPException(
            status_code=400,
            detail=(
                f"version mismatch: this build expects {CONSENT_DOC_VERSION!r}, "
                f"got {body.version!r}"
            ),
        )
    record_consent(body.version, actor="web")
    return consent_status()


@router.get("/documents")
def get_documents(lang: str = Query("en")) -> dict:
    """The legal documents + localized chrome for the first-launch step.

    ``lang`` is a UI language code; an unknown one falls back to English, and a
    missing translation falls back to the authoritative French canonical.
    """
    return documents_payload(lang)


@router.get("/download")
def download_documents(lang: str = Query("fr")) -> Response:
    """Download the legal documents in ``lang`` as a .zip (French for any gap)."""
    blob = build_download_zip(lang)
    safe = lang if lang.isalpha() and len(lang) <= 5 else "fr"
    return Response(
        content=blob,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="open-omniscience-legal-{safe}.zip"'},
    )


@router.post("/decline")
def post_decline(body: DeclineBody) -> dict:
    """DECLINE the legal documents -> uninstall the app (the maintainer's policy).

    Requires an explicit, typed confirmation (the language-neutral word
    ``UNINSTALL``) so an accidental click can never trigger it. On confirmation it
    removes the virtualenv, launchers and app folder and wipes the data dir & keys,
    then stops the server.
    """
    if not body.confirm or body.word.strip() != DECLINE_CONFIRM_WORD:
        raise HTTPException(
            status_code=400,
            detail=f"declining requires confirm=true and word={DECLINE_CONFIRM_WORD!r}",
        )
    return perform_decline_uninstall()
