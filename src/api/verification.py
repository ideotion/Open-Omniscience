"""
Verification API: honest image metadata / EXIF inspection.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Scoped explicitly as "metadata checks" -- NOT deepfake/manipulation detection
(that was fabricated and is quarantined). Reports what the file actually contains.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile

from src.verification.metadata import ImageError, extract_image_metadata

router = APIRouter(prefix="/api/verify", tags=["verification"])

# Refuse absurdly large uploads outright (single-user, local).
_MAX_UPLOAD = 50 * 1024 * 1024


@router.post("/image-metadata")
async def image_metadata(file: UploadFile) -> dict:
    """Extract format, dimensions, EXIF and GPS from an uploaded image."""
    # Read at most _MAX_UPLOAD+1 bytes so an oversized upload is rejected WITHOUT
    # first buffering the whole thing into memory.
    data = await file.read(_MAX_UPLOAD + 1)
    if len(data) > _MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="Image exceeds 50 MB limit.")
    try:
        meta = extract_image_metadata(data)
    except ImageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"filename": file.filename, **meta.to_dict()}
