"""P1 fix: article_intelligence's numpy/scikit-learn dependency must be optional.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Before this fix, ``src.services.article_intelligence`` hard-imported numpy and
scikit-learn at module top level with no try/except, even though most of
``ArticleIntelligenceAnalyzer``'s methods never touch either package. Since those
packages live behind pyproject's optional ``[analysis]`` extra, that made the whole
module — and therefore ``src.api.keyword_analysis`` and (transitively, via one
shared try/except in ``src/api/_wiring.py``) ``src.api.keyword_management``, which
has genuinely zero ML dependency — fail to import on a core-only install.

These tests simulate that core-only install by blocking ``numpy`` in
``sys.modules`` (Python raises ImportError for ``import numpy`` when
``sys.modules["numpy"] is None`` — the standard way to force an import failure
without needing the package to actually be absent) and reimporting the module
fresh, then prove: (a) the import itself no longer raises, (b) every pure-Python
method still works, and (c) the one method that genuinely needs scikit-learn still
fails — loudly and actionably, never silently — when it's missing.
"""

from __future__ import annotations

import importlib
import sys

import pytest

_MODULE_NAME = "src.services.article_intelligence"


def _reload_without_sklearn(monkeypatch):
    """Reimport article_intelligence with numpy unimportable; restored by monkeypatch."""
    # sys.modules[name] = None is the standard mechanism to force `import name` to
    # raise ImportError even when the real package is installed and already
    # importable — it does NOT require numpy/scikit-learn to actually be absent,
    # so this test is meaningful whether or not the [analysis] extra happens to be
    # installed in the environment running it.
    monkeypatch.setitem(sys.modules, "numpy", None)
    monkeypatch.setitem(sys.modules, "sklearn", None)
    monkeypatch.delitem(sys.modules, _MODULE_NAME, raising=False)
    return importlib.import_module(_MODULE_NAME)


def test_module_imports_cleanly_without_numpy_or_sklearn(monkeypatch):
    mod = _reload_without_sklearn(monkeypatch)
    assert mod.HAS_SKLEARN is False


def test_pure_python_methods_all_work_without_sklearn(monkeypatch):
    mod = _reload_without_sklearn(monkeypatch)
    analyzer = mod.ArticleIntelligenceAnalyzer()

    text1, text2 = "the cat sat on the mat", "the cat ran in the park"

    # None of these need numpy/sklearn at all.
    for method in ("jaccard", "euclidean", "manhattan"):
        score = analyzer.calculate_similarity(text1, text2, method=method)
        assert isinstance(score, float)

    cosine_no_tfidf = analyzer.calculate_similarity(
        text1, text2, method="cosine", use_tfidf=False
    )
    assert isinstance(cosine_no_tfidf, float)

    terms = analyzer.extract_terms_with_metadata(text1)
    assert "terms" in terms and "frequencies" in terms

    # group_by_similarity with a non-TF-IDF method also needs no ML dependency —
    # its similarity-matrix bookkeeping is a plain nested list, not np.zeros.
    grouped = analyzer.group_by_similarity(
        [{"content": text1}, {"content": text2}], method="jaccard"
    )
    assert isinstance(grouped, list) and grouped


def test_tfidf_cosine_similarity_fails_loudly_without_sklearn(monkeypatch):
    """Honesty by construction: a genuinely ML-dependent call must raise a clear,
    actionable error — never silently no-op or fall back to a degraded result."""
    mod = _reload_without_sklearn(monkeypatch)
    analyzer = mod.ArticleIntelligenceAnalyzer()

    with pytest.raises(ImportError, match=r"\[analysis\]"):
        analyzer.calculate_similarity(
            "the cat sat", "the cat ran", method="cosine", use_tfidf=True
        )

    # group_by_similarity defaults to TF-IDF cosine, so it must raise the same way.
    with pytest.raises(ImportError, match=r"\[analysis\]"):
        analyzer.group_by_similarity([{"content": "a b c"}, {"content": "a b d"}])


def test_tfidf_cosine_similarity_still_works_when_sklearn_is_installed():
    """No regression for a genuine [analysis]-extra install: skipped, not failed,
    when scikit-learn genuinely is not installed in this environment."""
    pytest.importorskip("sklearn")
    pytest.importorskip("numpy")
    mod = importlib.import_module(_MODULE_NAME)
    importlib.reload(mod)  # in case an earlier test in this file left it reimported
    assert mod.HAS_SKLEARN is True

    analyzer = mod.ArticleIntelligenceAnalyzer()
    score = analyzer.calculate_similarity(
        "the cat sat on the mat", "the cat ran in the park", method="cosine", use_tfidf=True
    )
    assert 0.0 <= score <= 1.0
