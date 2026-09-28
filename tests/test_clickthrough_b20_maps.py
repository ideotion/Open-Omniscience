"""Batch B20 of the 2026-09-27 row R walk, pinned: the five ooMap surfaces (World map,
Library > World coverage, Governments > Map, Governments > Statistics, Insights >
Super-groups ring map).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each lead was reproduced in Chromium first and measured there after. CI runs no browser,
so the behaviour runs as real, EXTRACTED code under node
(``tests/clickthrough_b20_node_test.js``: R1, R3, R4, R6, R9); what is wiring between
two files, a layout rule or a contract with the locale files is pinned here from the
shipped sources. R2 lives in ``tests/test_countries_geo.py`` (the asset) and R5 in
``tests/test_ring_country_split.py`` (the endpoint's sentences).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from src.stats import indicators
from tests.js_source_helper import (
    event_listener_bodies,
    function_body,
    read_static,
    strip_comments,
)

_ROOT = Path(__file__).resolve().parent.parent
_LOCALES = _ROOT / "src" / "static" / "locales"
_CODES = ("ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh")


def test_the_behaviour_runs_as_real_code_under_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "clickthrough_b20_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


# --- R1: the contested area's name ------------------------------------------ #


def test_the_contested_name_reads_the_locale_i18n_actually_exports():
    """``OOI18N.lang`` was never defined by i18n.js, so the resolver always fell back
    to English. The engine exports ``current()``; nothing in the UI may read ``.lang``."""
    i18n = read_static("i18n.js")
    assert "window.OOI18N = { setLang, apply, current," in i18n
    body = strip_comments(function_body(read_static("app-map.js"), "_ooDisputedName"))
    assert "OOI18N.current()" in body and "OOI18N.lang" not in body, body
    for name in ("app-map.js", "app-core.js", "app-boot.js", "app-insights.js", "app-sources.js"):
        assert not re.search(r"OOI18N\.lang\b", strip_comments(read_static(name))), name


# --- R3: one worldview across surfaces --------------------------------------- #


def test_the_sources_repaint_stamp_carries_the_worldview():
    """The Sources map's repaint guard fingerprinted the payload and the locale, so a
    worldview chosen on another map left it drawing the old convention."""
    src = read_static("app-sources.js")
    body = strip_comments(function_body(src, "renderCoverageMap"))
    stamp = re.search(r"const stamp = JSON\.stringify\(\[([^\]]*)\]\)", body)
    assert stamp and "worldview" in stamp.group(1), stamp and stamp.group(1)
    assert 'typeof ooMapWorldview === "function"' in body
    assert "function ooMapWorldview() { return _ooMapWorldview; }" in read_static("app-map.js")


# --- R4: the two maps that did not follow a language switch ------------------ #


def test_the_language_switch_redraws_the_statistics_and_ring_maps_from_cache():
    boot = read_static("app-boot.js")
    handlers = event_listener_bodies(boot, "oo:langchange")
    assert any("repaintStatMapFromCache()" in h and "repaintRingMapFromCache()" in h for h in handlers), (
        "the ONE oo:langchange listener must redraw both maps (a second listener is a second enumerator)"
    )
    stat = strip_comments(function_body(read_static("app-map.js"), "repaintStatMapFromCache"))
    ring = strip_comments(function_body(read_static("app-insights.js"), "repaintRingMapFromCache"))
    # The level map draws a ranked table instead of the svg (re-walk L-3), so the
    # statistics guard names both; the ring map only ever draws the svg.
    assert 'querySelector("svg#oo-choro, table")' in stat, "redraw only a map that is on screen"
    assert 'querySelector("svg#oo-choro")' in ring, "redraw only a map that is on screen"
    for body in (stat, ring):
        assert "api(" not in body, "a language switch must never fetch"


# --- R6: the Governments map's unit ------------------------------------------ #


def test_every_catalogue_unit_word_is_keyed_in_all_twelve_locales():
    """The legend prints the unit after its maximum; the WORD translates, a symbol or a
    code (%, USD, intl$) does not -- SI and number formatting stay as they are."""
    units = {i["unit"] for i in indicators.INDICATOR_CATALOG if i.get("unit")}
    words = {u for u in units if re.search(r"[a-z]{3,}", u) and u not in ("USD", "intl$")}
    assert {"years", "people", "index", "per 1,000"} <= words, words
    for code in _CODES:
        data = json.loads((_LOCALES / f"{code}.json").read_text(encoding="utf-8"))
        for w in sorted(words):
            assert data.get(w, "").strip(), (code, w)
    gov = strip_comments(function_body(read_static("app-gov-law.js"), "_govMapDraw"))
    assert "unit: meta.unit ? t(meta.unit)" in gov, "the legend must receive the translated unit word"


# --- R7: the worldview picker's width ---------------------------------------- #


def test_the_worldview_select_has_no_fixed_width_cap():
    """A 150 px cap cut the default label mid-word, and the cut part was "(assign
    nothing)" -- the clause saying what the default does. Measured in Chromium: the
    select now shows its label whole in en/fr/ar/zh at 1440 px and the page does not
    overflow at 375 px."""
    src = strip_comments(read_static("app-map.js"))
    sel = re.search(r'<select class="tiny" data-oomap-worldview[^>]*style="([^"]*)"', src)
    assert sel, "the worldview select moved"
    assert not re.search(r"max-width:\s*\d+px", sel.group(1)), sel.group(1)
    assert "max-width:100%" in sel.group(1), "it must still never be wider than its row"
    label = re.search(r'<label class="oomap-worldview" style="([^"]*)"', src)
    assert label and "flex-wrap:wrap" in label.group(1), "the label and select must wrap at phone width"


# --- R8: the concept chip at 375 px ------------------------------------------ #


def test_a_concept_chip_can_wrap_its_language_list():
    """``(ara/deu/eng/…)`` was one unbreakable word; at 375 px it pushed the page 6 px
    sideways. Each "/" is now a break opportunity and the chip is capped at its row."""
    body = function_body(read_static("app-insights.js"), "renderConceptBrowse")
    chip = body[body.index('class="chip lvl-group'):]
    chip = chip[:chip.index("</button>")]
    assert 'style="max-width:100%;overflow-wrap:anywhere"' in chip, chip
    assert '.join("/<wbr>")' in chip and '.join("/")' not in chip, chip


# --- R9: the contested claims on touch ---------------------------------------- #


def test_the_contested_hover_is_on_the_carrier_the_tip_convention_marks():
    """#oo-tip marks ``[title]`` elements and long-presses only ``.oo-tip-target``; an SVG
    ``<title>`` child is neither, so on a phone the claims could not be reached at all."""
    layer = strip_comments(function_body(read_static("app-map.js"), "_ooDisputedLayer"))
    assert ' title="${esc(ti)}"' in layer and "<title>" not in layer, layer
    boot = read_static("app-boot.js")
    assert 'querySelectorAll("[title]")' in boot and 'closest(".oo-tip-target")' in boot
