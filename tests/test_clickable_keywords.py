"""Clickable in-article keywords (Slice 1, maintainer concept 2026-07-01).

In the offline reader the user SEES the article's keywords and can CLICK one to
open its full analysis (KEYWORDS ARE CORPORA): the Keywords-tab list is clickable
AND the real indexed terms are marked inline in the Read body. A click opens a new
SPA tab hydrated from `?analyze=<term>&tab=keywords`, landing on the Keywords
subtab seeded with the term.

Honesty by construction (the ledger's "no naive text scan"): only the article's
TRUSTED indexed keyword terms are ever marked — the marks come from the corpus
keyword index, never a scan for arbitrary words.

Pure string-assertion wiring guards over the static assets (no fastapi) so they
run in the sandbox and CI; node --check proves reader.js/app.js syntax, and the
pure segmenter core was unit-verified in node during development. This pins the
wiring so it cannot silently regress between sessions.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"


def _read(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8")


def test_reader_keyword_click_opens_the_analysis_window():
    js = _read("reader.js")
    # The deep-link shape the SPA boot hydrates: analyze the term ON the Keywords subtab.
    assert '"/?analyze=" + encodeURIComponent(term) + "&tab=keywords"' in js
    # The Keywords-tab list is clickable (kwLink wraps each term in an anchor).
    assert "function kwLink(" in js
    assert "kwLink(t.term" in js
    # A real anchor to the SPA — middle/ctrl-click work; opens in a new tab.
    assert 'target="_blank"' in js and 'rel="noopener"' in js


def test_reader_marks_only_trusted_indexed_keywords_inline():
    js = _read("reader.js")
    # Inline marking exists and is fed by the article's INDEXED keyword terms
    # (corpus-keywords), never a naive scan of arbitrary words.
    assert "function markArticleBody(" in js
    assert "function primeKeywords(" in js
    assert "/api/insights/corpus-keywords?limit=60&article_ids=" in js
    assert "primeKeywords();" in js
    # The inline anchors carry the mark class and the same analysis URL.
    assert 'a.className = "r-kw-mark"' in js
    assert "a.href = analysisUrl(s.term)" in js
    # The Read pane must never break over the nicety — the pass is fully guarded.
    assert "the read pane must never break" in js.lower()


def test_reader_inline_marking_is_boundary_aware_and_dedups_the_fetch():
    js = _read("reader.js")
    # Word-boundaried for spaced scripts (so "election" never marks inside
    # "reelection"); a bare substring for CJK/Hangul (no word boundaries).
    assert "(?<![\\\\p{L}\\\\p{N}_])" in js  # boundary lookbehind in the source
    assert "function isCJK(" in js
    # Longest-first so a phrase keyword wins over its component words.
    assert "longest first" in js
    # The eager marking fetch PRIMES the Keywords tab — one request serves both.
    assert "_kwPromise" in js


def test_reader_css_styles_the_clickable_keywords():
    css = _read("reader.css")
    assert ".r-kw-mark" in css          # the inline body marks
    assert ".r-kw:hover" in css or ".r-kw:focus-visible" in css  # the tab-list links are interactive


def test_spa_hydrates_the_keyword_deep_link_onto_the_keywords_subtab():
    js = _read("app.js")
    # The boot handler reads ?tab=, validates the panel exists, and stashes it;
    # it is applied once the analysis subtab component is wired.
    assert 'sp.get("tab")' in js
    assert "_anBootTab" in js
    assert 'document.getElementById("an-" + _anBootTab)' in js
    assert "_anSubtabs.select(_anBootTab)" in js
    # The stash is applied right after the subtab component is created.
    i_wire = js.index('_anSubtabs = ooSubtabs($("an-subtabs")')
    i_apply = js.index("_anSubtabs.select(_anBootTab)")
    assert i_wire < i_apply, "the ?tab= deep link must be applied AFTER _anSubtabs exists"
