"""Settings ends at NINE subtabs; Safety folds in; Uninstall gets its own section.

Rulings 26/27/42 (field feedback 2026-08-07).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The ABSORPTION half is what matters here, not the tidier strip. Retiring a subtab is
only safe if every tool it carried is still reachable -- the Desk lesson -- so the bulk
of this file is the negative-space twin: each control that lived in Safety, asserted to
still exist AND to be inside the Advanced view, by id.
"""

from __future__ import annotations

import re

from tests.js_source_helper import function_body, object_literal, read_static, strip_comments

HTML = read_static("index.html")
APP = read_static("app.js")

# The end state ruling 42 names, in order.
_EXPECTED = [
    "graphics", "general", "cards", "models", "wikipedia",
    "offlinemap", "agenda", "data", "advanced",
]

# Every control the retired Safety subtab carried. Absorption is checked by id, because
# an id is what a deep link, a test anchor and the loader all resolve against.
_SAFETY_CONTROLS = [
    "safety-panel",          # at-rest encryption + the panel itself
    "atrest-state", "atrest-encrypt", "atrest-consent",
    "vacuum-btn", "vacuum-reclaim", "vacuum-result",
    "fixity-btn", "fixity-summary", "fixity-result",
    "fetch-mode", "http-proxy", "fetch-note",
    "discovery-external", "discovery-external-result",
]
_UNINSTALL_CONTROLS = [
    "panic-result",
    "uninstall-mode", "uninstall-custom", "uninstall-data", "uninstall-folder",
    "uninstall-passes", "uninstall-preview", "uninstall-result",
]


def _subtabs() -> list[str]:
    nav = HTML.split('id="set-subtabs"', 1)[1].split("</nav>", 1)[0]
    return re.findall(r'data-tab="([^"]+)"', nav)


def _view_of(anchor: str) -> str:
    views = [(m.start(), m.group(1)) for m in re.finditer(r'<div class="set-view" id="([^"]+)"', HTML)]
    at = HTML.index(anchor)
    return [name for pos, name in views if pos < at][-1]


def test_settings_has_exactly_the_nine_ruled_subtabs() -> None:
    got = _subtabs()
    assert got == _EXPECTED, f"ruling 42 names nine subtabs, in this order; got {got}"
    assert "safety" not in got, "Safety folded into Advanced (ruling 26)"


def test_every_subtab_button_has_a_view_and_every_view_a_button() -> None:
    """A button with no view is a dead click; a view with no button is unreachable
    markup. Either way something the reader can see is wrong."""
    views = set(re.findall(r'<div class="set-view" id="set-([^"]+)"', HTML))
    assert views == set(_EXPECTED), f"views {sorted(views)} != subtabs {sorted(_EXPECTED)}"


def test_nothing_from_safety_was_lost(  ) -> None:
    """The Desk lesson. Retiring the subtab must not retire its tools."""
    for el in _SAFETY_CONTROLS + _UNINSTALL_CONTROLS:
        assert f'id="{el}"' in HTML, f"{el} disappeared when Safety was folded in"
        assert _view_of(f'id="{el}"') == "set-advanced", f"{el} was left behind"


def test_uninstall_and_wipe_is_its_own_section_not_nested_in_safety() -> None:
    """Ruling 26, and the reason is not tidiness: panic wipe must not become hard to
    reach, because the person who needs it may need it in a hurry."""
    order = re.findall(r'data-adv="([a-z]+)"', HTML)
    assert "safety" in order and "uninstall" in order, f"both sections must exist; got {order}"
    # Its own TOP-LEVEL section: the uninstall markup must not sit inside the safety fold.
    safety_start = HTML.index('data-adv="safety"')
    safety_end = HTML.index("</details>", safety_start)
    uninstall_at = HTML.index('data-adv="uninstall"')
    assert uninstall_at > safety_end, (
        "Uninstall & wipe is nested inside the Safety section -- ruling 26 gives it its "
        "own, because one fold deeper is one click further from someone in a hurry"
    )
    # And the panic wipe travelled with it, rather than being left in Safety.
    assert HTML.index('id="panic-result"') > uninstall_at


def test_the_destructive_section_says_so_before_it_is_opened() -> None:
    """Its summary must warn in WORDS, not only in colour: a colour-only warning is
    invisible in greyscale and to a reader with a colour-vision difference."""
    summary = HTML.split('data-adv="uninstall"', 1)[1].split("</summary>", 1)[0]
    assert "irreversible" in summary.lower(), (
        "the collapsed summary must say what opening this leads to"
    )
    css = read_static("app.css")
    assert ".adv-sec-danger" in css, "the section needs its marked style"
    assert "var(--err)" in css.split(".adv-sec-danger", 1)[1][:300], (
        "use the theme's own --err, never a hardcoded red: a fixed hue fails some of "
        "the seventeen themes (the recorded --caveat/--warn contrast lesson)"
    )


def test_the_folded_sections_load_on_expand_not_on_subtab_select() -> None:
    """'Folded must not mean fetched.' Both loaders came WITH the markup: on the subtab
    they ran on select, and here they must run on expand."""
    loaders = object_literal(APP, "_ADV_LOADERS")
    assert "safety:" in loaders and "uninstall:" in loaders, (
        "a moved panel takes its loader with it -- the field report was 'can't find your "
        "keyword triage button', which was exactly a loader left behind"
    )
    assert "loadAtRestState()" in loaders and "onUninstallMode()" in loaders
    # ...and NOT on subtab select any more, or they would fire for every Advanced open.
    # BRACE-MATCHED, not split on a guessed delimiter: _ADV_LOADERS is a `const` that
    # follows showSetCat, so a slice ending at "the next function" swallows the very map
    # this assertion is about and can never fail (the recorded mis-slice trap).
    show = strip_comments(function_body(APP, "showSetCat"))
    assert "loadAtRestState()" not in show, (
        "loadAtRestState must fire on section expand, not when Advanced is selected"
    )


def test_advanced_stays_flat_with_no_second_level_subtab_strip() -> None:
    """Ruling 27: Advanced keeps its flat collapsible structure."""
    adv = HTML[HTML.index('id="set-advanced"'):]
    end = adv.find('<div class="tab-page"')
    adv = adv[:end] if end != -1 else adv
    assert 'class="tabs"' not in adv, (
        "Advanced must not grow a second-level subtab strip (ruling 27); its sections "
        "are flat <details> folds"
    )
