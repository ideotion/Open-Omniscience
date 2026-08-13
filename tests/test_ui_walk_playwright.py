"""
PlaywrightUiWalkDriver tests (0.3 gate row 8) — proves the REAL driver's navigation grammar,
console-error separation, and screenshot capture against a real Chromium instance, using a small
synthetic fixture page that reproduces the exact structural pattern the SPA uses (a top-level
nav, a relocated ``#subtab-strip``, a folded ``<details data-adv>`` section, a trigger button) —
never a hand-typed re-description of app.js's logic, so the driver's own click sequence is what
is under test, not a copy of it. The full live app is exercised separately by the actual
click-through run (see ``scripts/ui_clickthrough_run.py``); these tests are hermetic and fast,
and are what proves the driver's MECHANISM works before it is trusted against the real SPA.

Fixture content is injected via Playwright's ``page.set_content()``, never a hand-rolled
``data:text/html,`` URL — a raw ``#`` anywhere in the HTML/CSS/JS (this fixture uses several, in
CSS id-selectors and JS ``querySelector`` calls) is a URL FRAGMENT delimiter, so a ``data:`` URL
silently truncates the "page" at the first one, and a percent-escaping pass over the WHOLE string
just moves the corruption to whatever character it collides with next. ``set_content()`` has none
of this: it hands the browser real markup through CDP, no URL encoding involved.

Skip-guarded: this whole file is skipped (never a fabricated pass) if `playwright` is absent or
no Chromium build is reachable — the same convention as the sandboxed-crypto skip-guarded tests
elsewhere in this repo. The `uiwalk` extra is optional; a core install is unaffected.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")

from src.monitoring.ui_walk import Surface  # noqa: E402
from src.monitoring.ui_walk_playwright import PlaywrightUiWalkDriver  # noqa: E402

_CHROMIUM_PATH = os.environ.get("OO_TEST_CHROMIUM_PATH")
if not _CHROMIUM_PATH:
    # Fall back to the pinned build this environment ships (see the module docstring: the
    # extra pins the client library only, never a browser).
    _browsers_dir = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
    for _candidate in sorted(_browsers_dir.glob("chromium-*/chrome-linux/chrome")):
        _CHROMIUM_PATH = str(_candidate)
        break

pytestmark = pytest.mark.skipif(
    not _CHROMIUM_PATH or not Path(_CHROMIUM_PATH).exists(),
    reason="no pinned Chromium build reachable -- set OO_TEST_CHROMIUM_PATH or install one under "
    "PLAYWRIGHT_BROWSERS_PATH (never `playwright install`, which fetches one over the network)",
)


# A hermetic fixture reproducing the SPA's REAL navigation shape: a top-level `.nav-item`, a
# `_relocateSubtabs`-style shared `#subtab-strip` that a subtab nav gets moved INTO on tab
# select, a folded `<details data-adv>` section, and a trigger button that reveals content —
# exactly the four steps `PlaywrightUiWalkDriver.goto()` performs, so this fixture is what proves
# the click SEQUENCE, not merely that `page.click` works.
_NAV_FIXTURE_HTML = """
<!doctype html>
<html><body>
<nav>
  <button class="nav-item" data-tab="home" onclick="showTab('home')">Home</button>
  <button class="nav-item" data-tab="settings" onclick="showTab('settings')">Settings</button>
</nav>
<div id="subtab-strip"></div>
<nav id="set-subtabs" style="display:none">
  <button data-tab="graphics" onclick="selectSub('graphics')">Graphics</button>
  <button data-tab="advanced" onclick="selectSub('advanced')">Advanced</button>
</nav>
<div class="tab-page" id="tab-home">Home content</div>
<div class="tab-page" id="tab-settings" style="display:none">
  <div id="set-graphics">Graphics panel</div>
  <div id="set-advanced" style="display:none">
    <details data-adv="sources">
      <summary>Sources</summary>
      <div id="src-table">the sources table</div>
    </details>
  </div>
  <button id="trigger-btn" onclick="document.getElementById('opened-thing').style.display=''">
    Open a dialog
  </button>
  <div id="opened-thing" style="display:none">opened content</div>
