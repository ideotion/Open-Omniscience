"""Does an article's own text refute the language its feed or page asserted? (R699, cause 1)

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. The 2026-10-06 keyword triage found Cyrillic news text tagged ``en``:
новости in 2,094 articles, 2,087 of them tagged English, and 50 of the 54 foreign words
read in the English shard were Cyrillic (``docs/ledger/OPEN_QUEUE.md``, "WHAT THE KEYWORD
TRIAGE RUN EXPOSED", cause 1). The asserted ``Article.language`` drives extraction, so a
Russian article tagged English was cut under the English stoplist and every Russian
function word became an "English keyword". A stoplist can only hide that; the fix is to
stop believing a tag the text itself contradicts.

WHAT COUNTS AS A CONTRADICTION. Only the WRITING SYSTEM, never vocabulary: a language
whose script is not in doubt (English is written in Latin letters, Russian in Cyrillic,
Greek in Greek) is refuted when fewer than :data:`OWN_SCRIPT_MIN_SHARE` of the text's
letters are in that script. Script is a fact you can count, not a model's guess, so this
can overrule an assertion where the statistical detector (``langdetect.py``) is only ever
allowed to fill an absent one. It then hands the article to that detector, which names
the language or leaves it honestly unknown -- this module never names one itself.

WHAT IT REFUSES TO JUDGE. A language written in more than one script (Serbian, Bosnian,
Azerbaijani, Kazakh, Uzbek, Mongolian, Punjabi ...) and a code it does not know: no
contradiction can be shown, so none is claimed. A text with fewer than
:data:`MIN_LETTERS` letters: too little to count. Japanese and Korean list Han among
their own scripts, so a Chinese text tagged ``ja`` is NOT refuted (the scripts overlap and
a count cannot separate them); a ``zh`` tag on a text with no Han at all is.
"""

from __future__ import annotations

import unicodedata

#: The share of a text's letters that must be in the asserted language's own script. Below
#: it the tag is refuted. Low on purpose: an English article quoting a Russian statement at
#: length is still mostly Latin, and a page that is three quarters Cyrillic is not English.
OWN_SCRIPT_MIN_SHARE = 0.25

#: Fewer letters than this and no judgement is made (a headline-only body proves nothing).
MIN_LETTERS = 100

#: How much text is read. An article does not change script halfway through, and the
#: check runs on every indexed article, so a bounded prefix is enough.
SAMPLE_CHARS = 5000

_LATIN = ("LATIN",)
_CYRILLIC = ("CYRILLIC",)
_ARABIC = ("ARABIC",)
_DEVANAGARI = ("DEVANAGARI",)
_HAN = ("CJK",)

#: Languages written in ONE script (or a fixed set that always occurs together), keyed by
#: the primary subtag. The script names are the first word of ``unicodedata.name``.
_OWN_SCRIPTS: dict[str, tuple[str, ...]] = {
    **dict.fromkeys(
        (
            "en", "fr", "de", "es", "it", "pt", "nl", "hu", "id", "ms", "sv", "da", "nb",
            "nn", "no", "pl", "sl", "hr", "ro", "cs", "sk", "ca", "sw", "et", "lv", "lt",
            "tr", "fi", "is", "ga", "cy", "eu", "gl", "mt", "sq", "tl", "fil", "af", "vi",
            "lb", "fo", "br", "oc", "eo", "la", "so", "ha", "yo", "ig", "zu", "xh",
        ),
        _LATIN,
    ),
    **dict.fromkeys(("ru", "uk", "bg", "be", "mk"), _CYRILLIC),
    **dict.fromkeys(("ar", "fa", "ur", "ps", "ckb", "sd"), _ARABIC),
    **dict.fromkeys(("hi", "mr", "ne"), _DEVANAGARI),
    "el": ("GREEK",),
    "he": ("HEBREW",),
    "yi": ("HEBREW",),
    "bn": ("BENGALI",),
    "ta": ("TAMIL",),
    "te": ("TELUGU",),
    "kn": ("KANNADA",),
    "ml": ("MALAYALAM",),
    "gu": ("GUJARATI",),
    "th": ("THAI",),
    "lo": ("LAO",),
    "km": ("KHMER",),
    "my": ("MYANMAR",),
    "ka": ("GEORGIAN",),
    "hy": ("ARMENIAN",),
    "am": ("ETHIOPIC",),
    "si": ("SINHALA",),
    "zh": _HAN,
    "ja": ("CJK", "HIRAGANA", "KATAKANA", "KATAKANA-HIRAGANA"),
    "ko": ("HANGUL", "CJK"),
}


def primary_subtag(language: str | None) -> str:
    """``"en-US"`` / ``"EN_gb"`` / ``" en "`` -> ``"en"``; empty for no language."""
    raw = (language or "").strip().lower().replace("_", "-")
    return raw.split("-", 1)[0]


def own_scripts(language: str | None) -> tuple[str, ...] | None:
    """The script(s) ``language`` is written in, or ``None`` when that is not one fixed answer."""
    return _OWN_SCRIPTS.get(primary_subtag(language))


def _script_of(ch: str) -> str:
    name = unicodedata.name(ch, "")
    return name.split(" ", 1)[0] if name else ""


def own_script_share(language: str | None, text: str | None) -> tuple[float, int] | None:
    """``(share of letters in the language's own script, letters counted)``, or ``None``
    when the language has no fixed script. Only the first :data:`SAMPLE_CHARS` are read."""
    allowed = own_scripts(language)
    if allowed is None:
        return None
    letters = own = 0
    for ch in (text or "")[:SAMPLE_CHARS]:
        if not ch.isalpha():
            continue
        letters += 1
        if _script_of(ch) in allowed:
            own += 1
    return (own / letters if letters else 0.0), letters


def script_refutes(language: str | None, text: str | None) -> bool:
    """True when ``text`` is demonstrably NOT written in ``language``'s script.

    False whenever no judgement can be made (no language, a multi-script or unknown
    language, too few letters) -- an absent proof is never a refutation.
    """
    measured = own_script_share(language, text)
    if measured is None:
        return False
    share, letters = measured
    return letters >= MIN_LETTERS and share < OWN_SCRIPT_MIN_SHARE
