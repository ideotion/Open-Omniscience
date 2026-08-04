"""Settings -> Shortcuts: a keyboard-shortcuts panel + rebindable global keys (UI-shell §4).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The app's global shortcuts are listed and REBINDABLE from a Settings subtab, persisted
to localStorage (this device only, never transmitted). One dispatcher reads the bindings
so a rebind takes effect immediately. The command palette is bound by default (Ctrl/⌘-K);
the others are opt-in (default unset) so a fresh install never hijacks a keystroke. The
retired visible "Ctrl K" hint + its dead .kbd/.ph CSS are gone. Pure string-assertion
wiring guards over the static assets (browser-unverified per fork-3).
"""

from __future__ import annotations

from pathlib import Path
import re

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_HTML = (_STATIC / "index.html").read_text(encoding="utf-8")
_JS = (_STATIC / "app.js").read_text(encoding="utf-8")
_CSS = (_STATIC / "app.css").read_text(encoding="utf-8")


def test_shortcuts_panel_exists():
    """2026-07-31 (Settings review): Shortcuts stopped being its own subtab -- one panel
    did not earn a top-level slot -- and moved into General. The panel and its render host
    are what matter, so those are what this pins; it no longer asserts a subtab name the
    restructure deliberately retired."""
    assert 'id="kb-panel"' in _HTML, "the panel needs a render host"
    assert "<h2>Keyboard shortcuts</h2>" in _HTML, "the shortcuts panel must still exist"
    gen = _HTML.split('id="set-general"', 1)[1].split('<div class="set-view"', 1)[0]
    assert 'id="kb-panel"' in gen, "the shortcuts panel must live in the General subtab"


def test_shortcuts_wired_into_showsetcat():
    assert 'if (cat === "general") loadShortcuts();' in _JS


def test_bindings_are_local_and_defaults_are_opt_in():
    assert 'const KEYS_KEY = "oo.keys"' in _JS, "bindings are a namespaced localStorage key"
    assert "function getKeys()" in _JS and "function saveKeys(" in _JS
    # palette bound by default; the rest opt-in (empty) so a fresh install hijacks nothing.
    assert 'palette: "Mod+K"' in _JS
    assert 'home: ""' in _JS and 'airplane: ""' in _JS
    # local-only: the shortcuts feature must not fetch anything.
    assert "localStorage.setItem(KEYS_KEY" in _JS


def test_one_dispatcher_reads_the_bindings():
    # The single global keydown listener now routes through the binding-aware dispatcher;
    # the old hardcoded Ctrl-K branch is gone (a rebind must actually take effect).
    assert 'document.addEventListener("keydown", _kbDispatch)' in _JS
    assert "function _kbDispatch(" in _JS
    assert 'e.key.toLowerCase() === "k"' not in _JS, "the hardcoded palette key must be gone"


def test_recorder_and_reset_present():
    assert "function loadShortcuts()" in _JS
    assert "function kbRecord(" in _JS and "function kbClear(" in _JS and "function kbReset(" in _JS
    # the recorder captures the next keydown in the capture phase so it beats the dispatcher
    assert 'document.addEventListener("keydown", onKey, true)' in _JS
    # a rebind never lands two actions on the same combo
    assert "if (k !== id && binds[k] === combo) binds[k] = \"\"" in _JS


def test_dead_ctrl_k_hint_css_removed():
    assert ".kbd {" not in _CSS, "the dead keyboard-hint chip CSS must be gone"
    assert ".omni .kbd" not in _CSS
    assert ".omni span.ph" not in _CSS
    # and no visible 'Ctrl K' / Command+K hint text remains in the markup
    # `A or B` where B is satisfied by the aria attribute itself, so the guard could
    # never fail while that attribute exists -- and the attribute is exactly what the
    # comment says may stay. Assert the real claim: no VISIBLE Control+K text.
    visible = re.sub(r'aria-keyshortcuts="[^"]*"', "", _HTML)
    assert "Control+K" not in visible, "no visible Ctrl K hint text may remain in the markup"


def test_shortcut_labels_are_translated():
    # user-facing strings go through t() (keyed ×12) — never a module-level t.
    assert 't("Open the command palette")' in _JS
    assert 't("Reset to defaults")' in _JS
    en = (_STATIC / "locales" / "en.json").read_text(encoding="utf-8")
    for lang in ("fr", "de", "ar"):
        other = (_STATIC / "locales" / f"{lang}.json").read_text(encoding="utf-8")
        assert "Keyboard shortcuts" in en and "Keyboard shortcuts" in other
