"""
Custody API: record, query, verify, and anchor chain-of-custody entries.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Exposes the src/custody package over the loopback REST API. Verification needs no
DB (a posted bundle is checked in-process), matching the offline guarantee of the
standalone scripts/verify_custody.py.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.custody.anchor import AnchorError, AnchorUnavailable, available_providers, get_provider
from src.custody.log import CustodyAction, CustodyLog, verify_export
from src.custody.settings import (
    VALID_ANCHORING,
    CustodySettingsError,
    availability,
    load_settings,
    save_settings,
)
from src.custody.signing import HybridSigner

router = APIRouter(prefix="/api/custody", tags=["custody"])


def _log() -> CustodyLog:
    """A fresh log handle bound to the current data dir (honours OO_DATA_DIR)."""
    return CustodyLog()


class LogRequest(BaseModel):
    item_id: str
    item_hash: str
    action: str
    actor: str | None = None
    metadata: dict | None = None


@router.post("/log")
def log_action(req: LogRequest) -> dict:
    """Append a signed, chained custody entry for an item."""
    try:
        action = CustodyAction(req.action)
    except ValueError as exc:
        valid = ", ".join(a.value for a in CustodyAction)
        raise HTTPException(status_code=400, detail=f"unknown action; use one of: {valid}") from exc
    log = _log()
    try:
        entry = log.record(
            req.item_id, req.item_hash, action, actor=req.actor, metadata=req.metadata
        )
        return entry.to_dict()
    finally:
        log.close()


@router.get("/providers")
def list_providers() -> dict:
    """List anchor providers and their honest availability status."""
    return {"providers": available_providers()}


@router.get("/export")
def export(item_id: str | None = None) -> dict:
    """Export an offline-verifiable custody bundle (optionally for one item)."""
    log = _log()
    try:
        return log.export(item_id=item_id)
    finally:
        log.close()


def _settings_status() -> dict:
    """Combine stored preferences with what the build can actually do.

    The response always exposes both the *requested* preference and the
    *effective* reality, so the GUI can never show a PQC/OTS toggle as "on" when
    the supporting library is not installed.
    """
    prefs = load_settings()
    avail = availability()
    # Build the signer the way the log would, to report the real identity that
    # would sign entries under the current preference (creates keys on first use).
    signer = HybridSigner(use_pqc=prefs.pqc_enabled)
    return {
        **prefs.to_dict(),
        "anchoring_modes": list(VALID_ANCHORING),
        "pqc_available": avail["pqc_available"],
        # Why, not just whether: a build with no [pqc] extra and one whose pqcrypto
        # cannot complete a sign/verify round trip both report False, and only one of
        # them is fixed by installing something.
        "pqc_reason": avail["pqc_reason"],
        "pqc_effective": signer.is_hybrid,  # signed as hybrid only if truly available
        "ots_available": avail["ots_available"],
        "ots_reason": avail["ots_reason"],
        "ots_effective": prefs.anchoring_mode == "opentimestamps" and avail["ots_available"],
        "key_protection": signer.key_protection,
        "signer": signer.public_identity().to_dict(),
    }


class SettingsUpdate(BaseModel):
    pqc_enabled: bool | None = None
    anchoring_mode: str | None = None
    auto_log_on_ingest: bool | None = None
    default_actor: str | None = None
    # Informed-consent gate for the ONE transition that starts a recurring, silent,
    # per-ingest network egress (P1 audit finding): turning anchoring_mode ON to
    # "opentimestamps". See src.custody.settings.save_settings.
    ots_consent: bool = False


@router.get("/settings")
def get_settings() -> dict:
    """Return custody preferences plus their effective (availability-aware) state."""
    return _settings_status()


@router.put("/settings")
def put_settings(req: SettingsUpdate) -> dict:
    """Update custody preferences (partial). Returns the new effective state."""
    try:
        save_settings(req.model_dump(exclude_unset=True))
    except CustodySettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _settings_status()


@router.get("/{item_id}")
def entries(item_id: str) -> dict:
    log = _log()
    try:
        items = [e.to_dict() for e in log.entries_for(item_id)]
        if not items:
            raise HTTPException(status_code=404, detail="no custody entries for that item")
        return {"item_id": item_id, "entry_count": len(items), "entries": items}
    finally:
        log.close()


@router.get("/{item_id}/verify")
def verify_item(item_id: str) -> dict:
    """Verify the full custody chain in this store (the item must be present)."""
    log = _log()
    try:
        if not log.entries_for(item_id):
            raise HTTPException(status_code=404, detail="no custody entries for that item")
        ok, issues = log.verify()
        return {"verified": ok, "issues": issues}
    finally:
        log.close()


class VerifyBundleRequest(BaseModel):
    bundle: dict
    require_signer: bool = False


@router.post("/verify")
def verify_bundle(req: VerifyBundleRequest) -> dict:
    """Verify a posted custody bundle offline (no DB needed)."""
    ok, issues = verify_export(req.bundle, require_signer=req.require_signer)
    return {"verified": ok, "issues": issues}


class AnchorRequest(BaseModel):
    merkle_root: str
    provider: str = "local"
    metadata: dict | None = None
    # Informed-consent gate (P1 audit finding, UI invariant #14/#14e): OpenTimestamps
    # is REAL, IP-revealing network egress to a third party, so the ENDPOINT -- not
    # just today's one "Anchor root" button -- must refuse to fire it without an
    # explicit, per-call yes. The frontend only ever sets this to True after
    # ensureOnline()'s consent flow has run; a caller that never went through the UI
    # (a script, a future surface, an MCP tool) gets the same honest 400 a
    # missing/unknown provider gets, never a silent submission. Scoped to
    # "opentimestamps" specifically, not every non-local name: the public-chain
    # stubs (ethereum/ipfs/arweave) never actually attempt egress -- they always
    # raise AnchorUnavailable/503 with their own "not implemented" reason -- and
    # gating consent ahead of that would swap an honest 503 for a misleading 400
    # about consent for an action that was never going to happen anyway.
    consent: bool = False


@router.post("/anchor")
def anchor(req: AnchorRequest) -> dict:
    """Anchor a Merkle root via a provider (default: local, offline).

    Non-local providers may require network and carry privacy implications; an
    unavailable provider returns 503 with a clear reason rather than a fake receipt.
    The "opentimestamps" provider also requires ``consent: true`` -- see
    :class:`AnchorRequest`.
    """
    try:
        provider = get_provider(req.provider)
    except AnchorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if req.provider == "opentimestamps" and not req.consent:
        raise HTTPException(
            status_code=400,
            detail=(
                f"The {req.provider!r} anchor provider requires network egress to a "
                "third party and reveals your IP and timing to it. Retry with "
                "consent: true after the operator has explicitly confirmed this "
                "specific submission."
            ),
        )
    try:
        receipt = provider.anchor(req.merkle_root, req.metadata)
        return receipt.to_dict()
    except AnchorUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AnchorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        close = getattr(provider, "close", None)
        if close:
            close()
