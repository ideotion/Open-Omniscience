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

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
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
    from src.safety import make_encrypted_backup
    from src.safety.crypto import EncryptionError

    if not body.passphrase:
        raise HTTPException(status_code=400, detail="a passphrase is required")
    try:
        blob = make_encrypted_backup(body.passphrase)
    except EncryptionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StreamingResponse(
        io.BytesIO(blob),
        media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename=open-omniscience-backup.ooenc"},
    )


@router.post("/restore/encrypted")
async def restore_encrypted(file: UploadFile = File(...), passphrase: str = Form(...)) -> dict:
    """Decrypt + validate + restore an encrypted backup (a tampered/wrong-passphrase file is refused)."""
    from src.backup.sqlite_backup import BackupError
    from src.safety import restore_encrypted_backup
    from src.safety.crypto import EncryptionError

    blob = await file.read()
    try:
        return restore_encrypted_backup(blob, passphrase)
    except EncryptionError as exc:
        raise HTTPException(status_code=400, detail=f"decryption failed: {exc}") from exc
    except BackupError as exc:
        raise HTTPException(status_code=400, detail=f"not a valid backup: {exc}") from exc


@router.post("/panic")
def panic(body: PanicBody) -> dict:
    """Irreversibly wipe the local data dir (DB, keys, caches). Requires confirm=true.

    The app must be restarted afterwards. See the honest limit in the response.
    """
    if not body.confirm:
        raise HTTPException(status_code=400, detail="set confirm=true to wipe (irreversible)")
    from src.safety import panic_wipe

    return panic_wipe(confirm=True)


@router.post("/uninstall")
def uninstall(body: PanicBody) -> dict:
    """Remove the virtualenv + desktop launchers, then stop the server. Requires confirm=true.

    Keeps your data (use /panic to destroy that). Deletion happens in a detached watcher
    after the server exits — so the response returns first and the app shuts down cleanly.
    """
    if not body.confirm:
        raise HTTPException(status_code=400, detail="set confirm=true to uninstall")
    from src.safety.uninstall import request_uninstall

    return request_uninstall(confirm=True)
