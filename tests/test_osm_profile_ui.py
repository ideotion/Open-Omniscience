"""Brands, contact channels and freshness on the page (v0.6.0 B3b, S06-01 S3): wiring, language, and the renderers in node.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The renderers are driven in node (``tests/osm_profile_node_test.js``); here the wiring around them and the strings they and the
server say are pinned.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from tests.js_source_helper import function_source

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "static"


def test_the_renderers_behave():
    proc = subprocess.run(["node", str(ROOT / "tests" / "osm_profile_node_test.js")], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout


def test_the_view_is_in_the_world_map_tab_after_the_trends_and_hidden_until_read():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    tab = html.partition('id="tab-timemap"')[2].partition('<div class="tab-page"')[0]
    assert '<section class="panel" id="osm-profile" hidden>' in tab and 'id="osm-profile-body"' in tab
    assert tab.index('id="osm-trends"') < tab.index('id="osm-profile"')
    js = (STATIC / "app-map.js").read_text(encoding="utf-8")
    load = function_source(js, "loadOsmProfile")
    assert "sec.hidden = true" in load and "++_osmProfileSeq" in load
    assert "ensureOnline" not in load + function_source(js, "_osmProfileFetch"), "reading a local table asked for the network consent"
    assert "await loadOsmProfile" not in js, "the completeness figures must not wait on the surfaces"


def test_the_two_second_count_poll_leaves_the_surfaces_alone_and_an_empty_lane_clears_them():
    js = (STATIC / "app-map.js").read_text(encoding="utf-8")
    load = function_source(js, "loadOsmCompleteness")
    assert "if (!(opts && opts.poll)) loadOsmProfile(done)" in load
    assert "loadOsmProfile([])" in load


def test_the_route_is_local_and_the_view_reads_nothing_else():
    js = (STATIC / "app-map.js").read_text(encoding="utf-8")
    body = "".join(function_source(js, n) for n in ("loadOsmProfile", "_osmProfileFetch", "_renderOsmProfile", "_osmProfileBody", "_osmProfileDraw"))
    assert "fetch(" not in body and "http" not in body.replace("https://", "")
    fetch = function_source(js, "_osmProfileFetch")
    assert "/api/osm/countries/${encodeURIComponent(a3)}/profile/${tab}?limit=${_osmProfileLimit}" in fetch


def test_changing_the_tab_or_the_key_does_not_rebuild_the_tabs_and_so_keeps_the_keyboard_focus():
    js = (STATIC / "app-map.js").read_text(encoding="utf-8")
    assert "_renderOsmProfile" not in function_source(js, "_osmProfileShowTab")
    render = function_source(js, "_renderOsmProfile")
    assert "ooSubtabs(nav, _osmProfileShowTab)" in render
    assert render.count("addEventListener(") == 2, "one change listener and one click listener on the host, none inside a rewritten body"
    assert "_renderOsmProfile" not in render.partition('addEventListener("change"')[2]


def test_every_view_string_and_every_server_string_ships_in_twelve_languages():
    from src.osm import profile as PF

    strings = [
        PF.METHOD_BRANDS, PF.CAVEAT_BRANDS, PF.METHOD_CHANNELS, PF.CAVEAT_CHANNELS, PF.METHOD_FRESHNESS, PF.CAVEAT_FRESHNESS,
        PF.METHOD_CHANGES_BRANDS, PF.METHOD_CHANGES_CHANNELS, PF.METHOD_CHANGES_FRESHNESS, PF.CAVEAT_CHANGES, PF.METHOD_PRIOR, PF.CAVEAT_PRIOR,
        "OpenStreetMap brands, contact channels and freshness", "Brands and operators", "Contact channels", "Data freshness",
        "Within a year", "One to two years", "Two to five years", "More than five years", "After the vintage", "Edited", "Checked", "Social",
        "Brands, by number of places", "Brand identifiers (brand:wikidata), by number of places", "Brand", "Show more", "{shown} of {total} shown.",
        "Social services", "Service", "Places by number of channels carried", "Channels carried",
        "Not available: neither the extract nor a change file states a date to measure the ages from.",
        "Last edited, counted back from the vintage", "Last edited", "No timestamp", "Carrying a check_date",
        "{present} of {n} places carry a check_date ({share}).", "check_date aged", "Not a date",
        "Counted from the extract of {extract}, with change files applied through {through}.",
        "Counted from the extract of {extract}; no change file has been applied since.", "Counted now", "What the daily change files changed",
    ]
    for path in sorted((STATIC / "locales").glob("*.json")):
        loc = json.loads(path.read_text("utf-8"))
        for s in strings:
            assert s in loc, (path.name, s)
            assert sorted(re.findall(r"\{\w+\}", s)) == sorted(re.findall(r"\{\w+\}", loc[s])), (path.name, "placeholders differ", s)


def test_the_key_sets_on_the_page_are_the_keys_the_server_reads():
    """The social services the page names are the ones the server counts: a service added on one side would be a column the other does not have."""
    from src.osm import profile as PF

    js = (STATIC / "app-map.js").read_text(encoding="utf-8")
    names = re.search(r"const OSM_SOCIAL_NAMES = \{(.*?)\};", js, re.S)
    assert names
    assert re.findall(r"(\w+):", names.group(1)) == list(PF.SOCIAL_SERVICES)
    fresh = re.search(r"const OSM_AGE_LABELS = \[(.*?)\];", js, re.S)
    assert fresh and re.findall(r'\["(\w+)"', fresh.group(1)) == [*PF.AGE_BUCKETS, "after"]
