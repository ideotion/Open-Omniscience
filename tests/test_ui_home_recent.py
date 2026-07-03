"""Home dashboard: "Most recent by tag" recency lens (item #36 / #6).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A recency LENS onto the corpus (never a reweighting): newest-first by the article's
PUBLISHED date among sources carrying a chosen source tag, reusing /api/sources/facets
(the tag list) + /api/articles (tags + sort_by=date). Every title deep-links to the
offline stored reader (invariant #6). The panel is hidden until it has a tag + articles
so Home is never blank-and-silent (the Briefing still renders). The top trend-graph strip
already exists via loadHomeTrends (this test guards it still runs). Pure string-assertion
wiring guard (browser-unverified per fork-3).
"""

from __future__ import annotations

import re
from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_HTML = (_STATIC / "index.html").read_text(encoding="utf-8")
_JS = (_STATIC / "app.js").read_text(encoding="utf-8")


def test_recent_panel_exists_and_starts_hidden():
    m = re.search(r'<section[^>]*id="home-recent-panel"[^>]*>', _HTML)
    assert m, "the Most-recent panel must exist"
    assert "hidden" in m.group(0), "it starts hidden (Home is never blank-and-silent)"
    assert 'id="home-recent-tag"' in _HTML and 'id="home-recent"' in _HTML
    assert 'onchange="loadHomeRecentList(this.value)"' in _HTML


def test_wired_into_loadHome_and_trend_strip_kept():
    assert "loadHomeRecent();" in _JS
    assert "function loadHomeRecent(" in _JS and "function loadHomeRecentList(" in _JS
    # the top trend-graph strip already exists — guard it still loads
    assert "loadHomeTrends();" in _JS


def test_reuses_existing_endpoints_only():
    assert "/api/sources/facets" in _JS
    assert '"/api/articles?tags=" + encodeURIComponent(tag) + "&sort_by=date&sort_dir=desc' in _JS


def test_titles_open_the_offline_reader_invariant6():
    assert '/api/articles/${a.id}/view' in _JS
    assert 't("offline stored copy")' in _JS


def test_failsafe_hides_panel_on_no_data():
    # no tags -> hide; error -> hide; never a broken/empty div on Home.
    assert "if (!tags.length) { panel.hidden = true; return; }" in _JS
    assert "catch (e) { panel.hidden = true; }" in _JS


def test_recency_label_is_honest_and_translated():
    # honest: ordering is by the publisher-set published date, stated visibly.
    assert "published date (set by the publisher)" in _HTML
    en = (_STATIC / "locales" / "en.json").read_text(encoding="utf-8")
    fr = (_STATIC / "locales" / "fr.json").read_text(encoding="utf-8")
    assert '"Most recent"' in en and '"Most recent"' in fr
