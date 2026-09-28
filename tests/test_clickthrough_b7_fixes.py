"""Row N and two chart defects from the 2026-09-26 delegated click-through, pinned.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each fix was reproduced in Chromium first and checked there after
(``docs/audit/delegated-clickthrough-2026-09-26/`` holds the rows). CI runs no
browser, so these tests pin the mechanism each fix relies on; the behavioural halves
run as real code under node:

* ``tests/oochart_legend_resize_node_test.js`` -- N3 (a hidden series keeps its
  legend chip) and U10 (the chart refits when its host narrows);
* ``tests/cross_language_lens_node_test.js`` -- N2 (the URL names the ACTIVE tab)
  and N14 (a language group of one);
* ``tests/cross_language_notice_node_test.js`` -- N13 and N14 (the disclosure).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from tests.js_source_helper import (
    app_js,
    assert_absent,
    assert_present,
    event_listener_bodies,
    function_body,
    read_static,
)

_ROOT = Path(__file__).resolve().parent.parent
_LOCALES = _ROOT / "src" / "static" / "locales"


def _locales() -> dict[str, dict]:
    out = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in _LOCALES.glob("*.json")}
    assert len(out) == 12, f"expected 12 locale files, found {len(out)}"
    return out


def _keyed_everywhere(*keys: str) -> None:
    for loc, data in _locales().items():
        for k in keys:
            assert data.get(k), f"{loc}.json has no value for {k[:60]!r}"
            # every placeholder the frame interpolates survives the translation
            for slot in re.findall(r"\{\w+\}", k):
                assert slot in data[k], f"{loc}.json dropped {slot} from {k[:60]!r}"


def _node(name: str) -> str:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / name)], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


# --- N3 + U10: the chart toolkit ------------------------------------------- #


def test_oochart_legend_and_resize_run_as_real_code():
    out = _node("oochart_legend_resize_node_test.js")
    assert "all assertions passed" in out


def test_an_all_hidden_chart_says_how_to_get_a_series_back():
    body = function_body(app_js(), "ooChart")
    assert_present(body, 't9("Every series is hidden. Click a legend entry to show it again.")')
    _keyed_everywhere("Every series is hidden. Click a legend entry to show it again.")


def test_one_observer_per_chart_host_and_it_is_released_on_redraw():
    body = function_body(app_js(), "ooChart")
    # the previous observer is disconnected before a new drawing takes the host...
    assert_present(body, "el._ooChartRO.disconnect(); el._ooChartRO = null;")
    # ...and the drawn chart arms one, as the not-yet-laid-out host does
    assert_present(body, "_ooChartWatch(el, W);")
    assert_present(body, "if (!avail) { _ooChartWatch(el, 0); return; }")
    assert_absent(body, "_ooChartPending", why="the one-shot observer it replaced")


# --- N2: the analysis URL follows the active tab ---------------------------- #


def test_a_deep_link_lens_is_read_before_the_restored_tab_rewrites_the_url():
    hyd = function_body(app_js(), "_hydrateCardCorpus")
    code = "\n".join(ln for ln in hyd.splitlines() if not ln.strip().startswith("//"))
    assert re.search(
        r"const lens = _anReadLensFromUrl\(\);\s*showTab\(\"analyze\", false\);", code
    ), "the deep link's lens must be read before showTab hydrates the restored tab"
    # the N1 order is kept: hydrated before showTab
    assert re.search(r"_anHydrated = true;[\s\S]*showTab\(\"analyze\", false\)", code)


def test_writing_the_lens_first_names_the_active_tab():
    body = function_body(app_js(), "_anWriteLensToUrl")
    assert_present(body, "_anUrlNamesActiveTab(sp);")


# --- N4: Date is the default article order (Q508) -------------------------- #


def test_the_article_sort_defaults_to_date():
    html = read_static("index.html")
    sel = re.search(r'<select id="an-adv-sort"[\s\S]*?</select>', html)
    assert sel, "#an-adv-sort is gone"
    block = re.sub(r"<!--[\s\S]*?-->", "", sel.group(0))
    assert '<option value="date" selected>' in block
    assert block.count(" selected") == 1
    # relevance stays an explicit choice
    assert '<option value="">Relevance / recency</option>' in block


def test_the_default_order_is_not_reported_as_a_filter():
    body = function_body(app_js(), "_anFilterSummary")
    assert_present(body, 'if (sb && !(sb === "date" && !asc))')


# --- N5, U9: redrawn on a live language switch, from what they already hold -- #


def test_the_language_switch_redraws_watches_price_and_agenda():
    hs = event_listener_bodies(app_js(), "oo:langchange")
    for call in ("_renderWatches();", "_anRepaintPrice();", "renderAgenda();"):
        assert any(call in h for h in hs), f"{len(hs)} listener(s), none calls {call}"


def test_the_redraws_never_fetch():
    js = app_js()
    for name in ("_renderWatches", "_anRepaintPrice", "_anPriceHtml"):
        assert_absent(function_body(js, name), "api(", why=f"{name} must redraw from memory")
    # loadWatches keeps the payload the redraw uses
    assert_present(function_body(js, "loadWatches"), '_wtLast = await api("/api/watches");')


# --- N6: the reader's own words are not dictionary words -------------------- #


def test_watch_name_query_and_analysis_tab_label_opt_out_of_the_walker():
    js = app_js()
    rw = function_body(js, "_renderWatches")
    assert_present(rw, "<b data-i18n-dyn>${esc(w.name)}</b>")
    assert_present(rw, '<span class="muted" data-i18n-dyn>— “${esc(w.query)}”</span>')
    assert_present(
        function_body(js, "_anRenderStrip"), '<button class="an-tab-label" data-i18n-dyn'
    )
    # the mechanism those attributes rely on
    assert "data-i18n-dyn" in read_static("i18n.js")


# --- N7, U9: fixed server sentences go through their keys -------------------- #


def test_the_keyword_hover_caveat_is_translated_and_keyed():
    src = (_ROOT / "src" / "analytics" / "queries.py").read_text(encoding="utf-8")
    m = re.search(
        r'"caveat": \(\s*"(Counts only, never a score\.[^"]*)"\s*"([^"]*)"\s*"([^"]*)"', src
    )
    assert m, "the keyword-stats caveat moved -- re-point this test"
    caveat = "".join(m.groups())
    _keyed_everywhere(caveat)
    assert_present(function_body(app_js(), "ooKwStatInit"), '" · " + t(d.caveat)')


def test_the_meeus_hover_sentences_are_translated_and_keyed():
    from src.events import astronomy

    _keyed_everywhere(astronomy._METHOD, astronomy._ACCURACY)
    ag = read_static("app-agenda.js")
    # Both halves still go through their keys; since the 2026-09-26 leftovers (Y11) they
    # are joined by a KEYED frame, not a literal "; " (tests/test_clickthrough_b13_leftovers.py).
    assert_present(function_body(ag, "_astroNote"), "tr(x.method)")
    assert_present(function_body(ag, "_astroNote"), "tr(x.acc)")
    assert_absent(ag, 'moon.method + "; " + moon.acc')
    assert_absent(ag, 'season.method + "; " + season.acc')
    assert ag.count("_astroTitle(_moonLabel(moon.kind, t9m), moon, t9m, tf9m)") == 1
    assert ag.count("_astroTitle(_moonLabel(moon.kind, t9), moon, t9, tf9)") == 1
    assert ag.count("_astroTitle(_seasonLabel(season.name, t9m), season, t9m, tf9m)") == 1


def test_the_keyword_hover_caches_the_payload_not_a_line_in_one_language():
    body = function_body(app_js(), "ooKwStatInit")
    assert_present(body, "applyTo(el, fmt(v), true)")
    assert_present(body, "cache.set(term, d || {});")


# --- N8: Enlarge keeps the label size ---------------------------------------- #


def test_the_enlarged_mind_map_is_drawn_wider_not_squeezed():
    body = function_body(app_js(), "renderAnMindmap")
    assert_present(body, 'const svgW = big ? `${(100 * W / 680).toFixed(1)}%` : "100%";')
    assert body.count('width="${svgW}"') == 2, "both mind-map views must use the scaled width"
    assert_absent(body, 'width="100%" style="background:var(--panel2)')
    # it scrolls in its own box, opened on the seed, so the controls stay in reach
    assert body.count("${tree}</svg>` + boxClose") == 1
    assert body.count("${edges}${nodesSvg}</svg>` + boxClose") == 1
    assert body.count("centreBox();") == 2


# --- N9: the Trends value wraps on a phone ----------------------------------- #


def test_the_trend_value_wraps_at_phone_width():
    css = read_static("app.css")
    assert re.search(
        r"@media \(max-width:600px\) \{\s*\.tb-row \{ flex-wrap:wrap; \}\s*"
        r"\.tb-val \{ flex:1 1 100%; min-width:0; white-space:normal; \}\s*\}",
        css,
    ), "the 375 px wrap rule for .tb-row/.tb-val is gone"


# --- N11: the search result count is keyed ----------------------------------- #


def test_the_search_count_line_is_keyed():
    body = function_body(app_js(), "doSearch")
    assert_present(body, 'stf("{n} result(s) (showing {shown})"')
    assert_present(body, 'stf("{n} result(s)", {n: data.total})')
    assert_absent(body, "`${data.total} result(s)`")
    _keyed_everywhere("{n} result(s)", "{n} result(s) (showing {shown})")


# --- N12: the concept view says it ignores the literal toggle ---------------- #


def test_the_concept_view_says_it_shows_every_language():
    key = (
        "This view always shows the concept in every language; "
        "the other tabs are showing only the words you typed."
    )
    body = function_body(app_js(), "renderAnMindmap")
    assert_present(body, f't("{key}")')
    assert_present(body, 'const literal = _anExpand ? ""')
    assert_present(body, 'data-on-click="_anSetExpand(true)"')
    _keyed_everywhere(key)


# --- N13, N14: the cross-language disclosure and the counts ----------------- #


def test_the_disclosure_suites_run_as_real_code():
    assert "all assertions passed" in _node("cross_language_notice_node_test.js")
    assert "all assertions passed" in _node("cross_language_lens_node_test.js")


def test_the_new_frames_and_singulars_are_keyed():
    _keyed_everywhere(
        "{term} denotes several concepts, so it was not expanded.",
        "{term}: expanded to {searched} of {total} forms.",
        "{n} article",
        "mention",
    )
    notice = function_body(app_js(), "_crossLangNotice")
    assert_present(notice, '(cross.caveat && cross.expanded) ? t(cross.caveat) : ""')
    kw = function_body(app_js(), "ooKwStatInit")
    assert_present(kw, 'd.mentions === 1 ? t("mention") : t("mentions")')
    assert_present(kw, 'd.articles === 1 ? t("article") : t("articles")')
