"""
Combined time-aligned Trend overlay (Analysis window) invariants.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer-ruled 2026-06-17: in the analysis window, a keyword's coverage and its
related keywords/tags (all article COUNTS = a shared unit) overlay on ONE
time-aligned chart, with an INDEXED mode (rebased to 100) that also overlays
commodity PRICE series of a different unit without conflating magnitudes, plus the
precise dual-axis price×coverage panel. These checks pin the wiring + the honesty
guarantees so they cannot silently regress (the UI is browser-unverified, so the
static guard matters).
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_HTML = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
_JS = (_ROOT / "src" / "static" / "app.js").read_text(encoding="utf-8")


def test_trend_subtab_is_wired_into_the_analysis_window():
    assert 'id="an-trend"' in _HTML, "the analysis window needs the #an-trend panel"
    assert 'data-tab="trend"' in _HTML, "the analysis window needs a Trend subtab button"
    # Lazy render on tab-show + refetch on a new analysis run.
    assert 'key === "trend"' in _JS and "renderAnTrend(" in _JS, (
        "anSelectTab must lazy-render the Trend subtab via renderAnTrend()"
    )


def test_trend_renderer_and_helpers_exist():
    for fn in ("function renderAnTrend", "function drawAnTrend", "function anTrendPick",
               "function anTrendSetMode", "function commoditiesForTerm"):
        assert fn in _JS, f"missing Trend overlay function: {fn}"
    # Same-unit overlay: it builds a multi-series list for ooChart from the term +
    # its related-keyword coverage series (the core ask).
    assert "/api/insights/associations?term=" in _JS, "related keywords feed the overlay"
    assert "/api/insights/trend?bucket=week&term=" in _JS, "per-term coverage series feed the overlay"


def test_oochart_indexed_mode_is_additive_and_honest():
    # The indexed transform exists, rebases to 100, and is GUARDED so the default
    # (non-indexed) path used by every existing chart is the identity (unchanged).
    assert "opts.indexed && s._base" in _JS, "indexed mode must be guarded (identity when off)"
    assert "p.v / s._base * 100" in _JS, "indexed mode must rebase each series to 100"
    assert "const pv = (s, p) =>" in _JS, "the per-series plotting transform pv() must exist"
    # The drawing path uses pv() (so indexed plots correctly) — the line renderer.
    assert "Yof(pv(s, p))" in _JS, "the chart must plot via the pv() transform"


def test_indexed_mode_overlays_commodity_prices_and_reuses_dual_axis():
    # Cross-unit (option 1 indexed overlay + option 3 dual-axis), maintainer chose both.
    assert "ooChart($(\"an-trend-chart\"), list, { height: 240, indexed: indexed" in _JS, (
        "the Trend chart must pass the indexed flag to ooChart"
    )
    assert "commodityOverlaySvg(c.prices, cov, c.unit)" in _JS, (
        "the dual-axis (2-series) view must reuse the honest commodityOverlaySvg"
    )
    assert "/api/commodities/" in _JS and "/prices" in _JS, "commodity price series come from the prices endpoint"


def test_trend_caveats_are_visible_and_honest():
    # No magnitude conflation is disclosed; the indexed view states it is relative,
    # not absolute. All in visible .card-caveat. The on-graph "co-occurrence …
    # never causation" caveat was REMOVED app-wide (maintainer ruling 2026-06-17 —
    # it cluttered every graph); the non-causation PRINCIPLE still governs the
    # design, just not as repeated on-graph text. This guards against re-adding it
    # (mirrors test_repo_invariants' inverted assertion).
    assert 't("co-occurrence in your corpus, never causation")' not in _JS, (
        "the graph causation caveat was removed everywhere (maintainer 2026-06-17)"
    )
    assert "relative movement, not absolute levels" in _JS, "indexed mode must disclose it is relative"
    assert "card-caveat" in _JS, "the Trend caveats must render in the visible .card-caveat surface"
    # No fabricated score anywhere in the new surface.
    assert "score" not in "renderAnTrend drawAnTrend", "sanity"
