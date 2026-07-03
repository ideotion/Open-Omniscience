"""Two-window consolidation: Source-competitive ported into the #an flagship (item 4).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The app is converging on ONE in-SPA analysis window (#an); the legacy #corpus-win
keyword modal is retired at the routing layer (openCorpus -> openAnalysisFor). The
ONE capability the modal still had that #an lacked was the Source-competitive subtab.
Batch F ports it INTO #an (absorption: nothing lost — the modal can now be retired in
a later browser-verified pass without losing a capability). It reuses the EXISTING
/api/insights/corpus-sources (+ /api/framing when a query defines the corpus)
endpoints; DESCRIPTIVE divergence, never a ranking / winner / composite score. Pure
string-assertion wiring guard (browser-unverified per fork-3).
"""

from __future__ import annotations

from pathlib import Path

from tests.test_repo_invariants import _ui_source

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_JS = (_STATIC / "app.js").read_text(encoding="utf-8")
_HTML = (_STATIC / "index.html").read_text(encoding="utf-8")


def test_routing_is_already_converged_on_the_an_window():
    # a keyword now spawns its own #an analysis tab — the singleton route
    assert "function openCorpus(term) { openAnalysisFor(term); }" in _JS
    # the retired #corpus-win modal is NEVER shown (no live opener)
    assert 'corpus-win").showModal' not in _JS
    assert "corpus-win').showModal" not in _JS


def test_an_flagship_now_has_a_competitive_subtab():
    # the #an nav gains the Competitive facet + its panel
    assert '<button data-tab="competitive"' in _HTML
    assert 'id="an-competitive"' in _HTML
    # dispatched lazily on show + re-rendered on a fresh corpus if visible
    assert 'if (key === "competitive") renderAnCompetitive(_anLastParams);' in _JS
    assert 'setTimeout(() => renderAnCompetitive(p), 0);' in _JS
    assert "_anCompetitive.key = null;" in _JS   # reset on a new analysis run


def test_competitive_reuses_existing_endpoints_scoped_to_the_an_corpus():
    assert "async function renderAnCompetitive(" in _JS
    # corpus-sources takes the #an params (article_ids OR query) -> scoped correctly
    assert 'api("/api/insights/corpus-sources?" + p.toString()' in _JS
    # framing is query-only: fetched ONLY when a query defines the corpus, honestly
    # absent (never wrong data) for an article-set corpus
    assert 'query ? api("/api/framing?query=" + encodeURIComponent(query))' in _JS
    assert 'const query = p.get("query");' in _JS


def test_competitive_is_descriptive_never_a_ranking_or_score():
    # the visible "not a ranking / no composite score" disclosure is present
    assert "never a ranking or a credibility judgement" in _JS
    assert "there is no winner and no composite score" in _JS
    # n=1 -> honest "nothing to compare"; tone falls back to a REAL value, never invented
    assert "Only one source in this corpus — nothing to compare." in _JS
    assert "(f.avg_tone != null) ? f.avg_tone : r.mean_tone" in _JS
    # no fabricated competitive score anywhere
    assert "competitiveScore" not in _JS and "competitive_score" not in _JS


def test_absorption_an_covers_every_modal_subtab():
    # nothing lost (the Desk lesson): #an declares every facet the retired modal had.
    for tab in ("keywords", "mindmap", "articles", "links", "sentiment", "sources",
                "competitive", "trend"):
        assert f'data-tab="{tab}"' in _HTML, f"#an must serve the {tab} facet"
