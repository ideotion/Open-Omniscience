"""Clickable-keyword hover-stats (wave 4 I, task 2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Hovering any keyword surface marked data-kwstat surfaces its REAL stats — total
mentions, distinct-article spread, the windowed recent-vs-prior trend RATE, and the top
co-occurrences (GET /api/insights/keyword-stats) — through the ONE #oo-tip bubble in the
SPA (invariant #17), and via the native title in the standalone reader (which has no
#oo-tip). Counts only, the endpoint's caveat rides along, NO score. Lazy + cached (no
fetch storm), loopback-only (airplane-safe). Pure string-assertion wiring guard
(browser-unverified per fork-3).
"""

from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_JS = (_STATIC / "app.js").read_text(encoding="utf-8")
_READER = (_STATIC / "reader.js").read_text(encoding="utf-8")


def test_spa_hover_handler_uses_the_oo_tip_convention():
    assert "ooKwStatInit" in _JS
    # lazy, cached fetch of the real stats endpoint
    assert '"/api/insights/keyword-stats?term=" + encodeURIComponent(term)' in _JS
    # writes the #oo-tip convention (dataset.ooTip / the shared #oo-tip bubble)
    assert "el.dataset.ooTip = text" in _JS
    assert 'document.getElementById("oo-tip")' in _JS
    # hover + keyboard focus both trigger it (invariant #17 covers focus)
    assert 'document.addEventListener("mouseover", onHover, true)' in _JS
    assert 'document.addEventListener("focusin", onHover, true)' in _JS


def test_spa_keyword_surfaces_are_marked():
    # the analysis-window Keywords chips
    assert '<button class="chip" data-kwstat="${esc(term.term)}"' in _JS
    # the Insights Trends bars
    assert '<a class="tb-label" href="#" data-kwstat="${esc(t.term)}"' in _JS
    # the keyword list rows (given a placeholder title so #oo-tip marks them)
    assert '<a href="#" data-kwstat="${esc(t.term)}" title="${esc(t.term)}"' in _JS


def test_spa_stats_are_counts_with_method_caveat_no_score():
    # mentions + distinct-article spread + windowed trend rate + co-occurrences
    assert 't("mentions")' in _JS and 't("articles")' in _JS
    assert 't("trend")' in _JS and "tr.growth" in _JS
    assert "d.cooccurrences" in _JS
    # the endpoint caveat is appended (method/caveat visible)
    assert 'd.caveat ? " · " + d.caveat : ""' in _JS
    # honest empty state for an unknown term
    assert 't("Not in your corpus yet — no stats.")' in _JS
    # the transient "Loading…" placeholder is live-bubble-only (persist=false), never
    # written to dataset.ooTip/title, so an abandoned+failed fetch can't strand it as
    # the element's permanent tooltip (runtime-review fix).
    assert 'applyTo(el, t("Loading keyword stats…"), false)' in _JS
    assert "function applyTo(el, text, persist)" in _JS


def test_reader_marks_and_hover_handler():
    # in-article marks + Keywords-tab links carry data-kwstat
    assert 'a.setAttribute("data-kwstat", s.term)' in _READER
    assert "data-kwstat=\"' + esc(term) + '\"" in _READER
    # a lazy, cached, guarded hover enriches the native title with the real stats
    assert "function enrichKwStat(" in _READER
    assert '"/api/insights/keyword-stats?term=" + encodeURIComponent(term)' in _READER
    assert "kwStatLine(d)" in _READER
    # counts + the caveat, never a score
    assert '" mentions · "' in _READER
    assert "d.caveat" in _READER


def test_strings_translated_x12():
    import json

    for loc in ("en", "fr", "de", "ar", "zh"):
        data = json.loads((_STATIC / "locales" / f"{loc}.json").read_text(encoding="utf-8"))
        for key in ("Loading keyword stats…", "trend", "Not in your corpus yet — no stats."):
            assert key in data, f"{loc}.json missing {key!r}"
