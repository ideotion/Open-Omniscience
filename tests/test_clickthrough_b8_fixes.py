"""Batch B8 of the 2026-09-26 delegated click-through, pinned: the Home at-a-glance strip
(H8, P7, S4, U5), Home at phone width (S7, T3), the Library's Database & storage tiles
(S6), and the task-manager page (T5, T6, O4).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each fix was reproduced in Chromium first and measured there after
(``docs/audit/delegated-clickthrough-2026-09-26/`` holds the rows). CI runs no browser,
so the behaviour runs as real, EXTRACTED code under node
(``tests/clickthrough_b8_node_test.js``) and the layout fixes are pinned by the CSS
rule each one rests on.
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
    css_rule,
    event_listener_bodies,
    function_body,
    object_literal,
    read_static,
)

_ROOT = Path(__file__).resolve().parent.parent
_LOCALES = _ROOT / "src" / "static" / "locales"


def _locales() -> dict[str, dict]:
    out = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in _LOCALES.glob("*.json")}
    assert len(out) == 12, f"expected 12 locale files, found {len(out)}"
    return out


def _string_values(literal: str) -> list[str]:
    """The double-quoted VALUES of a flat `{key: "value", ...}` JS object literal."""
    vals = re.findall(r":\s*\"((?:[^\"\\]|\\.)*)\"", literal)
    assert vals, "no string values parsed out of the literal"
    return vals


def test_the_behaviour_runs_as_real_code_under_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "clickthrough_b8_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


# --- H8, P7, S4, S6, U5: the labels ---------------------------------------- #


def test_every_count_label_and_split_hover_is_keyed_in_all_twelve_locales():
    """The labels reach t() through a VARIABLE, so none of the four i18n gates can see
    them -- which is exactly how `sources_qualified` and friends shipped as a string no
    locale file held (the fallback `k.replace(/_/g, " ")`). This check is the gate for
    them: every value of both maps, keyed in every locale, every placeholder kept."""
    home = read_static("app-home.js")
    wanted = _string_values(object_literal(home, "HOME_STAT_LABELS")) + _string_values(
        object_literal(home, "HOME_SOURCE_SPLIT_HOVER")
    )
    assert len(wanted) == 12, f"expected 9 labels + 3 hovers, parsed {len(wanted)}"
    for loc, data in _locales().items():
        for key in wanted:
            assert data.get(key), f"{loc}.json has no value for {key[:60]!r}"
            for slot in re.findall(r"\{\w+\}", key):
                assert slot in data[key], f"{loc}.json dropped {slot} from {key[:60]!r}"


def test_the_three_source_split_keys_are_labelled_on_the_home_strip():
    labels = object_literal(read_static("app-home.js"), "HOME_STAT_LABELS")
    for key in ("sources_qualified", "sources_pending", "sources_candidates"):
        assert f"{key}:" in labels, f"HOME_STAT_LABELS has no label for {key}"


def test_the_library_tiles_use_the_one_shared_label_map():
    """S6: the Library carried its own map for three keys and printed the rest raw."""
    lib = read_static("app-library.js")
    assert_absent(lib, "DB_STAT_LABELS", why="the tiles read Home's map (homeStatLabel)")
    paint = function_body(lib, "_paintDbStatLabels")
    assert_present(paint, "homeStatLabel(k)")
    assert_present(paint, "homeSourceSplitHover(k, counts)")
    load = function_body(lib, "loadDbStats")
    assert_present(load, "_paintDbStatLabels();")
    # The tiles own their text, so the walker never caches a French label as the English.
    assert_present(load, 'class="stat" id="db-t-${k}" data-i18n-dyn')


def test_the_langchange_listener_repaints_the_glance_and_the_tiles_without_fetching():
    handlers = event_listener_bodies(app_js(), "oo:langchange")
    assert any("repaintHomeGlance()" in h for h in handlers), (
        f"{len(handlers)} oo:langchange listener(s), none repaints the Home strip"
    )
    assert any("_paintDbStatLabels()" in h for h in handlers), (
        f"{len(handlers)} oo:langchange listener(s), none relabels the Library tiles"
    )
    # The repaint reads the cache: it neither calls api() nor re-runs the loaders.
    home = read_static("app-home.js")
    repaint = function_body(home, "repaintHomeGlance")
    assert_absent(repaint, "api(")
    assert_absent(repaint, "loadHome")
    assert_absent(function_body(read_static("app-library.js"), "_paintDbStatLabels"), "api(")


# --- S7, T3: Home at 375 px ------------------------------------------------ #


def test_the_corpus_tier_wraps_between_its_parts_and_keeps_its_caveat_on_screen():
    """A whole-chip nowrap put the early-corpus caveat 71 px off a 375 px screen. The chip
    now wraps between badge, numbers and caveat, and the caveat itself is never nowrap,
    so no width can push it out of view (the caveats-visible non-negotiable)."""
    css = read_static("app.css")
    tier = css_rule(css, ".corpus-tier").replace(" ", "")
    assert "flex-wrap:wrap" in tier and "max-width:100%" in tier, tier
    assert "white-space:nowrap" not in tier, "the whole tier chip is nowrap again"
    caveat = css_rule(css, ".corpus-tier .tier-caveat").replace(" ", "")
    assert "nowrap" not in caveat
    for rule in re.findall(r"([^{}]*)\{[^{}]*white-space:\s*nowrap", css):
        assert ".tier-caveat" not in rule, f"the caveat is made nowrap by: {rule.strip()}"


# --- T5, T6, O4: the task-manager page ------------------------------------- #


def test_the_task_manager_tab_row_scrolls_inside_its_own_box():
    tm = read_static("taskmanager.html")
    tabs = css_rule(tm, ".tm-tabs").replace(" ", "")
    assert "overflow-x:auto" in tabs, tabs
    button = css_rule(tm, ".tm-tabs button").replace(" ", "")
    assert "flex:none" in button, button


def test_the_task_manager_awaits_the_locale_before_walking_the_document():
    body = function_body(read_static("taskmanager.html"), "applyLang")
    assert_present(body, "Promise.resolve(lang && I.setLang ? I.setLang(lang) : null)")
    assert_present(body, ".then(function () { if (I.apply) I.apply(document); })")


def test_the_task_manager_langchange_listener_retitles_and_repaints_from_cache():
    tm = read_static("taskmanager.html")
    handlers = event_listener_bodies(tm, "oo:langchange")
    assert any("OOI18N.apply(document.head)" in h for h in handlers), (
        "setLang's own apply() starts at document.body, so the <title> needs its own walk"
    )
    assert any("repaintFromCache()" in h for h in handlers)
    repaint = function_body(tm, "repaintFromCache")
    for call in ("renderSummary(", "paintHealth()", 't("Live")'):
        assert_present(repaint, call)
    assert_absent(repaint, "api(")
    assert_absent(repaint, "refresh()")
