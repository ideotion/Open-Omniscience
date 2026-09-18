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
from tests.js_source_helper import app_js

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
# index.html's JS was externalised into cached app.js (audit PR H); the tab-nav
# history logic now lives there, so read both (a MOVE, not a loss).
# app_js() is the whole UI ENGINE (the ordered modules app.js was split into,
# S-3 2026-08-20) -- never one file behind an .exists() guard, which would have
# quietly dropped the engine here and let every "must be absent" assertion below
# pass against source that no longer contains what it checks.
_INDEX = "\n".join(
    [
        (_STATIC / "index.html").read_text(encoding="utf-8"),
        app_js(),
        (_STATIC / "app.css").read_text(encoding="utf-8"),
    ]
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
    # After a successful unlock, the app REPLACES /unlock (never href), so Back cannot
    # return to the passphrase screen.
    #
    # ASSERTED AS THE PROPERTY, NOT AS ONE SPELLING. This used to read
    # `'location.replace("/")' in _UNLOCK`, and S04-09 gave the FRESH-corpus path a
    # different destination (`/?wikiwizard=1`, the first-run wizard hand-off) while
    # keeping `replace`. The literal check reddened on a change that preserved
    # everything it exists to protect. What matters is that every navigation out of
    # this page replaces rather than pushes, and that each destination is a same-origin
    # path -- which is strictly more than the old line checked.
    import re

    assert "location.href" not in _UNLOCK, "a href assignment would leave /unlock on the stack"
    targets = re.findall(r"location\.replace\(([^)]*)\)", _UNLOCK)
    assert targets, "nothing navigates away from the unlock page at all"
    for target in targets:
        literal = target.strip()
        if literal.startswith(("'", '"')):
            assert literal[1:].startswith("/"), f"replace() leaves the origin: {literal}"
        else:
            # A variable destination: the value must be built from same-origin literals
            # in this file, and every one of them checked the same way.
            values = re.findall(rf"{re.escape(literal)}\s*=\s*([^;\n]+)", _UNLOCK)
            assert values, f"replace({literal}) reads a destination this file never sets"
            for value in values:
                for lit in re.findall(r"""["']([^"']*)["']""", value):
                    assert lit.startswith("/"), f"replace({literal}) can leave the origin: {lit!r}"
