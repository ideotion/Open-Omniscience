"""The four accessibility defects measured on the live app on 2026-09-09, pinned.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT WAS MEASURED, AND WHERE. A Chromium + axe-core sweep of the running app
(port 8011, ink theme, en, 1440x900) reported violations on exactly four
surfaces; every other surface swept the same day -- home, feed, insights,
observatory, timemap, agenda, markets, library, law, settings, and the Export /
Import dialogs -- reported ZERO. That "zero everywhere else" is why each fix
below is SCOPED rather than lifted app-wide: a blanket rule would restyle
surfaces that have no finding to fix, and this repo's own ledger records that a
fix wider than its evidence is how a visual change lands unexamined.

  1. Help, 8 documents: link-in-text-block 23 nodes + scrollable-region-focusable
     11 nodes. (`docs/ledger/OPEN_QUEUE.md`'s 2026-09-09 entry recorded 15 and 3
     from a narrower sweep; the per-document numbers are user-manual 6/3,
     quickstart 6/6, ethics 4/0, roadmap 3/2, governance/security/design/
     architecture 1/0 each.)
  2. Command palette: scrollable-region-focusable 1 (`#pal-list`).
  3. Analysis window: nested-interactive 1 (`role="tab"` holding two buttons).
  4. `/tasks` (the standalone task-manager page, never previously swept):
     color-contrast 2, landmark-one-main 1, page-has-heading-one 1, region 4.

After the fixes all four surfaces measure ZERO, re-measured on the same fixture.

ONE FIX WAS WRONG FIRST, AND THE RE-MEASUREMENT IS WHY IT IS NOT SHIPPED.
Finding 3 was first "fixed" by moving `role="tab"` onto the label button and
marking the wrapper `role="presentation"`. axe then reported
`aria-required-children` instead -- one serious violation traded for another,
because a presentational wrapper's descendants are not promoted into a
tablist's owned set. The shipped form describes the strip as a LIST, which is
what a set of closable analyses actually is. ``test_the_analysis_strip_is_not_a
_tablist_because_a_tab_may_not_own_a_widget`` is the guard that keeps the
rejected form from coming back.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.js_source_helper import (
    assert_absent,
    assert_present,
    function_source,
    read_static,
)

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"


def _css() -> str:
    return read_static("app.css")


def _index() -> str:
    return read_static("index.html")


def _taskmanager() -> str:
    return (_STATIC / "taskmanager.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Help -- links in running text, and scrollable code blocks
# ---------------------------------------------------------------------------

def test_documentation_links_are_not_distinguished_by_colour_alone() -> None:
    """axe link-in-text-block, 23 nodes across the eight Help documents.

    The global rule is ``a { text-decoration:none }``, so a link inside a
    paragraph of prose differed from its surrounding text ONLY by colour --
    WCAG 1.4.1. The fix must reach BOTH populations the sweep found: the five
    in-document links (`.prose`) and the panel's own `/docs` intro link, which
    sits in a `.muted` paragraph OUTSIDE `.prose`.
    """
    css = _css()
    m = re.search(r"^\s*\.prose a[^{]*\{([^}]*)\}", css, re.M)
    assert m, "the .prose anchor rule is gone"
    decl = m.group(1)
    assert "text-decoration:underline" in decl.replace(" ", ""), (
        "prose links must carry a non-colour distinction (WCAG 1.4.1); "
        f"the rule now reads: {decl.strip()}"
    )
    assert "#tab-help a" in m.group(0), (
        "the Help panel's own intro link (the /docs Swagger anchor) is not inside "
        ".prose, so a .prose-only rule leaves one of the measured nodes unfixed"
    )


def test_scrollable_code_blocks_and_tables_are_reachable_by_keyboard() -> None:
    """axe scrollable-region-focusable, 11 nodes, every one a ``<pre>``.

    ``.prose pre`` and ``.prose table`` are declared ``overflow-x:auto`` and hold
    no focusable child, so a keyboard-only reader could not scroll a wide code
    block at all. ``tabindex="0"`` is the rule's own remedy.
    """
    css = _css()
    assert "overflow-x:auto" in css, "the premise changed: .prose no longer scrolls"
    src = function_source(read_static("app-settings.js"), "mdToHtml")
    assert_present(src, '<pre tabindex="0">',
                   why="a scrollable code block must be a tab stop")
    assert_present(src, '<table tabindex="0">',
                   why="a .prose table carries the same overflow-x:auto")


# ---------------------------------------------------------------------------
# 2. The command palette's results list
# ---------------------------------------------------------------------------

def test_the_palette_results_list_is_a_tab_stop() -> None:
    """axe scrollable-region-focusable, 1 node (`#pal-list`).

    The rows are plain divs, and the input's arrow keys move the SELECTION
    rather than scrolling the region, so the list itself had no keyboard route.
    """
    html = _index()
    m = re.search(r'<div class="pal-list" id="pal-list"[^>]*>', html)
    assert m, "#pal-list is gone"
    assert 'tabindex="0"' in m.group(0), (
        "the scrollable palette results list must be focusable; found: " + m.group(0)
    )


# ---------------------------------------------------------------------------
# 3. The analysis window's open-tab strip
# ---------------------------------------------------------------------------

def test_the_analysis_strip_entry_does_not_nest_widgets() -> None:
    """axe nested-interactive, 1 node.

    Each strip entry holds an ACTIVATE button and a CLOSE button. Whatever role
    the wrapper carries, it must not be a widget role, or the two buttons are
    nested inside a third interactive element.
    """
    src = function_source(read_static("app-analysis.js"), "_anRenderStrip")
    assert_present(src, 'class="an-tab-label"', why="the activate control is gone")
    assert_present(src, 'class="an-tab-x"', why="the close control is gone")
    assert_absent(src, 'role="tab"',
                  why="a tab is a widget role and this entry contains two buttons")
    assert_present(src, 'role="listitem"',
                   why="the entry needs a non-widget container role")


def test_the_analysis_strip_is_not_a_tablist_because_a_tab_may_not_own_a_widget() -> None:
    """The REJECTED first fix, kept out.

    Moving ``role="tab"`` onto the label button and marking the wrapper
    ``role="presentation"`` was measured raising ``aria-required-children`` --
    axe does not promote a presentational wrapper's descendants into the
    tablist's owned set. Both halves of that form are guarded here so it cannot
    return as a "cleanup".
    """
    html = _index()
    m = re.search(r'<div id="an-tabstrip"[^>]*>', html)
    assert m, "#an-tabstrip is gone"
    assert 'role="list"' in m.group(0), (
        'the strip must be a list, not a tablist; found: ' + m.group(0)
    )
    src = function_source(read_static("app-analysis.js"), "_anRenderStrip")
    assert_absent(src, 'role="presentation"',
                  why="the presentational-wrapper form was measured raising "
                      "aria-required-children and must not come back")
    # The window's OWN subtabs keep the invariant-#18 tablist grammar untouched.
    assert 'id="an-subtabs"' in html, "the analysis window's subtabs are gone"


# ---------------------------------------------------------------------------
# 4. The standalone task-manager page
# ---------------------------------------------------------------------------

def test_the_task_manager_page_dims_text_with_a_colour_not_an_opacity() -> None:
    """axe color-contrast, 2 nodes, measured composited at 2.99:1 (need 4.5).

    The page declared ``.muted { opacity:.6 }``, so ``rgb(140,149,166)``
    composited down to ``rgb(90,97,109)`` on ``rgb(15,18,24)``. An opacity is
    also multiplicative -- an ancestor's opacity dims it again -- where a colour
    is not.
    """
    html = _taskmanager()
    m = re.search(r"^\s*\.muted \{([^}]*)\}", html, re.M)
    assert m, "the task manager's .muted rule is gone"
    decl = m.group(1)
    assert "opacity" not in decl, (
        "secondary text on this page must be dimmed by COLOUR, not opacity "
        f"(that measured 2.99:1); found: {decl.strip()}"
    )
    assert "color:" in decl.replace(" ", "") or "color :" in decl, (
        f"expected a real colour; found: {decl.strip()}"
    )


def test_the_task_manager_page_has_a_main_landmark_and_one_heading() -> None:
    """axe landmark-one-main 1, page-has-heading-one 1, region 4.

    Everything below the header sat in no landmark, so there was nothing to skip
    to and no heading to orient by. ``#tm-tabs`` was flagged despite being a
    ``<nav>`` because ``role="tablist"`` REPLACES the implicit navigation role --
    it stopped being a landmark the moment it became a tablist, which is the part
    a reader is most likely to get wrong.
    """
    html = _taskmanager()
    assert html.count("<main>") == 1 and html.count("</main>") == 1, (
        "the page needs exactly one main landmark"
    )
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    assert h1, "the page has no h1"
    assert "sr-only" in h1.group(0), (
        "the heading is for orientation, not decoration -- it should not add a "
        "visible title bar the page already has"
    )
    assert "data-i18n" in h1.group(0), "the heading must translate like every other string"
    # The four `region` nodes must all end up inside a landmark.
    body = html[html.index("</header>"):]
    main = body[body.index("<main>"):body.index("</main>")]
    for node in ('id="tm-summary"', 'id="tm-tabs"', 'id="p-processes"'):
        assert node in main, f"{node} is still outside the main landmark"
    assert re.search(r'<footer id="tm-foot"', html), (
        "the page footer must be a landmark of its own, not a bare div"
    )


def test_the_task_manager_heading_reuses_an_existing_key() -> None:
    """No new string: "Task manager" is already keyed in all twelve locales.

    Adding a key would have moved the i18n ratchet for a heading that is only
    ever read aloud; reusing the shipped one keeps the gate at 100% untouched.
    """
    import json

    locales = sorted((_STATIC / "locales").glob("*.json"))
    assert len(locales) == 12, f"expected 12 locale files, found {len(locales)}"
    for path in locales:
        data = json.loads(path.read_text(encoding="utf-8"))
        mapping = data.get("map", data)
        assert mapping.get("Task manager"), f"{path.name} has no 'Task manager' key"
