"""
S5.2 — the rule-based subjectivity / loaded-language engine.

Proves the multilingual lexicon-file engine across THREE scripts (en Latin / ru Cyrillic /
ar Arabic) with the shipped SEED lexicons, the descriptive components + spans, and — the
load-bearing honesty — the per-language GAP (a language with no lexicon is declared
unmeasured, never scored at 0) and the no-composite-score discipline (field NAMES checked).
"""

from __future__ import annotations

from src.analytics import subjectivity as S


def _assert_no_score_keys(obj):
    """Walk the dict KEYS (not the repr) for a forbidden composite-score field name — the
    caveat legitimately says 'no score', so a repr substring check would false-trip."""
    banned = ("score", "rating", "ranking", "verdict", "credibility")
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert not any(b in str(k).lower() for b in banned), f"score-shaped key {k!r}"
            _assert_no_score_keys(v)
    elif isinstance(obj, list):
        for x in obj:
            _assert_no_score_keys(x)


def test_lexicons_load_for_three_scripts():
    for lang in ("en", "ru", "ar"):
        lex = S.load_lexicon(lang)
        assert lex and len(lex) >= 10, f"{lang} seed lexicon should load non-empty"
    assert {"en", "ru", "ar"} <= S.available_languages()


def test_absent_or_empty_language_has_no_lexicon():
    assert S.load_lexicon("de") is None  # no de.txt shipped
    assert S.load_lexicon("") is None and S.load_lexicon(None) is None


def test_comment_and_blank_lines_are_ignored():
    lex = S.load_lexicon("en")
    assert lex is not None
    assert not any(w.startswith("#") for w in lex)  # header comments never become terms


def test_english_loaded_language_components_and_spans():
    d = S.subjectivity("This is an outrageous scandal, absolutely shocking.", "en")
    assert d["available"] is True and d["language"] == "en"
    assert d["n_loaded"] >= 3 and 0 < d["density"] <= 1
    assert {"outrageous", "scandal", "absolutely", "shocking"} <= set(d["terms"])
    # spans point at the real text (for a highlight surface)
    txt = "This is an outrageous scandal, absolutely shocking."
    for sp in d["spans"]:
        assert txt[sp["start"]:sp["end"]].lower() == sp["term"].lower()
    _assert_no_score_keys(d)


def test_clean_text_is_measured_zero_not_a_gap():
    # a supported language with no loaded terms is a REAL measurement (density 0.0),
    # DISTINCT from the unmeasured gap of an unsupported language.
    d = S.subjectivity("The committee met on Tuesday to review the annual budget.", "en")
    assert d["available"] is True and d["n_loaded"] == 0 and d["density"] == 0.0


def test_cyrillic_and_arabic_scripts_match():
    ru = S.subjectivity("Это возмутительный скандал и позор.", "ru")
    assert ru["available"] is True and ru["n_loaded"] >= 2
    assert "скандал" in ru["terms"]
    ar = S.subjectivity("هذه فضيحة و كارثة.", "ar")
    assert ar["available"] is True and ar["n_loaded"] >= 2
    assert "فضيحة" in ar["terms"]


def test_honest_gaps_never_a_fabricated_zero():
    no_lex = S.subjectivity("Ein Skandal und eine Katastrophe.", "de")
    assert no_lex["available"] is False and "lexicon" in no_lex["reason"]
    assert "n_loaded" not in no_lex  # a gap carries NO measurement, not a 0
    unknown = S.subjectivity("some text", None)
    assert unknown["available"] is False and unknown["reason"] == "language unknown"
    empty = S.subjectivity("   ", "en")
    assert empty["available"] is False and empty["reason"] == "empty"


def test_engine_does_not_import_or_reuse_vader():
    # VADER is VALENCE, not subjectivity — the investigation concluded not to force it.
    src = (S.__file__)
    text = open(src, encoding="utf-8").read()
    assert "import vader" not in text.lower() and "sentimentintensity" not in text.lower()


def test_script_mismatch_is_a_gap_not_a_fabricated_zero():
    # Russian text mislabelled 'en' (source-asserted language is unreliable) must NOT read as
    # a measured clean 0.0 — it is unmeasurable by the Latin lexicon -> an honest gap (#1/#3).
    d = S.subjectivity("Правительство объявило шокирующий скандал.", "en")
    assert d["available"] is False and "script" in d["reason"]
    assert "n_loaded" not in d  # a gap carries NO measurement, never a density 0.0
    # the SAME text under its true language IS measured
    ru = S.subjectivity("Правительство объявило шокирующий скандал.", "ru")
    assert ru["available"] is True and ru["n_loaded"] >= 1


def test_cjk_under_a_latin_lexicon_is_a_gap_not_zero():
    d = S.subjectivity("这是一个非常震撼的丑闻报道", "en")
    assert d["available"] is False and "n_loaded" not in d


def test_replaced_lexicon_is_picked_up_without_restart(tmp_path, monkeypatch):
    import os
    import time

    monkeypatch.setattr(S, "_BASE", tmp_path)
    S._CACHE.clear()
    (tmp_path / "xx.txt").write_text("scandal\noutrage\n", encoding="utf-8")
    assert S.load_lexicon("xx") == frozenset({"scandal", "outrage"})
    # overwrite + bump mtime -> the mtime-aware cache reloads (never serves the stale set)
    (tmp_path / "xx.txt").write_text("fury\n", encoding="utf-8")
    os.utime(tmp_path / "xx.txt", (time.time() + 5, time.time() + 5))
    assert S.load_lexicon("xx") == frozenset({"fury"})
    S._CACHE.clear()
