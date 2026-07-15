"""S13 — the Conjunction-Lens N-keyword picker (analysis-window Keywords subtab).

The picker calls the live GET /api/insights/corpus-algebra (∩ all / ∪ any / ∖ first-only),
renders each set's n + the set EXPRESSION as the corpus label, and opens the exact result set
as its own corpus via openAnalysisForIds (the exact-set precedent). Source-pinned + node --check
guarded (no headless browser here); honest empty/1-keyword states; counts only, never a score.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from pathlib import Path

_JS = Path("src/static/app.js").read_text(encoding="utf-8")


def test_picker_functions_and_controls_are_wired():
    for fn in ("function anConjunctionHtml", "async function anCombine", "function anCombineHtml",
               "function anOpenCombined"):
        assert fn in _JS, fn
    assert 'id="an-conj-terms"' in _JS and 'id="an-conj-result"' in _JS
    # the three set-algebra ops
    for op in ("anCombine('intersection')", "anCombine('union')", "anCombine('difference')"):
        assert op in _JS, op


def test_picker_calls_the_live_corpus_algebra_endpoint():
    assert "/api/insights/corpus-algebra?terms=" in _JS
    assert "&op=" in _JS


def test_open_as_corpus_uses_the_exact_id_set_path():
    # the result set opens its own corpus via the exact-set precedent, labelled by the expression
    seg = _JS[_JS.index("function anOpenCombined"): _JS.index("function anRenderKwChips")]
    assert "openAnalysisForIds(d.article_ids" in seg


def test_picker_is_hosted_in_the_keywords_subtab_render():
    # anRenderKwChips prepends the picker in BOTH branches (empty + populated keyword sets).
    assert _JS.count("anConjunctionHtml()") >= 2


def test_honest_empty_and_bounded_states():
    seg = _JS[_JS.index("function anConjunctionHtml"): _JS.index("function anRenderKwChips")]
    assert "Enter at least one keyword" in seg  # honest 0-keyword state
    assert "Empty set" in seg  # honest empty-result state
    assert "Result bounded" in seg and "SUBSET" in seg  # discloses a capped result honestly
    assert "never a score" in seg  # the honesty disclaimer is shown


def test_no_score_word_leaks_as_a_field():
    seg = _JS[_JS.index("function anCombineHtml"): _JS.index("async function anCombine")].lower()
    # the render shows counts (n) only; the only 'score' occurrence anywhere is the disclaimer.
    for banned in ("ranking", "rating", "grade"):
        assert banned not in seg, banned
