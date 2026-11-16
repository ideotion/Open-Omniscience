"""When the Wikipedia lane's run state last changed, and through which door.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field test 2026-11-14, row 73: one machine's lane sat halted for days, across two
restarts, and the soak reading said "0 rows a day, no gap", which is also what a quiet
lane says. The setting says halted; only this record says since when. Written by
``src.scheduler.settings.save_settings`` and read by the soak reading and the scheduler
status. It lives in the corpus key-value store, beside the settings and not in them, so
it is never a field a caller could set.
"""

from __future__ import annotations

import logging

_LOG = logging.getLogger(__name__)


#: The ``app_state`` key holding WHEN the Wikipedia lane's run state last changed.
STATE_CHANGE_KEY = "wiki.lane_state_change"


def note_change(before: str | None, after: str, *, by: str) -> None:
    """Record when the lane's run state changed, and how. Never raises.

    FIELD TEST 2026-11-14, ROW 73: one machine's lane had been halted for days, across two
    restarts, and the soak reading said 0 rows a day and no gap, so nobody reading it could
    tell a halted lane from a quiet one, nor when the halt began. The SETTING says halted;
    only this record says SINCE WHEN and through which door: ``settings-save`` is a save
    that named the state (the toggle, the wizard), ``settings-replacement`` is the
    damaged-settings replacement, which writes ``halted`` for a lane the save did not
    mention. Kept beside the settings rather than in them, so it is never a field a caller
    could set.
    """
    from datetime import UTC, datetime

    try:
        from src.config.kv_store import kv_set_json

        kv_set_json(
            STATE_CHANGE_KEY,
            {"from": before, "state": after, "at": datetime.now(UTC).isoformat(), "by": by},
        )
    except Exception as exc:  # noqa: BLE001 - a record of the change must never fail the save
        _LOG.warning("could not record when the Wikipedia lane state changed: %s", type(exc).__name__)


def last_change() -> dict | None:
    """The last recorded change of the lane's run state, or ``None`` when none was recorded."""
    try:
        from src.config.kv_store import kv_get_json

        blob = kv_get_json(STATE_CHANGE_KEY)
    except Exception:  # noqa: BLE001 - an unreadable record is no record
        return None
    return blob if isinstance(blob, dict) and blob.get("state") else None
