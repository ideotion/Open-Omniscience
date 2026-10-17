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
from src.monitoring.secret_scrub import record_text

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

    from src.database.country_form import (
        JOURNAL_KEY,
        KEY,
        MigrationUnfinished,
        StoreFormUnreadable,
        store_form,
    )

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
    except MigrationUnfinished as exc:
        stopped = _kv(JOURNAL_KEY) or {}
        return {"form": None, "readable": False, "unfinished": True, "command": command, "note": record_text(exc, typed=False),
                "journal": {"state": stopped.get("state"), "rewritten": stopped.get("rewritten")}}
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
                        "free_bytes": est.get("free_bytes"), "left_as_stored": rep.unmapped, "time": est.get("time"),
                        "search_index": est.get("fts")}
            except MigrationRefused as exc:
                plan = {"refused": record_text(exc, typed=False)}
            except Exception as exc:  # noqa: BLE001 - a locked or keyless file, a read that failed: the class is the answer
                plan = {"refused": f"the plan could not be read ({type(exc).__name__}); nothing was changed"}
    # The article index keeps the tokenizer it was created with; an index from before 0.5 splits Hindi and Bengali words
    # at their vowel signs until the migration rebuilds it, so the card says which one this store has.
    try:
        from src.database.fts import fts_tokenizer

        index_tokenizer = fts_tokenizer(db.connection())
    except Exception:  # noqa: BLE001 - a diagnostic degrades: "could not read" is its own answer, never "current"
        index_tokenizer = "unreadable"
    return {
        "form": form,
        "readable": True,
        "search_index": {"tokenizer": index_tokenizer, "needs_rebuild": index_tokenizer == "legacy"},
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
