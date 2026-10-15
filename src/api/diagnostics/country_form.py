"""Which form the store keeps its country codes in, and where a migration stands (0.5 row B1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Read-only and cheap: it reads the store's marker and the migration's journal, and scans nothing.
The migration itself is a command run with the app closed (``open-omniscience migrate-countries``):
it needs the file to itself, so there is no button here that could start it.

A NEW slice imported before the release run, the way ``runs.py`` is, so the split guard's pinned
positions stay where they were.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from src.database.session import get_db

from ._base import router

@router.get("/country-form")
def country_form_status(estimate: bool = False, db: Session = Depends(get_db)) -> dict:
    """The form of this store (``alpha2`` or ``alpha3``) and the last migration's journal, if any.

    ``alpha2`` is what every store made before 0.5 holds; it is a normal, working state, and the
    app reads and writes it exactly as before. Nothing here is a warning, and nothing is migrated
    by looking at it. ``estimate=true`` also reads how many rows a migration would rewrite (one GROUP BY
    per country column, through a read-only connection, so the app may stay open); the time is NOT guessed
    here, because it is measured only inside the run, on a window it rolls back. A plain ``def``: it runs in
    the threadpool.
    """
    import json

    from sqlalchemy import text

    command = "open-omniscience migrate-countries"  # the command that moves a store, as it is typed

    from src.backup.country_migration import JOURNAL_KEY
    from src.database.country_form import KEY, StoreFormUnreadable, store_form

    def _kv(key: str) -> dict | None:
        row = db.execute(text('SELECT value FROM "app_state" WHERE key = :k'), {"k": key}).first()
        if not row:
            return None
        try:
            value = json.loads(row[0])
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    try:
        form = store_form()
    except StoreFormUnreadable:
        return {"form": None, "readable": False, "command": command,
                "note": "the form of this store could not be read, so nothing was assumed"}
    marker = _kv(KEY) or {}
    journal = _kv(JOURNAL_KEY)
    plan = None
    if estimate:
        from pathlib import Path

        from src.backup.country_migration import MigrationRefused, migrate
        from src.database.session import engine

        if engine.url.get_backend_name() == "sqlite" and engine.url.database:
            try:
                rep = migrate(Path(engine.url.database), estimate_only=True)
                est = rep.estimate or {}
                plan = {"rows_to_rewrite": est.get("rows_to_rewrite"), "store_bytes": est.get("store_bytes"),
                        "free_bytes": est.get("free_bytes"), "left_as_stored": rep.unmapped, "time": est.get("time")}
            except MigrationRefused as exc:
                plan = {"refused": str(exc)}
    return {
        "form": form,
        "readable": True,
        "stamped_by": marker.get("set_by"),
        "stamped_at": marker.get("at"),
        "migrated": form == "alpha3" and marker.get("set_by") != "new-store",
        "command": command,
        "estimate": plan,
        "journal": None if journal is None else {
            "state": journal.get("state"),
            "rewritten": journal.get("rewritten"),
            "backup": (journal.get("backup") or {}).get("path") if isinstance(journal.get("backup"), dict) else None,
            "started_at": journal.get("started_at"),
        },
    }
