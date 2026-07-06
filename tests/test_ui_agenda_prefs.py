"""
Wave 3 H — agenda calendar SUBSCRIPTIONS migrated to the server (DB-reliability D4).

The agenda's calendar subscriptions used to live only in browser localStorage
("oo.agenda.subs") — invisible to the server, absent from every backup, and lost on a
browser reset. This wiring moves the SUBSCRIPTIONS onto the durable GET/PUT
/api/agenda/prefs store so they survive a reinstall and ride backups, while honoring the
server's ``configured`` flag (unconfigured → keep the first-run "subscribe to all"
default, never silently dropping calendars).

Deliberately NOT migrated: the feed EXCLUSIONS ("oo.agenda.excluded", ruled a per-machine
store 2026-06-15) and the chosen VIEW ("oo.agenda.view", a per-device display preference)
stay in localStorage — a per-device curation/display choice, not a corpus subscription.

Browser-unverified per fork-3 — node-checked + grep-guarded here.
"""

from __future__ import annotations

from tests.test_repo_invariants import _ui_source


def test_agenda_subscriptions_use_the_server_endpoint():
    ui = _ui_source()
    assert "/api/agenda/prefs" in ui, "the agenda must read/write the server-side prefs endpoint"
    assert "agLoadPrefs" in ui, "a loader that GETs the server prefs must exist"
    assert "agPutPrefs" in ui, "a best-effort PUT helper must persist subscription changes"
    assert "_agPrefs" in ui, "an in-memory prefs cache must back the synchronous getters"


def test_agenda_subscriptions_no_longer_use_localstorage():
    ui = _ui_source()
    # The subs read/write calls for the subscriptions must be gone (a comment naming the
    # retired key is fine — it is not an API call).
    assert 'localStorage.getItem("oo.agenda.subs")' not in ui, "subscriptions must not be READ from localStorage"
    assert 'localStorage.setItem("oo.agenda.subs"' not in ui, "subscriptions must not be WRITTEN to localStorage"


def test_agenda_exclusions_and_view_stay_per_machine():
    ui = _ui_source()
    # The per-machine rulings are preserved: exclusions + view keep their localStorage store.
    assert 'localStorage.getItem("oo.agenda.excluded")' in ui, "exclusions stay a per-machine localStorage store"
    assert 'localStorage.getItem("oo.agenda.view")' in ui, "the chosen view stays a per-device localStorage preference"


def test_agenda_first_run_default_honors_the_configured_flag():
    ui = _ui_source()
    # Unconfigured (server has no explicit choice) → keep subscribing to every calendar.
    assert "!_agPrefs.configured" in ui, "the first-run 'subscribe to all' default must gate on configured=false"
