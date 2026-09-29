"""Analytic 1 on the page and on Home (S05-04 S5; Q815 · 1, Q817 «aggregates as cards», Q823 ⛔).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The card is made from the OSM lane, and Q823 (ODbL) is unanswered, so it is made for Home and
for nothing that leaves the machine: a bulletin, a lead report or a card audit never runs its
producer, and says which producer it held. The view sits in the World map tab (a data tab,
invariant #8), with the four keys side by side and the caveat visible.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.osm import ingest
from tests import _osm_lane_helpers
from tests._osm_lane_helpers import FIXTURE
from tests.js_source_helper import function_source

osm_lane_dir = _osm_lane_helpers.osm_lane_dir
ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "static"


def test_one_card_per_complete_country_the_four_keys_side_by_side(osm_lane_dir):
    from src.briefing.producers import osm_tag_completeness

    assert osm_tag_completeness(None) == [], "a card with no lane"
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    (card,) = osm_tag_completeness(None)
    assert card.bucket == "context" and card.n == 4
    assert card.signal["present"] == {"opening_hours": 1, "website": 1, "email": 2, "phone": 2}
    assert card.caveat and card.method
    assert "score" not in json.dumps(card.signal)
    assert card.evidence[0]["url"] == "/#timemap"


def test_the_lane_card_is_made_for_home_and_held_from_every_other_caller(osm_lane_dir, monkeypatch):
    from src.briefing import registry
    from src.briefing.producers import osm_tag_completeness

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    monkeypatch.setattr(registry, "_REGISTRY", [("osm_tag_completeness", osm_tag_completeness)])
    monkeypatch.setattr(registry, "_disabled_names", lambda: frozenset())
    cards, stats = registry.run_all_bounded(None)
    assert cards == [] and stats["held_q823"] == ["osm_tag_completeness"]
    assert stats["producers_total"] == 0, "a held producer counted as one that ran"
    cards, stats = registry.run_all_bounded(None, lanes=True)
    assert [c.type for c in cards] == ["osm_tag_completeness"] and stats["held_q823"] == []
    assert registry.run_all(None) == [], "run_all is what the card audit and the lead report call"


def test_only_homes_refresh_asks_for_the_lane_cards():
    import ast

    callers = []
    for path in (ROOT / "src").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "run_all_bounded"
                    and any(k.arg == "lanes" for k in node.keywords)):
                callers.append(str(path.relative_to(ROOT)))
    assert callers == ["src/briefing/service.py"], callers


def test_the_bulletin_names_what_it_held():
    src = (ROOT / "src" / "bulletin" / "cards.py").read_text(encoding="utf-8")
    assert '"held_q823": sorted(stats.get("held_q823") or [])' in src
    assert "lanes=" not in src


def test_the_view_is_in_the_world_map_tab_hidden_until_a_country_is_read():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    tab = html.partition('id="tab-timemap"')[2].partition('<div class="tab-page"')[0]
    assert '<section class="panel" id="osm-completeness" hidden>' in tab
    js = (STATIC / "app-map.js").read_text(encoding="utf-8")
    load = function_source(js, "loadOsmCompleteness")
    assert 'filter((c) => c.status === "complete")' in load and "sec.hidden = true" in load


def test_the_caveat_is_visible_and_the_share_is_never_a_zero_for_no_places():
    js = (STATIC / "app-map.js").read_text(encoding="utf-8")
    render = function_source(js, "_renderOsmCompleteness")
    assert 'class="card-caveat"' in render
    share = function_source(js, "_osmCompShare")
    assert 'k.share == null ? "—"' in share
    draw = function_source(js, "_osmCompDrawMap")
    assert "k.share != null" in draw, "a region with no places was painted as 0 %"


def test_counting_per_region_is_a_local_post_and_allowlisted():
    js = (STATIC / "app-map.js").read_text(encoding="utf-8")
    body = function_source(js, "osmCountAdmin1")
    assert "/admin1" in body and 'method: "POST"' in body
    assert "ensureOnline" not in body, "a local count asked for the network consent"
    assert '"osmCountAdmin1"' in (STATIC / "oo-on.js").read_text(encoding="utf-8")


def test_every_view_and_card_string_ships_in_twelve_languages():
    from src.osm.completeness import ADMIN1_CAVEAT, ADMIN1_METHOD, CAVEAT, METHOD

    strings = [METHOD, CAVEAT, ADMIN1_METHOD, ADMIN1_CAVEAT, "OpenStreetMap tag completeness", "Count per region",
               "Per region: the region outlines are not built on this install, so no region is counted.",
               "{share} % ({present} of {n})", "Map data completeness", "OpenStreetMap tag completeness: {country}"]
    for path in sorted((STATIC / "locales").glob("*.json")):
        loc = json.loads(path.read_text("utf-8"))
        for s in strings:
            assert s in loc, (path.name, s)
