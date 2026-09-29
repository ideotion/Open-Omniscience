"""S13 + S05-11 S3 — the Conjunction-Lens N-keyword picker, on every vertical.

ONE component (``conjLensHtml(pfx, scope)``) hosts the lens: in the analysis window's Keywords
subtab (``an``) with a scope select (the whole corpus, press and the web, Wikipedia, law), and in
``#conj-dialog`` (``cd``) opened from Living sources' Wikipedia and Law panels and from the place
card. It calls the live GET /api/insights/corpus-algebra with the scope, renders each set's n and
the set EXPRESSION, the three panels over the same set (where the terms cluster, when it was
discussed, compare with another combination), the near search, and opens the exact result set as
its own corpus via openAnalysisForIds. Counts only, never a score.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from pathlib import Path

from tests.js_source_helper import app_js, function_body

_JS = app_js()
_HTML = (Path(__file__).resolve().parents[1] / "src/static/index.html").read_text(encoding="utf-8")


def test_picker_functions_and_controls_are_wired():
    for fn in ("function conjLensHtml", "function anConjunctionHtml", "async function conjCombine",
               "function anCombineHtml", "function conjOpenCombined", "function conjPanelsHtml",
               "async function conjContrast", "function conjSearchNear", "function openConjunctionLens"):
        assert fn in _JS, fn
    lens = function_body(_JS, "conjLensHtml")
    assert 'id="${pfx}-conj-terms"' in lens and 'id="${pfx}-conj-result"' in lens
    for op in ("intersection", "union", "difference"):
        assert f"conjCombine('${{pfx}}','{op}')" in lens, op


def test_the_analysis_window_hosts_the_lens_with_a_scope_select():
    assert "conjLensHtml(\"an\")" in function_body(_JS, "anConjunctionHtml")
    lens = function_body(_JS, "conjLensHtml")
    assert 'id="${pfx}-conj-scope"' in lens and "conjScope('${pfx}')" in lens
    for ch in ('["web", "Press and the web"]', '["wikipedia", "Wikipedia"]', '["law", "Law"]'):
        assert ch in _JS, ch


def test_picker_calls_the_live_endpoints_with_the_scope():
    combine = function_body(_JS, "conjCombine")
    assert "/api/insights/corpus-algebra?terms=" in combine and "&op=" in combine
    assert "expand=intensity,trend" in combine and "_conjScopeParams(h.scope)" in combine
    contrast = function_body(_JS, "conjContrast")
    assert "/api/insights/corpus-contrast?terms=" in contrast and "_conjScopeParams(h.scope)" in contrast
    params = function_body(_JS, "_conjScopeParams")
    assert "&place=" in params and "&channel=" in params


def test_every_vertical_has_an_entry_point():
    assert "openConjunctionLensChannel('wikipedia')" in _HTML
    assert "openConjunctionLensChannel('law')" in _HTML
    assert '<dialog id="conj-dialog"' in _HTML and 'id="conj-dialog-body"' in _HTML
    # the place card opens the lens scoped to the articles naming the place
    assert "openConjunctionLens({place_id: d.id" in _JS
    assert "pc-conj" in function_body(_JS, "renderPlaceCard")


def test_open_as_corpus_uses_the_exact_id_set_path():
    assert "openAnalysisForIds(d.article_ids" in function_body(_JS, "conjOpenCombined")


def test_the_near_search_runs_in_the_search_tab():
    seg = function_body(_JS, "conjSearchNear")
    assert 'showTab("search")' in seg and "d.near.query" in seg and "doSearch()" in seg


def test_picker_is_hosted_in_the_keywords_subtab_render():
    # anRenderKwChips prepends the picker in BOTH branches (empty + populated keyword sets),
    # and restores the held result in both.
    body = function_body(_JS, "anRenderKwChips")
    assert body.count("anConjunctionHtml()") >= 2
    assert body.count('_conjRestore("an")') >= 2


def test_honest_empty_bounded_and_scoped_states():
    assert "Enter at least one keyword" in function_body(_JS, "conjCombine")  # 0-keyword
    combined = function_body(_JS, "anCombineHtml")
    assert "Empty set" in combined
    assert "Result bounded" in combined and "SUBSET" in combined
    assert "Read in: {scope} · {n} articles" in combined  # the scope always named
    assert "the first articles only" in combined  # a capped place scope, disclosed
    assert "never a score" in function_body(_JS, "conjLensHtml")
    panels = function_body(_JS, "conjPanelsHtml")
    assert "never a rank of importance" in panels
    assert "not the publication date" in panels
    assert "never a verdict" in function_body(_JS, "conjContrastHtml")


def test_no_score_word_leaks_as_a_field():
    for fn in ("anCombineHtml", "conjPanelsHtml", "conjContrastHtml"):
        seg = function_body(_JS, fn).lower()
        for banned in ("ranking", "rating", "grade"):
            assert banned not in seg, (fn, banned)


def test_the_lens_repaints_on_a_language_switch():
    assert "repaintConjunctionLens()" in (Path(__file__).resolve().parents[1]
                                          / "src/static/app-boot.js").read_text(encoding="utf-8")
