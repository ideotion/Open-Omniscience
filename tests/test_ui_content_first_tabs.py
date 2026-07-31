"""Content-first absorption guard: Sources + Wikipedia live in Settings, not the sidebar.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Invariant #8 (the UI shows DATA, never plumbing): the former "Sources" and
"Wikipedia" sidebar tabs are dissolved into Settings -> Sources / Settings ->
Wikipedia. This is the Desk-lesson absorption guard -- it proves (a) the sidebar
no longer carries those tabs, (b) showTab() reroutes the legacy names into
Settings, and (c) EVERY control that moved still resolves inside the Settings
panels (nothing was silently lost). Pure string-assertion wiring guards over the
static assets so they run in the sandbox and CI (browser-unverified per fork-3).
"""

from __future__ import annotations

import re
from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_HTML = (_STATIC / "index.html").read_text(encoding="utf-8")
_JS = (_STATIC / "app.js").read_text(encoding="utf-8")


def _sidebar_nav() -> str:
    """Just the primary sidebar <nav id="navGroups"> ... </nav> region.

    data-tab="sources" also appears in the analysis/insights/corpus facet navs, so
    the absorption assertion MUST be scoped to the sidebar, not the whole document.
    """
    m = re.search(r'<nav[^>]*id="navGroups".*?</nav>', _HTML, re.S)
    assert m, "the primary sidebar nav #navGroups must exist"
    return m.group(0)


def test_sidebar_has_no_sources_or_wikipedia_tab():
    nav = _sidebar_nav()
    assert 'data-tab="sources"' not in nav, "Sources must not be a sidebar tab (moved to Settings)"
    assert 'data-tab="wikipedia"' not in nav, "Wikipedia must not be a sidebar tab (moved to Settings)"
    assert 'data-tab="wiki"' not in nav, "the legacy Wikipedia tab must not be in the sidebar"


def test_no_top_level_sources_or_wiki_page_survives():
    # The whole tab-page never existed post-move; a stray one would re-introduce plumbing.
    assert 'id="tab-sources"' not in _HTML
    assert 'id="tab-wiki"' not in _HTML


def test_showtab_reroutes_legacy_names_into_settings():
    """showTab("sources")/showTab("wiki") land on Settings at the right place.

    2026-07-31: Sources moved into Advanced, so its redirect selects Advanced AND opens
    the section (_openAdvanced) rather than selecting a subtab that no longer exists. This
    is the guard that would have caught the deep-link landing on nothing."""
    assert 'if (name === "sources")' in _JS
    assert 'if (name === "wiki")' in _JS
    assert '_openAdvanced("sources")' in _JS
    assert '_setSubtabs.select("wikipedia")' in _JS


def test_settings_subtabs_expose_sources_and_wikipedia():
    """2026-07-31 (Settings review): Sources stopped being its own subtab and became a
    folded section of Advanced. What this guards is that both destinations are REACHABLE
    from the subtab strip, so the check follows Sources to its new address rather than
    pinning a subtab name that the restructure deliberately retired."""
    m = re.search(r'<nav[^>]*id="set-subtabs".*?</nav>', _HTML, re.S)
    assert m, "the Settings subtab nav #set-subtabs must exist"
    strip = m.group(0)
    assert 'data-tab="advanced"' in strip
    assert 'data-adv="sources"' in _HTML, "Sources must be reachable as an Advanced section"
    assert 'data-tab="wikipedia"' in strip


def test_sources_panel_absorbs_every_moved_control():
    # The source-management toolkit that left the sidebar now lives in Advanced → Sources.
    # The absorption list below is the point of the test and is unchanged.
    assert 'data-adv="sources"' in _HTML
    for ident in ("s-name", "s-domain", "s-rss", "s-tags", "src-table", "src-search",
                  "candidates-panel", "imp-file"):
        assert f'"{ident}"' in _HTML or f"id={ident}" in _HTML or ident in _HTML, (
            f"the moved Sources control '{ident}' must still resolve in Settings"
        )
    assert "addSource()" in _HTML and "seedDefaults()" in _HTML and "importSources()" in _HTML


def test_wikipedia_panel_absorbs_every_moved_control():
    # #set-wikipedia must carry the change-tracking + watch + offline-dump toolkit.
    assert 'id="set-wikipedia"' in _HTML
    for ident in ("wiki-status", "wiki-lang", "wiki-title", "wiki-pages", "wiki-changes",
                  "dump-lang", "dump-table", "dumpread-title"):
        assert ident in _HTML, f"the moved Wikipedia control '{ident}' must still resolve in Settings"
    assert "trackWikiNow()" in _HTML and "addWikiPage()" in _HTML and "startDump()" in _HTML
