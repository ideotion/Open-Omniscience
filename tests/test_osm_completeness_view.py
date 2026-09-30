"""Analytic 1 on the page and on Home (S05-04 S5; Q815 · 1, Q817 «aggregates as cards», Q823 ⛔).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The card is made from the OSM lane. Q823 = a lets OSM data leave with OpenStreetMap's credit, so
it is made for Home and for the bulletin, whose edition records which lane cards it shows and
credits OpenStreetMap against exactly those; a lead report or a card audit (no attribution
block) never runs its producer, and says which producer it held. The view sits in the World map tab (a data tab,
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


def test_only_the_carriers_that_credit_the_lane_ask_for_its_cards():
    import ast

    callers = []
    for path in (ROOT / "src").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "run_all_bounded"
                    and any(k.arg == "lanes" for k in node.keywords)):
                callers.append(str(path.relative_to(ROOT)))
    # Home's refresh, and the bulletin (whose edition credits OpenStreetMap against the lane
    # cards it shows). The lead report and the card audit have no attribution block.
    assert sorted(callers) == ["src/briefing/service.py", "src/bulletin/cards.py"], callers


def test_the_bulletin_carries_the_lane_cards_and_says_which_it_shows():
    src = (ROOT / "src" / "bulletin" / "cards.py").read_text(encoding="utf-8")
    assert '"held_q823": sorted(stats.get("held_q823") or [])' in src
    assert "lanes=True" in src and '"lane_cards_shown"' in src


def test_an_edition_that_shows_the_lane_card_credits_openstreetmap_and_one_that_does_not_does_not(
    osm_lane_dir, monkeypatch
):
    """The carrier end to end, minus the database: the cards section runs the lane producer,
    records that it SHOWS it, and the edition's attribution block keys on that record."""
    from datetime import date

    from src.backup.attribution import attribution_dicts, card_signals_from_edition
    from src.briefing import registry
    from src.briefing.producers import osm_tag_completeness
    from src.bulletin.cards import cards_by_type
    from src.bulletin.period import Period

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    monkeypatch.setattr(registry, "_REGISTRY", [("osm_tag_completeness", osm_tag_completeness)])
    monkeypatch.setattr(registry, "_disabled_names", lambda: frozenset())
    period = Period(cadence="weekly", start=date(2026, 9, 1), end=date(2026, 9, 8), baseline_start=date(2026, 8, 25))

    section = cards_by_type(None, period)
    assert section["lane_cards_shown"] == ["osm_tag_completeness"]
    assert section["held_q823"] == [], "the bulletin no longer holds the lane back"
    assert section["cards_shown_total"] == 1

    signals = card_signals_from_edition({"sections": [section]})
    assert signals == {"card:osm_tag_completeness"}
    (line,) = attribution_dicts(signals)
    assert line["key"] == "openstreetmap" and "ODbL" in line["text"] and "OpenStreetMap contributors" in line["text"]
    assert line["because"] == "card:osm_tag_completeness", "the line says what measured it"

    # no lane card in the document, no OpenStreetMap line: the credit follows the content
    assert card_signals_from_edition({"sections": [dict(section, lane_cards_shown=[])]}) == set()
    assert card_signals_from_edition({"sections": []}) == set() and card_signals_from_edition(None) == set()


def test_a_lane_producer_cannot_be_carried_without_its_credit():
    """The seam's reason to exist: every lane-only producer is an OSM-derived card, and the
    attribution registry credits OpenStreetMap against its signal. A future lane producer
    with a licence of its own fails here until its line exists."""
    from src.backup.attribution import OSM_DERIVED_CARDS, attribution_lines, card_signal
    from src.briefing.registry import LANE_ONLY_PRODUCERS

    for name in LANE_ONLY_PRODUCERS:
        lines = attribution_lines({card_signal(name)})
        assert lines, f"{name} is lane-only and has no licence line: it cannot leave without one"
    for name in OSM_DERIVED_CARDS:
        (line,) = attribution_lines({card_signal(name)})
        assert line.key == "openstreetmap" and "ODbL" in line.text and line.because == f"card:{name}"
    assert attribution_lines({card_signal("rising_now")}) == [], "no credit for a card that holds no OSM row"


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


