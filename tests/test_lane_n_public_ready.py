"""Public readiness of Home, Explore, the world map and the first run (lane N, 2026-11-13).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each test pins one fix from the 2026-11-13 re-walk of the journalist review (2026-09-30)
against today's main, measured in Chromium before the fix:

* the map's 229 country shapes carried a native SVG ``<title>`` (mouse only, unstyled)
  while the contested areas used the app's bubble; one carrier now, the ``title``
  attribute the #oo-tip convention (#17) opens on hover, focus and long-press. The code
  stays the visible label and the name sits in the bubble (Q302);
* zoomed in, the map had no scale: a scale bar measured at the centre of the view;
* light themes failed WCAG AA for the Explore tone words (2.81-4.42:1) and the map's
  pressed chips (3.47-4.40:1): text-safe tokens, mixed toward each theme's own --fg;
* at 390 px the Explore filters squeezed to 25 px slivers and the subtab strip took four
  rows: the filters stack and the strip is one row that scrolls sideways;
* the first-run guide asked about "pinned tabs" before saying what the app is, and
  offered catalogue provenance tags ("via:curated") as themes;
* Home's "Trending now" listed falling terms as "↑0.6×".
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tests.js_source_helper import app_js, function_body, read_static

_ROOT = Path(__file__).resolve().parents[1]


def test_every_country_shape_uses_the_one_hover_bubble():
    js = app_js()
    body = function_body(js, "ooMap")
    assert "><title>${esc(title)}</title></path>" not in body
    assert ' title="${esc(title)}"></path>' in body, "country shapes ride a title attribute (#17)"
    assert 't("(shown as a point)"))}"></circle>' in body, "a microstate's dot does too"


def test_hover_outlines_the_country_in_screen_pixels():
    css = read_static("app.css")
    rule = re.search(r"#oo-choro \[data-iso\]:hover \{([^}]*)\}", css)
    assert rule and "vector-effect:non-scaling-stroke" in rule.group(1)


def test_the_map_has_a_scale_bar_that_follows_zoom_and_resize():
    js = app_js()
    body = function_body(js, "ooMap")
    assert "data-oomap-scale" in body
    assert "_ooMapScaleBar(host, svg, vb);" in function_body(js, "_wireOoMap"), (
        "re-measured on every view change"
    )
    bar = function_body(js, "_ooMapScaleBar")
    assert "getScreenCTM()" in bar and "barPx < 8" in bar and "Math.max(8" not in bar
    css = read_static("app.css")
    rule = re.search(r"\.oomap-scale \{([^}]*)\}", css).group(1)
    assert "right:8px" in rule, "bottom left is the Country/layers group above 600 px"
    watch = function_body(js, "_ooMapScaleWatch")
    assert "ResizeObserver" in watch and "disconnect()" in watch


def test_the_scale_bar_arithmetic_runs_as_real_code():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "map_scale_bar_node_test.js")],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert "4 passed, 0 failed" in proc.stdout, proc.stdout


def test_text_safe_tone_and_chip_colours():
    css = read_static("app.css")
    assert "--ok-text:var(--ok); --err-text:var(--err);" in css
    assert ".pill.ok{ color:var(--ok-text);" in css and ".pill.err{ color:var(--err-text);" in css
    block = css.split("--ok-text / --err-text overrides", 1)[1].split("/* The world map", 1)[0]
    for theme in ("light", "paper", "dawn", "mint", "solar"):
        assert f':root[data-theme="{theme}"]' in block, theme
    js = app_js()
    tone = function_body(js, "_toneChip")
    assert '"var(--ok-text)"' in tone and '"var(--err-text)"' in tone
    assert 'color:var(--accent)"' not in function_body(js, "ooMap"), (
        "pressed map chips use --accent-text"
    )


def test_explore_on_a_phone():
    html = read_static("index.html")
    assert '<div class="row explore-filters">' in html
    css = read_static("app.css")
    narrow = css.split("PHONE WIDTH (lane N", 1)[1].split("\n    }\n", 1)[0]
    assert ".subtab-strip > nav.tabs { flex-wrap:nowrap; overflow-x:auto;" in narrow
    assert ".explore-filters > div { flex:1 1 100% !important;" in narrow
    paint = function_body(app_js(), "ooSubtabs")
    assert "nav.scrollLeft" in paint and "scrollIntoView" not in paint, (
        "the strip scrolls, never the page"
    )


def test_the_first_run_says_what_the_app_does_before_asking_anything():
    html = read_static("index.html")
    depth = html[
        html.index('data-step="depth"') : html.index("</section>", html.index('data-step="depth"'))
    ]
    intro = depth.split('<ul class="gw-intro"', 1)[1].split("</ul>", 1)[0]
    assert depth.index('class="gw-intro"') < depth.index("How much should the app show at once?")
    assert intro.count("<li>") == 3 and "<b>" not in intro, "one keyed text node per line"
    core = app_js()
    assert 'const _GW_STEPS = ["depth", "sources", "finish"];' in core, "no new step (Q1121)"
    src = function_body(core, "_gwRenderSources")
    assert '(x.indexOf("via:") !== 0 || curTags.indexOf(x) >= 0)' in src, (
        "provenance tags are not themes, unless the config already filters on one: then it is SHOWN"
    )
    assert "_gwSrc.keep" not in core, "no filter member kept out of the reader's sight"
    assert 'dlg.querySelector(".gw-intro")' in function_body(core, "openGuide")
    assert '<ul class="gw-intro" tabindex="-1"' in html


def test_home_trending_lists_only_rising_terms():
    js = read_static("app-home.js")
    assert "↑${x.growth}×" not in js
    assert js.count("trendRateText(x, {short: true})") == 2
    load = function_body(js, "loadHomeTrends")
    assert "growthIsRatio(x) === true && !(Number(x.growth) > 1)" in load
    empty = load.split("if (!terms.length) {", 1)[1].split("return;", 1)[0]
    assert "_homeTrendTerms = [];" in empty and "_renderOverviewTrends();" in empty, (
        "the Overview row must not keep the last poll's chips once every term is filtered out"
    )


def test_home_most_recent_defaults_to_a_subject_tag():
    load = function_body(read_static("app-home.js"), "loadHomeRecent")
    assert 'String(k).indexOf("via:") === 0' in load
    assert ".sort((a, b) => (_isVia(a.key) ? 1 : 0) - (_isVia(b.key) ? 1 : 0))" in load, (
        "ordered, never excluded"
    )