</div>
<script>
  function showTab(name) {
    document.querySelectorAll('.tab-page').forEach(function (p) {
      p.style.display = (p.id === 'tab-' + name) ? '' : 'none';
    });
    // _relocateSubtabs-style: move THIS tab's own subtab nav into the shared strip.
    var strip = document.getElementById('subtab-strip');
    if (name === 'settings') {
      var nav = document.getElementById('set-subtabs');
      strip.appendChild(nav);
      nav.style.display = '';
    } else {
      strip.innerHTML = '';
    }
  }
  function selectSub(name) {
    document.querySelectorAll('#tab-settings > div[id^="set-"]').forEach(function (v) {
      v.style.display = (v.id === 'set-' + name) ? '' : 'none';
    });
  }
  function setTheme(t) { document.body.setAttribute('data-test-theme', t); }
  window.OOI18N = { setLang: function (c) { document.body.setAttribute('data-test-lang', c); } };
</script>
</body></html>
"""


@contextlib.contextmanager
def _new_driver(tmp_path=None, *, greyscale=False):
    """Launches a fresh browser/page/driver and yields it, tearing everything down (browser
    THEN the Playwright driver subprocess) before returning control to the caller. A proper
    nested ``with`` block matters here, not just style: two ``sync_playwright()`` instances
    entered back-to-back in the SAME thread without the first one FULLY exiting (its own
    ``with`` block closed) intermittently raise "using Playwright Sync API inside the asyncio
    loop" on the second -- reproduced live when this helper used manual
    ``cm.__enter__()``/``cm.__exit__()`` instead of a real ``with``."""
    with playwright_sync.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=_CHROMIUM_PATH)
        try:
            page = browser.new_page()
            driver = PlaywrightUiWalkDriver(
                page, base_url="", screenshot_dir=tmp_path, greyscale=greyscale
            )
            yield driver
        finally:
            browser.close()


@pytest.fixture
def driver(tmp_path):
    with _new_driver(tmp_path) as d:
        d.page.set_content(_NAV_FIXTURE_HTML)
        yield d


def test_goto_clicks_through_nav_tab_subtab_and_advanced_section(driver):
    surface = Surface(
        "sources_test",
        "Sources (test fixture)",
        nav_tab="settings",
        subtab="advanced",
        advanced_section="sources",
        dom_id="src-table",
    )
    assert driver.is_visible("src-table") is False  # not on settings yet
    driver.goto(surface)
    assert driver.is_visible("src-table") is True
    # the details element must actually be OPEN, not merely present in the DOM (a closed
    # <details>'s content has no rendered box, so is_visible() would already catch this --
    # this assertion pins the MECHANISM, not just the outcome).
    is_open = driver.page.eval_on_selector('details[data-adv="sources"]', "el => el.open")
    assert is_open is True


def test_goto_clicks_an_optional_trigger_after_navigating(driver):
    surface = Surface(
        "trigger_test",
        "Trigger (test fixture)",
        nav_tab="settings",
        trigger="#trigger-btn",
        dom_id="opened-thing",
    )
    assert driver.is_visible("opened-thing") is False
    driver.goto(surface)
    assert driver.is_visible("opened-thing") is True


def test_is_visible_false_for_a_nonexistent_dom_id_never_raises(driver):
    assert driver.is_visible("this-id-does-not-exist-anywhere") is False


# A SECOND fixture reproducing the real app's ACTUAL current shape for "analyze"/"settings" as
# found live 2026-08-13 (see ui_walk.py's module docstring): NEITHER carries a
# `.nav-item[data-tab=...]` at all. Settings opens via a footer gear button whose ONLY identifying
# trait is its `onclick`; the analysis window has no click target whatsoever -- it is reached
# purely by calling `openAnalysisFor(query)`, the same function a keyword-chip click or the
# omnibar's Enter invokes, which internally calls `showTab('analyze')` itself (mirroring the
# real app's `_anSpawn` -> `_anActivate` -> `showTab` chain).
_NO_NAV_ITEM_FIXTURE_HTML = """
<!doctype html>
<html><body>
<nav>
  <button class="nav-item" data-tab="home" onclick="showTab('home')">Home</button>
  <!-- deliberately NO .nav-item for settings or analyze -- matches the real app. -->
