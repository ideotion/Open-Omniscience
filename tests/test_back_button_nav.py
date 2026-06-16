"""The Back button navigates tabs — never escapes to the passphrase screen.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Diagnosed bug (UI plan §7): tab navigation used history.replaceState, so tabs
added no history entries; a locked API response did location.href="/unlock". The
only prior entry was /unlock, so Back landed on the passphrase screen. Fix: tabs
PUSH history (+ a popstate handler re-renders), and every hop to/from /unlock
REPLACES so the unlock screen never sits in the back stack.
"""

from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
# index.html's JS was externalised into cached app.js (audit PR H); the tab-nav
# history logic now lives there, so read both (a MOVE, not a loss).
_INDEX = "\n".join(
    (_STATIC / f).read_text(encoding="utf-8")
    for f in ("index.html", "app.js", "app.css")
    if (_STATIC / f).exists()
)
_UNLOCK = (_STATIC / "unlock.html").read_text(encoding="utf-8")


def test_tab_nav_pushes_history_and_handles_back():
    # showTab pushes a real history entry on user navigation...
    assert 'history.pushState(null, "", "#" + name)' in _INDEX
    # ...and Back/Forward re-renders the tab from the URL.
    assert 'addEventListener("popstate"' in _INDEX
    # The initial render must NOT push (it replaces), so /home isn't a dead Back.
    assert 'showTab((location.hash || "#home").slice(1), false)' in _INDEX


def test_unlock_hops_replace_so_back_never_returns_to_passphrase():
    # A locked API response replaces (not href) the current entry with /unlock.
    assert 'location.replace("/unlock")' in _INDEX
    assert 'location.href = "/unlock"' not in _INDEX
    # After a successful unlock, the app replaces /unlock with / (not href).
    assert 'location.replace("/")' in _UNLOCK
    assert 'location.href = "/"' not in _UNLOCK
