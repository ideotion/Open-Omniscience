"""Explore: Search and the analysis on one sidebar page (R47; 0.5 slice S05-09 S6).

Q1120 = a's Graft 1, confirmed by the maintainer's answer 5 = a on the 2026-09-29 question
list. It supersedes invariant #22's "never a sidebar entry". What may not regress:

- ONE sidebar entry, Explore, and one page holding the search on top and the analysis
  under it; every older entry point (showTab("search"), showTab("analyze"), a #search or
  #analyze link, a Lead, a keyword) lands on it.
- A search with words or a filter renders the analysis of the SAME set under its list,
  with no button to press. A search with neither lists every article and analyses nothing.
- The list and the analysis never silently describe two different sets: an analysis
  opened from elsewhere sets the list aside and says whose analysis is shown.
- Explore is a Ring-1 tab: the dial pins it at Standard and Full, never at Essentials.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import function_body, function_source, read_static

_STATIC = Path(__file__).resolve().parent.parent / "src" / "static"


def test_one_sidebar_entry_opens_one_page_with_both_parts():
    html = read_static("index.html")
    nav = html.split('id="navGroups"', 1)[1].split("</nav>", 1)[0]
    assert nav.count('data-tab="explore"') == 1
    assert 'data-tab="search"' not in nav and 'data-tab="analyze"' not in nav
    page = html.split('<div class="tab-page" id="tab-explore">', 1)[1].split('<div class="tab-page"', 1)[0]
    assert '<div class="explore-part" id="tab-search">' in page
    assert '<div class="explore-part" id="tab-analyze">' in page
    assert page.index('id="tab-search"') < page.index('id="tab-analyze"'), "the search sits above the analysis"
    # The analysis renders on its own: the old "Analyze" button would be a second way to
    # do what the search already did.
    assert "Analyze →" not in page and 'data-on-click="openAnalysis()"' not in page


def test_every_older_entry_point_lands_on_explore():
    shell = read_static("app-shell.js")
    show = function_body(shell, "showTab")
    assert 'if (name === "search" || name === "analyze") name = "explore";' in show
    # The redirect runs before the tab lookup, so neither old name can reach a page of its own.
    assert show.index('name = "explore"') < show.index('document.getElementById("tab-" + name)')
    assert 'if (name === "explore" && !_anHydrated)' in show, "opening Explore hydrates the restored analysis"
    assert 'explore: "an-subtabs"' in shell, "the analysis subtabs ride the top strip on Explore"
    assert re.search(r"explore:\s*\(\)\s*=>\s*buildSearchTimeScope\(\)", shell)


def test_a_search_analyses_its_own_set_and_only_when_there_is_one():
    ana = read_static("app-analysis.js")
    body = function_body(ana, "doSearch")
    assert '["query", "source", "language", "start_date", "end_date"].some((k) => p.get(k))' in body
    assert "_exploreFromSearch = true;" in body and "_anSpawn(seed);" in body
    assert "finally { _exploreFromSearch = false; }" in body, "the flag cannot stay set after a failure"
    assert "_exploreListAll = true;" in body, "an empty search lists everything and analyses nothing"
    # The analysis is spawned only after the list has rendered, never in place of it.
    assert body.index("annotateArticleDups(p, t);") < body.index("_anSpawn(seed);")
    # The seed is taken when the search is CALLED, so the analysis is of the set listed,
    # and an older answer that lands after a newer search is dropped rather than drawn.
    assert body.index("const seed = _searchSeed();") < body.index("await api(")
    assert body.count("if (seq !== _searchSeq) return;") == 2, "both the answer and the failure of a stale search"
    assert "return _anSpawn(_searchSeed());" in function_body(ana, "openAnalysis")


def test_a_background_refresh_never_spawns_or_switches_the_analysis():
    """doSearch also re-lists in the background (an ingest finishing, a restore). On
    Explore that must not add a tab or switch away from the analysis being read."""
    body = function_body(read_static("app-analysis.js"), "doSearch")
    assert "if (!refresh) _searchSpawnDue = true;" in body
    assert "if (spawn && onExplore && hasSet)" in body
    for name, calls in (("app-sources.js", 4), ("app-backup.js", 1)):
        src = read_static(name)
        assert src.count("doSearch({refresh: true})") == calls, name
        assert "doSearch()" not in src, f"{name} re-lists without saying it is a refresh"


def test_dragging_the_date_range_does_not_open_a_tab_per_step():
    ana = read_static("app-analysis.js")
    build = function_body(ana, "buildSearchTimeScope")
    assert "clearTimeout(_searchTsTimer);" in build and "setTimeout(() => doSearch(), 350)" in build


def test_refining_the_searchs_own_tab_sets_the_list_aside():
    """Advanced search refines the active tab IN PLACE, changing its key: the list above
    still describes the old set, so Explore must re-sync."""
    run = function_body(read_static("app-analysis.js"), "anRunAdvanced")
    assert run.index("key: _advTabKey(q, adv)") < run.index("_exploreSync();")


def test_the_overview_draws_when_an_analysis_opens_onto_it():
    """select("overview") runs before loadAnalysis has params, and anSelectTab returns early
    without them: the landing subtab drew nothing until another subtab was visited and left.
    Under Explore it sits beneath a search the reader just ran, so it must draw on arrival."""
    ana = read_static("app-analysis.js")
    load = function_body(ana, "loadAnalysis")
    assert 'if ($("an-overview") && $("an-overview").style.display !== "none") setTimeout(() => renderAnOverview(p), 0);' in load
    assert load.index("_anLastParams = p;") < load.index("renderAnOverview(p)"), "params exist before it draws"


def test_the_page_stays_put_for_its_own_search_and_scrolls_for_an_outside_one():
    ana = read_static("app-analysis.js")
    act = function_body(ana, "_anActivate")
    assert 'if (!onExplore) showTab("explore");' in act
    assert "if (!onExplore && !_exploreFromSearch)" in act and "scrollIntoView" in act


_SYNC_HARNESS = r"""
const els = {};
function mk(id) { return els[id] = { id, hidden: false, textContent: "" }; }
mk("search-out"); mk("explore-note");
function $(id) { return els[id] || null; }
const window = {};
let _anActiveId = null, _anTabs = [];
let _exploreSearchKey = null, _exploreListAll = false, _exploreFromSearch = false;
__SYNC__
const out = [];
function snap(tag) { out.push([tag, els["search-out"].hidden, els["explore-note"].hidden, els["explore-note"].textContent]); }
_exploreSync(); snap("no analysis");
_anTabs = [{id: "a", key: "q:climate", label: "climate"}]; _anActiveId = "a";
_exploreSearchKey = "q:climate"; _exploreSync(); snap("own search");
_anTabs.push({id: "b", key: "ids:lead", label: "A Lead"}); _anActiveId = "b";
_exploreSync(); snap("outside analysis");
_anActiveId = "a"; _exploreSync(); snap("back to own");
_exploreSearchKey = null; _exploreListAll = true; _anActiveId = "b"; _exploreSync(); snap("list all");
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_the_list_is_set_aside_only_while_it_describes_another_set(tmp_path):
    src = function_source(read_static("app-analysis.js"), "_exploreSync")
    script = tmp_path / "explore_sync.js"
    script.write_text(_SYNC_HARNESS.replace("__SYNC__", src), encoding="utf-8")
    r = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr
    rows = {tag: (out_hidden, note_hidden, text) for tag, out_hidden, note_hidden, text in json.loads(r.stdout)}
    assert rows["no analysis"][:2] == (False, True)
    assert rows["own search"][:2] == (False, True), "a search and its own analysis read as one set"
    out_hidden, note_hidden, text = rows["outside analysis"]
    assert out_hidden and not note_hidden and "“A Lead”" in text, "another set's analysis sets the list aside, and says so"
    assert rows["back to own"][:2] == (False, True), "nothing is lost: the list comes back with its own analysis"
    out_hidden, note_hidden, text = rows["list all"]
    assert not out_hidden and not note_hidden and text.startswith("The list above is every article.")


def test_explore_is_a_ring_one_tab():
    shell = read_static("app-shell.js")
    assert 'const RING0_TABS = ["home", "feed"];' in shell, "Explore is pinned at Standard and Full, not Essentials"


def test_the_insights_term_explorer_no_longer_shares_the_name():
    html = read_static("index.html")
    ins = html.split('id="ins-subtabs"', 1)[1].split("</nav>", 1)[0]
    assert '<button class="active" data-tab="explore">Keyword explorer</button>' in ins
    assert ">Explore<" not in ins


def test_every_new_string_is_keyed_x12():
    ana = read_static("app-analysis.js")
    sync = function_body(ana, "_exploreSync")
    keys = re.findall(r'tf\("([^"]+)"', sync) + ["Explore", "Keyword explorer"]
    assert len(keys) == 4
    for p in sorted((_STATIC / "locales").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        for k in keys:
            assert d.get(k, "").strip(), f"{p.name} has no key {k!r}"
            assert sorted(re.findall(r"\{(\w+)\}", d[k])) == sorted(re.findall(r"\{(\w+)\}", k))
