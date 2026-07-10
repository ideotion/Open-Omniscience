"""Optional zh/ja/th word segmentation (the [segmentation] extra).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Two families of tests:
  * GRACEFUL-DEGRADE tests run everywhere (no segmenter needed) — they prove a core
    install is byte-unchanged and the kill switch works.
  * SEGMENTER-PRESENT tests skip when the extra is absent — they prove the real win
    (whole-sentence junk -> real repeating words) and correct offsets.
"""

from __future__ import annotations

import pytest

from src.analytics.extract import BaselineExtractor
from src.analytics.managed import language_status
from src.analytics.segmentation import SEGMENTED_LANGUAGES, segment, segmenter_available

# A whole Chinese sentence: without segmentation this is ONE junk "keyword".
_ZH = "中国政府今天宣布了新的经济政策"
_JA = "日本政府は新しい経済政策を発表した"
_TH = "รัฐบาลไทยประกาศนโยบายเศรษฐกิจใหม่"


# --------------------------------------------------------------------------- #
# Graceful degrade — no segmenter required                                     #
# --------------------------------------------------------------------------- #

def test_segment_returns_none_for_a_space_delimited_language():
    # English is never segmented here — the caller keeps its whitespace tokenizer.
    assert segment("the quick brown fox", "en") is None


def test_segment_returns_none_when_disabled(monkeypatch):
    monkeypatch.setenv("OO_SEGMENTATION", "0")
    assert segment(_ZH, "zh") is None
    assert segmenter_available("zh") is False


def test_disabled_falls_back_byte_identically(monkeypatch):
    """With the layer off, zh extraction is the (junky) whitespace behaviour — proving
    the fallback path is exactly the pre-segmenter code."""
    monkeypatch.setenv("OO_SEGMENTATION", "0")
    terms = {t.normalized for t in BaselineExtractor().extract(_ZH, language="zh")}
    # the whole sentence survives as one token (the documented pre-segmenter junk)
    assert _ZH in terms


def test_unknown_language_and_empty_text_are_none():
    assert segment("", "zh") is None
    assert segment(_ZH, "xx") is None


def test_segmented_language_set():
    assert SEGMENTED_LANGUAGES == frozenset({"zh", "ja", "th"})


# --------------------------------------------------------------------------- #
# Segmenter present — the real win                                             #
# --------------------------------------------------------------------------- #

zh_only = pytest.mark.skipif(not segmenter_available("zh"), reason="jieba ([segmentation] extra) not installed")
ja_only = pytest.mark.skipif(not segmenter_available("ja"), reason="janome ([segmentation] extra) not installed")
th_only = pytest.mark.skipif(not segmenter_available("th"), reason="pythainlp ([segmentation] extra) not installed")


@zh_only
def test_zh_segments_into_real_words_with_valid_offsets():
    toks = segment(_ZH, "zh")
    assert toks is not None
    words = [w for w, _ in toks]
    # real words, not the whole sentence
    assert "经济" in words and "政策" in words
    assert _ZH not in words
    # every offset points at its word inside the source text
    for w, off in toks:
        assert _ZH[off : off + len(w)] == w


@zh_only
def test_zh_extraction_yields_real_terms_not_a_sentence_token():
    terms = {t.normalized for t in BaselineExtractor().extract(_ZH, language="zh") if t.kind == "term"}
    assert "经济" in terms  # a real 2-char word survives the min-length floor
    assert _ZH not in terms  # the whole-sentence junk token is gone


@ja_only
def test_ja_reconstructed_offsets_are_exact():
    toks = segment(_JA, "ja")
    assert toks is not None
    for w, off in toks:
        assert _JA[off : off + len(w)] == w
    words = [w for w, _ in toks]
    assert "経済" in words and "政策" in words


@th_only
def test_th_segments_marks_into_words_not_fragments():
    toks = segment(_TH, "th")
    assert toks is not None
    words = [w for w, _ in toks]
    # real words, not the mark-shattered fragments the whitespace tokenizer produced
    assert "เศรษฐกิจ" in words  # "economy"
    assert "รัฐบาล" in words  # "government"
    for w, off in toks:
        assert _TH[off : off + len(w)] == w


@pytest.mark.parametrize("lang", ["zh", "ja", "th"])
def test_adversarial_input_never_crashes_and_offsets_stay_valid(lang):
    """Empty / whitespace / emoji / mixed-script / very-long input must degrade to a
    valid token list or None — never raise (any error falls back to the default path)."""
    if not segmenter_available(lang):
        pytest.skip("segmenter not installed")
    for t in ["", "   ", "\n\t", "😀🎉", "COVID中国2024年", "。。。、、", "x" * 4000 + "经济"]:
        toks = segment(t, lang)
        if toks:
            for w, off in toks:
                assert t[off : off + len(w)] == w


@zh_only
def test_zh_mixed_script_keeps_latin_and_drops_digits():
    words = [w for w, _ in (segment("COVID中国2024年", "zh") or [])]
    assert "COVID" in words and "中国" in words
    assert "2024" not in words  # a pure-number token is not word-ish


@zh_only
def test_region_tagged_code_normalizes_to_the_segmenter():
    # Finding #1 (skeptic): a region/script subtag must reach the SAME segmenter as its
    # base, and its status must agree — else zh-CN reports 'functional' while extraction
    # silently skips segmentation.
    assert segmenter_available("zh-CN") and segmenter_available("ZH") and segmenter_available("zh_Hans")
    toks = segment("中国政府今天宣布了新的经济政策", "zh-CN")
    assert toks and "经济" in [w for w, _ in toks]
    assert language_status("zh-CN") == language_status("zh") == "functional"
    terms = {t.normalized for t in BaselineExtractor().extract("中国政府今天宣布了新的经济政策", language="zh-CN") if t.kind == "term"}
    assert "经济" in terms and "中国政府今天宣布了新的经济政策" not in terms


@zh_only
def test_latin_two_letter_tokens_do_not_leak_in_a_cjk_doc():
    # Finding #2 (skeptic): the 2-char floor is per-TOKEN — a stray Latin token (vs/ai/eu)
    # inside a segmented CJK doc still gets the 3-char Latin floor, so it never leaks.
    terms = {t.normalized for t in BaselineExtractor().extract("中国 vs 美国 ai 政策 eu 经济", language="zh") if t.kind == "term"}
    assert "政策" in terms and "中国" in terms  # real CJK words survive at floor 2
    assert not ({"vs", "ai", "eu"} & terms)  # 2-letter Latin dropped at floor 3


@zh_only
def test_language_status_flips_functional_when_segmenter_present():
    assert language_status("zh") == "functional"


def test_language_status_unsegmented_when_disabled(monkeypatch):
    monkeypatch.setenv("OO_SEGMENTATION", "0")
    for lang in ("zh", "ja", "th"):
        assert language_status(lang) == "unsegmented"