</nav>
<div class="sb-foot">
  <button onclick="showTab('settings')" title="Open Settings">gear</button>
</div>
<div class="tab-page" id="tab-home">Home content</div>
<div class="tab-page" id="tab-settings" style="display:none">settings panel</div>
<div class="tab-page" id="tab-analyze" style="display:none">
  <div id="an-query"></div>
</div>
<script>
  function showTab(name) {
    document.querySelectorAll('.tab-page').forEach(function (p) {
      p.style.display = (p.id === 'tab-' + name) ? '' : 'none';
    });
  }
  // Mirrors _anSpawn -> _anActivate -> showTab('analyze') for a query-seeded open.
  function openAnalysisFor(query) {
    showTab('analyze');
    document.getElementById('an-query').textContent = query || '';
  }
</script>
</body></html>
"""


@pytest.fixture
def no_nav_item_driver(tmp_path):
    with _new_driver(tmp_path) as d:
        d.page.set_content(_NO_NAV_ITEM_FIXTURE_HTML)
        yield d


def test_goto_reaches_settings_via_the_gear_button_with_no_nav_item_at_all(no_nav_item_driver):
    # The negative-space half: prove the OLD assumption (a `.nav-item[data-tab="settings"]`
    # click) would find nothing on this fixture -- so the fix is doing real work, not papering
    # over a selector that would have matched anyway.
    assert no_nav_item_driver.page.locator('.nav-item[data-tab="settings"]').count() == 0
    surface = Surface("settings_test", "Settings (test fixture)", nav_tab="settings",
                       dom_id="tab-settings")
    assert no_nav_item_driver.is_visible("tab-settings") is False
    no_nav_item_driver.goto(surface)
    assert no_nav_item_driver.is_visible("tab-settings") is True


def test_goto_reaches_analyze_via_openanalysisfor_with_no_click_target_at_all(no_nav_item_driver):
    # Same negative-space proof for "analyze": no nav-item, no button, nothing to click --
    # openAnalysisFor(search_query) is the ONLY path in, exactly like the real app.
    assert no_nav_item_driver.page.locator('.nav-item[data-tab="analyze"]').count() == 0
    surface = Surface("analysis_test", "Analysis (test fixture)", nav_tab="analyze",
                       search_query="election", dom_id="tab-analyze")
    assert no_nav_item_driver.is_visible("tab-analyze") is False
    no_nav_item_driver.goto(surface)
    assert no_nav_item_driver.is_visible("tab-analyze") is True
    seen_query = no_nav_item_driver.page.eval_on_selector(
        "#an-query", "el => el.textContent"
    )
    assert seen_query == "election"


def test_goto_analyze_defaults_to_an_empty_search_query(no_nav_item_driver):
    # The Surface default (search_query="") must reach openAnalysisFor as an empty string --
    # the "whole corpus, no filter" case -- never a placeholder/None that could confuse the
    # real app's own `(query || "").trim()` handling.
    surface = Surface("analysis_default", "Analysis (default query)", nav_tab="analyze",
                       dom_id="tab-analyze")
    no_nav_item_driver.goto(surface)
    seen_query = no_nav_item_driver.page.eval_on_selector("#an-query", "el => el.textContent")
    assert seen_query == ""


# A THIRD fixture: a trigger that opens a REAL native modal dialog (``.showModal()``, which
# installs the browser's own pointer-blocking backdrop -- a plain `open` attribute does NOT
# block anything, so this must call showModal() to reproduce the real failure). Found live
# 2026-08-13: a walk that clicks a trigger opening `<dialog id="ux-import">` and then moves to
# the NEXT surface without closing it times out on every step after, because the open dialog's
# backdrop intercepts pointer events on the whole page.
_DIALOG_FIXTURE_HTML = """
<!doctype html>
<html><body>
<nav>
  <button class="nav-item" data-tab="home" onclick="showTab('home')">Home</button>
  <button class="nav-item" data-tab="other" onclick="showTab('other')">Other</button>
</nav>
<div class="tab-page" id="tab-home">
  <button id="open-dialog-btn" onclick="document.getElementById('my-dialog').showModal()">
    Open a dialog
  </button>
