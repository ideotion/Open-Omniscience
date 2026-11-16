"""One statement of each safeguard per screen in the full UI (open-on-main row 76, R682/R685).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Measured on main 5b734340b in Chromium (state C, every sidebar tab and sub-tab): the same
safeguard sentence was printed twice or more on one screen. Each fix below drops the
REPEAT and keeps the one statement that stays visible on that screen:

* Home > Overview: every card's ranking line opened with "Ranked by a disclosed order ...,
  never a score.", and the family caveat under the Overview states that order once. The card
  now shows its own facts; the whole line stays in its hover.
* Explore > Overview: "counts only, never a verdict" under the page's own line saying it.
* Explore > Keywords, Combine keywords: "counts only, never a score" beside the keyword
  list's own caveat (the same lens opened as a dialog from Living sources or a place card
  keeps the clause: no page line sits above it there).
* World map > Stories: "never a verdict" above the caveat that says it.

Not changed, on purpose: a caveat or method the SERVER sends travels as the signal's own
caveat (every signal carries method + caveat + n), and the Library coverage bars keep their
"no score" line (pinned by test_region_floor_bars).
"""
from __future__ import annotations

import json
from pathlib import Path

from tests.js_source_helper import app_js, function_body

_ROOT = Path(__file__).resolve().parent.parent
_STATIC = _ROOT / "src" / "static"


def _locales() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (_STATIC / "locales").glob("*.json")}


_NEW = (
    "A headline from each lens. Open any to dig in.",
    "set algebra over N keywords. The set expression is the corpus label.",
    "Location-based events extracted from your corpus, by type. Deduced from text — click a place to open its corpus.",
)


def test_the_trimmed_strings_are_used_and_keyed_in_all_12_locales():
    js = app_js()
    tables = _locales()
    assert len(tables) == 12
    for key in _NEW:
        assert f't("{key}")' in js, key
        for lang, table in tables.items():
            assert table.get(key), f"{lang}: {key!r}"


def test_the_one_statement_each_screen_keeps_is_still_there():
    js = app_js()
    # Explore: the page line under the search keeps "counts only, never a verdict".
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    assert "Analytics over the articles your search matched — counts only, never a verdict." in html
    # Home Overview: the family caveat states the order and "Never a score" once.
    assert "One Lead per family, chosen by the same disclosed order" in js
    # Stories: the caveat under the type chips keeps "never a verdict or ranking".
    assert "counts only, never a verdict or ranking" in js


def test_the_overview_card_shows_its_own_facts_and_keeps_the_order_in_its_hover():
    ov = function_body(app_js(), "_overviewHtml")
    assert 'title="${esc(whyText)}">${esc(own || whyText)}' in ov, "the whole line stays in the hover"
    assert "frs.slice(1)" in ov and "frs[0].t === _ORDER" in ov, (
        "only the shared ranking sentence is dropped from the face, and only when it is first"
    )
    # The sentence matched is the server's own frame, so a change there fails here first.
    leads = (_ROOT / "src" / "briefing" / "leads.py").read_text(encoding="utf-8")
    assert 'frame("Ranked by a disclosed order (independent sources → sample magnitude → recency), never a score.")' in leads
    assert 'const _ORDER = "Ranked by a disclosed order (independent sources → sample magnitude → recency), never a score.";' in ov


def test_the_card_math_line_is_not_monospace():
    css = (_STATIC / "app.css").read_text(encoding="utf-8")
    rule = css.split(".card .sig {", 1)[1].split("}", 1)[0]
    assert "--mono" not in rule and "color:var(--muted)" in rule


def test_dawn_tone_word_has_its_own_stronger_mix():
    # Row 77: dawn's tone word read 4.21-4.43:1 at 40 %; 75 % clears every panel level.
    css = (_STATIC / "app.css").read_text(encoding="utf-8")
    dawn = css.split(':root[data-theme="dawn"] {', 1)[1].split("}", 1)[0]
    assert "--ok-text:color-mix(in srgb, var(--fg) 75%, var(--ok) 25%)" in dawn
