"""R52's lane hits in the one search box and the Search tab, and the window that adds ONE
version to the corpus.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The renderers are driven in node (``tests/lane_version_node_test.js``); this file pins the
wiring those renderers cannot see: the palette group, the dialog's markup, the language
switch, and the words the tables hand to ``t()``, which the literal ``t("...")`` gate cannot
see either.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import function_body, object_literal, read_static, strip_comments

_ROOT = Path(__file__).resolve().parent.parent
_LOCALES = _ROOT / "src" / "static" / "locales"


def _locales() -> dict[str, dict]:
    out = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in _LOCALES.glob("*.json")}
    assert len(out) == 12
    return out


def _dialog_html() -> str:
    html = read_static("index.html")
    at = html.index('<dialog id="lane-version"')
    return html[at : html.index("</dialog>", at) + len("</dialog>")]


def _search_tab_html() -> str:
    html = read_static("index.html")
    at = html.index('<div class="tab-page" id="tab-search">')
    return html[at : html.index('<div class="tab-page"', at + 1)]


def test_the_renderers_behave():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "lane_version_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout


def test_the_palette_shows_lane_hits_beside_the_corpus_hits_even_with_no_page_hit():
    """A held text can match where no watched page's title or local copy does, so the
    Wikipedia group must not return early on an empty page list when the lane has hits."""
    body = strip_comments(function_body(read_static("app-shell.js"), "_omniItems"))
    assert "laneOmniRows(g.lane, t)" in body
    assert "if (!items.length && !laneRows.length) return;" in body
    assert 't("Wikipedia texts held on this machine")' in body, "the rows are not marked as Wikipedia"


def test_the_window_has_no_inline_handler_and_its_composed_lines_own_their_language():
    dialog = _dialog_html()
    assert not re.search(r"\son[a-z]+=", dialog), "an inline handler in the new dialog (S05-09)"
    for dyn in ("lv-title", "lv-meta", "lv-notes", "lv-out", "lv-result"):
        tag = re.search(rf'<[a-z0-9]+ id="{dyn}"[^>]*>', dialog).group(0)
        assert "data-i18n-dyn" in tag, f"#{dyn} is composed with t() but the walker may cache it"
    # The text is DATA in the page's own language: a <pre> the walker skips, direction auto.
    assert re.search(r'<pre id="lv-text" dir="auto"', dialog)
    wire = strip_comments(function_body(read_static("app-living.js"), "_laneVersionWire"))
    assert 'addEventListener("click"' in wire and "laneVersionAdd()" in wire


def test_a_language_switch_redraws_the_open_window_from_what_it_holds():
    boot = strip_comments(read_static("app-boot.js"))
    assert "repaintLaneVersionFromCache()" in boot
    body = strip_comments(function_body(read_static("app-living.js"), "repaintLaneVersionFromCache"))
    assert "api(" not in body, "a language switch must never re-fetch"
    assert "dlg.open" in body


def test_adding_is_one_version_per_click_and_never_while_one_is_in_flight():
    body = strip_comments(function_body(read_static("app-living.js"), "laneVersionAdd"))
    assert "if (!s || s.added || s.busy) return;" in body
    assert '"/api/wiki/lane/add-to-corpus"' in body
    assert "source: s.d.source, owner_id: s.d.owner_id, revid: s.d.revid" in body, (
        "the add must name THE version the window shows, not whatever the search found last"
    )
    render = strip_comments(function_body(read_static("app-living.js"), "renderLaneVersion"))
    assert '$("lv-add").disabled = Boolean(s.added || s.busy);' in render


def test_the_search_tab_lists_the_lane_hits_beside_its_results_and_never_waits_for_them():
    """The Search tab is half of R52's «one search box»: the same words reach the lane's
    texts, listed below the corpus's table in their own section -- and the corpus's list
    must never wait on the lane's, so the call is not awaited."""
    tab = _search_tab_html()
    host = re.search(r'<div id="search-lane"[^>]*>', tab)
    assert host, "the Search tab has no Wikipedia section"
    assert tab.index('<table id="results">') < tab.index('<div id="search-lane"'), "hits ranked above the corpus"
    assert "data-i18n-dyn" in host.group(0) and " hidden" in host.group(0)
    assert not re.search(r"\son[a-z]+=", host.group(0))
    body = strip_comments(function_body(read_static("app-analysis.js"), "doSearch"))
    assert "searchLaneHits(" in body and "await searchLaneHits" not in body
    for box in ("source", "language", "start_date", "end_date"):
        assert f'"{box}"' in body, f"the {box} filter no longer tells the section it did not apply"


def test_the_section_is_wired_once_and_each_button_names_its_own_version():
    wire = strip_comments(function_body(read_static("app-living.js"), "_laneSearchWire"))
    assert 'host.addEventListener("click"' in wire
    assert "laneSearchAdd(source, ownerId, revid)" in wire and "openLaneVersion(source, ownerId, revid)" in wire
    add = strip_comments(function_body(read_static("app-living.js"), "laneSearchAdd"))
    assert "if (s.added[key] || s.busy[key]) return;" in add, "a second click could add a second copy"
    assert "JSON.stringify({source, owner_id: ownerId, revid})" in add
    boot = strip_comments(read_static("app-boot.js"))
    assert "repaintLaneSearchFromCache()" in boot
    repaint = strip_comments(function_body(read_static("app-living.js"), "repaintLaneSearchFromCache"))
    assert "api(" not in repaint, "a language switch must never re-run the search"


def test_the_caveat_the_section_shows_is_the_one_the_route_carries():
    from src.wiki import lane_search as S

    body = function_body(read_static("app-living.js"), "laneSearchHtml")
    assert f't("{S.CAVEAT}")' in body, "the Search tab's caveat drifted from the index's own"
    for code, d in _locales().items():
        assert d.get(S.CAVEAT, "").strip(), f"{code}.json has no value for the caveat"


def _table(fn: str) -> list[str]:
    """The sentences a renderer's ``said`` table hands to ``t()``."""
    body = function_body(read_static("app-living.js"), fn)
    return re.findall(r':\s*"([^"]+)"', object_literal(body, "said"))


def _lane_keys() -> list[str]:
    which = re.findall(r':\s*"([^"]+)"', object_literal(read_static("app-living.js"), "_LANE_WHICH"))
    return sorted(set(which + _table("laneAddedHtml") + _table("laneFailText") + _table("laneSearchHtml")))


def test_the_tables_hold_what_the_routes_can_answer():
    assert len(_lane_keys()) == 14, _lane_keys()
    from src.wiki import lane_search as S

    which = object_literal(read_static("app-living.js"), "_LANE_WHICH")
    for token in (S.WHICH_LATEST, S.WHICH_PREVIOUS, S.WHICH_EARLIER, S.WHICH_NEWEST):
        assert re.search(rf"\b{token}:", which), f"the token {token!r} has no words"
    absent = object_literal(function_body(read_static("app-living.js"), "laneSearchHtml"), "said")
    for token in (S.UNAVAILABLE_SQLITE, S.UNAVAILABLE_NOT_BUILT):
        assert re.search(rf"\b{token}:", absent), f"the index's refusal {token!r} has no words"


@pytest.mark.parametrize("key", _lane_keys())
def test_the_table_driven_words_are_keyed_x12(key):
    for code, d in _locales().items():
        assert key in d and d[key].strip(), f"{code}.json has no value for {key!r}"


def test_the_revision_frame_keeps_its_number_in_every_locale():
    for code, d in _locales().items():
        assert "{revid}" in d["revision {revid}"], code
