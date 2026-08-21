"""Content-provenance channel facet (wave 4 I, task 3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A Home "By channel" panel wiring GET /api/insights/source-types: article counts per
ASSERTED content channel (news/newsletter/wiki/statistics/law/market/discovery/untyped),
a descriptive fact known by construction, NEVER a quality score. Clicking a channel
resolves it to an explicit article-id set through /api/articles?source_type= (the
existing filter param) and opens the analysis window over exactly those ids, so ALL
analysis subtabs narrow honestly by channel using only endpoints that already exist.
Hidden when the corpus has no channels (Home is never blank-and-silent). Pure
string-assertion wiring guard (browser-unverified per fork-3).
"""

from __future__ import annotations

from pathlib import Path
from tests.js_source_helper import app_js

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_HTML = (_STATIC / "index.html").read_text(encoding="utf-8")
_JS = app_js()


def test_panel_exists_hidden_and_wired():
    import re

    m = re.search(r'<section[^>]*id="home-channels-panel"[^>]*>', _HTML)
    assert m and "hidden" in m.group(0)
    assert 'id="home-channels"' in _HTML
    assert "loadHomeChannels();" in _JS
    assert "async function loadHomeChannels(" in _JS


def test_reads_source_types_and_shows_counts_per_channel():
    assert '"/api/insights/source-types"' in _JS
    # article counts per channel are shown (f.source_type + f.articles)
    assert "f.source_type" in _JS and "f.articles" in _JS


def test_click_narrows_the_whole_corpus_via_the_source_type_filter():
    assert "async function openChannelCorpus(" in _JS
    # resolves the channel to an id set through the existing /api/articles?source_type=
    assert '"/api/articles?source_type=" + encodeURIComponent(st)' in _JS
    # then hands the exact id set to the analysis window (all subtabs narrow)
    assert "openAnalysisForIds(ids," in _JS


def test_descriptive_channel_never_a_quality_score():
    # the visible caveat states it is an asserted channel, never a quality score
    assert "never a quality score" in _HTML  # the panel intro <p>
    # ... and the same on the chip hover (invariant #17 layering)
    assert 't("An asserted content channel (newsletter, web article, wiki, statistic, law, market, discovery), never a quality score. Click a channel to explore its corpus.")' in _JS


def test_failsafe_hides_when_no_channels():
    assert "if (!facets.length) { panel.hidden = true; box.innerHTML = \"\"; return; }" in _JS


def test_strings_translated_x12():
    import json

    for loc in ("en", "fr", "de", "ar", "zh"):
        data = json.loads((_STATIC / "locales" / f"{loc}.json").read_text(encoding="utf-8"))
        assert "By channel" in data
        assert "Channel: {c}" in data


def test_a_share_is_always_shown_against_a_stated_denominator():
    """A bare count cannot answer "is this channel most of my corpus or a rounding
    error?", so each chip carries its share -- and the denominator is stated, because an
    unstated one is the usual way a percentage lies.

    The denominator is honest by construction on both sides: ``Article.source_id`` is NOT
    NULL, so every article lands in exactly one channel, and ``source_type_facets``
    excludes quarantined articles exactly as the browse path does (it did not, until the
    fix in this same change), so the facets really do sum to the corpus the share is a
    share OF.
    """
    body = _JS[_JS.index("async function loadHomeChannels("):]
    body = body[:body.index("async function openChannelCorpus(")]
    assert "facets.reduce(" in body, "the denominator must be computed, not assumed"
    assert "{n} articles across {k} channels" in body, "and stated to the reader"
    # The raw count stays BESIDE the share: the number is what the reader checks the
    # percentage against, so this adds to the chip rather than replacing its contents.
    assert "f.articles" in body and "share(f.articles)" in body
    # A sub-0.5% channel must not round to a bare "0%", which reads as nothing at all.
    assert '"<1%"' in body


def test_the_chips_keep_their_click_rather_than_becoming_bars():
    """The project's chart framework prescribes sorted bars for part-to-whole, and
    ``_ooShareBars`` already implements exactly that -- but its rows are not clickable and
    these chips open the channel's corpus. Swapping them would trade a working tool for a
    prettier read of the same numbers (the standing "never lose a tool" rule), so the
    shares came to the chips instead."""
    body = _JS[_JS.index("async function loadHomeChannels("):]
    body = body[:body.index("async function openChannelCorpus(")]
    assert "openChannelCorpus(" in body, "every chip must still open its corpus"
    assert "_ooShareBars(" not in body, "the clickable chips are not replaced by bars"
