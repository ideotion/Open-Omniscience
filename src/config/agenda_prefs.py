"""
Server-side agenda "smart-calendar" subscription preferences (DB-reliability D4).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Which curated calendars the operator subscribes to (and which they explicitly
exclude), plus the agenda view, used to live ONLY in browser ``localStorage``
(``oo.agenda.subs`` / ``oo.agenda.excluded`` / ``oo.agenda.view``) — so the server
never saw them, they were absent from every backup, and they did not survive a
browser reset (gap analysis D4). This backs them with a durable ``app_state`` row,
transactional and inside the (encrypted) corpus DB, with a REST path the frontend
can adopt later (it keeps its client fallback until then).

Honesty: these are *preferences*, never analytics. ``configured`` tells the client
whether the server has an explicit choice yet — an unconfigured server means "use
your first-run default" (the frontend subscribes to every calendar), so moving the
store server-side never silently drops a first-run user's calendars.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_KV_KEY = "agenda.prefs"

# Defensive bounds — the calendar-key vocabulary is owned by the frontend, so we
# validate SHAPE (list-of-short-strings) rather than an enum, and cap sizes so a
# stored preference blob can never grow unbounded.
_MAX_ITEMS = 500
_MAX_KEY_LEN = 128
_MAX_VIEW_LEN = 32


class AgendaPrefsError(ValueError):
    """Raised when an agenda-prefs update carries an invalid value."""


@dataclass
class AgendaPrefs:
    subs: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    view: str = "month"
    # False until the operator has saved a choice: the client then keeps its
    # first-run default (subscribe to every calendar) instead of an empty set.
    configured: bool = False

    def to_dict(self) -> dict:
        return {
            "subs": list(self.subs),
            "excluded": list(self.excluded),
            "view": self.view,
            "configured": self.configured,
        }


def _clean_keys(value, label: str) -> list[str]:
    if not isinstance(value, list):
        raise AgendaPrefsError(f"{label} must be a list of calendar keys")
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise AgendaPrefsError(f"{label} entries must be strings")
        key = item.strip()
        if not key:
            continue
        if len(key) > _MAX_KEY_LEN:
            raise AgendaPrefsError(f"{label} key is too long (max {_MAX_KEY_LEN} chars)")
        if key not in seen:
            seen.add(key)
            out.append(key)
    if len(out) > _MAX_ITEMS:
        raise AgendaPrefsError(f"{label} has too many entries (max {_MAX_ITEMS})")
    return out


def load_prefs() -> AgendaPrefs:
    """Load the stored agenda prefs (honest defaults + ``configured=False`` when unset)."""
    from src.config.kv_store import kv_get_json

    raw = kv_get_json(_KV_KEY)
    if raw is None:
        return AgendaPrefs()
    prefs = AgendaPrefs(configured=True)
    try:
        prefs.subs = _clean_keys(raw.get("subs", []), "subs")
        prefs.excluded = _clean_keys(raw.get("excluded", []), "excluded")
    except AgendaPrefsError:
        # A corrupt stored blob must not take down the agenda — degrade to empty.
        prefs.subs, prefs.excluded = [], []
    view = raw.get("view", "month")
    prefs.view = str(view)[:_MAX_VIEW_LEN] if isinstance(view, str) and view.strip() else "month"
    return prefs


def save_prefs(updates: dict) -> AgendaPrefs:
    """Apply a partial update (only provided keys change) and persist to app_state."""
    current = load_prefs()
    if "subs" in updates and updates["subs"] is not None:
        current.subs = _clean_keys(updates["subs"], "subs")
    if "excluded" in updates and updates["excluded"] is not None:
        current.excluded = _clean_keys(updates["excluded"], "excluded")
    if "view" in updates and updates["view"] is not None:
        view = str(updates["view"]).strip()
        if not view or len(view) > _MAX_VIEW_LEN:
            raise AgendaPrefsError(f"view must be 1..{_MAX_VIEW_LEN} characters")
        current.view = view
    current.configured = True

    from src.config.kv_store import kv_set_json

    kv_set_json(_KV_KEY, {"subs": current.subs, "excluded": current.excluded, "view": current.view})
    return current
