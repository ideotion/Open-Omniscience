"""Which content languages the keyword/analytics engine can MANAGE today.

A language is *managed* when keyword extraction is functional: a stoplist exists
AND its words can be tokenised. ``zh``/``ja``/``th`` have no word segmentation in the
core install, so their extraction is broken UNLESS the optional ``[segmentation]``
extra (jieba / janome / pythainlp — see src.analytics.segmentation) is installed, at
which point they carry a vendored stoplist and become functional. The *no_stoplist*
languages tokenise but leak function words — junk that pollutes analytics (false
keywords, skewed associations) AND inflates the corpus (every aggregation pays for it).

Maintainer ruling (2026-06-18): sources in UNMANAGED languages seed **disabled by
default** — kept, never deleted, re-enablable — so the app stops accumulating
un-analysable junk until a stoplist for that language lands. This module is the ONE
source of truth; both the engine report and the source gating read it.

The managed set mirrors the verified-present stoplists (self-test covers
en/de/fr/es/it/pt/nl/ru/ar/hu/id + el/bg; the evidence batch seeded
sv/da/nb/no/pl/sr/sl, and the 2026-06-18 keyword-log added Greek/Bulgarian grammar
stoplists). fi/tr/uk/hi/bn and the rest are deliberately NOT claimed: they tokenise
but leak (uk's sample even mixed ru-spelled tokens, so its language signal is not
yet trustworthy).

2026-07-01 (live 727k-keyword corpus): the languages above that were backed only
by PARTIAL hand-grown batches (de/es/it/pt/nl/ru/ar/el/bg/da/hr/hu/id/no/nb/pl/sl/
sv still leaked grammar — gestern, вчера, serían) now carry the FULL stopwords-iso
list vendored in configs/stopwords_iso/. Those lists are LANGUAGE-SCOPED (kept out
of global_stopwords()), so adding a complete Latin-script list is collision-free.
The managed SET is unchanged — only the stoplist QUALITY improved. sr/bs/az remain
managed via hand-grown batches (absent from stopwords-iso).
"""

from __future__ import annotations

MANAGED_LANGUAGES: frozenset[str] = frozenset(
    {
        "en", "fr", "de", "es", "it", "pt", "nl", "ru", "ar", "hu", "id",
        "sv", "da", "nb", "no", "pl", "sr", "sl",
        # 2026-06-18 keyword-log: hand-filtered grammar stoplists added (distinct
        # GREEK/CYRILLIC scripts, so no Latin-corpus collision). These were the
        # highest-volume no_stoplist languages (el 4992, bg 3090 keywords).
        "el", "bg",
        # 2026-06-22 field test: hi (Devanagari) + bn (Bengali) are UI languages that
        # were no_stoplist (leaking grammar into the index). Distinct scripts -> the
        # global stopword union is collision-free; pure-grammar stoplists added in
        # src/analytics/extract.py. (zh/ja stay UNSEGMENTED — a stoplist can't fix the
        # missing word segmentation.)
        "hi", "bn",
        # 2026-06-22 field test, remainder batch. All verified to tokenise WHOLE words
        # (the managed bar) on 2026-06-22 and given pure-grammar stoplists in
        # src/analytics/extract.py — so their sources stop seeding disabled:
        #   fa/ur  Arabic script (distinct -> collision-free stoplist; the tokenizer now
        #          keeps diacritized words whole via _ARABIC_MARKS).
        #   uk     Cyrillic (the gated 2026-06-18 set expanded to a full stoplist; the
        #          union filters it regardless of the ru-mislabel noise that gated it).
        #   ro/cs/sk/ca/sw/az/et  Latin; stoplists added with length>=4 / accented-only
        #          words so a content-word collision in es/it/pt/en/de/nl is impossible.
        #   tr/fi  agglutinative but space-segmented (whole words); their stoplists were
        #          already present from the 2026-06-12/17 evidence passes — promoted now.
        #   bs/hr  share the Serbian-Latin stoplist already in the union (sr is managed).
        # (vi stays unmanaged: it is SYLLABLE-segmented — "kinh tế" splits — so words
        # fragment; th is UNSEGMENTED below. Both verified 2026-06-22.)
        "fa", "ur", "uk", "ro", "cs", "sk", "ca", "sw", "az", "et",
        "tr", "fi", "bs", "hr",
        # 2026-07-10 segmenter wave: ko (Hangul) + mr (Marathi/Devanagari) are
        # SPACE-segmented (eojeol / word boundaries) and now carry the full vendored
        # stopwords-iso list — distinct scripts, so the global union stays collision-free.
        # (Korean particles stay glued to their noun, the same agglutination caveat as
        # tr/fi; a morphological analyser is future work.) zh/ja/th are handled below —
        # they only reach "functional" when the [segmentation] extra is present.
        "ko", "mr",
    }
)
# No word segmentation -> keyword extraction is broken regardless of a stoplist.
# th (Thai) added 2026-06-22: Thai has no inter-word spaces AND its vowel marks are
# Mn, so the tokenizer shatters a Thai run into mark-bounded fragments (verified) —
# a stoplist cannot fix missing segmentation, so it is honestly UNSEGMENTED, not
# no_stoplist. (vi is syllable-segmented, a milder case kept as no_stoplist.)
UNSEGMENTED: frozenset[str] = frozenset({"zh", "ja", "th"})


def normalize_lang(lang: str | None) -> str:
    """Bare ISO-639-1 code: lowercased, region/script stripped ('en-US' -> 'en')."""
    if not lang:
        return ""
    return lang.strip().lower().replace("_", "-").split("-")[0]


def is_managed(lang: str | None) -> bool:
    """True when the keyword engine can analyse this language today.

    An unknown/empty language is NOT 'managed' but is also not 'unmanaged' for the
    gating purpose — callers decide; the source gating leaves unknown-language
    sources enabled (we cannot justify disabling what we cannot classify)."""
    return language_status(lang) == "functional"


def language_status(lang: str | None) -> str:
    """'functional' | 'unsegmented' | 'no_stoplist' | 'unknown' for one language."""
    n = normalize_lang(lang)
    if not n:
        return "unknown"
    if n in UNSEGMENTED:
        # A word segmenter (the optional [segmentation] extra) turns a space-less
        # script into real words; with the vendored stoplist present zh/ja/th are then
        # functional. Absent the extra they stay honestly 'unsegmented' (a core install
        # is byte-unchanged). The import is local to avoid an import cycle.
        from src.analytics.segmentation import segmenter_available

        return "functional" if segmenter_available(n) else "unsegmented"
    if n in MANAGED_LANGUAGES:
        return "functional"
    return "no_stoplist"


def is_unmanaged(lang: str | None) -> bool:
    """True only for a KNOWN language the engine cannot analyse (no_stoplist or
    unsegmented). Unknown/empty returns False — never disable what we can't classify."""
    return language_status(lang) in ("no_stoplist", "unsegmented")
