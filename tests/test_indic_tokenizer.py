"""Devanagari/Bengali words must tokenize WHOLE, and hi/bn are now managed (P1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field test 2026-06-22 (engine report): hi + bn were no_stoplist UI languages. The
real defect was deeper than a missing stoplist — the word tokenizer (`_WORD_RE`)
excluded Indic combining marks (matras/viramas are Unicode Mn, not `\\w`), so
"सरकार" split at the ा matra into "सरक"+"र". This pins the fix (whole-word
tokenization) + the stoplist + the managed-language promotion.
"""

from __future__ import annotations

from src.analytics.extract import BaselineExtractor, _WORD_RE
from src.analytics.managed import is_managed, language_status


def test_devanagari_word_is_not_split_at_a_matra():
    # "सरकार" = स र क ा र : the ा (U+093E) matra must stay attached, not end the word.
    assert _WORD_RE.findall("सरकार") == ["सरकार"], "Devanagari word split at a combining mark"


def test_bengali_word_with_virama_stays_whole():
    # "জন্য" carries the virama ্ (U+09CD); it must not break the token.
    assert _WORD_RE.findall("জন্য") == ["জন্য"]


def test_latin_tokenization_is_unchanged_by_the_indic_fix():
    # The change only WIDENS word continuations with Indic marks; Latin is byte-identical.
    assert _WORD_RE.findall("The G7 met in São-Paulo's hall") == [
        "The", "G7", "met", "in", "São-Paulo's", "hall"
    ]


def test_hindi_content_survives_grammar_is_filtered():
    terms = {t.normalized for t in BaselineExtractor().extract(
        "सरकार ने जनता के लिए यह फैसला नहीं बदला।", title="", language="hi"
    )}
    assert "सरकार" in terms and "जनता" in terms  # content nouns extracted whole
    assert "लिए" not in terms and "नहीं" not in terms  # >=3-char grammar filtered by the stoplist


def test_bengali_content_survives_grammar_is_filtered():
    terms = {t.normalized for t in BaselineExtractor().extract(
        "সরকার নতুন নীতি ঘোষণা করেছে এবং জনগণের জন্য নয়।", title="", language="bn"
    )}
    assert "সরকার" in terms and "নীতি" in terms
    assert "করেছে" not in terms and "জন্য" not in terms


def test_hi_bn_are_now_managed():
    assert is_managed("hi") and is_managed("bn")
    assert language_status("hi") == "functional" and language_status("bn") == "functional"
    # zh/ja stay unsegmented — a stoplist can't fix missing segmentation.
    assert language_status("zh") == "unsegmented"
