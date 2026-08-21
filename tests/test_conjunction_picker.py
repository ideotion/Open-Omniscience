"""S13 — the Conjunction-Lens N-keyword picker (analysis-window Keywords subtab).

The picker calls the live GET /api/insights/corpus-algebra (∩ all / ∪ any / ∖ first-only),
renders each set's n + the set EXPRESSION as the corpus label, and opens the exact result set
as its own corpus via openAnalysisForIds (the exact-set precedent). Source-pinned + node --check
guarded (no headless browser here); honest empty/1-keyword states; counts only, never a score.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from tests.js_source_helper import app_js, function_body

_JS = app_js()


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
    seg = function_body(_JS, "anOpenCombined")
    assert "openAnalysisForIds(d.article_ids" in seg


def test_picker_is_hosted_in_the_keywords_subtab_render():
    # anRenderKwChips prepends the picker in BOTH branches (empty + populated keyword sets).
    assert _JS.count("anConjunctionHtml()") >= 2


def test_honest_empty_and_bounded_states():
    """Each honest state, scoped to the function that renders it.

    This test used to slice from anConjunctionHtml to anRenderKwChips -- four
    functions -- and three of its four claims were satisfied by siblings, not by the
    picker it named. Tightening the slice to anConjunctionHtml's real body made
    "Enter at least one keyword" fail, which is where the strings actually live:
    the 0-keyword state is anCombine's, the empty/bounded states are anCombineHtml's,
    and only the no-score disclaimer belongs to the picker itself.
    """
    assert "Enter at least one keyword" in function_body(_JS, "anCombine")  # 0-keyword
    combined = function_body(_JS, "anCombineHtml")
    assert "Empty set" in combined  # honest empty-result state
    assert "Result bounded" in combined and "SUBSET" in combined  # a capped result, disclosed
    assert "never a score" in function_body(_JS, "anConjunctionHtml")  # the disclaimer


def test_no_score_word_leaks_as_a_field():
    seg = function_body(_JS, "anCombineHtml").lower()
    # the render shows counts (n) only; the only 'score' occurrence anywhere is the disclaimer.
    for banned in ("ranking", "rating", "grade"):
        assert banned not in seg, banned
