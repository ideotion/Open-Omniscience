"""The country-code duplicate-key scan (Q310 = a, gate row K's artifact).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A NEW slice rather than a route appended to an existing one (2026-09-16). The Q1139
split's guard pins every route's POSITION, not just its presence, and the snapshot it
compares against is the pre-split table -- so the least disruptive way to add a route is
a file imported LAST, which appends one entry and moves nothing. That keeps the split
guard's own claim ("the split lost nothing") readable: every position it asserts is
still the position the pre-split module registered.

The scan itself lives in ``src/backup/country_codes.py``, beside the restore normaliser
whose registry it shares. One registry, two consumers: a second copy is how the scan
comes to agree with the normaliser about a column neither of them covers.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from src.database.session import get_db

from ._base import router


@router.get("/country-code-duplicates")
def country_code_duplicates(db: Session = Depends(get_db)) -> dict:
    """Rows in the live corpus that differ only by the FORM of their country code.

    The artifact gate row K closes on: restore a real PRE-migration backup, run this,
    and read 0. It is READ-ONLY -- it writes nothing, takes no lock a reader would
    notice, and can be run at any time.

    A plain ``def`` so Starlette runs it in the threadpool: it issues one GROUP BY per
    country-bearing column, which on an encrypted corpus is real work through the
    codec, and an ``async def`` would do that on the event loop and freeze every other
    request for its duration (the recorded whole-server-freeze family).
    """
    from src.backup.country_codes import scan_live_corpus

    return scan_live_corpus(db)
