"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com
"""

"""
Stopwords Management for Open Omniscience

This module provides comprehensive stopwords management for multiple languages,
used in keyword extraction and text processing.

Author: Open Omniscience Team
"""

import logging

# Configure logging
logger = logging.getLogger(__name__)


class StopwordsManager:
    """
    Manages stopwords for multiple languages.

    Stopwords are common words that are typically filtered out during
    text processing (e.g., "the", "and", "a", "an", "in", etc.).

    Attributes:
        default_stopwords: Default English stopwords
        language_stopwords: Dictionary mapping language codes to stopword sets
        custom_stopwords: Custom stopwords added by users
    """

    # Default English stopwords
    DEFAULT_ENGLISH_STOPWORDS = {
        "a",
        "an",
        "the",
        "i",
        "you",
        "he",
        "she",
        "it",
        "we",
        "they",
        "me",
        "him",
        "her",
        "us",
        "them",
        "my",
        "your",
        "his",
        "its",
        "our",
        "their",
        "mine",
        "yours",
        "hers",
        "ours",
        "theirs",
        "am",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "shall",
        "should",
        "can",
        "could",
        "may",
        "might",
        "must",
        "very",
        "too",
        "so",
        "just",
        "only",
        "also",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "all",
        "any",
        "both",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "about",
        "above",
        "after",
        "again",
        "against",
        "and",
        "as",
        "at",
        "because",
        "before",
        "below",
        "between",
        "but",
        "by",
        "during",
        "for",
        "from",
        "if",
        "in",
        "into",
        "of",
        "off",
        "on",
        "once",
        "or",
        "ought",
        "out",
        "over",
        "own",
        "same",
        "than",
        "that",
        "then",
        "these",
        "this",
        "those",
        "through",
        "to",
        "under",
        "until",
        "up",
        "what",
        "which",
        "while",
        "who",
        "whom",
        "with",
        "s",
        "t",
        "d",
        "ll",
        "re",
        "ve",
        "m",
        "ma",
    }

    NEWS_STOPWORDS = {
        "said",
        "say",
        "says",
        "saying",
        "told",
        "tell",
        "tells",
        "according",
        "report",
        "reports",
        "reported",
        "reporting",
        "source",
        "sources",
        "official",
        "officials",
        "announced",
        "announcement",
        "announces",
        "released",
        "release",
        "releases",
        "published",
        "publish",
        "publishes",
        "wrote",
        "write",
        "writes",
        "writing",
        "written",
        "photo",
        "photos",
        "image",
        "images",
        "video",
        "videos",
        "footage",
        "story",
        "stories",
        "article",
        "articles",
        "news",
        "breaking",
        "live",
        "exclusive",
        "first",
        "latest",
        "year",
        "years",
        "month",
        "months",
        "week",
        "weeks",
        "day",
        "days",
        "today",
        "yesterday",
        "tomorrow",
        "now",
        "then",
        "soon",
        "later",
        "early",
        "late",
    }

    # Indefinite / quantifier pronouns + pro-adverbs — CLOSED-CLASS function words the
    # base English list missed, surfaced by the open-class detector
    # (analyze_keyword_log.py --generic-terms) as high-df non-topics on the 2026-07-01
    # corpus (something df=413, everyone/nothing/…). Safe to add: none is a content word
    # in another language.
    INDEFINITE_STOPWORDS = {
        "something", "anything", "everything", "nothing",
        "someone", "somebody", "everyone", "everybody",
        "anyone", "anybody", "nobody", "none",
        "whatever", "whoever", "somewhere", "anywhere", "everywhere",
    }

    # Platform / publishing FURNITURE — the same low-dual-use class English already
    # stoplists in NEWS_STOPWORDS (photo/video/story/article/news). Verified high-df in
    # the 2026-07-01 corpus (podcast 761, newsletter 529, cookies 412, gallery 206). The
    # collision-risky "content" (fr = "happy") is DELIBERATELY excluded from this global
    # English set — it rides the language-scoped channel instead; "comments" (plural, not
    # fr "comment" = how) is used.
    PLATFORM_STOPWORDS = {
        "podcast", "newsletter", "gallery", "cookies", "comments", "advertisement",
    }

    LANGUAGE_STOPWORDS = {
        "en": DEFAULT_ENGLISH_STOPWORDS | NEWS_STOPWORDS | INDEFINITE_STOPWORDS | PLATFORM_STOPWORDS,
        "fr": {
            "le",
            "la",
            "les",
            "un",
            "une",
            "des",
            "du",
            "de",
            "l",
            "ce",
            "cet",
            "cette",
            "ces",
            "mon",
            "ton",
            "son",
            "je",
            "tu",
            "il",
            "elle",
            "nous",
            "vous",
            "ils",
            "elles",
            "suis",
            "es",
            "est",
            "sommes",
            "etes",
            "sont",
            "que",
            "qui",
            "quoi",
            "dont",
            "ou",
            "et",
            "mais",
            "avec",
            "sans",
            "sous",
            "sur",
            "par",
            "pour",
        },
    }

    def __init__(self, custom_stopwords=None):
        self.default_stopwords = self.DEFAULT_ENGLISH_STOPWORDS.copy()
        self.language_stopwords = {}
        self.custom_stopwords = set(custom_stopwords or [])

        for lang, words in self.LANGUAGE_STOPWORDS.items():
            self.language_stopwords[lang] = words.copy()

        # LANGUAGE-SCOPED stoplists vendored from stopwords-iso (MIT) for languages
        # the engine could tokenise but had no stoplist for (their function words
        # leaked as keywords). Kept SEPARATE from ``language_stopwords`` on purpose:
        # ``global_stopwords()`` unions ``language_stopwords`` language-agnostically,
        # so folding these in would let a word grammatical in one language (vi "nam")
        # hide a content word ("Nam") in another. ``get_stopwords(lang)`` returns them
        # only for THAT language (extraction is language-scoped), so the collision
        # cannot happen. (2026-06-23 keyword-engine report; STOPWORDS_ISO_AS_OF.)
        self.scoped_stopwords: dict[str, set[str]] = _load_scoped_stopwords()
        # RAW vendored-only snapshot, captured BEFORE the curated supplements below are merged
        # in -- the pure stopwords-iso grammar lists, with none of the hand-curated NEWS/PLATFORM/
        # publishing-boilerplate domain additions. Used by get_grammar_stopwords() (the NAV-SOUP
        # prose-density signal, src.services.prose_gate): those curated additions are CONTENT/
        # topical-noise words (e.g. "newsletter", "podcast"), not grammatical function words, and
        # a nav-soup page is often SATURATED with exactly them -- folding them into the
        # function-word count would blur the very distinction the prose gate measures.
        self._raw_scoped_stopwords: dict[str, set[str]] = {
            lang: set(words) for lang, words in self.scoped_stopwords.items()
        }
        # Merge the hand-curated supplements (temporal-deictic adverbs + publishing
        # boilerplate) into the SAME language-scoped channel (not the global union). A
        # curated language without a vendored file still gets its own scoped set here.
        for src in (CURATED_SCOPED_STOPWORDS, PUBLISHING_BOILERPLATE_SCOPED):
            for lang, curated in src.items():
                self.scoped_stopwords.setdefault(lang, set()).update(curated)

    def get_stopwords(self, language="en"):
        lang = language.lower()
        if lang in self.language_stopwords:
            stopwords = self.language_stopwords[lang].copy()
        elif lang in self.scoped_stopwords:
            stopwords = self.scoped_stopwords[lang].copy()  # its OWN list, not English
        else:
            stopwords = self.default_stopwords.copy()
        stopwords.update(self.custom_stopwords)
        return stopwords

    def filter_stopwords(self, words, language="en"):
        stopwords = self.get_stopwords(language)
        return [word for word in words if word.lower() not in stopwords]

    def get_grammar_stopwords(self, language="en"):
        """PURE closed-class grammar words only (articles, pronouns, prepositions,
        conjunctions, auxiliaries, indefinites) -- deliberately EXCLUDING the hand-curated
        NEWS_STOPWORDS/PLATFORM_STOPWORDS/publishing-boilerplate domain additions that
        ``get_stopwords()`` folds in for keyword-extraction dedup. Those additions are
        topical non-content words (e.g. "newsletter", "podcast", "cookies"), not
        grammatical function words -- a nav/listing page is often saturated with exactly
        them, so counting them as "function words" would blur the prose/non-prose
        distinction this method exists for (src.services.prose_gate, the NAV-SOUP
        specimen ruling 2026-07-20). English: the base pronoun/determiner/auxiliary set
        plus the closed-class indefinite pronouns, no NEWS/PLATFORM words. Any other
        language: its vendored stopwords-iso list as-is (already pure grammar) if
        present, else the small hardcoded LANGUAGE_STOPWORDS grammar set (e.g. fr), else
        empty (honestly no signal rather than a wrong one)."""
        lang = language.lower()
        if lang == "en":
            return (self.DEFAULT_ENGLISH_STOPWORDS | self.INDEFINITE_STOPWORDS).copy()
        if lang in self._raw_scoped_stopwords:
            return self._raw_scoped_stopwords[lang].copy()
        if lang in self.language_stopwords:
            return self.language_stopwords[lang].copy()
        return set()


# Dated provenance for the vendored stopwords-iso snapshot (registered in
# configs/external_artifacts.yml; the freshness/protocol guard enforces it).
STOPWORDS_ISO_AS_OF = "2026-07"


# Curated temporal-deictic adverbs (yesterday/today/tomorrow + now/recently/currently
# and their extended forms) — the news-noise category English already stoplists in
# NEWS_STOPWORDS (today/yesterday/tomorrow/now/soon/later). They leaked as top keywords
# in every space-segmented managed language even after the full stopwords-iso lists
# landed (2026-07-01 corpus: gestern, вчера, mañana, domani, amanhã, gisteren — the iso
# lists carried "today" but not "yesterday"/"tomorrow"). These are hand-curated (NOT in
# stopwords-iso, so kept out of the auto-generated *.txt that build_stopwords.py
# overwrites) and merged into the LANGUAGE-SCOPED channel — never the language-agnostic
# global union — so, like the vendored lists, a word deictic in one language can never
# hide a same-spelled content word in another. Deliberately CONSERVATIVE: only closed
# deictic time adverbs. A dual-use word that also names a common noun is included ONLY
# where the deictic sense dominates a news corpus and the noun sense is negligible:
# de/nl "morgen" & es "mañana" (= tomorrow / morning). Truly ambiguous ones are OMITTED
# (it "ora" = now/hour, pt "logo" = soon/logo). en/fr already cover this class
# (NEWS_STOPWORDS / the French evidence batch), so they are not repeated here.
CURATED_SCOPED_STOPWORDS: dict[str, frozenset[str]] = {
    "de": frozenset(
        "gestern heute morgen vorgestern übermorgen damals derzeit momentan "
        "demnächst kürzlich neulich".split()
    ),
    "nl": frozenset(
        "gisteren vandaag morgen eergisteren overmorgen straks onlangs "
        "tegenwoordig zojuist".split()
    ),
    "ru": frozenset(
        "вчера сегодня завтра позавчера послезавтра сейчас теперь недавно "
        "нынче ныне скоро".split()
    ),
    "es": frozenset(
        "ayer hoy mañana anteayer anoche ahora actualmente recientemente pronto".split()
    ),
    "it": frozenset(
        "ieri oggi domani dopodomani stamattina adesso attualmente "
        "recentemente presto".split()
    ),
    "pt": frozenset(
        "ontem hoje amanhã anteontem agora atualmente recentemente cedo".split()
    ),
    # Croatian / Bosnian (BCS Latin, mutually intelligible; bs is aliased to the hr list).
    "hr": frozenset("jučer danas sutra prekjučer prekosutra sada nedavno uskoro".split()),
    "bs": frozenset("juče danas sutra prekjuče prekosutra sada nedavno uskoro".split()),
}


# Platform / publishing FURNITURE per language (advertising · content · comment-widget),
# the same low-dual-use class the English PLATFORM_STOPWORDS covers. Verified high-df in
# the 2026-07-01 corpus (de inhalte 159 · es publicidad 151 · nl column 154 · pt conteúdo
# 63). LANGUAGE-SCOPED like the temporal set — never the global union, so fr "content"
# (= happy) can never be hidden by de/es "contenido"/"inhalte". Applied only to languages
# that use the scoped channel (not en/fr, which take the language_stopwords branch — the
# English furniture lives in PLATFORM_STOPWORDS above).
PUBLISHING_BOILERPLATE_SCOPED: dict[str, frozenset[str]] = {
    "de": frozenset("inhalte werbung anzeige newsletter kommentare".split()),
    "es": frozenset("publicidad contenido boletín comentarios".split()),
    "it": frozenset("pubblicità contenuti newsletter commenti".split()),
    "pt": frozenset("publicidade conteúdo boletim comentários".split()),
    "nl": frozenset("column nieuwsbrief reclame inhoud reacties".split()),
    "ru": frozenset("реклама рассылка комментарии".split()),
}


def _load_scoped_stopwords() -> dict[str, set[str]]:
    """Load the vendored per-language stopword lists (configs/stopwords_iso/*.txt).

    Network-free; missing dir = no-op (the engine simply keeps those languages
    no_stoplist). One file per ISO-639-1 code, one lowercased word per line."""
    import pathlib

    base = pathlib.Path(__file__).resolve().parents[2] / "configs" / "stopwords_iso"
    out: dict[str, set[str]] = {}
    if not base.is_dir():
        return out
    for f in base.glob("*.txt"):
        words = {
            w.strip().lower()
            for w in f.read_text(encoding="utf-8").splitlines()
            if w.strip()
        }
        if words:
            out[f.stem.lower()] = words
    return out


stopwords_manager = StopwordsManager()
