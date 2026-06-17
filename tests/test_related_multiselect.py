"""
Related subtab — multi-select branch (PR 4b).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer-ruled 2026-06-17: let the user SELECT several near-dup clusters and/or
shared origins in the Related subtab and branch their UNION into one new corpus
(associated research over a hand-picked combination). Frontend-only, reuses the
existing per-row branch endpoints. Browser-unverified -> static guard.
"""

from __future__ import annotations

from pathlib import Path

_JS = (Path(__file__).resolve().parents[1] / "src" / "static" / "app.js").read_text(encoding="utf-8")


def test_multiselect_controls_exist():
    assert 'class="an-rel-pick"' in _JS, "each Related row needs a selection checkbox"
    assert 'data-kind="c"' in _JS and 'data-kind="o"' in _JS, "clusters + origins are both selectable"
    assert "function anRelUpdateSel" in _JS, "the live selected-count helper must exist"
    assert "Branch selected into a new corpus →" in _JS, "the multi-select branch button must exist"


def test_branch_selected_unions_clusters_and_origins():
    fn = _JS.split("async function branchSelectedRelated(", 1)[1].split("\n    }", 1)[0]
    assert "an-rel-pick:checked" in fn, "it must read the checked rows"
    assert "_anRelatedClusters[" in fn, "selected clusters contribute their article_ids"
    assert "articles-by-link" in fn, "selected origins fetch their citing-article ids"
    assert "openAnalysisForIds(arr" in fn, "the UNION spawns one new corpus"
    assert "new Set()" in fn, "ids are de-duplicated across the selected rows"


def test_per_row_branch_preserved():
    # PR 4b must not regress the single-row branches (#299 / #309).
    assert "function branchFromRelated" in _JS and "function branchFromOrigin" in _JS