# ---- every document form the carrier reaches carries the credit, or none does -------------------

_LANE_EDITION = {
    "layer": "A",
    "period": {"cadence": "weekly", "start": "2026-09-01", "end": "2026-09-08"},
    "attribution": [
        {"key": "openstreetmap", "because": "card:osm_tag_completeness",
         "text": "Map data — © OpenStreetMap contributors (https://www.openstreetmap.org/copyright), "
                 "available under the Open Database License 1.0 (ODbL, https://opendatacommons.org/licenses/odbl/1-0/)."},
    ],
    "sections": [{"section": "cards", "lane_cards_shown": ["osm_tag_completeness"], "types": []}],
}


def test_the_html_bulletin_carries_the_credit_like_the_markdown_one():
    """HTML is the default view: an OpenStreetMap card there without the credit would break
    Q823 = a whatever the Markdown says."""
    from src.bulletin.render import render_html, render_markdown

    for out in (render_html(_LANE_EDITION), render_markdown(_LANE_EDITION)):
        assert "© OpenStreetMap contributors" in out and "ODbL" in out
    bare = dict(_LANE_EDITION)
    del bare["attribution"]
    assert "OpenStreetMap contributors" not in render_html(bare), "an old record says nothing, never a guess"


def test_the_evidence_zip_credits_the_lane_card_its_edition_json_carries(tmp_path):
    import json
    import zipfile

    from src.bulletin.evidence import build_evidence_archive
    from tests.test_bulletin_evidence import _P, _corpus

    edition = {k: v for k, v in _LANE_EDITION.items() if k != "attribution"}  # the API's bare layer_a
    rep = build_evidence_archive(_corpus(2), edition, _P, tmp_path)
    with zipfile.ZipFile(rep["path"]) as z:
        text = z.read("ATTRIBUTION.md").decode("utf-8")
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
    assert "© OpenStreetMap contributors" in text and "ODbL" in text
    assert [a["key"] for a in manifest["attribution"]] == ["openstreetmap"]
    (tmp_path / "plain").mkdir()
    plain = build_evidence_archive(_corpus(2), {"layer": "A", "sections": []}, _P, tmp_path / "plain")
    with zipfile.ZipFile(plain["path"]) as z:
        assert "OpenStreetMap" not in z.read("ATTRIBUTION.md").decode("utf-8")


def test_excluding_the_cards_section_drops_the_credit_it_alone_justified():
    from src.bulletin.review import apply_selection

    kept = apply_selection(_LANE_EDITION, exclude_sections=["through_time"])
    assert [a["key"] for a in kept["attribution"]] == ["openstreetmap"], "the card is still in the document"
    dropped = apply_selection(_LANE_EDITION, exclude_sections=["cards"])
    assert dropped["attribution"] == [], "no card, no credit for it"
    assert _LANE_EDITION["attribution"], "the record itself is untouched"
    mixed = dict(_LANE_EDITION, attribution=[dict(_LANE_EDITION["attribution"][0], because="table:osm_admin, card:osm_tag_completeness")])
    assert apply_selection(mixed, exclude_sections=["cards"])["attribution"][0]["because"] == "table:osm_admin"
    old = {"sections": [{"section": "cards"}]}
    assert "attribution" not in apply_selection(old, exclude_sections=["cards"]), "an old record stays silent"


def test_a_failed_source_query_still_leaves_the_card_credit_and_says_it_failed(monkeypatch):
    from src.bulletin import edition as E
    from src.bulletin import evidence as EV

    def boom(*_a, **_k):
        raise RuntimeError("statement deadline")

    monkeypatch.setattr(EV, "period_source_rows", boom)
    lines, err = E._attribution(None, None, _LANE_EDITION)
    assert [x["key"] for x in lines] == ["openstreetmap"] and "statement deadline" in err
    assert E._attribution(None, None, {"sections": []}) == ([], "RuntimeError: statement deadline")
