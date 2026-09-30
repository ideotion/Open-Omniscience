"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The onboarding tour (gate row K, brief S05-11 S5).

A short walk through what the sidebar pins at the reader's interface depth (the Ring dial,
S05-09). What may not regress is a refusal, not a feature:

* it NEVER STARTS BY ITSELF: it is opened by an explicit command (Settings -> General, the
  command palette, Help & docs) and by nothing else;
* it NARROWS NOTHING (the recorded onboarding lesson, LESSONS 2026-07-12: an onboarding picker
  must default to everything; emphasis is not exclusion): no stored record, no setting, no
  filter, no network;
* every sidebar tab is either its own step or named in the "more" step, so a tab added to the
  sidebar cannot be missing from the tour, and one with no sentence yet fails HERE, visibly;
* it changes no invariant #2 surface: the sidebar is not touched except by the button the
  reader presses inside the tour.

The step builder and renderer are driven in node (``tests/tour_node_test.js``).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_STATIC = _ROOT / "src" / "static"


def _html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def _tour_js() -> str:
    return (_STATIC / "app-tour.js").read_text(encoding="utf-8")


def _sidebar_tabs() -> list[str]:
    return re.findall(r'<button class="nav-item[^"]*" data-tab="([a-z]+)"', _html())


def test_the_module_is_loaded_before_boot_and_precached():
    html = _html()
    assert '<script src="/static/app-tour.js"></script>' in html
    assert html.index('src="/static/app-tour.js"') < html.index('src="/static/app-boot.js"')
    assert html.index('src="/static/app-shell.js"') < html.index('src="/static/app-tour.js"'), (
        "the tour calls uiDepth/paintNavMore/showTab, which the shell defines"
    )
    sw = (_STATIC / "sw.js").read_text(encoding="utf-8")
    assert "/static/app-tour.js" in sw, "an offline first load must still be able to open the tour"


def test_the_dialog_and_its_controls_exist():
    html = _html()
    assert '<dialog id="tour"' in html
    for ident in ("tour-body", "tour-skip", "tour-back", "tour-next"):
        assert f'id="{ident}"' in html, ident
    js = _tour_js()
    for ident in ("tour-body", "tour-skip", "tour-back", "tour-next"):
        assert f'"{ident}"' in js, f"{ident} is not wired"


def test_every_sidebar_tab_has_a_sentence_in_the_tour():
    tabs = _sidebar_tabs()
    assert tabs, "the sidebar's tabs were not found in index.html"
    js = _tour_js()
    blurb = re.search(r"function tourBlurb\(id, t\) \{(.*?)\n    \}", js, re.S).group(1)
    missing = [t for t in tabs if f'case "{t}":' not in blurb]
    assert not missing, (
        f"the sidebar has tabs the tour has no sentence for: {missing}. Add a case to "
        "tourBlurb (and its string to the 12 locales); the tour still shows the tab with "
        "its name and its button, but a tab with nothing to say is a gap, not a design."
    )
    # ...and no sentence for a tab that is gone
    stale = [c for c in re.findall(r'case "([a-z]+)":', blurb) if c not in tabs]
    assert not stale, f"tourBlurb has sentences for tabs the sidebar no longer has: {stale}"


def test_the_node_fixture_lists_the_real_sidebar():
    """tests/tour_node_test.js hard-codes the sidebar's ids; pin them to the page."""
    node = (_ROOT / "tests" / "tour_node_test.js").read_text(encoding="utf-8")
    ids = json.loads("[" + re.search(r"const IDS = \[(.*?)\];", node, re.S).group(1).replace("\n", " ") + "]")
    assert ids == _sidebar_tabs()


def test_it_opens_only_on_an_explicit_command():
    html = _html()
    callers = re.findall(r'data-on-click="openTour\(\)"', html)
    assert len(callers) == 2, "Settings -> General and Help & docs each carry the button"
    shell = (_STATIC / "app-shell.js").read_text(encoding="utf-8")
    assert 'label:"Take the tour"' in shell and "openTour()" in shell, "the command palette entry"
    oo_on = (_STATIC / "oo-on.js").read_text(encoding="utf-8")
    assert '"openTour"' in oo_on, "the data-on-click dispatcher must know the action"
    for other in _STATIC.glob("*.js"):
        if other.name in ("app-tour.js", "app-shell.js", "oo-on.js"):
            continue
        assert "openTour" not in other.read_text(encoding="utf-8"), (
            f"{other.name} opens the tour: it must not start without an explicit command"
        )


def test_it_narrows_nothing_and_keeps_no_record():
    js = re.sub(r"/\*.*?\*/", "", _tour_js(), flags=re.S)
    for banned in ("localStorage", "sessionStorage", "indexedDB", "fetch(", "api(", "XMLHttpRequest",
                   "setSetting", "saveSettings", "setUiDepth", "classList.add(\"hidden\")"):
        assert banned not in js, f"the tour must keep no record and make no call: found {banned}"
    assert not re.search(r"\bon(click|change|input|submit)\s*=", js), "the CSP has no 'unsafe-inline'"
    assert "The tour changes nothing" in js, "the promise is on the page, not only in a comment"


def test_a_depth_that_pins_fewer_tabs_still_names_every_one():
    js = _tour_js()
    assert 'kind: "more"' in js and "list: rest.map" in js, "the unpinned tabs are named"
    assert "_navMoreOpen = true; paintNavMore()" in js, "the button shows them in the sidebar"


def test_the_english_strings_are_all_keyed_in_the_locales():
    """The i18n gate's tf() detector does not see frames read through a local alias, so the
    frames the tour and the review build are pinned here."""
    en = json.loads((_STATIC / "locales" / "en.json").read_text(encoding="utf-8"))
    for name in ("app-tour.js", "app-evidence.js"):
        src = (_STATIC / name).read_text(encoding="utf-8")
        for m in re.finditer(r'\b(?:t|tf)\(\s*"((?:[^"\\]|\\.)*)"', src):
            key = m.group(1).encode().decode("unicode_escape") if "\\u" in m.group(1) else m.group(1)
            key = key.replace('\\"', '"')
            assert key in en, f"{name}: no en.json key for {key[:80]!r}"


def test_the_tour_steps_and_renderers_behave():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "tour_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout
