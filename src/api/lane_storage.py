"""Settings -> Storage's one read: each lane's size, budget, growth, and the disk left.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q1006 / Q1010 / Q1011 (ruled 2026-09-15) reach the UI through here; the arithmetic and
the table live in ``src.versioned.budget``, the machine reading in
``src.config.hardware_reading``. This module only serves them.

A READ, AND ONE THAT DEGRADES. A lane that has never run, a budget table that cannot be
parsed and a history the snapshot store cannot return are each a NAMED state in the
payload, never a 500: a storage panel that fails whole because one lane is missing would
hide the three figures it could still show.

LOOPBACK AND NETWORK-FREE. It stats files and reads the corpus; the budget a power user
raises is written through the existing ``PUT /api/scheduler/config``, which validates
it, so there is no second write path for the same setting.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.database.session import get_db

router = APIRouter(prefix="/api/storage", tags=["storage"])


@router.get("/lanes")
def storage_lanes(db: Session = Depends(get_db)) -> dict:
    """Every lane's measured size, its published and effective budget, its growth over
    the last 30 days (or the reason there is none), the boot hardware reading beside the
    reference machine, and the disk left on the data folder's drive."""
    from src.versioned.budget import storage_report

    return storage_report(db)
