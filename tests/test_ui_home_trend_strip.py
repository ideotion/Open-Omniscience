"""Home "Trending now" trend-graph strip contract (batch F item 3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The Home dashboard's compact strip of the top rising terms' sparklines (fed by
/api/insights/trending-windows with per-term daily series) — each deep-links to its
analysis window, the panel HIDES when nothing is trending (Home is never blank-and-
silent — the Briefing still renders), and batch F adds click-to-enlarge into the
interactive ooChart (matching the Insights Trends UX; the series is already in the
payload, no extra fetch). Pure string-assertion wiring guard (browser-unverified per
fork-3).
"""

from __future__ import annotations

from pathlib import Path

from tests.test_repo_invariants import _ui_source

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_JS = (_STATIC / "app.js").read_text(encoding="utf-8")


def test_home_trends_panel_and_loader_exist():
    ui = _ui_source()
    assert 'id="home-trends-panel"' in ui and 'id="home-trends"' in ui
    assert "async function loadHomeTrends()" in _JS
    assert "/api/insights/trending-windows?limit=4&series_top=4" in _JS


def test_strip_is_fail_safe_hidden_when_nothing_trending():
    # Home never blank-and-silent: no terms -> the panel hides, the Briefing remains.
    assert "if (!terms.length) { if (panel) panel.hidden = true;" in _JS


def test_each_term_deeplinks_and_shows_a_sparkline():
    assert "openAnalysisFor(" in _JS
    # the per-term daily series renders through the honest sparse->bars renderer
    assert 'dashChartSvg(x.series.map(p => ({observed_on: p.date, price: p.count})), "")' in _JS


def test_click_to_enlarge_added_reusing_chartEnlarge():
    assert "function enlargeHomeTrend(" in _JS
    assert "enlargeHomeTrend(${i})" in _JS
    # reuses the interactive ooChart enlarge dialog; no extra fetch (stashed payload)
    assert "_homeTrendTerms" in _JS and "_homeTrendCaveat" in _JS
    assert "chartEnlarge(x.term, [{label: x.term" in _JS
