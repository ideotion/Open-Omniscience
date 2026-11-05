"""Trends 2 and 3 on the page (v0.6.0 B3a, S06-01 S3): wiring, language, and the renderers in node.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The renderers are driven in node (``tests/osm_trends_node_test.js``); here the wiring around them
and the strings they and the server say are pinned.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.js_source_helper import function_source

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "static"


def test_the_renderers_behave():
    proc = subprocess.run(["node", str(ROOT / "tests" / "osm_trends_node_test.js")], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout


def test_the_view_is_in_the_world_map_tab_after_the_completeness_view_and_hidden_until_read():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    tab = html.partition('id="tab-timemap"')[2].partition('<div class="tab-page"')[0]
    assert '<section class="panel" id="osm-trends" hidden>' in tab
    assert tab.index('id="osm-completeness"') < tab.index('id="osm-trends"')
    js = (STATIC / "app-map.js").read_text(encoding="utf-8")
    load = function_source(js, "loadOsmTrends")
    assert "sec.hidden = true" in load and "/api/osm/countries/${encodeURIComponent(c.alpha3)}/trends" in load
    assert "ensureOnline" not in load, "reading a local table asked for the network consent"
    # not awaited: the completeness figures must not wait on the trends
    assert "await loadOsmTrends" not in js


def test_the_route_is_local_and_the_view_reads_nothing_else():
    js = (STATIC / "app-map.js").read_text(encoding="utf-8")
    body = "".join(function_source(js, n) for n in ("loadOsmTrends", "_renderOsmTrends", "_osmTrendCountry", "_osmTrendDrawAll"))
    assert "fetch(" not in body and "http" not in body.replace("https://", "")


def test_every_view_string_and_every_server_string_ships_in_twelve_languages():
    from src.osm import trends as TR

    strings = [
        TR.METHOD_ADOPTION, TR.CAVEAT_ADOPTION, TR.METHOD_OPENINGS, TR.CAVEAT_OPENINGS, TR.METHOD_PRIOR, TR.CAVEAT_PRIOR,
        "OpenStreetMap trends", "Adoption of tags over time", "Openings and closures",
        "No daily change file has been applied to this country yet, so there are no trends to show.",
        "Change files applied: {n}, dated {since} to {through}.", "This country's trends could not be read.",
        "Gained", "Lost", "Appeared", "Disappeared", "Stopped qualifying", "Disused key added", "Marked vacant", "Marked closed",
        "Day", "Hover for the method.", "Not observed between {from} and {to}.",
        "Sum of the counts shown: {n}. A place changed on several days or in several ways is counted each time.",
    ]
    for path in sorted((STATIC / "locales").glob("*.json")):
        loc = json.loads(path.read_text("utf-8"))
        for s in strings:
            assert s in loc, (path.name, s)


def test_the_two_second_count_poll_does_not_re_read_the_trends_and_a_slow_read_cannot_overwrite_a_newer_one():
    js = (STATIC / "app-map.js").read_text(encoding="utf-8")
    assert "loadOsmCompleteness({ poll: true })" in function_source(js, "_osmCompSchedulePoll")
    load = function_source(js, "loadOsmCompleteness")
    assert "if (!(opts && opts.poll)) loadOsmTrends(done)" in load
    trends = function_source(js, "loadOsmTrends")
    assert "++_osmTrendSeq" in trends and "if (seq !== _osmTrendSeq) return" in trends


def test_changing_the_tab_or_the_key_does_not_rebuild_the_panel_and_so_keeps_the_keyboard_focus():
    js = (STATIC / "app-map.js").read_text(encoding="utf-8")
    assert "_renderOsmTrends" not in function_source(js, "_osmTrendShowTab")
    render = function_source(js, "_renderOsmTrends")
    assert "ooSubtabs(nav, _osmTrendShowTab)" in render
    change = render.partition('addEventListener("change"')[2]
    assert "_renderOsmTrends" not in change and "o.value = _osmTrendKey" in change


def test_old_strings_are_gone_from_the_locales():
    for path in sorted((STATIC / "locales").glob("*.json")):
        loc = json.loads(path.read_text("utf-8"))
        assert "{n} counted in all." not in loc, path.name
