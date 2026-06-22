"""The Arabic-script tokenizer fix is ADDITIVE (field test 2026-06-22).

Arabic combining marks (harakat/tashkeel, superscript alef) are category Mn, so a
*diacritized* Persian/Urdu/Arabic word used to split at each mark exactly like the
Devanagari matra bug. ``_ARABIC_MARKS`` allows them ONLY as word continuations, which
must be additive: undiacritized text (the common news case) stays byte-identical, and
no Latin/Cyrillic/Greek token is affected — this proves both.
"""

from __future__ import annotations

from src.analytics.extract import _WORD_RE


def _toks(text: str) -> list[str]:
    return [m.group(0) for m in _WORD_RE.finditer(text)]


def test_undiacritized_arabic_script_is_unchanged():
    # Common news text (no harakat): whole words, exactly as before the fix.
    assert _toks("دولت برای مردم سیاست را تغییر داد") == [
        "دولت", "برای", "مردم", "سیاست", "را", "تغییر", "داد",
    ]
    assert _toks("حکومت نے عوام کے لیے فیصلہ کیا") == [
        "حکومت", "نے", "عوام", "کے", "لیے", "فیصلہ", "کیا",
    ]
    assert _toks("الحكومة قالت إنها ستغير السياسة") == [
        "الحكومة", "قالت", "إنها", "ستغير", "السياسة",
    ]


def test_diacritized_word_now_stays_whole():
    # With tashkeel the word used to shatter at every mark; now it is ONE token.
    diac = "الْحُكُومَة قَالَت"
    toks = _toks(diac)
    assert len(toks) == 2, toks  # two whole words, not a pile of mark-bounded fragments
    # The marks are kept inside the token (continuation), never a leading mark.
    assert all(not _WORD_RE.match(t[0]) is None for t in toks)


def test_latin_cyrillic_greek_are_byte_unchanged():
    # The fix only adds Arabic-block marks to the continuation class, so other scripts
    # tokenise exactly as before.
    assert _toks("The government said it would act") == [
        "The", "government", "said", "it", "would", "act",
    ]
    assert _toks("Уряд змінить політику країни") == ["Уряд", "змінить", "політику", "країни"]
    assert _toks("Η κυβέρνηση άλλαξε πολιτική") == ["Η", "κυβέρνηση", "άλλαξε", "πολιτική"]