</div>
<div class="tab-page" id="tab-other" style="display:none">Other content</div>
<dialog id="my-dialog"><p>dialog content</p></dialog>
<script>
  function showTab(name) {
    document.querySelectorAll('.tab-page').forEach(function (p) {
      p.style.display = (p.id === 'tab-' + name) ? '' : 'none';
    });
  }
</script>
</body></html>
"""


def test_goto_closes_a_leftover_open_dialog_before_navigating():
    with _new_driver() as d:
        d.page.set_content(_DIALOG_FIXTURE_HTML)
        # Surface 1: on "home", click the trigger that opens a real showModal() dialog.
        d.goto(Surface("open_dialog", "Open a dialog", nav_tab="home",
                        trigger="#open-dialog-btn", dom_id="my-dialog"))
        assert d.page.locator("dialog[open]").count() == 1
        # Surface 2: a PLAIN nav-item click on a different tab. Without the fix this times out
        # (the modal backdrop intercepts the click) -- prove it succeeds and the dialog is gone.
        d.goto(Surface("other_tab", "Other", nav_tab="other", dom_id="tab-other"))
        assert d.is_visible("tab-other") is True
        assert d.page.locator("dialog[open]").count() == 0


# A FOURTH fixture: two DIFFERENT tabs' subtab navs sharing the SAME data-tab value ("shared"),
# reproducing the real app's stale-sibling-in-#subtab-strip shape (a prior relocation is set
# display:none and left behind rather than removed, so a plain selector can resolve to more
# than one element once two tabs have been visited).
_STALE_SIBLING_FIXTURE_HTML = """
<!doctype html>
<html><body>
<nav>
  <button class="nav-item" data-tab="alpha" onclick="showTab('alpha')">Alpha</button>
  <button class="nav-item" data-tab="beta" onclick="showTab('beta')">Beta</button>
</nav>
<div id="subtab-strip"></div>
<nav id="alpha-subtabs" style="display:none">
  <button data-tab="shared" onclick="void(0)">Alpha's shared-named subtab</button>
</nav>
<nav id="beta-subtabs" style="display:none">
  <button data-tab="shared" onclick="document.getElementById('beta-target').style.display=''">
    Beta's shared-named subtab
  </button>
</nav>
<div class="tab-page" id="tab-alpha">alpha content</div>
<div class="tab-page" id="tab-beta" style="display:none">
  <div id="beta-target" style="display:none">the real beta content</div>
</div>
<script>
  function showTab(name) {
    document.querySelectorAll('.tab-page').forEach(function (p) {
      p.style.display = (p.id === 'tab-' + name) ? '' : 'none';
    });
    // Mirrors the REAL app (confirmed live, 2026-08-13: driving app.js and reading
    // #subtab-strip's innerHTML afterwards): relocate the tab's OWN nav into the strip,
    // but hide -- never remove -- whatever nav was already sitting there from a PRIOR
    // relocation, so it survives in the DOM as a display:none sibling.
    var strip = document.getElementById('subtab-strip');
    Array.prototype.forEach.call(strip.children, function (child) {
      child.style.display = 'none';
    });
    var nav = document.getElementById(name + '-subtabs');
    strip.appendChild(nav);
    nav.style.display = '';
  }
