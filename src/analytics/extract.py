"""
Pluggable keyword & entity extraction (offset-aware).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Turns an article body into ``ExtractedTerm``s carrying their occurrence count and
the char offset of their first occurrence (so the surrounding sentence can be
shown later, sliced from the stored article text). Two honest backends:

  * **BaselineExtractor** (core, no deps): topical n-gram *terms* (stopword-filtered,
    lowercased) PLUS *entities* detected as stand-alone ALL-CAPS **acronyms** only
    (WHO, NATO, USA). Title-Case was dropped as an entity signal — it is anglocentric
    and wrong for a multilingual corpus (German capitalises every noun; Romance
    languages capitalise sentence starts; Arabic/CJK have no case). A person/org/
    location ``kind`` comes only from a supplied gazetteer / spaCy; an unvouched
    acronym gets the honest generic kind ``entity``. Best for space-delimited scripts;
    it does not pretend to segment CJK/Arabic.
  * **SpacyExtractor** (opt-in ``[nlp]`` extra): real PERSON/ORG/GPE/LOC entities
    from a local spaCy model, reusing the baseline for topical terms. Constructed
    only if spaCy + a model are installed; callers fall back to baseline otherwise.

Every term records which extractor produced it; an entity ``kind`` is a
"labelled-by-X" assertion, never asserted as ground truth.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from html import unescape
from pathlib import Path

import yaml

from src.analytics.managed import normalize_lang
from src.analytics.segmentation import segment
from src.services.stopwords import stopwords_manager

# A word token: starts with a (unicode) letter, may contain letters, marks,
# apostrophes and hyphens. Digits-only / punctuation tokens are ignored.
# Indic combining marks (Unicode category Mn/Mc): dependent vowel signs (matras),
# the virama, anusvara/visarga/candrabindu, nukta. Python's stdlib `\w` does NOT
# match these (they're Marks, not alphanumerics), so "सरकार" used to split at the ा
# matra into "सरक"+"र" — Hindi/Bengali keywords were mangled, not merely unstoplisted
# (field test 2026-06-22). Allowing them ONLY as word CONTINUATIONS is additive: no
# Latin/Cyrillic/Greek/Arabic token uses these codepoints, so those scripts are
# byte-unchanged. (Other Indic/Thai scripts have the same need but are out of scope —
# zh/ja stay unsegmented regardless.)
_DEVANAGARI_MARKS = "ऀ-ःऺ-ॏ॑-ॗॢॣ"
_BENGALI_MARKS = "ঁ-ঃ়া-্ৗৢৣ"
# Arabic-script combining marks (harakat/tashkeel, superscript alef, Quranic signs):
# category Mn — NOT matched by \w, so a *diacritized* Persian/Urdu/Arabic word would
# split at a mark exactly like the Devanagari matra bug. Allowed ONLY as word
# CONTINUATIONS, which is additive: undiacritized text (the common news case — the
# fa/ur samples tokenise whole with or without this) is byte-unchanged; this only
# JOINS a token a mark would otherwise split, never splits one. Defined with \u
# escapes in a NORMAL string (the literal mark glyphs are hard to embed) then
# interpolated into the raw char class, mirroring the Devanagari/Bengali ranges.
_ARABIC_MARKS = "ؐ-ًؚ-ٰٟۖ-ۜ۟-۪ۤۧۨ-ۭ"
_WORD_RE = re.compile(
    rf"[^\W\d_][\w'’\-{_DEVANAGARI_MARKS}{_BENGALI_MARKS}{_ARABIC_MARKS}]*", re.UNICODE
)

_DEFAULT_MAX_TERMS = 80
_DEFAULT_MAX_ENTITIES = 80
_MIN_TERM_LEN = 3
# A word segmenter (zh/ja/th) yields SHORT real words — 中国 (China), 政策 (policy),
# 日本 (Japan) are 2 characters — so the Latin 3-char minimum would drop most of them.
# A space-less script has no 1-char function words to protect against (the stoplist +
# per-language filtering handle 了/的/は/を), so 2 is the honest floor there.
_MIN_SEG_TERM_LEN = 2
# CJK ideographs + kana + Hangul syllables + Thai — the scripts the 2-char floor is for.
# A LATIN token in a segmented doc (a stray "vs"/"ai"/"eu") keeps the 3-char floor, so
# lowering the floor for real CJK/Thai words never leaks 2-letter Latin junk.
_CJK_THAI_RE = re.compile(r"[぀-ヿ㐀-鿿가-힣฀-๿豈-﫿]")


def _term_floor(word: str, segmented: bool) -> int:
    """Minimum length for a candidate term: 2 for a CJK/Thai word in a segmented doc,
    3 otherwise (the Latin floor). Per-TOKEN, not per-document, so a Latin token inside
    a CJK article is still held to 3."""
    return _MIN_SEG_TERM_LEN if (segmented and _CJK_THAI_RE.search(word)) else _MIN_TERM_LEN

# --------------------------------------------------------------------------- #
# Markup strip at the extraction chokepoint (field diagnostics 2026-06-21)
# --------------------------------------------------------------------------- #
# When a stored article body still carries raw HTML/CSS — a pre-2026-06-20 .eml
# import, or any fetch path that kept markup — the word tokenizer mints `div`,
# `span`, `max-width`, `font-size` … as "keywords" (the live log showed a 36.5k
# unknown-language junk bucket dominated by exactly these). The web scrape path
# is clean (trafilatura), but we defend at the ONE place every path passes
# through — keyword extraction — so a re-index cleans existing rows regardless of
# which path stored the markup, and any future leak is caught by construction.
#
# A real tag is `<`/`</` immediately followed by a tag-name letter, ending in a
# whitespace/`/`/`>`-bounded close: this matches `<div>`, `<div class="x">`,
# `<br/>`, `</p>` but NOT an angle-bracketed URL `<https://x>` or prose like
# "x < y > z", so clean text is left byte-for-byte identical (keyword offsets
# into the stored body stay exact).
_MARKUP_STYLE_SCRIPT_RE = re.compile(
    r"<(style|script)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL
)
_MARKUP_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_MARKUP_TAG_RE = re.compile(r"</?[a-zA-Z][\w-]*(\s[^<>]*?)?/?>", re.DOTALL)
_MARKUP_ENTITY_RE = re.compile(r"&[#a-zA-Z][#a-zA-Z0-9]*;")


def _has_markup(text: str) -> bool:
    """Cheap, precise gate: True only when an actual strip would change ``text``."""
    return bool(
        _MARKUP_TAG_RE.search(text)
        or _MARKUP_STYLE_SCRIPT_RE.search(text)
        or _MARKUP_COMMENT_RE.search(text)
        or _MARKUP_ENTITY_RE.search(text)
    )


def strip_markup(text: str) -> str:
    """Drop HTML/CSS markup from ``text``; return it unchanged when there is none.

    Order matters (the email ``_strip_html`` lesson): <style>/<script> BLOCKS go
    first (their CSS/JS must never survive as body text), then HTML comments
    (incl. MSO conditional comments containing '>'), then every remaining tag,
    then HTML entities are decoded (so `&nbsp;`/`&copy;` don't become `nbsp`/
    `copy` keywords). Clean text is returned byte-identical so a term's recorded
    first-offset still points at the right place in the stored article body.
    """
    if not _has_markup(text):
        return text
    out = _MARKUP_STYLE_SCRIPT_RE.sub(" ", text)
    out = _MARKUP_COMMENT_RE.sub(" ", out)
    out = _MARKUP_TAG_RE.sub(" ", out)
    return unescape(out)

# All-caps tokens that are NOT entities (emphasis / chrome / titles), so the
# acronym detector doesn't mistake them for organisations. Kept deliberately small
# and evidence-driven — the keyword-diagnostics logs surface new ones to add.
_ACRONYM_STOP: frozenset[str] = frozenset(
    {
        "ok", "vs", "am", "pm", "aka", "faq", "ceo", "cfo", "cto", "vip", "rip",
        "diy", "asap", "fyi", "no", "so", "yes", "etc", "via", "na",
    }
)

# CAPS PUBLISHING/HEADLINE FURNITURE that survives the acronym detector -- field
# evidence 2026-07-18 (the maintainer's live ~500k-article Families export): FOTO /
# VIDEO / LIVE / INFO / PREMIUM / PDF / RSS ranked among the top "entities". This
# operates ONLY on standalone ALL-CAPS tokens at the acronym-DETECTION layer, exactly
# like _ACRONYM_STOP -- the lowercase content words (it/es/pt "foto", en "live" the
# verb/adjective...) are UNTOUCHED terms, never removed from the index. Evidence-grown
# + tunable; ship only what the export showed, never speculative additions.
_CAPS_FURNITURE_STOP: frozenset[str] = frozenset(
    {"foto", "video", "live", "info", "premium", "pdf", "rss"}
)

# Canonical-form Roman numeral (strict subtractive notation), length >= 2. Deliberately
# STRICT: a malformed run (IIII, VX, IC) does NOT match, so this never over-reaches past
# a token that is genuinely, unambiguously a numeral shape (§0 row 4 of the 2026-07-18
# entity-families brief).
_ROMAN_NUMERAL_RE = re.compile(r"^M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")


def _is_strict_roman_numeral(token: str) -> bool:
    """True for a canonical Roman numeral of length >= 2 (II, III, XIV, MMXXVI...)."""
    return len(token) >= 2 and bool(_ROMAN_NUMERAL_RE.fullmatch(token))


# Real acronyms that ALSO happen to be well-formed Roman numerals -- the negative space
# the Roman-numeral exclusion must not swallow (LIV Golf; DC = Washington/direct current;
# CD = Compact Disc; XL as a clothing-size/brand acronym; MC = Master of Ceremonies; DM =
# Deutsche Mark/direct message; CM as an org acronym; MD = Doctor of Medicine, an
# everyday byline acronym; CV = Curriculum Vitae). Evidence-grown allowlist, same
# discipline as _ACRONYM_STOP -- add only on real, common-knowledge-verifiable evidence,
# never speculatively widen (the brief's own seed + the two highest-confidence additions
# a skeptic pass over every 2-letter roman-valid string surfaced: "md"/"cv"; lower-
# confidence candidates like "mi"/"di"/"vi"/"li" are DELIBERATELY left out pending real
# corpus evidence, not assumed).
_ROMAN_NUMERAL_ACRONYM_ALLOWLIST: frozenset[str] = frozenset(
    {"liv", "dc", "cd", "xl", "mc", "dm", "cm", "md", "cv"}
)


def _is_caps_run_word(w: str) -> bool:
    """True for an all-caps token of length >= 2 with at least one letter.

    Covers plain acronyms (WHO) and digit/hyphen-bearing ones (G7, COVID-19); used
    both to spot an acronym candidate and to detect an all-caps headline/shout run.
    """
    return len(w) >= 2 and w.isupper() and any(c.isalpha() for c in w)


# Field 2026-07-14: an all-caps word carrying an ACCENTED LATIN letter (DÉCOUVREZ, ABONNÉ) is a
# shouted Latin word, not an acronym -- but Greek (ΕΕ) / Cyrillic (СССР) acronyms are legitimate,
# so we only exclude ACCENTED LATIN, never all non-ASCII.
_ACCENTED_LATIN_RE = re.compile(r"[À-ɏ]")
# ASCII all-caps CALL-TO-ACTION strings (share/subscribe buttons) that the acronym rule (#283)
# otherwise mis-tags as ENTITIES. Applied in the entity path only (casefolded), so a match merely
# DEMOTES the word to a plain term -- it never removes a keyword. Evidence-driven + tunable
# (stoplist-architecture rule); a real acronym homograph is not among these.
_CTA_STOP: frozenset[str] = frozenset(
    {
        "share", "shares", "subscribe", "subscribed", "follow", "followers", "signup", "login",
        "partagez", "partager", "abonner", "abonnez", "sabonner", "abonnezvous", "suivez",
        "teilen", "abonnieren", "compartir", "suscribir", "suscribete", "seguir", "condividi",
    }
)
# Field 2026-07-14: tracker/analytics URLs bleeding into the token stream mint junk keywords
# (utm_source / mc_eid / path fragments; ~889k `tracking` mentions). A URL is not prose -- strip
# the whole http(s)/www span BEFORE tokenizing so its residue never becomes a keyword or an entity.
# Prose keywords come from the article body, not from a link, so this loses no real content.
_URL_STRIP_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)


def _strip_urls(text: str) -> str:
    """Remove http(s)/www URL spans so their query-param / path residue is never tokenized."""
    return _URL_STRIP_RE.sub(" ", text)


# --------------------------------------------------------------------------- #
# Digit-heavy "code" tokens (field diagnostics 2026-06-23)
# --------------------------------------------------------------------------- #
# The live keyword log showed a ~35k bucket of alphanumeric code tokens (A-10C,
# internal IDs, model-variant cruft, clock timecodes 1h15) minted as junk
# keywords. They cannot be separated from REAL digit-bearing terms by a digit
# RATIO — the maintainer's own keep/drop examples (a-10 keep vs a-10c drop) are
# shape-identical modulo a trailing letter. The discriminator that works is the
# number of letter<->digit transitions: a real designation keeps its digits in ONE
# run (a-10, f-18, covid-19, g7, g20, cop26, b52, mp3, web3, x86 = exactly 1
# transition), while a code / ID / variant ALTERNATES (a-10c, a1b2, x1y2z3 = >= 2).
# We drop the >= 2-transition tokens. The handful of REAL multi-transition terms
# (influenza subtypes H1N1/H5N1…, the diabetes marker A1C) are an allowlisted
# exception — exactly the _ACRONYM_STOP / _PLURAL_DENYLIST pattern, tunable from the
# diagnostics logs. This is deliberately CONSERVATIVE: a single-transition timecode
# fragment like `h15` (from `1h15`) is shape-identical to `b52`/`mp3` and so cannot
# be caught this way — instead the unigram loop drops a digit-bearing token that is
# glued immediately AFTER a digit in the source (1h15 -> h15, 3a4b -> a4b), which is
# always a tokenizer split of a larger code (real prose space-separates numbers).
# OO_CODE_TOKEN_FILTER=0 disables the whole rule.
_CODE_TOKEN_KEEP: frozenset[str] = frozenset(
    {
        # influenza A subtypes (hemagglutinin Hx / neuraminidase Nx) — real epidemic
        # terms with >= 2 transitions; never let the code rule eat them.
        "h1n1", "h1n2", "h2n2", "h3n2", "h3n8", "h5n1", "h5n6", "h5n8",
        "h7n7", "h7n9", "h9n2", "h10n8",
        "a1c",  # hemoglobin A1c (diabetes marker)
        "x86_64",  # the one common underscore-bearing real term (CPU architecture)
    }
)


def _alnum_transitions(word: str) -> int:
    """Count letter<->digit class changes across a token's alphanumerics.

    Hyphens, apostrophes and underscores are not a class and are skipped, so
    ``a-10`` and ``a10`` both count 1. ``a10`` -> 1, ``a10c`` -> 2, ``h1n1`` -> 3,
    ``covid19`` -> 1, ``mp3`` -> 1, a pure word (no digits) -> 0.
    """
    prev = ""  # "L" | "D"
    n = 0
    for ch in word:
        if ch.isdigit():
            cur = "D"
        elif ch.isalpha():
            cur = "L"
        else:
            continue
        if prev and cur != prev:
            n += 1
        prev = cur
    return n


def _is_code_token(word: str) -> bool:
    """True for a CODE / identifier token that should never be a natural-language keyword.

    Two cases, both case-insensitive, both behind ``OO_CODE_TOKEN_FILTER``:
      * an UNDERSCORE inside the token (gd_combo_table, font_family, utm_source) — a CSS
        / template / code identifier; NO natural orthography in any supported language
        uses a word-internal underscore, so this is false-positive-safe for real words
        (the ~35k "?"-bucket of newsletter/CSS template artefacts, field log 2026-06-23);
      * a multi-segment alphanumeric code (>= 2 letter<->digit transitions: a-10c, a1b2).
    A pure word (no underscore, no digits) is never a code token; a real one-transition
    designation (a-10, covid-19, g7, mp3) is kept; the handful of real multi-transition /
    underscore terms (H1N1, A1C, x86_64) are allowlisted in ``_CODE_TOKEN_KEEP``.
    """
    if os.getenv("OO_CODE_TOKEN_FILTER", "1") == "0":
        return False
    if word.casefold() in _CODE_TOKEN_KEEP:
        return False
    if "_" in word:
        return True
    return _alnum_transitions(word) >= 2


# Curated extra stoplist: very common function words / fillers that the per-language
# sets miss, plus number-words, across the major Latin-script languages. Combined
# with the per-language sets into global_stopwords(). The user can add more from
# the Settings tab (keyword filter).
#
# Migrated (Phase 4.1, PR #740/#744 remediation) from an in-Python string blob into
# configs/stopwords_extra/<lang>.yml data files -- a REPRESENTATION change only. The
# split is a readability/maintenance convenience, NOT a per-language scoping
# guarantee: global_stopwords() unions every file's words below regardless of which
# file a word lives in (unlike configs/keyword_baseline/, which IS genuinely scoped
# per language). See configs/stopwords_extra/PROVENANCE.md for the evidence trail
# (field-log dates, mention counts, collision-safety reasoning) preserved verbatim
# from the original inline comments. tests/test_analytics_extract.py pins the
# stopword SET as byte-identical to the pre-migration blob.
_STOPWORDS_EXTRA_DIR = Path(__file__).resolve().parents[2] / "configs" / "stopwords_extra"


def _load_extra_stopwords() -> frozenset[str]:
    """Union of every configs/stopwords_extra/*.yml file's word list. A missing or
    empty directory is a no-op (never invents a stopword); a malformed individual
    file is skipped rather than crashing extraction."""
    words: set[str] = set()
    if _STOPWORDS_EXTRA_DIR.is_dir():
        for path in sorted(_STOPWORDS_EXTRA_DIR.glob("*.yml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                continue
            words.update(str(w) for w in (data.get("stopwords") or []))
    return frozenset(words)


_EXTRA_STOPWORDS: frozenset[str] = _load_extra_stopwords()
# News text often uses a curly apostrophe (’) — match those spellings of any
# contraction too, so "don't" and "don’t" are both filtered without listing each twice.
_EXTRA_STOPWORDS = _EXTRA_STOPWORDS | frozenset(
    w.replace("'", "’") for w in _EXTRA_STOPWORDS if "'" in w
)


@lru_cache(maxsize=1)
def global_stopwords() -> frozenset[str]:
    """Union of all built-in per-language stoplists + the curated extra set.

    Language-agnostic: a word that is a stopword in any supported language (or in
    the curated extra list) is treated as one. Used both at extraction time and at
    query time (so leaky terms already in the store are hidden retroactively).
    """
    s: set[str] = set(_EXTRA_STOPWORDS)
    s |= set(stopwords_manager.default_stopwords)
    for lang in getattr(stopwords_manager, "language_stopwords", {}):
        s |= set(stopwords_manager.get_stopwords(lang))
    return frozenset(s)


def _stopset(language: str) -> frozenset[str]:
    return frozenset(stopwords_manager.get_stopwords(language)) | global_stopwords()


@dataclass
class ExtractedTerm:
    term: str  # display form (entities keep case; terms are lowercased)
    normalized: str  # dedup key (casefold)
    kind: str  # term | person | org | location | entity
    count: int
    first_offset: int | None


_ELISION = re.compile(r"\b([dlncjmst]|qu)['’](?=\w)", re.IGNORECASE)


def _deelide(word: str) -> str:
    """Strip a leading Romance elision from a single token: l'assemblée -> assemblée,
    d'euros -> euros, qu'il -> il, c'est -> est. The elided article/pronoun is
    tokenization noise, not meaning (French/Italian/Catalan/Occitan…). Cheap guard:
    only touch tokens that actually carry an apostrophe."""
    if "'" in word or "’" in word:
        return _ELISION.sub("", word)
    return word


def _normalize(s: str) -> str:
    # French elisions are tokenization noise, not meaning: "d'euros" is about
    # euros, "l'ia" about ia. Strip the elided article before keying (field
    # log 2026-06-11). Contraction STOPWORDS like c'est stay listed verbatim
    # (they're filtered before this matters).
    s = _ELISION.sub("", s)
    return " ".join(s.split()).casefold()


class BaselineExtractor:
    """Dependency-free n-gram terms + Title-Case entity detection."""

    name = "baseline"

    def __init__(
        self,
        *,
        gazetteer: dict[str, str] | None = None,
        max_terms: int = _DEFAULT_MAX_TERMS,
        max_entities: int = _DEFAULT_MAX_ENTITIES,
    ):
        # gazetteer maps normalized name -> kind ("person"|"org"|"location").
        self.gazetteer = gazetteer or {}
        self.max_terms = max_terms
        self.max_entities = max_entities

    # -- entities ---------------------------------------------------------- #

    def _entities(self, text: str) -> list[ExtractedTerm]:
        """Detect entities as stand-alone ALL-CAPS acronyms only.

        Title-Case ("World", German "Behauptung") was DROPPED as an entity signal:
        it is anglocentric and wrong for a multilingual corpus — German capitalises
        every noun, Romance languages capitalise sentence starts / months /
        nationalities, and Arabic/CJK have no case at all (2026-06-16 keyword-log
        finding: ~60–75% of case "entities" per language were common words, and the
        flag carried no person/org/location semantics anyway). The ONE reliable,
        language-independent case signal is an all-caps ACRONYM standing out in
        mixed-case text (WHO, NATO, USA).

        The normalized form is kept UPPERCASE so an acronym stays distinct from a
        lowercase homograph (WHO != who, US != us) and survives the stopword filter —
        the answer to the WHO/Who problem. Real person/org/place entities come from
        the gazetteer / spaCy (language-aware), applied here and in extract().
        """
        tokens = list(_WORD_RE.finditer(text))
        n = len(tokens)
        agg: dict[str, dict] = {}
        for i, tok in enumerate(tokens):
            surface = tok.group(0)
            if not _is_caps_run_word(surface):
                continue
            if surface.casefold() in _ACRONYM_STOP:
                continue
            if surface.casefold() in _CAPS_FURNITURE_STOP:
                # Publishing/headline furniture (FOTO, VIDEO, LIVE...) -- the lowercase
                # content word is untouched, this only demotes the shouted CHROME form.
                continue
            # An accented-Latin all-caps word (DÉCOUVREZ) or a known CTA button word (PARTAGEZ,
            # SUBSCRIBE) is a shouted term, NOT an acronym entity — demote it to a plain term.
            if _ACCENTED_LATIN_RE.search(surface) or surface.casefold() in _CTA_STOP:
                continue
            if _is_code_token(surface):
                # A-10C-style multi-segment code, not a real acronym entity (G7 /
                # COVID-19 are one transition and survive; H1N1 is allowlisted).
                continue
            if (
                _is_strict_roman_numeral(surface)
                and surface.casefold() not in _ROMAN_NUMERAL_ACRONYM_ALLOWLIST
            ):
                # A pure Roman numeral (XIV, III) is not an organisation/entity, UNLESS
                # it is a known real acronym that also happens to be well-formed
                # (LIV Golf, DC, CD...) -- the allowlist protects that negative space.
                continue
            # A real acronym stands out against mixed-case neighbours; an all-caps
            # token ADJACENT to another all-caps word is part of a HEADLINE/shout run
            # (catches the first & last word of the run, not just the middle).
            prev = tokens[i - 1].group(0) if i > 0 else ""
            nxt = tokens[i + 1].group(0) if i + 1 < n else ""
            if _is_caps_run_word(prev) or _is_caps_run_word(nxt):
                continue
            norm = surface  # PRESERVE case: WHO != who, US != us
            a = agg.get(norm)
            if a is None:
                a = {"count": 0, "first": tok.start(), "surface": surface}
                agg[norm] = a
            a["count"] += 1

        entities = [
            ExtractedTerm(
                term=a["surface"],
                normalized=norm,
                kind=self.gazetteer.get(norm.casefold(), "entity"),
                count=a["count"],
                first_offset=a["first"],
            )
            for norm, a in agg.items()
        ]
        entities.sort(key=lambda e: (-e.count, e.first_offset or 0))
        return entities[: self.max_entities]

    # -- topical terms ----------------------------------------------------- #

    def _terms(self, text: str, language: str) -> list[ExtractedTerm]:
        # Bare ISO code: a region/script subtag (zh-CN, en-US) must reach the SAME
        # segmenter + scoped stoplist as its base language, and must agree with
        # managed.language_status() (which normalizes) — else a zh-CN article reports
        # 'functional' while extraction silently skips segmentation.
        language = normalize_lang(language)
        stop = _stopset(language)
        # A word segmenter (the optional [segmentation] extra) rescues a space-less
        # script (zh/ja/th) — real words instead of one sentence-long token / mark
        # fragments. It returns (word, offset); None means "not segmentable here" and
        # we fall back to the byte-identical whitespace tokenizer below.
        seg = segment(text, language)
        if seg is not None:
            toks = [(w.lower(), off) for w, off in seg]
            segmented = True
        else:
            # De-elide each token: the contracted article (l'/d'/qu'/c'…) is noise, so
            # "l'assemblée" is the keyword "assemblée" and "qu'il" reduces to the stopword
            # "il". Without this the whole "l'assemblée" form was kept as a keyword.
            toks = [(_deelide(m.group(0).lower()), m.start()) for m in _WORD_RE.finditer(text)]
            segmented = False
        counts: Counter[str] = Counter()
        first_at: dict[str, int] = {}

        def _record(term: str, offset: int) -> None:
            counts[term] += 1
            first_at.setdefault(term, offset)

        # Unigrams (content words only). Drop digit-heavy CODE tokens (A-10C, a1b2 —
        # see _is_code_token) and glued <digits><token> fragments (1h15 -> h15), which
        # leaked ~35k junk keywords; real designations (a-10, covid-19, b52, mp3) stay.
        for word, off in toks:
            if len(word) < _term_floor(word, segmented) or word in stop or word.isdigit():
                continue
            if _is_code_token(word):
                continue
            if off > 0 and text[off - 1].isdigit() and any(c.isdigit() for c in word):
                continue  # tokenizer split of a glued code/timecode (1h15 -> h15)
            _record(word, off)
        # Bigrams / trigrams over the raw token stream, dropping ones bounded by
        # stopwords so phrases stay meaningful ("prime minister", not "of the").
        for size in (2, 3):
            for k in range(len(toks) - size + 1):
                window = toks[k : k + size]
                words = [w for w, _ in window]
                # Drop a phrase if ANY token is a stopword, too short/numeric, or a
                # code token, so fillers/codes don't leak inside n-grams.
                if any(
                    w in stop or len(w) < _term_floor(w, segmented) or w.isdigit() or _is_code_token(w)
                    for w in words
                ):
                    continue
                # Drop a repeated-token n-gram ("share share", "now now now") — a chrome/CTA
                # artifact of duplicated button/label text, never a real phrase (field 2026-07-14).
                if len(set(words)) == 1:
                    continue
                phrase = " ".join(words)
                # Drop a phrase whose JOINED form is itself a stopword ENTRY. The vendored
                # scoped lists carry many MULTI-WORD stopword phrases — 379 of 645 in vi.txt
                # (e.g. "bao giờ" = when) — whose component syllables are NOT standalone
                # entries, so the per-word check above lets the whole filler phrase leak as a
                # keyword. Matching the joined phrase activates those existing entries (field
                # test 2026-07-08). NOTE: this is a PARTIAL fix for syllable-segmented
                # languages (vi/zh/ja/th) — the single-syllable fragments + multi-syllable
                # function words that fragment across token boundaries still leak; the real
                # cure is a word segmenter (ledger P4.4, ruling-gated).
                if phrase in stop:
                    continue
                _record(phrase, window[0][1])

        terms = [
            ExtractedTerm(term=t, normalized=t, kind="term", count=c, first_offset=first_at.get(t))
            for t, c in counts.items()
            if c >= 1
        ]
        terms.sort(key=lambda e: (-e.count, len(e.term)))
        return terms[: self.max_terms]

    def extract(self, text: str, *, title: str = "", language: str = "en") -> list[ExtractedTerm]:
        if not text or not text.strip():
            return []
        text = strip_markup(text)  # never mint div/span/max-width/font-size keywords
        text = _strip_urls(text)   # never mint utm_source/mc_eid/path-fragment keywords from links
        entities = self._entities(text)
        ent_norms = {e.normalized for e in entities}
        # Topical terms. A term whose normalized form is in the gazetteer is promoted
        # to its real person/org/location kind — with Title-Case dropped, NAMED
        # entities now come from the gazetteer / spaCy (language-aware), not from
        # capitalisation. Terms duplicating a detected acronym are skipped.
        terms: list[ExtractedTerm] = []
        for t in self._terms(text, language):
            if t.normalized in ent_norms:
                continue
            kind = self.gazetteer.get(t.normalized)
            if kind:
                terms.append(
                    ExtractedTerm(
                        term=t.term,
                        normalized=t.normalized,
                        kind=kind,
                        count=t.count,
                        first_offset=t.first_offset,
                    )
                )
            else:
                terms.append(t)
        return entities + terms


class SpacyExtractor:
    """Opt-in real NER (PERSON/ORG/GPE/LOC) + baseline topical terms."""

    name = "spacy"
    _LABELS = {
        "PERSON": "person",
        "PER": "person",
        "ORG": "org",
        "GPE": "location",
        "LOC": "location",
        "FAC": "location",
        "NORP": "org",
    }

    def __init__(
        self,
        model: str = "en_core_web_sm",
        *,
        max_entities: int = _DEFAULT_MAX_ENTITIES,
        baseline: BaselineExtractor | None = None,
    ):
        import spacy  # raises ImportError if the [nlp] extra is absent

        self._nlp = spacy.load(model, disable=["lemmatizer", "tagger"])
        self.model = model
        self.max_entities = max_entities
        self._baseline = baseline or BaselineExtractor()

    def extract(self, text: str, *, title: str = "", language: str = "en") -> list[ExtractedTerm]:
        if not text or not text.strip():
            return []
        text = strip_markup(text)  # never mint div/span/max-width/font-size keywords
        text = _strip_urls(text)   # never mint utm_source/mc_eid/path-fragment keywords from links
        doc = self._nlp(text[:1_000_000])  # spaCy default max length guard
        ents: dict[str, ExtractedTerm] = {}
        for ent in doc.ents:
            kind = self._LABELS.get(ent.label_)
            if kind is None:
                continue
            norm = _normalize(ent.text)
            if norm in ents:
                ents[norm].count += 1
            else:
                ents[norm] = ExtractedTerm(ent.text, norm, kind, 1, ent.start_char)
        entities = sorted(ents.values(), key=lambda e: (-e.count, e.first_offset or 0))[
            : self.max_entities
        ]
        # Topical terms from the baseline (entities here are model-labelled), minus
        # any that duplicate a detected entity.
        ent_norms = {e.normalized for e in entities}
        terms = [t for t in self._baseline._terms(text, language) if t.normalized not in ent_norms]
        return entities + terms


def get_extractor(name: str = "baseline", *, gazetteer: dict[str, str] | None = None, **kw):
    """Factory. ``name='spacy'`` falls back to baseline if the extra is missing."""
    if name == "spacy":
        try:
            return SpacyExtractor(baseline=BaselineExtractor(gazetteer=gazetteer), **kw)
        except Exception:  # noqa: BLE001 - spaCy/model absent -> honest fallback
            return BaselineExtractor(gazetteer=gazetteer)
    return BaselineExtractor(gazetteer=gazetteer)
