"""
Safety API: fetch-mode/proxy settings, encrypted backup/restore, panic wipe.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

All local, loopback-only, and (for the destructive/state-changing routes) protected by the
app's cross-origin refusal middleware. Each response states the honest limit of the
protection it provides — we never imply anonymity or at-rest secrecy we cannot deliver.
"""

from __future__ import annotations

import io

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.safety import settings as safety_settings

router = APIRouter(prefix="/api/safety", tags=["safety"])

_PROXY_NOTE = (
    "Protected mode routes fetches through your proxy and sends a generic User-Agent. "
    "We use and verify the proxy is set; we cannot guarantee anonymity — run and trust "
    "the proxy (e.g. Tor) yourself. SOCKS proxies need the optional [safety] extra."
)


class SettingsUpdate(BaseModel):
    fetch_mode: str | None = None
    http_proxy: str | None = None
    # ETH-02/RM-03: opt-in for the one external-service call in the app
    # (DuckDuckGo topic discovery). Off by default; the UI states plainly that
    # the query leaves the machine.
    discovery_external_enabled: bool | None = None


class PassphraseBody(BaseModel):
    passphrase: str


class PanicBody(BaseModel):
    confirm: bool = False


class SecureEraseBody(BaseModel):
    confirm: bool = False
    # Optional full free-space overwrite AFTER the panic crypto-erase (Single/Triple/
    # Octuple pass). Defence-in-depth only — the corpus is already unrecoverable.
    passes: int = 1


class UninstallBody(BaseModel):
    confirm: bool = False
    # minimal (venv+launchers) | full (+app folder) | secure (+wipe data&keys) | custom.
    mode: str = "minimal"
    # Only consulted when mode == "custom"; each off by default (data dies only on opt-in).
    remove_folder: bool = False
    wipe_data: bool = False


def _uninstall_flags(body: UninstallBody) -> tuple[bool, bool]:
    """Resolve (remove_folder, wipe_data) from the chosen mode. Data is destroyed ONLY
    in 'secure' (or an explicit 'custom' opt-in) — never in minimal/full."""
    mode = (body.mode or "minimal").lower()
    if mode == "minimal":
        return False, False
    if mode == "full":
        return True, False
    if mode == "secure":
        return True, True
    if mode == "custom":
        return bool(body.remove_folder), bool(body.wipe_data)
    raise HTTPException(status_code=400, detail=f"unknown uninstall mode: {body.mode!r}")


@router.get("/settings")
def get_settings() -> dict:
    s = safety_settings.load_settings()
    return {**s.to_dict(), "note": _PROXY_NOTE}


@router.put("/settings")
def update_settings(body: SettingsUpdate) -> dict:
    try:
        s = safety_settings.save_settings(body.model_dump(exclude_unset=True))
    except safety_settings.SafetySettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**s.to_dict(), "note": _PROXY_NOTE}


@router.post("/backup/encrypted")
def encrypted_backup(body: PassphraseBody) -> StreamingResponse:
    """Download a passphrase-encrypted snapshot of the corpus (AES-256-GCM + scrypt)."""
    from src.backup.sqlite_backup import BackupError
    from src.safety import make_encrypted_backup
    from src.safety.crypto import EncryptionError

    if not body.passphrase:
        raise HTTPException(status_code=400, detail="a passphrase is required")
    try:
        blob = make_encrypted_backup(body.passphrase)
    except (EncryptionError, BackupError) as exc:
        # BackupError includes the encrypted-store refusal (an encrypted corpus
        # must use the streaming encrypted backup, not this decrypt-to-plaintext
        # path) — surface it as a clean 400, never an ungraceful 500.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StreamingResponse(
        io.BytesIO(blob),
        media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename=open-omniscience-backup.ooenc"},
    )


# NOTE: POST /api/safety/restore/encrypted (decrypt + REPLACE the live corpus)
# was REMOVED on 2026-06-13 (maintainer ruling: restore is additive-only).
# Restoring goes exclusively through the merge engine (the oo-backup-2 artifact +
# POST /api/database/v2/restore), which never overwrites the corpus. Encrypted
# backup CREATION (POST /api/safety/backup/encrypted) stays.


@router.post("/panic")
def panic(body: PanicBody) -> dict:
    """Irreversibly crypto-erase the local data dir (DB, keys, caches). Requires
    confirm=true.

    Phase 1 of the two-phase wipe (audit OO-02): destroys the SQLCipher salt page so the
    encrypted corpus is permanently unrecoverable at any size, then removes the data dir —
    fast enough to complete even under seizure. The response reports whether the corpus
    was encrypted (``encrypted_corpus``); if not, the caller should recommend the optional
    full pass below. The app must be restarted afterwards. See the honest limit in the
    response.
    """
    if not body.confirm:
        raise HTTPException(status_code=400, detail="set confirm=true to wipe (irreversible)")
    from src.safety import panic_wipe

    return panic_wipe(confirm=True)


@router.post("/secure-erase")
def secure_erase(body: SecureEraseBody) -> dict:
    """Optional phase 2: a full free-space overwrite of the corpus volume after /panic.

    Defence-in-depth ONLY — the panic crypto-erase already made the corpus unrecoverable;
    this scrubs the freed ciphertext blocks ``passes`` times (1/3/8). Requires confirm=true.
    Honest limit: byte-overwrite does not guarantee erasure on SSD/flash/CoW media."""
    if not body.confirm:
        raise HTTPException(status_code=400, detail="set confirm=true to run the full overwrite")
    from src.safety.crypto_erase import full_secure_erase

    try:
        return full_secure_erase(body.passes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/uninstall/plan")
def uninstall_plan(mode: str = "minimal", remove_folder: bool = False,
                   wipe_data: bool = False) -> dict:
    """Preview exactly what a given uninstall mode would remove — deletes NOTHING.

    The UI calls this before confirming so the user sees the precise paths (informed
    consent). Data is only ever in the plan for 'secure' or an explicit 'custom' opt-in."""
    body = UninstallBody(mode=mode, remove_folder=remove_folder, wipe_data=wipe_data)
    rf, wd = _uninstall_flags(body)
    from src.safety.uninstall import plan_uninstall

    return plan_uninstall(remove_folder=rf, wipe_data=wd)


@router.post("/uninstall")
def uninstall(body: UninstallBody) -> dict:
    """Uninstall per the chosen mode, then stop the server. Requires confirm=true.

    Modes (data dies only in 'secure'/'custom' opt-in): minimal = venv + launchers;
    full = + the app folder; secure = + wipe data & keys (best-effort overwrite, honest
    limit). Deletion happens in a detached watcher after the server exits — so the
    response returns first and the app shuts down cleanly."""
    if not body.confirm:
        raise HTTPException(status_code=400, detail="set confirm=true to uninstall")
    rf, wd = _uninstall_flags(body)
    from src.safety.uninstall import request_uninstall

    return request_uninstall(confirm=True, remove_folder=rf, wipe_data=wd)