</script>
</body></html>
"""


def test_goto_subtab_click_is_scoped_to_the_visible_nav_only():
    with _new_driver() as d:
        d.page.set_content(_STALE_SIBLING_FIXTURE_HTML)
        # Visit alpha first (relocates alpha-subtabs into the strip).
        d.goto(Surface("alpha", "Alpha", nav_tab="alpha", dom_id="tab-alpha"))
        # Now visit beta's "shared"-named subtab. #subtab-strip now contains BOTH alpha-subtabs
        # (display:none, left behind) and beta-subtabs (visible) -- a selector with no
        # visibility scoping would match alpha's stale button first (DOM order) and either
        # click the wrong (invisible) element or time out waiting for it to become visible.
        d.goto(Surface("beta_shared", "Beta > shared", nav_tab="beta", subtab="shared",
                        dom_id="beta-target"))
        assert d.is_visible("beta-target") is True


# A FIFTH scenario: a `url`-based surface (the standalone /tasks page) performs a REAL
# navigation away from the SPA -- found live 2026-08-13: a `nav_tab`-based surface visited
# right after one then silently no-ops (openAnalysisFor is simply undefined on the "wrong"
# page, and the driver's own defensive `typeof === 'function'` guard swallows that). Two
# genuinely separate pages are needed to test this (set_content() only ever replaces the
# CURRENT document, it cannot simulate navigating AWAY to a different URL) -- page.route()
# intercepts requests to a fake origin and serves each "page" hermetically, no real network.
_FAKE_ORIGIN = "http://ui-walk-fixture.invalid"
_SPA_PAGE_HTML = (
    "<!doctype html><html><body>"
    '<nav><button class="nav-item" data-tab="home" onclick="showTab(\'home\')">Home</button></nav>'
    '<div class="tab-page" id="tab-home">home content</div>'
    "<script>function showTab(name){"
    "document.querySelectorAll('.tab-page').forEach(function(p){"
    "p.style.display=(p.id==='tab-'+name)?'':'none';});}"
    "function openAnalysisFor(q){showTab('home');}"  # stands in for the real function
    "</script></body></html>"
)
_TASKS_PAGE_HTML = "<!doctype html><html><body>a totally different static page</body></html>"


@contextlib.contextmanager
def _spa_and_tasks_driver():
    with playwright_sync.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=_CHROMIUM_PATH)
        try:
            page = browser.new_page()

            def _fulfil(route):
                url = route.request.url
                body = _TASKS_PAGE_HTML if url.endswith("/tasks") else _SPA_PAGE_HTML
                route.fulfill(status=200, content_type="text/html", body=body)

            page.route(f"{_FAKE_ORIGIN}/**", _fulfil)
            driver = PlaywrightUiWalkDriver(page, base_url=_FAKE_ORIGIN)
            yield driver
        finally:
            browser.close()


def test_goto_restores_the_spa_after_a_url_based_surface_navigates_away():
    with _spa_and_tasks_driver() as d:
        d.goto(Surface("tasks", "Task manager", url="/tasks", dom_id="tm-tabs"))
        assert "a totally different static page" in d.page.content()
        # Without the fix, this would silently no-op (openAnalysisFor undefined on this page)
        # -- prove the SPA is restored and the surface is genuinely reached.
        d.goto(Surface("home_after_tasks", "Home", nav_tab="home", dom_id="tab-home"))
        assert d.is_visible("tab-home") is True


def test_ensure_on_spa_is_a_noop_when_already_on_the_spa_root():
    # The negative-space companion: when nothing navigated away, _ensure_on_spa must not
    # perform an unnecessary reload (which would lose in-page state a real reload would too).
    with _spa_and_tasks_driver() as d:
        d.goto(Surface("home_first", "Home", nav_tab="home", dom_id="tab-home"))
        d.page.evaluate("document.title = 'marker-not-reloaded'")
        d.goto(Surface("home_again", "Home again", nav_tab="home", dom_id="tab-home"))
        assert d.page.evaluate("document.title") == "marker-not-reloaded"


def test_goto_requires_nav_tab_or_url(driver):
    # A surface with neither must raise loudly (never silently do nothing) -- this is a
    # construction-error, not a "not found" case, so it is asserted at goto() time.
    bad = Surface("bad", "Bad surface", dom_id="tab-home")  # no nav_tab, no url
    try:
        driver.goto(bad)
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_pageerror_always_fails_the_step_and_is_never_conflated_with_console_noise():
    with _new_driver() as d:
        d.page.set_content(
            "<!doctype html><html><body>ok"
            "<script>throw new Error('deliberate test pageerror');</script>"
            "</body></html>"
        )
        d.page.wait_for_timeout(100)
        errors = d.console_errors()
        assert any("deliberate test pageerror" in e for e in errors)
        summary = d.console_error_summary()
        assert summary["pageerror"] == 1
        assert summary["console_error_real"] == 0


def test_the_documented_429_noise_is_filtered_from_console_errors_but_still_counted_separately():
    with _new_driver() as d:
        d.page.set_content(
            "<!doctype html><html><body>ok"
            "<script>console.error("
            "'Failed to load resource: the server responded with a status of "
            "429 (Too Many Requests)');</script>"
            "</body></html>"
        )
        d.page.wait_for_timeout(100)
        # the FILTERED list (what a walk step's pass/fail is judged on) must be empty -- this
        # is the exact defect the 2026-07-22 audit's own methodology caveat warns against:
        # treating rate-limit console noise as a real failure would manufacture a false crisis.
        errors = d.console_errors()
        assert errors == []
        # but the RAW line must still be visible on the summary -- honesty requires the noise
        # be counted, not silently discarded from the record entirely.
        summary = d.console_error_summary()
        assert summary["console_error_total"] == 1
        assert summary["console_error_noise_429"] == 1
        assert summary["console_error_real"] == 0


def test_a_genuine_console_error_still_fails_the_step():
    with _new_driver() as d:
        d.page.set_content(
            "<!doctype html><html><body>ok"
            "<script>console.error('TypeError: x is undefined');</script>"
            "</body></html>"
        )
        d.page.wait_for_timeout(100)
        errors = d.console_errors()
        assert any("TypeError: x is undefined" in e for e in errors)
        summary = d.console_error_summary()
        assert summary["console_error_real"] == 1
        assert summary["console_error_noise_429"] == 0


def test_screenshot_writes_a_file_and_returns_its_path(driver, tmp_path):
    surface = Surface("home_test", "Home (test fixture)", dom_id="tab-home")
    path = driver.screenshot(surface)
    assert path is not None
    assert Path(path).exists()
    assert Path(path).stat().st_size > 0


def test_screenshot_returns_none_when_no_screenshot_dir_configured():
    with _new_driver() as d:  # no tmp_path -> screenshot_dir=None
        d.page.set_content("<!doctype html><html><body>ok</body></html>")
        assert d.screenshot(Surface("x", "X", dom_id="tab-home")) is None


def test_greyscale_applies_a_real_document_level_filter():
    # Content must be set BEFORE the driver applies the filter -- set_content() replaces the
    # whole document (a fresh documentElement), so a filter applied to an about:blank page and
    # then wiped by a later set_content() would prove nothing about the real code path (in real
    # use the driver's __init__ applies the filter AFTER its own auto-boot navigation, never
    # before content exists).
    with playwright_sync.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=_CHROMIUM_PATH)
        try:
            page = browser.new_page()
            page.set_content("<!doctype html><html><body>ok</body></html>")
            d = PlaywrightUiWalkDriver(page, base_url="", greyscale=True)
            d.page.wait_for_timeout(50)
            filt = d.page.evaluate("getComputedStyle(document.documentElement).filter")
            assert "grayscale" in filt
        finally:
            browser.close()


def test_set_theme_calls_the_pages_own_global_settheme(driver):
    driver.set_theme("mint")
    val = driver.page.evaluate("document.body.getAttribute('data-test-theme')")
    assert val == "mint"


def test_set_locale_calls_the_pages_own_ooi18n_setlang(driver):
    driver.set_locale("ar")
    val = driver.page.evaluate("document.body.getAttribute('data-test-lang')")
    assert val == "ar"


def test_computed_style_returns_real_values_never_declared_css(driver):
    driver.page.evaluate("document.getElementById('tab-home').style.color = 'rgb(1, 2, 3)'")
    style = driver.computed_style("#tab-home")
    assert style["color"] == "rgb(1, 2, 3)"


def test_computed_style_returns_empty_dict_for_a_missing_selector_never_raises(driver):
    assert driver.computed_style("#does-not-exist") == {}


def test_computed_style_can_read_a_pseudo_element():
    # This is the exact mechanism behind two real shipped defects (CLAUDE.md): an `::after`
    # inherits every property it does not itself declare from a lower-specificity rule that
    # also matches, and this is invisible to reading source CSS -- only getComputedStyle(el,
    # '::after') catches it. Prove computed_style() can read the pseudo-element at all.
    html = (
        "<!doctype html><html><head><style>"
        ".a::after{content:'x'} .b::after{content:'x';width:4px} #target::after{}"
        "</style></head><body>"
        "<div id='target' class='a b'></div>"
        "</body></html>"
    )
    with _new_driver() as d:
        d.page.set_content(html)
        style = d.computed_style("#target", pseudo="::after")
        assert style["width"] == "4px"  # inherited from .b, invisible in #target's own rule
