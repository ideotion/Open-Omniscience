"""Legal consent endpoints (first-run acceptance of the legal document set).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Loopback-only, single-user: this records the local Utilisateur's explicit
acceptance of the documents under ``docs/legal/``. Like everything else in the
app, it is NOT telemetry -- the consent record stays on the machine (see
``src.legal.consent``). The web GUI uses these endpoints to drive a first-run
acceptance modal; the CLI uses ``src.legal.consent`` directly.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.legal.consent import (
    CONSENT_DOC_VERSION,
    consent_status,
    record_consent,
)

router = APIRouter(prefix="/api/legal", tags=["legal"])


class AcceptBody(BaseModel):
    """Body for POST /api/legal/consent: the document-set version being accepted."""

    version: str = CONSENT_DOC_VERSION


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
